"""Evidence run for pos_rank depth chart scoring (§5.9a / §5.10.1, D19 / D20).

Reports, on live cached depth charts:
  1. Week 1 depth scores for real RB1/RB2 and WR1/WR2/WR3, by name
  2. One RB1's score at Weeks 1, 3 and 5 — the fade
  3. Pinning: the dt each team's chart resolved to
  4. FLEX Week 1: a real RB2 against a real WR2
"""
from __future__ import annotations

import polars as pl
import yaml

from brady_bot.config import load_config
from brady_bot.derive.context import build_week_context
from brady_bot.derive.depth import (
    derive_pos_ranks,
    posrank_score,
    posrank_weights,
)
from brady_bot.derive.injuries import pin_depth_to_latest_week
from brady_bot.models import GameContext, Player, Position, TeamStats, WeekContext
from brady_bot.normalizer import load_overrides, resolve_player
from brady_bot.optimizer import optimize_lineup
from brady_bot.paths import DATA_DIR
from brady_bot.pickers.flex import FlexPicker
from brady_bot.pickers.rb import RBPicker
from brady_bot.pickers.wr import WRPicker
from brady_bot.sources import nflverse
from brady_bot.sources.cache import CacheStore
from brady_bot.sources.schema import DEPTH_GSIS_ID, DEPTH_POS_ABB, DEPTH_POS_RANK, DEPTH_TEAM

BAR = "=" * 78


def _ctx(roster: list[Player], week: int, pos_rank, **kw) -> WeekContext:
    teams = sorted({p.team for p in roster})
    games = {
        t: GameContext(
            game_id=f"{t}-g",
            home_team=t,
            away_team=teams[(i + 1) % len(teams)],
            game_total=44,
            home_implied_total=22,
            away_implied_total=22,
        )
        for i, t in enumerate(teams)
    }
    neutral = {t: 0.0 for t in teams}
    return WeekContext(
        season=2026,
        week=week,
        fetched_at="2026-09-13T00:00:00Z",
        roster=roster,
        team_stats={
            t: TeamStats(
                team=t,
                season=2026,
                through_week=max(week - 1, 1),
                offense_rank=16,
                total_defense_rank=16,
                scoring_efficiency_rank=16,
                defense_calibre_rank=16,
                qb_turnover_rank=16,
            )
            for t in teams
        },
        games=games,
        adj_fpa={p: neutral for p in ("QB", "RB", "WR", "TE")},
        calibre_rank={p: {} for p in ("QB", "RB", "WR", "TE")},
        player_teams={p.player_id: p.team for p in roster},
        pos_rank=pos_rank,
        injury_counts={t: {"OL": 0, "FRONT_SEVEN_INTERIOR": 0, "SECONDARY": 0} for t in teams},
        oline_ranks={t: 16 for t in teams},
        static_ids={"rb_tier1": set(), "rb_tier2": set(), "wr_top5": set(), "elite_tes": set()},
        blended=week <= 4,
        **kw,
    )


def _depth_factor(picker, ctx, player, factor="depth_chart"):
    return next(f for f in picker.score_factors(ctx, player) if f.name == factor)


def _pick(pinned: pl.DataFrame, names: dict[str, str], pos: str, rank: int, team: str):
    """One charted player at (team, pos, rank) as a Player."""
    rows = pinned.filter(
        (pl.col(DEPTH_TEAM).cast(pl.Utf8).str.to_uppercase() == team)
        & (pl.col(DEPTH_POS_ABB).cast(pl.Utf8).str.to_uppercase() == pos)
        & (pl.col(DEPTH_POS_RANK) == rank)
    )
    if rows.is_empty():
        return None
    pid = str(rows.row(0, named=True)[DEPTH_GSIS_ID])
    return Player(
        player_id=pid,
        name=names.get(pid, pid),
        team=team,
        position=Position(pos),
    )


def main() -> None:
    cfg = load_config()
    cache = CacheStore()
    players_df = nflverse.load_players_cached(cache)
    season = cfg.league.season
    depth = nflverse.load_depth_charts(cache, [season, season - 1])

    names = {
        str(r["gsis_id"]): str(r.get("display_name") or r.get("full_name") or r["gsis_id"])
        for r in players_df.select(
            [c for c in ("gsis_id", "display_name", "full_name") if c in players_df.columns]
        ).to_dicts()
        if r.get("gsis_id")
    }

    pinned = pin_depth_to_latest_week(depth, 1)
    pos_rank = derive_pos_ranks(depth, 1, overrides=cfg.resolved_depth_overrides)

    print(BAR)
    print("0. PINNING (non-negotiable #8b) — rows before/after max-dt filter")
    print(BAR)
    print(f"  raw rows          : {depth.height}")
    print(f"  pinned rows       : {pinned.height}")
    if "dt" in depth.columns:
        per_team = (
            pinned.group_by(DEPTH_TEAM).agg(pl.col("dt").n_unique().alias("dts")).sort(DEPTH_TEAM)
        )
        bad = per_team.filter(pl.col("dts") > 1)
        print(f"  teams pinned      : {per_team.height}")
        print(f"  teams with >1 dt  : {bad.height} (must be 0)")
        print(f"  dt range kept     : {pinned['dt'].min()} .. {pinned['dt'].max()}")
    print(f"  RB ranks resolved : {len(pos_rank['RB'])}")
    print(f"  WR ranks resolved : {len(pos_rank['WR'])}")
    print(f"  TE ranks resolved : {len(pos_rank['TE'])}")

    rb_picker, wr_picker = RBPicker(cfg), WRPicker(cfg)
    picks: dict[str, Player] = {}
    print()
    print(BAR)
    print("1. WEEK 1 DEPTH SCORES FROM LIVE CHARTS")
    print(BAR)
    for team in ("KC", "LAC", "DEN"):
        team_picks: dict[str, Player] = {}
        for pos, rank in (("RB", 1), ("RB", 2), ("RB", 3), ("WR", 1), ("WR", 2), ("WR", 3)):
            p = _pick(pinned, names, pos, rank, team)
            if p:
                team_picks[f"{pos}{rank}"] = p
        if not team_picks:
            continue
        ctx1 = _ctx(list(team_picks.values()), 1, pos_rank)
        print(f"  {team}")
        for key, p in team_picks.items():
            picker = rb_picker if p.position == Position.RB else wr_picker
            f = _depth_factor(picker, ctx1, p)
            rank = pos_rank[p.position.value].get(p.player_id)
            print(
                f"    {key:<4} {p.name:<24} pos_rank={rank}  "
                f"score={f.score:.2f}  weight={f.weight:.2f}  input={f.raw_value}"
            )
        picks = picks or team_picks

    rb1 = picks.get("RB1")
    if rb1:
        print()
        print(BAR)
        print(f"2. THE FADE — {rb1.name} (RB1) at 35% current snap share")
        print(BAR)
        for week in (1, 2, 3, 4, 5):
            ctx = _ctx([rb1], week, pos_rank, snap_share={rb1.player_id: 0.35})
            f = _depth_factor(rb_picker, ctx, rb1)
            w_pr, w_us = posrank_weights(week)
            print(
                f"  week {week}  posrank={posrank_score(1, 'RB'):.2f}@{w_pr:>4.0%}  "
                f"usage=0.20@{w_us:>4.0%}  ->  {f.score:.3f}   {f.raw_value}"
            )

    rb2, wr2 = picks.get("RB2"), picks.get("WR2")
    if rb2 and wr2:
        print()
        print(BAR)
        print("3. FLEX WEEK 1 — Opportunity is 40%, so depth position decides")
        print(BAR)
        flex = FlexPicker(cfg)
        ctx = _ctx([rb2, wr2], 1, pos_rank)
        starters, bench = flex.select(ctx, [rb2, wr2])
        for s in starters + bench:
            opp = next(f for f in s.factors if f.name == "opportunity")
            print(
                f"  {s.player.name:<24} ({s.player.position.value}2)  "
                f"opportunity={opp.score:.2f}  start_score={s.start_score:.3f}"
            )
        print(f"  FLEX slot -> {starters[0].player.name}")

    print()
    print(BAR)
    print("4. FULL PIPELINE — real roster through build_week_context + optimizer")
    print(BAR)
    overrides = load_overrides()
    roster = []
    for r in yaml.safe_load((DATA_DIR / "roster.yaml").read_text()).get("roster") or []:
        try:
            roster.append(
                resolve_player(
                    r["name"],
                    r.get("team"),
                    r.get("position"),
                    players_df,
                    cfg.team_aliases,
                    overrides,
                )
            )
        except Exception as exc:  # evidence run only — the CLI still halts on this
            print(f"  [skip] {r['name']}: {exc}")
    print(f"  roster resolved   : {len(roster)} players")

    ctx = build_week_context(roster, cfg, 1, cache, players_df=players_df)
    lineup = optimize_lineup(ctx, cfg)
    print("\n  --- week 1 ---")
    print(
        f"  pos_rank resolved : RB={len(ctx.pos_rank['RB'])} "
        f"WR={len(ctx.pos_rank['WR'])} TE={len(ctx.pos_rank['TE'])}"
    )
    print(f"  no_depth_entry    : {len(ctx.no_depth_entry)}")
    print(f"  snap_share keys   : {len(ctx.snap_share)}  (current season only, no prior W10-18)")
    starters = [(slot, s) for slot, s in lineup.starters.items() if s]
    for slot, s in starters:
        f = next((x for x in s.factors if x.name in ("depth_chart", "opportunity")), None)
        if not f:
            continue
        print(f"  {slot:<5} {s.player.name:<22} {f.name:<12} {f.score:>5.2f}  {f.raw_value}")
    for w in [w for w in ctx.warnings if "no_depth_entry" in w][:5]:
        print(f"  WARN {w}")

    # Re-score the same live pos_rank against later weeks. A full week-5 context cannot
    # be built until the current season has data — derive_team_ranks halts on <32 teams,
    # which is non-negotiable #8 doing its job, not a depth-scoring problem.
    print("\n  --- same roster, same live pos_rank, later weeks ---")
    rb_by_pos = {Position.RB: RBPicker(cfg), Position.WR: WRPicker(cfg)}
    tracked = [
        (slot, s)
        for slot, s in starters
        if s.player.position in rb_by_pos and s.factors
    ]
    for week in (1, 3, 5):
        ctx.week = week
        bits = []
        for _slot, s in tracked:
            picker = rb_by_pos[s.player.position]
            f = _depth_factor(picker, ctx, s.player)
            bits.append(f"{s.player.name.split()[-1]}={f.score:.2f}")
        print(f"  week {week}: {'  '.join(bits)}")


if __name__ == "__main__":
    main()
