"""Opportunity Share board — docs/depth-chart/opportunity_share.md Steps 3–7.

Full section payload for one team: Target / Rush / RZ Target / RZ Rush shares,
Qty, GP badges, bellcow, and team RZ play mix. True Depth Chart keeps using
the lighter Target/Rush helpers in opportunity_share.py; this module is the
Opportunity Share page pipeline.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import polars as pl

from brady_bot.derive.opportunity_share import (
    _regular_season_frame,
    _round1,
    _weekly_rush_share,
    _weekly_target_share,
    is_bellcow,
)
from brady_bot.normalizer import normalize_team
from brady_bot.sources.schema import (
    PS_PLAYER_ID,
    PS_PLAYER_NAME,
    PS_POSITION,
    PS_TEAM,
    PS_WEEK,
)

PBP_WEEK = "week"
PBP_POSTEAM = "posteam"
PBP_PLAY_TYPE = "play_type"
PBP_YARDLINE_100 = "yardline_100"
PBP_RECEIVER_ID = "receiver_player_id"
PBP_RUSHER_ID = "rusher_player_id"
PBP_SEASON_TYPE = "season_type"

OFFENSIVE_PLAY_TYPES = frozenset({"pass", "run"})


@dataclass(frozen=True)
class RzMix:
    rz_plays: int
    rz_pass_pct: float | None
    rz_rush_pct: float | None
    rz_pass_plays: int = 0
    rz_rush_plays: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "rz_plays": self.rz_plays,
            "rz_pass_pct": self.rz_pass_pct,
            "rz_rush_pct": self.rz_rush_pct,
        }


def completed_weeks(player_stats: pl.DataFrame) -> tuple[int, ...]:
    df = _regular_season_frame(player_stats)
    if df.is_empty() or PS_WEEK not in df.columns:
        return ()
    return tuple(sorted(int(w) for w in df[PS_WEEK].unique().to_list()))


def _pbp_week(pbp: pl.DataFrame, week: int) -> pl.DataFrame:
    if pbp.is_empty():
        return pbp
    df = pbp
    if PBP_SEASON_TYPE in df.columns:
        df = df.filter(pl.col(PBP_SEASON_TYPE) == "REG")
    if PBP_WEEK in df.columns:
        df = df.filter(pl.col(PBP_WEEK) == week)
    return df


def _team_rz_mix(rz: pl.DataFrame, team: str, aliases: dict[str, str]) -> RzMix:
    if rz.is_empty() or PBP_POSTEAM not in rz.columns:
        return RzMix(rz_plays=0, rz_pass_pct=None, rz_rush_pct=None)
    rows = [
        r
        for r in rz.to_dicts()
        if normalize_team(str(r.get(PBP_POSTEAM) or ""), aliases) == team
    ]
    if not rows:
        return RzMix(rz_plays=0, rz_pass_pct=None, rz_rush_pct=None)
    plays = len(rows)
    pass_plays = sum(1 for r in rows if r.get(PBP_PLAY_TYPE) == "pass")
    rush_plays = sum(1 for r in rows if r.get(PBP_PLAY_TYPE) == "run")
    return RzMix(
        rz_plays=plays,
        rz_pass_plays=pass_plays,
        rz_rush_plays=rush_plays,
        rz_pass_pct=_round1(pass_plays / plays * 100) if plays else None,
        rz_rush_pct=_round1(rush_plays / plays * 100) if plays else None,
    )


def _rz_target_shares(rz: pl.DataFrame, aliases: dict[str, str]) -> dict[tuple[str, str], dict]:
    if rz.is_empty():
        return {}
    rz_pass = rz.filter(
        (pl.col(PBP_PLAY_TYPE) == "pass") & pl.col(PBP_RECEIVER_ID).is_not_null()
    )
    if rz_pass.is_empty():
        return {}
    out: dict[tuple[str, str], dict] = {}
    # Count per (team, player), then divide by team totals.
    counts: dict[tuple[str, str], int] = defaultdict(int)
    team_totals: dict[str, int] = defaultdict(int)
    for r in rz_pass.to_dicts():
        team = normalize_team(str(r.get(PBP_POSTEAM) or ""), aliases)
        pid = str(r.get(PBP_RECEIVER_ID) or "")
        if not team or not pid:
            continue
        counts[(team, pid)] += 1
        team_totals[team] += 1
    for (team, pid), n in counts.items():
        denom = team_totals[team]
        out[(team, pid)] = {
            "rz_targets": n,
            "rz_target_share_pct": _round1(n / denom * 100) if denom else None,
        }
    return out


def _rz_rush_shares(rz: pl.DataFrame, aliases: dict[str, str]) -> dict[tuple[str, str], dict]:
    if rz.is_empty():
        return {}
    rz_run = rz.filter(
        (pl.col(PBP_PLAY_TYPE) == "run") & pl.col(PBP_RUSHER_ID).is_not_null()
    )
    if rz_run.is_empty():
        return {}
    counts: dict[tuple[str, str], int] = defaultdict(int)
    team_totals: dict[str, int] = defaultdict(int)
    for r in rz_run.to_dicts():
        team = normalize_team(str(r.get(PBP_POSTEAM) or ""), aliases)
        pid = str(r.get(PBP_RUSHER_ID) or "")
        if not team or not pid:
            continue
        counts[(team, pid)] += 1
        team_totals[team] += 1
    out: dict[tuple[str, str], dict] = {}
    for (team, pid), n in counts.items():
        denom = team_totals[team]
        out[(team, pid)] = {
            "rz_carries": n,
            "rz_rush_share_pct": _round1(n / denom * 100) if denom else None,
        }
    return out


def compute_week_rows(
    player_stats: pl.DataFrame,
    pbp: pl.DataFrame,
    week: int,
    team: str,
    team_aliases: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], RzMix]:
    """Steps 3–6 for one team in one week."""
    aliases = team_aliases or {}
    team = normalize_team(team, aliases)
    df = _regular_season_frame(player_stats)
    if df.is_empty():
        return [], RzMix(rz_plays=0, rz_pass_pct=None, rz_rush_pct=None)
    df = df.filter(pl.col(PS_WEEK) == week)
    if df.is_empty():
        return [], RzMix(rz_plays=0, rz_pass_pct=None, rz_rush_pct=None)

    tgt = _weekly_target_share(df).to_dicts()
    rsh = _weekly_rush_share(df).to_dicts()

    tgt_map: dict[str, dict] = {}
    rsh_map: dict[str, dict] = {}
    for r in tgt:
        if normalize_team(str(r[PS_TEAM]), aliases) != team:
            continue
        tgt_map[str(r[PS_PLAYER_ID])] = r
    for r in rsh:
        if normalize_team(str(r[PS_TEAM]), aliases) != team:
            continue
        rsh_map[str(r[PS_PLAYER_ID])] = r

    pbp_w = _pbp_week(pbp, week)
    plays = pbp_w
    if not plays.is_empty() and PBP_PLAY_TYPE in plays.columns:
        plays = plays.filter(pl.col(PBP_PLAY_TYPE).is_in(list(OFFENSIVE_PLAY_TYPES)))
    rz = plays
    if not rz.is_empty() and PBP_YARDLINE_100 in rz.columns:
        rz = rz.filter(pl.col(PBP_YARDLINE_100) <= 20)
    else:
        rz = pl.DataFrame()

    rz_mix = _team_rz_mix(rz, team, aliases)
    rz_tgt = _rz_target_shares(rz, aliases)
    rz_rsh = _rz_rush_shares(rz, aliases)

    rows: list[dict[str, Any]] = []
    for pid in set(tgt_map) | set(rsh_map):
        t = tgt_map.get(pid)
        r = rsh_map.get(pid)
        base = t or r
        assert base is not None
        rzt = rz_tgt.get((team, pid))
        rzr = rz_rsh.get((team, pid))
        # RZ fill: 0.0 when player qualifies for that metric's population but
        # had no RZ look/carry; null when the metric does not apply.
        if t is not None:
            rz_targets = rzt["rz_targets"] if rzt else 0
            rz_target_pct = rzt["rz_target_share_pct"] if rzt else 0.0
        else:
            rz_targets = None
            rz_target_pct = None
        if r is not None:
            rz_carries = rzr["rz_carries"] if rzr else 0
            rz_rush_pct = rzr["rz_rush_share_pct"] if rzr else 0.0
        else:
            rz_carries = None
            rz_rush_pct = None

        targets = int(t["targets"]) if t else None
        carries = int(r["carries"]) if r else None
        tgt_pct = float(t["target_share_pct"]) if t and t.get("target_share_pct") is not None else None
        rsh_pct = float(r["rush_share_pct"]) if r and r.get("rush_share_pct") is not None else None
        touches = (targets or 0) + (carries or 0)
        position = str(
            (t or {}).get(PS_POSITION) or (r or {}).get(PS_POSITION) or ("RB" if r else "")
        )
        rows.append(
            {
                "team": team,
                "player_id": pid,
                "player": str(base.get(PS_PLAYER_NAME) or ""),
                "position": position,
                "targets": targets,
                "target_share_pct": _round1(tgt_pct),
                "carries": carries,
                "rush_share_pct": _round1(rsh_pct),
                "rz_targets": rz_targets,
                "rz_target_share_pct": _round1(rz_target_pct),
                "rz_carries": rz_carries,
                "rz_rush_share_pct": _round1(rz_rush_pct),
                "touches": touches,
                "gp": 1,
                "gp_tgt": 1 if tgt_pct is not None else 0,
                "gp_rsh": 1 if rsh_pct is not None else 0,
                "bellcow": position == "RB" and is_bellcow(rsh_pct),
            }
        )

    rows.sort(key=lambda row: (-row["touches"], row["player"]))
    return rows, rz_mix


def _mean(vals: list[float | None]) -> float | None:
    cleaned = [float(v) for v in vals if v is not None]
    return _round1(sum(cleaned) / len(cleaned)) if cleaned else None


def compute_all_rows(
    player_stats: pl.DataFrame,
    pbp: pl.DataFrame,
    team: str,
    team_aliases: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], RzMix, tuple[int, ...]]:
    """Step 7 All-view for one team over completed weeks."""
    aliases = team_aliases or {}
    team = normalize_team(team, aliases)
    weeks = completed_weeks(player_stats)
    if not weeks:
        return [], RzMix(rz_plays=0, rz_pass_pct=None, rz_rush_pct=None), ()

    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    mix_weeks: list[RzMix] = []
    for w in weeks:
        rows, mix = compute_week_rows(player_stats, pbp, w, team, aliases)
        if mix.rz_plays > 0:
            mix_weeks.append(mix)
        for row in rows:
            by_player[row["player_id"]].append(row)

    # Cumulative RZ mix (Step 7) — sum plays, not average of weekly %.
    if mix_weeks:
        pass_plays = sum(m.rz_pass_plays for m in mix_weeks)
        rush_plays = sum(m.rz_rush_plays for m in mix_weeks)
        total = pass_plays + rush_plays
        all_mix = RzMix(
            rz_plays=total,
            rz_pass_plays=pass_plays,
            rz_rush_plays=rush_plays,
            rz_pass_pct=_round1(pass_plays / total * 100) if total else None,
            rz_rush_pct=_round1(rush_plays / total * 100) if total else None,
        )
    else:
        all_mix = RzMix(rz_plays=0, rz_pass_pct=None, rz_rush_pct=None)

    out: list[dict[str, Any]] = []
    for pid, weekly in by_player.items():
        latest = weekly[-1]
        tgt_weeks = [w for w in weekly if w["target_share_pct"] is not None]
        rsh_weeks = [w for w in weekly if w["rush_share_pct"] is not None]
        targets = sum(w["targets"] for w in tgt_weeks) if tgt_weeks else None
        carries = sum(w["carries"] for w in rsh_weeks) if rsh_weeks else None
        tgt_pct = _mean([float(w["target_share_pct"]) for w in tgt_weeks])
        rsh_pct = _mean([float(w["rush_share_pct"]) for w in rsh_weeks])
        rz_targets = (
            sum(w["rz_targets"] or 0 for w in tgt_weeks) if tgt_weeks else None
        )
        rz_carries = (
            sum(w["rz_carries"] or 0 for w in rsh_weeks) if rsh_weeks else None
        )
        rz_tgt_pct = (
            _mean([float(w["rz_target_share_pct"]) for w in tgt_weeks])
            if tgt_weeks
            else None
        )
        rz_rsh_pct = (
            _mean([float(w["rz_rush_share_pct"]) for w in rsh_weeks])
            if rsh_weeks
            else None
        )
        position = latest["position"]
        out.append(
            {
                "team": team,
                "player_id": pid,
                "player": latest["player"],
                "position": position,
                "targets": targets,
                "target_share_pct": tgt_pct,
                "carries": carries,
                "rush_share_pct": rsh_pct,
                "rz_targets": rz_targets,
                "rz_target_share_pct": rz_tgt_pct,
                "rz_carries": rz_carries,
                "rz_rush_share_pct": rz_rsh_pct,
                "touches": (targets or 0) + (carries or 0),
                "gp": len(weekly),
                "gp_tgt": len(tgt_weeks),
                "gp_rsh": len(rsh_weeks),
                "bellcow": position == "RB" and is_bellcow(rsh_pct),
            }
        )

    out.sort(key=lambda row: (-row["touches"], row["player"]))
    return out, all_mix, weeks


def build_team_board(
    player_stats: pl.DataFrame,
    pbp: pl.DataFrame,
    team: str,
    view: str,
    *,
    season: int,
    team_aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    """API payload for one team and view (`all` or a week number string)."""
    aliases = team_aliases or {}
    team = normalize_team(team, aliases)
    weeks = completed_weeks(player_stats)

    if view == "all":
        rows, rz_mix, _ = compute_all_rows(player_stats, pbp, team, aliases)
        return {
            "team": team,
            "view": "all",
            "season": season,
            "season_group_label": "Season to Date",
            "rz_mix": rz_mix.as_dict(),
            "rows": rows,
            "completed_weeks": list(weeks),
        }

    try:
        week_num = int(view)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid view {view!r}") from e

    rows, rz_mix = compute_week_rows(player_stats, pbp, week_num, team, aliases)
    return {
        "team": team,
        "view": week_num,
        "season": season,
        "season_group_label": "Season",
        "rz_mix": rz_mix.as_dict(),
        "rows": rows,
        "completed_weeks": list(weeks),
    }
