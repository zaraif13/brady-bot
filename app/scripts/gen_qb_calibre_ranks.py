"""Generate config/qb_calibre_ranks.yaml from lineup-picker-QB-CALIBRE.md (S12).

The spec doc is authoritative. Transcribing 99 names by hand is exactly how a
ranking picks up a silent typo, so the config is generated from the markdown
table and the generator is kept for re-runs when the list is revised.

    python scripts/gen_qb_calibre_ranks.py [--check]

``--check`` regenerates in memory and diffs against the committed YAML instead of
writing, so CI can prove the config still matches the doc.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
SPEC = MODULE_ROOT / "docs" / "lineup" / "lineup-picker-qb-calibre.md"
OUT = MODULE_ROOT / "config" / "qb_calibre_ranks.yaml"

HEADER = """\
# Authoritative QB calibre ranking, 2026 season. Rank 1 = best.
#
# Consumed by WR Step 5, TE Step 5, FLEX Step 4 (§7.3) and DEF Step 2 (§8.6,
# inverted). All four read this one rank so they never disagree about how good a
# given quarterback is. NEVER consumed by the QB picker's own scoring — the QB
# equation has no self-calibre factor.
#
# Unlisted QBs fall back to derived per-game fantasy points (tech spec §5.6),
# flagged qb_calibre_derived_fallback. Eight deep-bench QBs on the playing-style
# table are deliberately absent here; so is any mid-season arrival.
#
# GENERATED from docs/lineup/lineup-picker-qb-calibre.md by
# scripts/gen_qb_calibre_ranks.py — edit the spec doc, then re-run. Names resolve
# to gsis_id at startup filtered by team AND position; ambiguity halts.
qb_calibre_ranks:
"""

# The doc lays the ranking out three (rank, player, team) triples per row.
_CELL = re.compile(r"^\d+$")


def parse_spec(text: str) -> list[tuple[int, str, str]]:
    entries: dict[int, tuple[str, str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        # Walk triples; skip header rows and any table that is not the ranking.
        for i in range(0, len(cells) - 2, 3):
            rank_s, name, team = cells[i], cells[i + 1], cells[i + 2]
            if not _CELL.match(rank_s):
                continue
            if not name or not team or len(team) > 3:
                continue
            rank = int(rank_s)
            if rank in entries and entries[rank] != (name, team):
                raise SystemExit(
                    f"spec has conflicting entries for rank {rank}: "
                    f"{entries[rank]} vs {(name, team)}"
                )
            entries[rank] = (name, team)
    return [(r, *entries[r]) for r in sorted(entries)]


def render(entries: list[tuple[int, str, str]]) -> str:
    width = max(len(n) for _, n, _ in entries) + 3  # quotes + trailing comma
    lines = [HEADER]
    for rank, name, team in entries:
        rank_cell = f"{rank},"
        name_cell = f'"{name}",'
        # Team codes are always quoted: bare NO (New Orleans) is boolean false under
        # YAML 1.1, which would silently strip the Saints from the ranking.
        lines.append(
            f'  - {{rank: {rank_cell:<4}name: {name_cell:<{width}}team: "{team}"}}\n'
        )
    return "".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="diff instead of write")
    args = ap.parse_args()

    if not SPEC.exists():
        raise SystemExit(f"spec not found: {SPEC}")
    entries = parse_spec(SPEC.read_text())

    ranks = [r for r, _, _ in entries]
    if not ranks:
        raise SystemExit("no ranking rows parsed — has the doc's table changed shape?")
    expected = list(range(1, len(ranks) + 1))
    if ranks != expected:
        missing = sorted(set(expected) - set(ranks))
        dupes = sorted({r for r in ranks if ranks.count(r) > 1})
        raise SystemExit(f"ranks not contiguous 1..{len(ranks)}: missing={missing} dupes={dupes}")

    rendered = render(entries)
    if args.check:
        current = OUT.read_text() if OUT.exists() else ""
        if current != rendered:
            print(f"{OUT} is out of date with {SPEC.name}", file=sys.stderr)
            raise SystemExit(1)
        print(f"{OUT.name} matches {SPEC.name} ({len(entries)} QBs)")
        return

    OUT.write_text(rendered)
    teams = sorted({t for _, _, t in entries})
    print(f"wrote {OUT} — {len(entries)} QBs, {len(teams)} teams")


if __name__ == "__main__":
    main()
