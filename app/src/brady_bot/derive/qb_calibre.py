"""S12 QB calibre ranking — static list with a derived fallback (D21).

QB calibre answers "how good is this quarterback" only when scoring *someone else*:
a receiver whose ceiling is capped by his own QB (WR/TE Step 5, FLEX Step 4) or a
defence sizing up the opponent (DEF Step 2). Those four factors must agree on the same
number for the same quarterback, so the rank comes from one human-verified list rather
than four reads of a derived per-game average.

The QB picker's own equation has no self-calibre factor, so nothing here reaches it.
"""
from __future__ import annotations

FALLBACK_FLAG = "qb_calibre_derived_fallback"


def merge_qb_calibre(
    static_ranks: dict[str, int],
    derived_ranks: dict[str, int],
) -> tuple[dict[str, int], set[str]]:
    """Overlay S12 onto the derived QB ranking, returning (ranks, fallback_ids).

    A QB on the list gets his listed rank. A QB absent from it — the eight deep-bench
    names, or any mid-season practice-squad promotion, since the list is never updated
    in-season — keeps his derived rank and is reported in ``fallback_ids`` so consumers
    can flag the factor ``qb_calibre_derived_fallback``.

    Unlisted QBs deliberately keep the derived scale rather than being pushed past
    rank 99: a promoted arm who actually produces should score on what he produced.
    """
    merged: dict[str, int] = dict(derived_ranks)
    merged.update(static_ranks)
    fallback = {pid for pid in derived_ranks if pid not in static_ranks}
    return merged, fallback


def fallback_warnings(
    qb1_by_team: dict[str, str],
    fallback_ids: set[str],
    names: dict[str, str],
) -> list[str]:
    """Warn once per starting QB scoring someone else's factor off the derived path.

    Never a halt — handling the unlisted starter is the fallback's entire purpose — but
    it is 15% of every WR/TE on that team and 30% of the D/ST facing them, so it should
    not pass silently.
    """
    out: list[str] = []
    for team, starter in sorted(qb1_by_team.items()):
        if starter not in fallback_ids:
            continue
        out.append(
            f"{FALLBACK_FLAG}: {names.get(starter, starter)} ({team.upper()}) starts but is "
            f"not on the S12 QB calibre list — calibre derived from this season's fantasy "
            f"points per game instead"
        )
    return out
