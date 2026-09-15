"""Build WeekContext from sources + derive layer."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import polars as pl

from brady_bot.config import AppConfig
from brady_bot.derive.adj_fpa import derive_adj_fpa
from brady_bot.derive.blending import (
    is_blended_week,
    max_reg_week_from_frames,
    prior_season_week_window,
)
from brady_bot.derive.calibre import derive_player_calibre
from brady_bot.derive.depth import (
    SCORED_POSITIONS,
    derive_depth_chart_order,
    derive_pos_ranks,
    posrank_active,
)
from brady_bot.derive.injuries import build_injury_map, count_all_units
from brady_bot.derive.qb_calibre import fallback_warnings, merge_qb_calibre
from brady_bot.derive.roles import derive_roles, derive_snap_shares
from brady_bot.derive.team_ranks import derive_team_ranks
from brady_bot.models import GameContext, Player, WeekContext
from brady_bot.normalizer import (
    normalize_team,
    resolve_depth_overrides,
    resolve_qb_calibre_ranks,
    resolve_qb_styles,
    resolve_static_lists,
)
from brady_bot.players_index import NFL_TEAMS, TEAM_NAMES
from brady_bot.sources import nflverse, odds
from brady_bot.sources.cache import CacheStore
from brady_bot.sources.schema import (
    DEPTH_GSIS_ID,
    DEPTH_TEAM,
    PS_CARRIES,
    PS_PLAYER_ID,
    PS_POSITION,
    PS_TEAM,
)


def _player_teams(
    roster: list[Player],
    depth: pl.DataFrame,
    player_stats: pl.DataFrame,
    aliases: dict[str, str],
) -> dict[str, str]:
    """Map player_id → team abbr from roster, depth charts, and recent stats."""
    out: dict[str, str] = {}
    for p in roster:
        out[p.player_id] = p.team.upper()

    if not depth.is_empty():
        id_col = DEPTH_GSIS_ID if DEPTH_GSIS_ID in depth.columns else PS_PLAYER_ID
        if id_col in depth.columns and DEPTH_TEAM in depth.columns:
            for r in depth.select([id_col, DEPTH_TEAM]).unique().to_dicts():
                pid = r.get(id_col)
                team = r.get(DEPTH_TEAM)
                if pid is None or team is None:
                    continue
                out[str(pid)] = normalize_team(str(team), aliases)

    if not player_stats.is_empty():
        id_col = PS_PLAYER_ID if PS_PLAYER_ID in player_stats.columns else DEPTH_GSIS_ID
        team_col = PS_TEAM if PS_TEAM in player_stats.columns else "recent_team"
        if id_col in player_stats.columns and team_col in player_stats.columns:
            for r in player_stats.select([id_col, team_col]).drop_nulls().unique().to_dicts():
                pid = r.get(id_col)
                team = r.get(team_col)
                if pid is None or team is None:
                    continue
                out.setdefault(str(pid), normalize_team(str(team), aliases))
    return out


def _rush_att_per_game(
    player_stats: pl.DataFrame,
    season: int,
    through_week: int,
) -> dict[str, float]:
    """Trailing rush attempts (carries) per game for QBs.

    Denominator is games played — one stats row per game — per §5.10.2 / D18.
    """
    if player_stats.is_empty():
        return {}
    ps = player_stats
    if "season" in ps.columns:
        ps = ps.filter(pl.col("season") == season)
    if "week" in ps.columns and through_week > 0:
        ps = ps.filter(pl.col("week") <= through_week)
    elif through_week <= 0:
        return {}
    if PS_POSITION in ps.columns:
        ps = ps.filter(pl.col(PS_POSITION).cast(pl.Utf8).str.to_uppercase() == "QB")
    att_col = PS_CARRIES if PS_CARRIES in ps.columns else next(
        (c for c in ("rushing_attempts", "rush_attempts", "rushing_att") if c in ps.columns),
        None,
    )
    if att_col is None:
        return {}
    id_col = PS_PLAYER_ID if PS_PLAYER_ID in ps.columns else DEPTH_GSIS_ID
    if id_col not in ps.columns or ps.is_empty():
        return {}
    out: dict[str, float] = {}
    for r in (
        ps.group_by(id_col)
        .agg(
            pl.col(att_col).fill_null(0).sum().alias("atts"),
            # pl.len(), not .count() — a game with a null carries value is still a
            # game played and must stay in the denominator.
            pl.len().alias("games"),
        )
        .to_dicts()
    ):
        pid = r.get(id_col)
        games = int(r.get("games") or 0)
        if pid is None or games <= 0:
            continue
        out[str(pid)] = float(r.get("atts") or 0) / games
    return out


def _catalog_names(players: pl.DataFrame, roster: list[Player]) -> dict[str, str]:
    """gsis_id → display name over the whole S7 catalog, roster names taking priority."""
    out: dict[str, str] = {}
    if not players.is_empty() and {"gsis_id", "display_name"} <= set(players.columns):
        for r in players.select(["gsis_id", "display_name"]).drop_nulls().to_dicts():
            out[str(r["gsis_id"])] = str(r["display_name"])
    for p in roster:
        out[p.player_id] = p.name
    return out


def _bye_teams(schedules: pl.DataFrame, season: int, week: int, aliases: dict[str, str]) -> list[str]:
    if schedules.is_empty():
        return []
    df = schedules
    if "season" in df.columns:
        df = df.filter(pl.col("season") == season)
    if "game_type" in df.columns:
        df = df.filter(pl.col("game_type") == "REG")
    playing: set[str] = set()
    if "week" in df.columns:
        wk = df.filter(pl.col("week") == week)
        for col in ("home_team", "away_team"):
            if col in wk.columns:
                playing |= {normalize_team(str(t), aliases) for t in wk[col].to_list() if t}
    all_teams = set(NFL_TEAMS)
    return sorted(all_teams - playing) if playing else []


def _games_from_schedules(
    schedules: pl.DataFrame,
    season: int,
    week: int,
    odds_by_name: dict,
    aliases: dict[str, str],
    odds_unavailable: bool,
) -> dict[str, GameContext]:
    """Build GameContext per team. Prefer Odds API lines when matched; else schedule lines."""
    # Reverse map: full Odds API name -> abbreviation
    name_to_abbr = {name.lower(): abbr for abbr, name in TEAM_NAMES.items()}
    for alias, abbr in (aliases or {}).items():
        if len(str(alias)) > 3:
            name_to_abbr[str(alias).lower()] = normalize_team(str(abbr), aliases)

    def odds_abbr(full_name: str | None) -> str | None:
        if not full_name:
            return None
        return name_to_abbr.get(str(full_name).strip().lower())

    # Index odds payloads by (home_abbr, away_abbr)
    odds_by_matchup: dict[tuple[str, str], dict] = {}
    seen: set[str] = set()
    for payload in (odds_by_name or {}).values():
        if not isinstance(payload, dict) or not payload.get("game_total"):
            continue
        gid = str(payload.get("game_id") or "")
        if gid and gid in seen:
            continue
        if gid:
            seen.add(gid)
        h = odds_abbr(str(payload.get("home") or ""))
        a = odds_abbr(str(payload.get("away") or ""))
        if h and a:
            odds_by_matchup[(h, a)] = payload

    games: dict[str, GameContext] = {}
    if schedules.is_empty():
        return games
    df = schedules
    if "season" in df.columns:
        df = df.filter(pl.col("season") == season)
    if "week" in df.columns:
        df = df.filter(pl.col("week") == week)
    for r in df.to_dicts():
        home = normalize_team(str(r.get("home_team") or ""), aliases)
        away = normalize_team(str(r.get("away_team") or ""), aliases)
        if not home or not away:
            continue
        game_id = str(r.get("game_id") or f"{away}@{home}")
        total = 44.0
        spread = 0.0
        home_imp = 22.0
        away_imp = 22.0
        has_schedule_line = r.get("total_line") is not None or r.get("spread_line") is not None

        matched = odds_by_matchup.get((home, away))
        if matched:
            total = float(matched["game_total"])
            spread = float(matched.get("spread") or 0.0)
            home_imp = float(matched["home_implied_total"])
            away_imp = float(matched["away_implied_total"])
            if matched.get("game_id"):
                game_id = str(matched["game_id"])
        else:
            if r.get("total_line") is not None:
                total = float(r["total_line"])
            if r.get("spread_line") is not None:
                spread = float(r["spread_line"])
                home_imp = (total / 2.0) + (abs(spread) / 2.0)
                away_imp = (total / 2.0) - (abs(spread) / 2.0)
                if spread > 0:
                    home_imp, away_imp = away_imp, home_imp
            elif r.get("total_line") is not None:
                home_imp = away_imp = total / 2.0
            if odds_unavailable and not has_schedule_line:
                home_imp = away_imp = 22.0
                total = 44.0
                spread = 0.0

        ctx = GameContext(
            game_id=game_id,
            home_team=home,
            away_team=away,
            game_total=total,
            spread=spread,
            home_implied_total=home_imp,
            away_implied_total=away_imp,
        )
        games[home] = ctx
        games[away] = ctx
    return games


def build_week_context(
    roster: list[Player],
    cfg: AppConfig,
    week: int,
    cache: CacheStore | None = None,
    *,
    no_cache: bool = False,
    refresh_odds: bool = False,
    players_df: pl.DataFrame | None = None,
) -> WeekContext:
    cache = cache or CacheStore()
    season = cfg.league.season
    seasons = [season, season - 1]
    warnings: list[str] = []

    schedules = nflverse.load_schedules(cache, seasons, no_cache=no_cache)
    player_stats = nflverse.load_player_stats(cache, seasons, no_cache=no_cache)
    try:
        team_stats = nflverse.load_team_stats(cache, seasons, no_cache=no_cache)
    except Exception:
        team_stats = pl.DataFrame()
        warnings.append("team_stats unavailable; using neutral team ranks")
    try:
        snaps = nflverse.load_snap_counts(cache, seasons, no_cache=no_cache)
    except Exception:
        snaps = pl.DataFrame()
    try:
        injuries_df = nflverse.load_injuries(cache, [season], no_cache=no_cache)
    except Exception:
        injuries_df = pl.DataFrame()
        warnings.append("injuries unavailable")
    try:
        depth = nflverse.load_depth_charts(cache, [season], no_cache=no_cache)
    except Exception:
        depth = pl.DataFrame()

    if players_df is None:
        players_df = nflverse.load_players_cached(cache, no_cache=no_cache)

    cfg.resolved_static = resolve_static_lists(cfg.static_lists, players_df, cfg.team_aliases)

    # QB playing-style table is authoritative — unresolved names hard-fail (lineup-picker-QB.md)
    cfg.resolved_qb_styles = resolve_qb_styles(
        cfg.static_lists.get("qb_styles") or [],
        players_df,
        cfg.team_aliases,
    )

    # S11 depth overrides — unresolved or ambiguous names halt (§5.9a / §10.3b)
    cfg.resolved_depth_overrides = resolve_depth_overrides(
        cfg.depth_overrides,
        players_df,
        cfg.team_aliases,
    )

    # S12 QB calibre ranking — resolved by team AND position; ambiguity halts (D21)
    cfg.resolved_qb_calibre = resolve_qb_calibre_ranks(
        cfg.qb_calibre_ranks,
        players_df,
        cfg.team_aliases,
    )

    odds_events, odds_unavailable, odds_warn = odds.fetch_odds(
        cache, no_cache=no_cache, refresh_odds=refresh_odds
    )
    if odds_warn:
        warnings.append(odds_warn)
    odds_map = odds.average_odds_to_games(odds_events)

    through_week = max(0, week - 1)  # completed weeks of current season
    prior_ts = team_stats.filter(pl.col("season") == season - 1) if "season" in team_stats.columns else team_stats
    cur_ts = team_stats.filter(pl.col("season") == season) if "season" in team_stats.columns else team_stats

    max_reg = max_reg_week_from_frames(season - 1, schedules, player_stats, snaps, team_stats)
    prior_lo, prior_hi = prior_season_week_window(max_reg)

    team_ranks = derive_team_ranks(
        cur_ts,
        player_stats,
        season,
        max(through_week, 1),
        prior_team_stats=prior_ts,
        blend_week=week,
        prior_week_lo=prior_lo,
        prior_week_hi=prior_hi,
        team_aliases=cfg.team_aliases,
    )

    adj_fpa: dict[str, dict[str, float]] = {}
    for pos in ("QB", "RB", "WR", "TE"):
        adj_fpa[pos] = derive_adj_fpa(
            player_stats,
            schedules,
            pos,
            season,
            through_week,
            cfg.league,
            week=week,
            prior_week_lo=prior_lo,
            prior_week_hi=prior_hi,
            team_aliases=cfg.team_aliases,
        )

    min_games = int(cfg.weights.global_cfg.get("calibre_min_games", 3))
    calibre: dict[str, dict[str, int]] = {}
    for pos in ("QB", "RB", "WR", "TE", "K"):
        calibre[pos] = derive_player_calibre(
            player_stats,
            pos,
            season,
            max(through_week, 1),
            cfg.league,
            min_games=min_games,
        )

    # D21 — QB is the one position whose calibre is not derived. S12's static ranking
    # overlays the derived map so WR/TE Step 5, FLEX Step 4 and DEF Step 2 all read the
    # same number; QBs off the list keep their derived rank, flagged for the breakdown.
    # The QB picker has no self-calibre factor, so nothing here changes its Start Score.
    calibre["QB"], qb_calibre_fallback = merge_qb_calibre(
        cfg.resolved_qb_calibre, calibre["QB"]
    )

    inj_map = build_injury_map(injuries_df, week)
    roles, target_share, qb1 = derive_roles(
        player_stats,
        depth,
        inj_map,
        season,
        through_week,
        week=week,
        prior_week_lo=prior_lo,
        prior_week_hi=prior_hi,
    )
    # Current-season snap share only. The prior-season W10–18 component was retired
    # from RB Step 3 by D19 — pos_rank occupies that slot — so no prior_snaps frame is
    # passed here. Prior-season data is still used elsewhere, notably player calibre.
    snap_share = derive_snap_shares(
        snaps,
        season,
        through_week,
        prior_snaps=None,
        week=week,
        players=players_df,
    )

    # Current-season-only WR roles: the usage half of the depth blend. ctx.roles stays
    # blended for identification (teammate injury, WR-health checks). From Week 5 the
    # blend is current-only anyway, so the two maps are the same object.
    roles_current: dict[str, str] = roles
    if posrank_active(week):
        roles_current, _, _ = derive_roles(
            player_stats,
            depth,
            inj_map,
            season,
            through_week,
            week=week,
            current_only=True,
        )

    # §5.9a — pinned pos_rank per scored position, depth overrides applied last.
    pos_rank = derive_pos_ranks(
        depth,
        week,
        overrides=cfg.resolved_depth_overrides,
        aliases=cfg.team_aliases,
    )

    # Gate identity — same position scoping as pos_rank, plus QB. KR/PR excluded so a
    # special-teams row cannot overwrite a starter the way the old flat map did.
    depth_order = derive_depth_chart_order(depth, week)

    # D20 — a rostered RB/WR/TE the chart omits scores 0.00 like a rank 4+, so flag it:
    # absence can be a data gap rather than a real demotion. Only while pos_rank still
    # carries weight; past Week 4 the absence has no scoring effect.
    no_depth_entry: list[str] = []
    if posrank_active(week):
        names = _catalog_names(players_df, roster)
        for p in roster:
            if p.position.value not in SCORED_POSITIONS:
                continue
            if p.player_id in pos_rank.get(p.position.value, {}):
                continue
            no_depth_entry.append(p.player_id)
            warnings.append(
                f"no_depth_entry: {names.get(p.player_id, p.name)} ({p.team}) is not on "
                f"the pinned {p.position.value} depth chart — pos_rank scores 0.00"
            )

    # D21 — a QB1 off the S12 list is scoring someone else's factor from the derived
    # fallback. Never a halt (that is the fallback's whole purpose), but it should be
    # visible, since it is 15% of a WR/TE and 30% of a D/ST facing that team.
    if qb_calibre_fallback:
        warnings.extend(
            fallback_warnings(
                qb1, qb_calibre_fallback, _catalog_names(players_df, roster)
            )
        )

    injury_counts = count_all_units(injuries_df, depth, list(NFL_TEAMS), week)
    bye = _bye_teams(schedules, season, week, cfg.team_aliases)
    games = _games_from_schedules(schedules, season, week, odds_map, cfg.team_aliases, odds_unavailable)
    player_teams = _player_teams(roster, depth, player_stats, cfg.team_aliases)
    rush_att_pg = _rush_att_per_game(player_stats, season, max(through_week, 1))

    return WeekContext(
        season=season,
        week=week,
        fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        roster=roster,
        injuries=inj_map,
        team_stats=team_ranks,
        games=games,
        adj_fpa=adj_fpa,
        calibre_rank=calibre,
        roles=roles,
        player_teams=player_teams,
        rush_att_pg=rush_att_pg,
        snap_share=snap_share,
        target_share=target_share,
        roles_current=roles_current,
        injury_counts=injury_counts,
        bye_teams=bye,
        depth_chart_order=depth_order,
        pos_rank=pos_rank,
        no_depth_entry=no_depth_entry,
        qb1_by_team={k.upper(): v for k, v in qb1.items()},
        static_ids=cfg.resolved_static,
        qb_styles=dict(cfg.resolved_qb_styles),
        qb_calibre_fallback=qb_calibre_fallback,
        oline_ranks=dict(cfg.oline_ranks),
        blended=is_blended_week(week),
        odds_unavailable=odds_unavailable,
        warnings=warnings,
    )
