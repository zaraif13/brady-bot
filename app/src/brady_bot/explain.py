"""Plain-language explanations for lineup decisions (no score dumps).

Lineup slots are unlabeled duplicates (two RB slots, two WR slots) — never
"WR1"/"RB2" as fantasy slot names. Those strings mean NFL depth-chart roles.
"""
from __future__ import annotations

import re

from brady_bot.derive.depth import NO_DEPTH_ENTRY
from brady_bot.models import FactorScore, ScoredPlayer

GATE_PHRASES: dict[str, str] = {
    "bye": "team on bye this week",
    "unavailable": "listed as unavailable / out",
    "not_qb1": "not listed as the team's depth-chart QB1",
    "not_te1": "not listed as the team's depth-chart TE1",
    "rb_tier1": "RB tier-1 auto-start",
    "wr_top5": "WR top-5 auto-start",
    "te_top4": "TE top-4 auto-start",
    "only_rostered": "only rostered player at this position",
}

FACTOR_LABELS: dict[str, str] = {
    "style": "QB style fit",
    "pass_catcher": "pass-catcher health",
    "oline": "offensive line",
    "matchup": "matchup",
    "secondary_injury": "opponent secondary injuries",
    "baseline": "game script / implied points",
    "depth_chart": "depth / snap role",
    "ranking": "player calibre rank",
    "teammate_injury": "teammate injury boost",
    "front_seven_injury": "opponent front-seven injuries",
    "qb_quality": "QB quality",
    "red_zone": "red-zone opportunity",
    "defense_calibre": "defense calibre",
    "sack_rate": "sack rate allowed",
    "opportunity": "opportunity / touches",
    "situation": "situation (QB / O-line)",
    "player_calibre": "within-position calibre",
    "wr_injury": "WR injury boost",
    "opp_qb": "opposing QB",
    "opp_skill": "opposing skill injuries",
    "opp_oline": "opposing O-line",
    "defensive_injury": "own defensive injuries",
}

# Internal optimizer keys → lineup display (no positional slot numbers)
LINEUP_SLOT_LABELS: dict[str, str] = {
    "QB": "QB",
    "RB1": "RB",
    "RB2": "RB",
    "WR1": "WR",
    "WR2": "WR",
    "TE": "TE",
    "FLEX": "FLEX",
    "DEF": "D/ST",
    "K": "K",
}


def display_slot(slot: str | None) -> str:
    """Map internal starter key to UI slot label (RB not RB1; DEF → D/ST)."""
    if not slot:
        return ""
    if slot in LINEUP_SLOT_LABELS:
        return LINEUP_SLOT_LABELS[slot]
    if slot.startswith("BN"):
        return "BN"
    if slot.startswith("IR"):
        return "IR"
    if slot in ("DST", "D/ST"):
        return "D/ST"
    return re.sub(r"\d+$", "", slot)


# Alias used by older call sites / tests
lineup_slot_label = display_slot


def empty_slot_warning(slot: str) -> str:
    """User-facing EMPTY warning without numbered lineup slots."""
    label = display_slot(slot)
    if label == "QB":
        return "QB slot EMPTY: no eligible quarterback"
    if label in ("RB", "WR"):
        return f"{label} slot EMPTY"
    if label == "D/ST":
        return "D/ST slot EMPTY"
    return f"{label} slot EMPTY"


def _snap_phrase(pct: str) -> str:
    try:
        share = float(pct.replace("%", "")) / (100.0 if "%" in pct else 1.0)
    except ValueError:
        return f"snap share ({pct})"
    if share >= 0.6 or (share > 1 and share >= 60):
        return "workhorse snaps (depth)"
    if share >= 0.5 or (share > 1 and share >= 50):
        return "high snap share (depth)"
    if share >= 0.3 or (share > 1 and share >= 30):
        return "committee snap share (depth)"
    if share > 0:
        return "limited snaps (depth)"
    return f"snap share ({pct})"


def _role_phrase(role: str) -> str:
    if role in ("RB1", "1"):
        return "team's RB1 on the depth chart"
    if role in ("RB2", "2"):
        return "committee RB2 on the depth chart"
    if role.startswith("RB") or role.isdigit():
        return "backup on the team's RB depth chart"
    if role == "WR1":
        return "team's WR1 on the depth chart"
    if role == "WR2":
        return "team's WR2 on the depth chart"
    if role.startswith("WR"):
        return f"team's {role} on the depth chart"
    if role == "TE1":
        return "team's TE1 on the depth chart"
    if role.startswith("TE"):
        return "backup on the team's TE depth chart"
    return f"depth chart role ({role})"


# Weeks 1–4 the depth factor leads with a pos_rank token — "RB1 1.00@50% + snap=35% …"
_DEPTH_TOKEN = re.compile(r"^(?:RB|WR|TE)[1-9]\d*\b")


def _depth_phrase(raw: str, name: str) -> str:
    """Plain language for the depth blend (§5.10.1) and the Week 5+ usage labels."""
    if raw.startswith(NO_DEPTH_ENTRY):
        return "not listed on the team's depth chart"
    if _DEPTH_TOKEN.match(raw):
        return _role_phrase(raw.split()[0])
    if raw == "snap=default":
        return "uncertain depth / snap role"
    if raw.startswith("snap="):
        return _snap_phrase(raw.split("=", 1)[1].split()[0])
    if raw.startswith("role="):
        return _role_phrase(raw.split("=", 1)[1])
    if raw == "inactive":
        return "no recorded offensive snaps"
    return FACTOR_LABELS.get(name, name.replace("_", " "))


def _factor_phrase(f: FactorScore) -> str:
    raw = (f.raw_value or "").strip()
    name = f.name

    if name == "depth_chart":
        return _depth_phrase(raw, name)

    if name == "matchup":
        if f.score >= 0.65:
            return "favorable matchup"
        if f.score <= 0.35:
            return "tough matchup"
        return "neutral matchup"

    if name == "baseline":
        if f.score >= 0.65:
            return "strong game-script outlook"
        if f.score <= 0.35:
            return "soft game-script outlook"
        return "average game-script outlook"

    if name in ("oline", "pass_catcher", "teammate_injury", "secondary_injury", "front_seven_injury"):
        label = FACTOR_LABELS.get(name, name.replace("_", " "))
        if f.score >= 0.7:
            return f"strong {label}"
        if f.score <= 0.3:
            return f"weak {label}"
        return label

    if name == "ranking" and raw.startswith("rank="):
        return "player calibre rank"

    if name == "style":
        if "dual" in raw.lower():
            return "dual-threat style"
        return "pocket-passer style"

    return FACTOR_LABELS.get(name, name.replace("_", " "))


def _top_signal_phrases(factors: list[FactorScore], n: int = 2) -> list[str]:
    if not factors:
        return []
    ordered = sorted(factors, key=lambda f: (-f.contribution, f.name))
    return [_factor_phrase(f) for f in ordered[:n]]


def _strip_score_dumps(text: str) -> str:
    """Ensure we never leak start_score / weight-style dumps (allow snap %)."""
    return re.sub(r"\bstart[_\s]?score\b[:\s]*[\d.]+", "", text, flags=re.I).strip()


def build_explanation(
    scored: ScoredPlayer,
    *,
    slot: str | None = None,
    outcome: str = "starter",  # starter | bench | ir
    beat_by: str | None = None,
    position_label: str | None = None,
    prior_beat_by: str | None = None,
) -> str:
    """
    Build 1–2 plain-language sentences. Never include Start Score or factor weights.
    Lineup slot names are QB/RB/WR/… (no WR1 fantasy-slot numbering).
    """
    if "ir" in scored.flags or outcome == "ir":
        return "On IR slot (excluded from start/bench pool)."

    reason = scored.gate_reason or ""
    gate = scored.gate_result
    slot_display = display_slot(slot) if slot else ""
    if not slot_display and position_label:
        slot_display = "D/ST" if position_label in ("DEF", "DST") else position_label

    if gate == "eliminated":
        phrase = GATE_PHRASES.get(reason, reason.replace("_", " ") if reason else "failed eligibility gate")
        return _strip_score_dumps(f"Benched: {phrase}.")

    if gate == "auto_start":
        phrase = GATE_PHRASES.get(reason, reason.replace("_", " ") if reason else "auto-start rule")
        if outcome == "bench":
            return _strip_score_dumps(f"Benched despite auto-start cue ({phrase}).")
        if slot == "FLEX" or slot_display == "FLEX":
            return _strip_score_dumps(
                f"Started at FLEX (chosen last from leftovers): {phrase}."
            )
        slot_bit = f" at {slot_display}" if slot_display else ""
        return _strip_score_dumps(f"Locked starter{slot_bit}: {phrase}.")

    signals = _top_signal_phrases(scored.factors, 2)
    signal_bit = ""
    if signals:
        signal_bit = " Strongest signals: " + "; ".join(signals) + "."

    bonus_bit = ""
    if "tier2_bonus" in scored.flags or scored.bonus > 0:
        bonus_bit = " Includes the Tier 2 strong-consideration bonus."
        if "score_capped" in scored.flags:
            bonus_bit += " Score hit the ceiling."

    if outcome == "starter":
        bit = slot_display or scored.player.position.value
        if bit in ("DEF", "DST"):
            bit = "D/ST"
        if bit == "FLEX" or slot == "FLEX":
            return _strip_score_dumps(
                f"Started at FLEX (chosen last from leftovers).{bonus_bit}{signal_bit}"
            )
        return _strip_score_dumps(f"Started at {bit}.{bonus_bit}{signal_bit}")

    # Bench: FLEX leftovers that also lost a dedicated RB/WR/TE slot get both beats.
    prior_label = scored.prior_label
    if prior_label and scored.prior_factors and (beat_by or slot == "FLEX" or slot_display == "FLEX"):
        pos = prior_label
        if pos in ("RB", "WR"):
            pos_bit = f"finished behind higher-ranked {pos}s for the two {pos} lineup slots"
        elif prior_beat_by:
            pos_bit = f"finished behind {prior_beat_by} for the {pos} slot"
        else:
            pos_bit = f"finished behind the starter at {pos}"
        if beat_by:
            flex_bit = f"then edged out for FLEX by {beat_by}"
        else:
            flex_bit = "then did not win FLEX (chosen last from leftovers)"
        return _strip_score_dumps(
            f"Benched: {pos_bit}, {flex_bit}.{bonus_bit}{signal_bit}"
        )

    if beat_by:
        contested = slot_display or "FLEX"
        return _strip_score_dumps(
            f"Benched: edged out for {contested} by {beat_by}.{bonus_bit}{signal_bit}"
        )
    pos = position_label or scored.player.position.value
    if pos in ("DEF", "DST"):
        pos = "D/ST"
    if pos in ("RB", "WR"):
        return _strip_score_dumps(
            f"Benched behind higher-ranked {pos}s for the two {pos} lineup slots.{bonus_bit}{signal_bit}"
        )
    if pos == "FLEX" or slot == "FLEX":
        return _strip_score_dumps(
            f"Benched: did not win FLEX (chosen last from leftovers).{bonus_bit}{signal_bit}"
        )
    return _strip_score_dumps(f"Benched behind the starter at {pos}.{bonus_bit}{signal_bit}")
