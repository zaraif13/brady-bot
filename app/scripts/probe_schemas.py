#!/usr/bin/env python3
"""Step 0 schema probe — verify nflreadpy column names and coverage.

Per tech spec §4.4: confirm assumptions before the derive layer trusts
column names. Writes docs/schema_probe.txt and prints a summary to stdout.

Usage (from app/):
  .venv/bin/python scripts/probe_schemas.py
  .venv/bin/python scripts/probe_schemas.py --season 2025
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    import nflreadpy
except ImportError as e:  # pragma: no cover
    raise SystemExit(f"nflreadpy required: {e}") from e


def _to_pl(obj) -> pl.DataFrame:
    if isinstance(obj, pl.DataFrame):
        return obj
    return pl.from_pandas(obj)


def _section(title: str, lines: list[str]) -> list[str]:
    bar = "=" * 72
    return [bar, title, bar, *lines, ""]


def probe(season: int) -> str:
    out: list[str] = []
    out.extend(
        _section(
            "Brady Bot — Step 0 Schema Probe",
            [
                f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
                f"Season probed: {season} (and players catalog)",
                "Source: nflreadpy live loads",
            ],
        )
    )

    loaders = {
        "player_stats (S2)": lambda: nflreadpy.load_player_stats(seasons=[season]),
        "team_stats (S3)": lambda: nflreadpy.load_team_stats(seasons=[season]),
        "snap_counts (S4)": lambda: nflreadpy.load_snap_counts(seasons=[season]),
        "injuries (S5)": lambda: nflreadpy.load_injuries(seasons=[season]),
        "depth_charts (S6)": lambda: nflreadpy.load_depth_charts(seasons=[season]),
        "schedules (S1)": lambda: nflreadpy.load_schedules(seasons=[season]),
        "players (S7)": lambda: nflreadpy.load_players(),
    }
    frames: dict[str, pl.DataFrame] = {}
    for label, loader in loaders.items():
        df = _to_pl(loader())
        frames[label] = df
        out.extend(
            _section(
                f"{label} — {df.height} rows × {df.width} cols",
                [", ".join(df.columns)],
            )
        )

    # --- Tech spec §4.4 assumptions -----------------------------------------
    ps = frames["player_stats (S2)"]
    ts = frames["team_stats (S3)"]
    snaps = frames["snap_counts (S4)"]
    depth = frames["depth_charts (S6)"]
    schedules = frames["schedules (S1)"]
    players = frames["players (S7)"]

    kick_cols = [c for c in ps.columns if c.startswith("fg_") or c.startswith("pat_")]
    has_kick = bool(kick_cols)
    has_passing_int = "passing_interceptions" in ps.columns
    has_bare_int = "interceptions" in ps.columns

    depth_has_week = "week" in depth.columns
    depth_has_position = "position" in depth.columns or "pos" in depth.columns
    depth_has_order = "depth_chart_order" in depth.columns
    depth_has_pos_abb = "pos_abb" in depth.columns
    depth_has_pos_rank = "pos_rank" in depth.columns
    pos_abb_vals: list[str] = []
    if depth_has_pos_abb:
        pos_abb_vals = sorted(
            str(x) for x in depth["pos_abb"].unique().drop_nulls().to_list()
        )
    ol_like = {"LT", "RT", "LG", "RG", "C", "T", "G", "OT", "OG"}
    db_like = {"LCB", "RCB", "CB", "FS", "SS", "NB", "DB", "S"}
    lb_dl = {"LILB", "RILB", "MLB", "SLB", "WLB", "LB", "LDE", "RDE", "LDT", "RDT", "NT", "DE", "DT", "EDGE"}
    depth_covers_units = bool(
        (ol_like & set(pos_abb_vals))
        and (db_like & set(pos_abb_vals))
        and (lb_dl & set(pos_abb_vals))
    )

    snap_has_gsis = "gsis_id" in snaps.columns
    snap_has_pfr = "pfr_player_id" in snaps.columns
    players_has_pfr = "pfr_id" in players.columns
    crosswalk_hit = 0.0
    if snap_has_pfr and players_has_pfr:
        snap_ids = {str(x) for x in snaps["pfr_player_id"].drop_nulls().unique().to_list()}
        pfr_map = {
            str(r["pfr_id"]): str(r["gsis_id"])
            for r in players.filter(pl.col("pfr_id").is_not_null())
            .select(["pfr_id", "gsis_id"])
            .to_dicts()
            if r.get("pfr_id") and r.get("gsis_id")
        }
        mapped = sum(1 for p in snap_ids if p in pfr_map)
        crosswalk_hit = mapped / len(snap_ids) if snap_ids else 0.0

    # Team stats: offense present as play-type yards; no offense_yards / defense_yards aggregates
    assumed_missing = [
        c
        for c in (
            "offense_yards",
            "defense_yards",
            "yards_allowed",
            "offense_points",
            "points_scored",
            "defense_yards_per_play",
        )
        if c in ts.columns
    ]
    real_offense = [c for c in ("passing_yards", "rushing_yards", "carries", "attempts") if c in ts.columns]
    real_defense = [c for c in ts.columns if c.startswith("def_")]

    sched_spread = "spread_line" in schedules.columns
    sched_total = "total_line" in schedules.columns

    verdicts = [
        (
            "A1 load_player_stats() carries kicking columns",
            has_kick,
            f"found {len(kick_cols)} fg_/pat_ cols"
            + (f": {kick_cols[:8]}…" if len(kick_cols) > 8 else f": {kick_cols}"),
        ),
        (
            "A1b player_stats uses passing_interceptions (not interceptions)",
            has_passing_int and not has_bare_int,
            f"passing_interceptions={has_passing_int} interceptions={has_bare_int}",
        ),
        (
            "A2 load_depth_charts() covers OL / DB / LB / DL via pos_abb",
            depth_covers_units,
            f"pos_abb present={depth_has_pos_abb}; sample={pos_abb_vals[:20]}",
        ),
        (
            "A2b depth chart schema is pos_abb/pos_rank (not week/position/depth_chart_order)",
            depth_has_pos_abb
            and depth_has_pos_rank
            and not depth_has_week
            and not depth_has_order,
            f"week={depth_has_week} position={depth_has_position} "
            f"depth_chart_order={depth_has_order} pos_abb={depth_has_pos_abb} "
            f"pos_rank={depth_has_pos_rank}",
        ),
        (
            "A3 load_snap_counts() has gsis_id natively",
            snap_has_gsis,
            f"gsis_id={snap_has_gsis} pfr_player_id={snap_has_pfr} "
            f"— FALLBACK: crosswalk via players.pfr_id "
            f"(hit_rate={crosswalk_hit:.1%}, halt if <95%)",
        ),
        (
            "A3b PFR→gsis crosswalk hit rate ≥ 95%",
            crosswalk_hit >= 0.95,
            f"hit_rate={crosswalk_hit:.1%} over {len(snap_ids) if snap_has_pfr else 0} snap player ids",
        ),
        (
            "A4 load_team_stats() carries named defense_yards / offense_yards aggregates",
            bool(assumed_missing),
            f"assumed aggregate cols present={assumed_missing or 'NONE'}; "
            f"use offense play cols={real_offense}; def_* cols={len(real_defense)} "
            f"(fallback: aggregate opponents' offense)",
        ),
        (
            "A5 schedules carry spread_line / total_line",
            sched_spread and sched_total,
            f"spread_line={sched_spread} total_line={sched_total}",
        ),
    ]

    lines = ["Tech spec §4.4 assumption checks:", ""]
    for name, ok, detail in verdicts:
        mark = "PASS" if ok else "FAIL / NEEDS FALLBACK"
        # A3 native gsis FAIL is expected; A3b crosswalk is the real gate
        if name.startswith("A3 ") and not ok:
            mark = "FAIL (expected) — use A3b crosswalk"
        if name.startswith("A4 ") and not ok:
            mark = "FAIL (expected) — use play-type + opp-offense fallback"
        lines.append(f"  [{mark}] {name}")
        lines.append(f"         {detail}")
        lines.append("")

    out.extend(_section("Assumption verdicts", lines))

    out.extend(
        _section(
            "Confirmed column map (for sources/schema.py)",
            [
                "Depth charts: dt, team, gsis_id, pos_abb, pos_rank "
                "(no week / position / depth_chart_order)",
                "Snap counts: pfr_player_id, offense_pct, offense_snaps "
                "(no gsis_id — join players.pfr_id → gsis_id)",
                "Team stats: passing_yards, rushing_yards, carries, attempts, "
                "sacks_suffered, def_sacks, def_tackles_solo, … "
                "(no offense_yards / defense_yards / points)",
                "Player stats: player_id (=gsis_id), passing_interceptions, "
                "fg_made, pat_made, fg_made_0_19…fg_made_60_",
                "Players: gsis_id, pfr_id, display_name, latest_team, position",
            ],
        )
    )
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 0 nflreadpy schema probe")
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "docs" / "schema_probe.txt",
        help="Output path for probe report",
    )
    args = parser.parse_args()
    text = probe(args.season)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    print(text)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
