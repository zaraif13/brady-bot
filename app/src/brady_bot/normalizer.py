from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import polars as pl

from brady_bot.models import Player, Position
from brady_bot.paths import DATA_DIR


class UnresolvedPlayerError(Exception):
    pass


class AmbiguousPlayerError(Exception):
    pass


_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\.?$", re.I)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.casefold().strip()
    text = _SUFFIX_RE.sub("", text).strip()
    # Drop apostrophes and periods without introducing spaces
    # (Ja'Marr → jamarr; A.J. → aj so "AJ Brown" matches "A.J. Brown")
    text = re.sub(r"['’`.]", "", text)
    text = _NON_ALNUM.sub(" ", text)
    return " ".join(text.split())


def normalize_team(team: str, aliases: dict[str, str]) -> str:
    t = (team or "").upper().strip()
    return aliases.get(t, t)


def load_overrides(path: Path | None = None) -> dict[str, str]:
    p = path or (DATA_DIR / "id_overrides.json")
    if not p.exists():
        return {}
    with p.open() as f:
        data = json.load(f) or {}
    return {normalize_name(k): str(v) for k, v in data.items()}


def resolve_player(
    name: str,
    team: str | None,
    position: str | None,
    players_df: pl.DataFrame,
    aliases: dict[str, str],
    overrides: dict[str, str] | None = None,
    logos: dict[str, str] | None = None,
) -> Player:
    overrides = overrides or {}
    logos = logos or {}
    key = normalize_name(name)
    if key in overrides:
        row = players_df.filter(pl.col("gsis_id") == overrides[key])
        if row.height == 0:
            raise UnresolvedPlayerError(f"Override id for {name!r} not found in players")
        return _row_to_player(row.row(0, named=True), aliases)

    team_n = normalize_team(team, aliases) if team else None
    pos = (position or "").upper() or None
    if pos == "DST":
        pos = "DEF"

    if pos == "DEF" and team_n:
        return Player(
            player_id=f"DEF-{team_n}",
            name=name or f"{team_n} Defense",
            team=team_n,
            position=Position.DEF,
            headshot=logos.get(team_n),
        )

    df = players_df.with_columns(
        pl.col("display_name").map_elements(normalize_name, return_dtype=pl.String).alias("_n")
    )
    matches = df.filter(pl.col("_n") == key)
    if team_n:
        narrowed = matches.filter(pl.col("latest_team").fill_null("").str.to_uppercase() == team_n)
        if narrowed.height:
            matches = narrowed
    if pos and pos != "DEF":
        narrowed = matches.filter(pl.col("position").fill_null("").str.to_uppercase() == pos)
        if narrowed.height:
            matches = narrowed

    if matches.height == 0:
        # fuzzy contains
        matches = df.filter(pl.col("_n").str.contains(key, literal=True))
        if team_n:
            matches = matches.filter(pl.col("latest_team").fill_null("").str.to_uppercase() == team_n)
        if pos and pos != "DEF":
            matches = matches.filter(pl.col("position").fill_null("").str.to_uppercase() == pos)

    if matches.height == 0:
        raise UnresolvedPlayerError(f"Could not resolve player {name!r} ({team}/{position})")
    if matches.height > 1:
        # Prefer active / recent
        if "last_season" in matches.columns:
            matches = matches.sort("last_season", descending=True, nulls_last=True)
        top = matches.head(5)
        if top.height > 1 and top["gsis_id"].n_unique() > 1:
            names = [
                f"{r['display_name']} ({r.get('latest_team')}/{r.get('position')})"
                for r in top.to_dicts()
            ]
            raise AmbiguousPlayerError(f"Ambiguous player {name!r}: {names}")
    row = matches.row(0, named=True)
    return _row_to_player(row, aliases)


def _row_to_player(row: dict, aliases: dict[str, str]) -> Player:
    pos_raw = (row.get("position") or "WR").upper()
    if pos_raw == "FB":
        pos_raw = "RB"
    if pos_raw not in Position.__members__:
        pos_raw = "WR"
    team = normalize_team(str(row.get("latest_team") or ""), aliases)
    return Player(
        player_id=str(row["gsis_id"]),
        name=str(row.get("display_name") or ""),
        team=team,
        position=Position(pos_raw),
        headshot=row.get("headshot"),
    )


def resolve_static_lists(
    static_lists: dict[str, list],
    players_df: pl.DataFrame,
    aliases: dict[str, str],
) -> dict[str, set[str]]:
    """Resolve name/team lists to gsis_id sets. Skips qb_styles (see resolve_qb_styles)."""
    out: dict[str, set[str]] = {}
    for key, entries in static_lists.items():
        if key == "qb_styles":
            continue
        ids: set[str] = set()
        for entry in entries:
            p = resolve_player(
                entry["name"],
                entry.get("team"),
                None,
                players_df,
                aliases,
            )
            ids.add(p.player_id)
        out[key] = ids
    return out


def resolve_depth_overrides(
    entries: list[dict],
    players_df: pl.DataFrame,
    aliases: dict[str, str],
) -> dict[str, tuple[str, int]]:
    """
    Resolve S11 depth overrides to gsis_id → (position, pos_rank) (§5.9a, §10.3b).

    Unresolved or ambiguous names raise, same as every other static list — a silently
    dropped entry would leave a known-stale rank driving a 20–40% factor with no
    visible error.
    """
    out: dict[str, tuple[str, int]] = {}
    for entry in entries or []:
        name = entry["name"]
        position = str(entry["position"]).upper()
        value = (position, int(entry["pos_rank"]))
        p = resolve_player(name, entry.get("team"), position, players_df, aliases)
        if p.player_id in out and out[p.player_id] != value:
            raise AmbiguousPlayerError(
                f"depth_overrides has conflicting entries for {name!r} ({p.player_id})"
            )
        out[p.player_id] = value
    return out


def resolve_qb_calibre_ranks(
    entries: list[dict],
    players_df: pl.DataFrame,
    aliases: dict[str, str],
) -> dict[str, int]:
    """
    Resolve S12 QB calibre ranks to gsis_id → rank (§7.3, §8.6, D21).

    Filters by team **and** QB position, never name alone: Buffalo carries both Josh
    Allen (1) and Kyle Allen (67), and "Josh Allen" is also a Jacksonville linebacker.
    Suffix stripping in ``normalize_name`` is what lets "Anthony Richardson Sr." here
    match nflverse's "Anthony Richardson".

    Unresolved or ambiguous names raise. A silent miss would drop a WR's or TE's Step 5
    factor — or 30% of a D/ST score — onto the derived fallback with nothing to show it.
    """
    out: dict[str, int] = {}
    claimed: dict[str, str] = {}
    for entry in entries or []:
        name = entry["name"]
        rank = int(entry["rank"])
        p = resolve_player(name, entry.get("team"), "QB", players_df, aliases)
        if p.player_id in claimed:
            raise AmbiguousPlayerError(
                f"qb_calibre_ranks entries {claimed[p.player_id]!r} (rank {out[p.player_id]}) "
                f"and {name!r} (rank {rank}) both resolved to {p.player_id}"
            )
        claimed[p.player_id] = name
        out[p.player_id] = rank
    return out


def resolve_qb_styles(
    entries: list[dict],
    players_df: pl.DataFrame,
    aliases: dict[str, str],
) -> dict[str, bool]:
    """
    Resolve qb_styles YAML to gsis_id → mobile bool.
    Filters by team + QB position. Unresolved/ambiguous names raise.
    """
    out: dict[str, bool] = {}
    for entry in entries or []:
        name = entry["name"]
        team = entry.get("team")
        mobile = bool(entry.get("mobile", False))
        p = resolve_player(name, team, "QB", players_df, aliases)
        out[p.player_id] = mobile
    return out
