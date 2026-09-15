from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from brady_bot.models import Lineup
from brady_bot.paths import DATA_DIR, ensure_dirs


def append_predictions(lineup: Lineup, path: Path | None = None) -> None:
    ensure_dirs()
    p = path or (DATA_DIR / "predictions.jsonl")
    rows = []
    for slot, scored in lineup.starters.items():
        if not scored:
            continue
        rows.append(_row(lineup, scored, slot))
    for scored in lineup.bench:
        rows.append(_row(lineup, scored, "BN"))
    for scored in lineup.ir:
        rows.append(_row(lineup, scored, "IR"))
    with p.open("a") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _row(lineup: Lineup, scored, slot: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "run_id": lineup.run_id,
        "run_timestamp": lineup.fetched_at,
        "season": lineup.season,
        "week": lineup.week,
        "player_id": scored.player.player_id,
        "name": scored.player.name,
        "position": scored.player.position.value,
        "slot": slot,
        "weighted_sum": scored.weighted_sum,
        "start_score": scored.start_score,
        "factors": {
            f.name: {"score": f.score, "weight": f.weight} for f in scored.factors
        },
        "gate_result": scored.gate_result,
        "flags": scored.flags,
        "blended": lineup.blended,
        "matchup_normalization": lineup.matchup_normalization,
        "actual_score": None,
    }
    if scored.bonus:
        row["bonus"] = scored.bonus
    return row


def backfill_actuals(week: int, actuals: dict[str, float], path: Path | None = None) -> int:
    """Update actual_score only for matching week rows. Returns count updated."""
    p = path or (DATA_DIR / "predictions.jsonl")
    if not p.exists():
        return 0
    lines = p.read_text().splitlines()
    updated = 0
    out = []
    for line in lines:
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("week") == week and row.get("player_id") in actuals:
            row["actual_score"] = actuals[row["player_id"]]
            updated += 1
        out.append(json.dumps(row))
    if updated:
        p.write_text("\n".join(out) + "\n")
    return updated
