from __future__ import annotations

import polars as pl

from brady_bot.derive.blending import (
    blend_rates,
    is_blended_week,
    max_reg_week_from_frames,
    prior_season_week_window,
    rb_prior_snap_week_window,
)
from brady_bot.models import InjuryRecord
from brady_bot.derive.injuries import pin_depth_to_latest_week
from brady_bot.sources.schema import (
    DEPTH_GSIS_ID,
    DEPTH_POS_ABB,
    DEPTH_POS_RANK,
    DEPTH_STARTER_RANK,
    DEPTH_TEAM,
    PLAYERS_GSIS_ID,
    PLAYERS_PFR_ID,
    PS_PLAYER_ID,
    PS_TARGETS,
    PS_TEAM,
    SNAP_CROSSWALK_MIN_HIT_RATE,
    SNAP_OFFENSE_PCT,
    SNAP_OFFENSE_SNAPS,
    SNAP_PFR_PLAYER_ID,
    SNAP_POSITION,
    SNAP_TEAM,
    SNAP_WEEK,
)


class SnapCrosswalkError(Exception):
    """PFR→gsis snap-id join hit rate below SNAP_CROSSWALK_MIN_HIT_RATE."""


def _snap_id_col(df: pl.DataFrame) -> str | None:
    """Prefer already-resolved gsis_id; else pfr_player_id (needs crosswalk)."""
    if "gsis_id" in df.columns and SNAP_PFR_PLAYER_ID not in df.columns:
        return "gsis_id"
    if SNAP_PFR_PLAYER_ID in df.columns:
        return SNAP_PFR_PLAYER_ID
    if "gsis_id" in df.columns:
        return "gsis_id"
    if PS_PLAYER_ID in df.columns:
        return PS_PLAYER_ID
    return None


def _offense_share_col(df: pl.DataFrame) -> tuple[pl.DataFrame, str | None]:
    if SNAP_OFFENSE_PCT in df.columns:
        return df, SNAP_OFFENSE_PCT
    if SNAP_OFFENSE_SNAPS in df.columns:
        team_col = SNAP_TEAM if SNAP_TEAM in df.columns else None
        if team_col and SNAP_WEEK in df.columns:
            df = df.with_columns(
                (
                    pl.col(SNAP_OFFENSE_SNAPS).fill_null(0)
                    / pl.col(SNAP_OFFENSE_SNAPS).fill_null(0).sum().over([team_col, SNAP_WEEK])
                ).alias("_share")
            )
            return df, "_share"
    return df, None


def _mean_shares(df: pl.DataFrame, id_col: str, off_col: str) -> dict[str, float]:
    """Mean per-game share. One row per game the player was on the game roster —
    inactive / IR / bye / suspended weeks have no row, so they are excluded from the
    denominator rather than averaged in as zeros (tech spec §5.10.2, D18)."""
    out: dict[str, float] = {}
    for r in (
        df.group_by(id_col).agg(pl.col(off_col).fill_null(0).mean().alias(off_col)).to_dicts()
    ):
        pid = r.get(id_col)
        if pid is None:
            continue
        val = float(r[off_col] or 0)
        out[str(pid)] = val / (100.0 if val > 1.5 else 1.0)
    return out


def _mean_shares_by_team(
    df: pl.DataFrame, id_col: str, team_col: str, off_col: str
) -> dict[tuple[str, str], float]:
    """Same games-played denominator as ``_mean_shares``, keyed (player, team)."""
    out: dict[tuple[str, str], float] = {}
    for r in (
        df.group_by([id_col, team_col])
        .agg(pl.col(off_col).fill_null(0).mean().alias(off_col))
        .to_dicts()
    ):
        pid = r.get(id_col)
        team = r.get(team_col)
        if pid is None or team is None:
            continue
        val = float(r[off_col] or 0)
        out[(str(pid), str(team).upper())] = val / (100.0 if val > 1.5 else 1.0)
    return out


def _pfr_to_gsis_map(players: pl.DataFrame) -> dict[str, str]:
    if players.is_empty() or PLAYERS_PFR_ID not in players.columns:
        return {}
    gsis_col = PLAYERS_GSIS_ID if PLAYERS_GSIS_ID in players.columns else None
    if not gsis_col:
        return {}
    out: dict[str, str] = {}
    for r in (
        players.filter(pl.col(PLAYERS_PFR_ID).is_not_null() & pl.col(gsis_col).is_not_null())
        .select([PLAYERS_PFR_ID, gsis_col])
        .to_dicts()
    ):
        out[str(r[PLAYERS_PFR_ID])] = str(r[gsis_col])
    return out


def _crosswalk_share_keys(
    shares: dict[str, float],
    *,
    id_col: str,
    pfr_to_gsis: dict[str, str],
    pfr_ids_seen: set[str],
) -> dict[str, float]:
    """Remap PFR-keyed shares to gsis_id. Enforce hit-rate halt over pfr_ids_seen."""
    if id_col != SNAP_PFR_PLAYER_ID:
        return shares

    total = len(pfr_ids_seen)
    if total == 0:
        return {}
    mapped = sum(1 for p in pfr_ids_seen if p in pfr_to_gsis)
    hit_rate = mapped / total
    if hit_rate < SNAP_CROSSWALK_MIN_HIT_RATE:
        raise SnapCrosswalkError(
            f"Snap PFR→gsis crosswalk hit rate {hit_rate:.1%} "
            f"({mapped}/{total}) below minimum {SNAP_CROSSWALK_MIN_HIT_RATE:.0%}"
        )

    out: dict[str, float] = {}
    for pfr_id, share in shares.items():
        gsis = pfr_to_gsis.get(pfr_id)
        if gsis is None:
            continue
        # If duplicate PFR maps collide (shouldn't), keep max share
        out[gsis] = max(out.get(gsis, 0.0), share)
    return out


def derive_snap_shares(
    snap_counts: pl.DataFrame,
    season: int,
    through_week: int,
    prior_snaps: pl.DataFrame | None = None,
    *,
    week: int | None = None,
    prior_week_lo: int | None = None,
    prior_week_hi: int | None = None,
    players: pl.DataFrame | None = None,
) -> dict[str, float]:
    """
    Offense snap share keyed by gsis_id for picker lookup.

    Live S4 frames are keyed on ``pfr_player_id``; pass ``players`` (S7) to
    crosswalk via ``pfr_id``. Hit rate below ``SNAP_CROSSWALK_MIN_HIT_RATE``
    raises ``SnapCrosswalkError``.
    """
    blend_week = week if week is not None else through_week
    if snap_counts.is_empty() and (prior_snaps is None or prior_snaps.is_empty()):
        return {}

    needs_crosswalk = False
    frames = [snap_counts]
    if prior_snaps is not None and not prior_snaps.is_empty():
        frames.append(prior_snaps)
    for frame in frames:
        if not frame.is_empty() and SNAP_PFR_PLAYER_ID in frame.columns:
            needs_crosswalk = True
            break

    pfr_to_gsis: dict[str, str] = {}
    if needs_crosswalk:
        if players is None or players.is_empty():
            raise SnapCrosswalkError(
                "Snap counts use pfr_player_id but players catalog was not provided for crosswalk"
            )
        pfr_to_gsis = _pfr_to_gsis_map(players)
        if not pfr_to_gsis:
            raise SnapCrosswalkError("Players catalog has no usable pfr_id → gsis_id pairs")

    pfr_ids_seen: set[str] = set()

    def _collect_pfr(df: pl.DataFrame) -> None:
        if SNAP_PFR_PLAYER_ID in df.columns:
            pfr_ids_seen.update(
                str(x) for x in df[SNAP_PFR_PLAYER_ID].drop_nulls().unique().to_list()
            )

    cur: dict[str, float] = {}
    cur_id_col: str | None = None
    if not snap_counts.is_empty():
        df = snap_counts
        if "season" in df.columns:
            df = df.filter(pl.col("season") == season)
        if through_week > 0 and "week" in df.columns:
            df = df.filter(pl.col("week") <= through_week)
        elif through_week <= 0:
            df = df.head(0)

        cur_id_col = _snap_id_col(df) if not df.is_empty() else None
        if cur_id_col and not df.is_empty():
            _collect_pfr(df)
            df, off_col = _offense_share_col(df)
            if off_col:
                cur = _mean_shares(df, cur_id_col, off_col)

    if not is_blended_week(blend_week) or prior_snaps is None or prior_snaps.is_empty():
        return _crosswalk_share_keys(
            cur,
            id_col=cur_id_col or "gsis_id",
            pfr_to_gsis=pfr_to_gsis,
            pfr_ids_seen=pfr_ids_seen,
        )

    if prior_week_lo is None or prior_week_hi is None:
        max_reg = max_reg_week_from_frames(season - 1, prior_snaps, snap_counts)
        prior_week_lo, prior_week_hi = rb_prior_snap_week_window(max_reg)

    prior = prior_snaps
    if "season" in prior.columns:
        prior = prior.filter(pl.col("season") == season - 1)
    if "week" in prior.columns:
        prior = prior.filter(
            (pl.col("week") >= prior_week_lo) & (pl.col("week") <= prior_week_hi)
        )

    prior_id_col = _snap_id_col(prior)
    if not prior_id_col:
        return _crosswalk_share_keys(
            cur,
            id_col=cur_id_col or "gsis_id",
            pfr_to_gsis=pfr_to_gsis,
            pfr_ids_seen=pfr_ids_seen,
        )
    _collect_pfr(prior)
    prior, off_col = _offense_share_col(prior)
    if not off_col:
        return _crosswalk_share_keys(
            cur,
            id_col=cur_id_col or "gsis_id",
            pfr_to_gsis=pfr_to_gsis,
            pfr_ids_seen=pfr_ids_seen,
        )
    prior_map = _mean_shares(prior, prior_id_col, off_col)

    # Blend in native id space (both PFR or both gsis), then crosswalk once
    blended = {
        pid: blend_rates(
            prior_map.get(pid, cur.get(pid, 0.0)),
            cur.get(pid, prior_map.get(pid, 0.0)),
            blend_week,
        )
        for pid in set(cur) | set(prior_map)
    }
    # Prefer prior_id_col if cur empty
    id_col = cur_id_col or prior_id_col
    return _crosswalk_share_keys(
        blended,
        id_col=id_col,
        pfr_to_gsis=pfr_to_gsis,
        pfr_ids_seen=pfr_ids_seen,
    )


def target_shares_by_team(
    player_stats: pl.DataFrame,
    season: int,
    week_lo: int,
    week_hi: int,
    positions: tuple[str, ...] = ("WR",),
) -> dict[tuple[str, str], float]:
    """(player_id, team) -> mean per-game share of team targets over [week_lo, week_hi].

    Per §5.10.2 / D18 the denominator is **games the player played**, so the share is
    computed within each game and then averaged over the games he has a stats row for.
    Summing targets across the window and dividing by the team's window total would
    put games he missed into his denominator, diluting a healthy player's real role.
    """
    if player_stats.is_empty() or PS_TARGETS not in player_stats.columns:
        return {}
    ps = player_stats
    if "season" in ps.columns:
        ps = ps.filter(pl.col("season") == season)
    if "week" in ps.columns:
        ps = ps.filter((pl.col("week") >= week_lo) & (pl.col("week") <= week_hi))
    if "position" in ps.columns:
        wanted = [p.upper() for p in positions]
        ps = ps.filter(pl.col("position").cast(pl.Utf8).str.to_uppercase().is_in(wanted))
    if ps.is_empty():
        return {}
    id_col = PS_PLAYER_ID if PS_PLAYER_ID in ps.columns else "gsis_id"
    team_col = PS_TEAM if PS_TEAM in ps.columns else ("recent_team" if "recent_team" in ps.columns else None)
    if id_col not in ps.columns or not team_col:
        return {}

    tgt = pl.col(PS_TARGETS).fill_null(0)
    # Group targets within a single game when a week column exists; without one the
    # frame is treated as a single period (fixtures, aggregated inputs).
    over = [team_col, "week"] if "week" in ps.columns else [team_col]
    team_tgt = tgt.sum().over(over)
    ps = ps.with_columns(
        pl.when(team_tgt > 0).then(tgt / team_tgt).otherwise(0.0).alias("_gshare")
    )
    return _mean_shares_by_team(ps, id_col, team_col, "_gshare")


def snap_shares_by_team(
    snap_counts: pl.DataFrame,
    season: int,
    week_lo: int,
    week_hi: int,
    positions: tuple[str, ...] = ("RB", "FB"),
    *,
    players: pl.DataFrame | None = None,
) -> dict[tuple[str, str], float]:
    """(gsis_id, team) -> mean per-game offensive snap share over [week_lo, week_hi].

    Team-keyed counterpart of ``derive_snap_shares``. Games-played denominator per
    §5.10.2 / D18 — missed games are excluded, never counted as zero.
    """
    if snap_counts.is_empty():
        return {}
    df = snap_counts
    if "season" in df.columns:
        df = df.filter(pl.col("season") == season)
    if SNAP_WEEK in df.columns:
        df = df.filter((pl.col(SNAP_WEEK) >= week_lo) & (pl.col(SNAP_WEEK) <= week_hi))
    if df.is_empty() or SNAP_TEAM not in df.columns:
        return {}

    id_col = _snap_id_col(df)
    if not id_col:
        return {}
    # Share must be computed against the whole team's offensive snaps, so derive it
    # before narrowing to the position group.
    df, off_col = _offense_share_col(df)
    if not off_col:
        return {}
    if SNAP_POSITION in df.columns:
        wanted = [p.upper() for p in positions]
        df = df.filter(pl.col(SNAP_POSITION).cast(pl.Utf8).str.to_uppercase().is_in(wanted))
    if df.is_empty():
        return {}
    shares = _mean_shares_by_team(df, id_col, SNAP_TEAM, off_col)
    if id_col != SNAP_PFR_PLAYER_ID:
        return shares

    if players is None or players.is_empty():
        raise SnapCrosswalkError(
            "Snap counts use pfr_player_id but players catalog was not provided for crosswalk"
        )
    pfr_to_gsis = _pfr_to_gsis_map(players)
    out: dict[tuple[str, str], float] = {}
    for (pfr_id, team), share in shares.items():
        gsis = pfr_to_gsis.get(pfr_id)
        if gsis is None:
            continue
        out[(gsis, team)] = max(out.get((gsis, team), 0.0), share)
    return out


def _depth_order_by_player(depth_charts: pl.DataFrame, through_week: int) -> dict[str, int]:
    """Depth order keyed by gsis_id — uses pos_rank on the pinned snapshot."""
    if depth_charts.is_empty():
        return {}
    dc = pin_depth_to_latest_week(depth_charts, max(through_week, 1))
    id_col = DEPTH_GSIS_ID if DEPTH_GSIS_ID in dc.columns else PS_PLAYER_ID
    order_col = DEPTH_POS_RANK if DEPTH_POS_RANK in dc.columns else (
        "depth_chart_order" if "depth_chart_order" in dc.columns else None
    )
    if id_col not in dc.columns or order_col is None:
        return {}
    # Prefer WR rows when a player appears at multiple pos_abb (rare)
    if DEPTH_POS_ABB in dc.columns:
        wr = dc.filter(pl.col(DEPTH_POS_ABB).cast(pl.Utf8).str.to_uppercase() == "WR")
        if wr.height:
            dc = wr
    out: dict[str, int] = {}
    for r in dc.to_dicts():
        if r.get(id_col) is None:
            continue
        out[str(r[id_col])] = int(r.get(order_col) or 99)
    return out


def derive_roles(
    player_stats: pl.DataFrame,
    depth_charts: pl.DataFrame,
    injuries: dict[str, InjuryRecord],
    season: int,
    through_week: int,
    *,
    week: int | None = None,
    prior_week_lo: int | None = None,
    prior_week_hi: int | None = None,
    current_only: bool = False,
) -> tuple[dict[str, str], dict[str, float], dict[str, str]]:
    """Returns roles, target_share, qb1_by_team per §5.9.

    Depth chart uses pinned ``dt`` / ``week`` snapshot with ``pos_abb`` + ``pos_rank``.
    WR roles remain target-share primary (tech spec §5.9 / D6); depth ``pos_rank``
    is the 1pp tiebreak only.

    ``current_only`` drops the prior-season component of the WR target-share blend
    while keeping the depth-chart snapshot pinned to the real week. That yields the
    usage half of the depth blend, which ``pos_rank`` fades into across Weeks 1–4
    (§5.10.1).
    """
    roles: dict[str, str] = {}
    target_share: dict[str, float] = {}
    qb1_by_team: dict[str, str] = {}
    pin_week = week if week is not None else max(through_week, 1)
    blend_week = pin_week
    if current_only:
        blend_week = 5  # any week past the blending window

    # Depth chart orders + QB1 / TE1 / RB — always on pinned snapshot
    if not depth_charts.is_empty():
        dc = pin_depth_to_latest_week(depth_charts, pin_week)
        id_col = DEPTH_GSIS_ID if DEPTH_GSIS_ID in dc.columns else PS_PLAYER_ID
        pos_col = DEPTH_POS_ABB if DEPTH_POS_ABB in dc.columns else (
            "position" if "position" in dc.columns else ("pos" if "pos" in dc.columns else None)
        )
        team_col = DEPTH_TEAM
        order_col = DEPTH_POS_RANK if DEPTH_POS_RANK in dc.columns else (
            "depth_chart_order" if "depth_chart_order" in dc.columns else None
        )
        if id_col in dc.columns and pos_col and team_col in dc.columns:
            for team in dc[team_col].unique().to_list():
                tdf = dc.filter(pl.col(team_col) == team)
                team_key = str(team).upper()
                # QB1 with promotion
                qbs = tdf.filter(pl.col(pos_col).cast(pl.Utf8).str.to_uppercase() == "QB")
                if order_col:
                    qbs = qbs.sort(order_col)
                for r in qbs.to_dicts():
                    pid = str(r[id_col]) if r[id_col] is not None else ""
                    if not pid or pid == "None":
                        continue
                    order = int(r.get(order_col) or 99)
                    roles[pid] = f"QB{order}"
                    if order == DEPTH_STARTER_RANK or (
                        qb1_by_team.get(team_key) is None
                        and not (injuries.get(pid) and injuries[pid].is_unavailable)
                    ):
                        if pid not in injuries or not injuries[pid].is_unavailable:
                            qb1_by_team.setdefault(team_key, pid)
                if team_key not in qb1_by_team:
                    for r in qbs.to_dicts():
                        if r[id_col] is None:
                            continue
                        qb1_by_team[team_key] = str(r[id_col])
                        break
                # TE depth with effective-start promotion
                tes = tdf.filter(pl.col(pos_col).cast(pl.Utf8).str.to_uppercase() == "TE")
                if order_col:
                    tes = tes.sort(order_col)
                te1 = None
                for r in tes.to_dicts():
                    if r[id_col] is None:
                        continue
                    pid = str(r[id_col])
                    order = int(r.get(order_col) or 99)
                    available = pid not in injuries or not injuries[pid].is_unavailable
                    if te1 is None and available:
                        te1 = pid
                        roles[pid] = "TE1"
                    elif order == DEPTH_STARTER_RANK and not available:
                        # Chart TE1 is out — do not keep the TE1 label (promoted TE gets it)
                        roles[pid] = "TE1_OUT"
                    else:
                        roles[pid] = f"TE{order}"
                # RB depth labels by pos_rank order
                rbs = tdf.filter(
                    pl.col(pos_col).cast(pl.Utf8).str.to_uppercase().is_in(["RB", "FB"])
                )
                if order_col:
                    rbs = rbs.sort(order_col)
                for i, r in enumerate(rbs.to_dicts(), start=1):
                    if r[id_col] is None:
                        continue
                    roles[str(r[id_col])] = f"RB{i}"

    # WR roles by trailing / blended target share (§5.9)
    cur_shares: dict[tuple[str, str], float] = {}
    if through_week > 0:
        lo = max(1, through_week - 3)
        cur_shares = target_shares_by_team(player_stats, season, lo, through_week)

    prior_shares: dict[tuple[str, str], float] = {}
    if is_blended_week(blend_week):
        if prior_week_lo is None or prior_week_hi is None:
            max_reg = max_reg_week_from_frames(season - 1, player_stats)
            prior_week_lo, prior_week_hi = prior_season_week_window(max_reg)
        prior_shares = target_shares_by_team(
            player_stats, season - 1, prior_week_lo, prior_week_hi
        )

    keys = set(cur_shares) | set(prior_shares)
    blended: dict[tuple[str, str], float] = {}
    for key in keys:
        c = cur_shares.get(key)
        p = prior_shares.get(key)
        if is_blended_week(blend_week) and (p is not None or c is not None):
            blended[key] = blend_rates(p or 0.0, c or 0.0, blend_week)
        elif c is not None:
            blended[key] = c

    depth_orders = _depth_order_by_player(depth_charts, through_week)
    by_team: dict[str, list[tuple[str, float]]] = {}
    for (pid, team), share in blended.items():
        by_team.setdefault(team, []).append((pid, share))

    for team, rows in by_team.items():
        # Sort share desc; within 1pp prefer lower pos_rank (depth tiebreak, §5.9)
        rows.sort(key=lambda x: (-x[1], depth_orders.get(x[0], 99), x[0]))
        # Re-order any pair within 0.01 by depth (insertion over near-ties)
        for i in range(1, len(rows)):
            j = i
            while j > 0 and abs(rows[j][1] - rows[j - 1][1]) <= 0.01:
                prev_o = depth_orders.get(rows[j - 1][0], 99)
                cur_o = depth_orders.get(rows[j][0], 99)
                if cur_o < prev_o or (cur_o == prev_o and rows[j][0] < rows[j - 1][0]):
                    rows[j - 1], rows[j] = rows[j], rows[j - 1]
                    j -= 1
                else:
                    break
        for i, (pid, share) in enumerate(rows, start=1):
            target_share[pid] = share
            roles[pid] = f"WR{min(i, 4)}" if i <= 3 else "WR4+"

    return roles, target_share, qb1_by_team
