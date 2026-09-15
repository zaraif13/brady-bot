from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from brady_bot.normalizer import normalize_name, normalize_team
from brady_bot.paths import CONFIG_DIR
from brady_bot.players_index import NFL_TEAMS


class ConfigError(Exception):
    pass


@dataclass
class LeagueConfig:
    raw: dict[str, Any]
    season: int
    scoring: dict[str, float]
    name: str = "Dhaka Chamber of Football"


@dataclass
class WeightsConfig:
    raw: dict[str, Any]
    global_cfg: dict[str, Any]
    positions: dict[str, dict[str, float]]
    calibre_denominators: dict[str, int]
    flex_pool_sizes: dict[str, int]


@dataclass
class AppConfig:
    league: LeagueConfig
    weights: WeightsConfig
    static_lists: dict[str, list]
    team_aliases: dict[str, str]
    oline_ranks: dict[str, int] = field(default_factory=dict)
    depth_overrides: list[dict[str, Any]] = field(default_factory=list)
    # S12 authoritative QB calibre ranking, rank 1 = best (D21)
    qb_calibre_ranks: list[dict[str, Any]] = field(default_factory=list)
    resolved_static: dict[str, set[str]] = field(default_factory=dict)
    resolved_qb_styles: dict[str, bool] = field(default_factory=dict)
    # gsis_id -> (position, pos_rank); beats the published depth chart (§5.9a)
    resolved_depth_overrides: dict[str, tuple[str, int]] = field(default_factory=dict)
    # gsis_id -> calibre rank; consumed by WR/TE/FLEX/DEF, never by the QB picker
    resolved_qb_calibre: dict[str, int] = field(default_factory=dict)


def _load_yaml(path: Path) -> Any:
    with path.open() as f:
        return yaml.safe_load(f) or {}


# Keys under a position block that are not factor weights (excluded from sum-to-1.0)
_NON_FACTOR_WEIGHT_KEYS = frozenset({"tier2_bonus"})


def _validate_weights(weights: dict[str, Any]) -> dict[str, dict[str, float]]:
    positions: dict[str, dict[str, float]] = {}
    for key in ("qb", "rb", "wr", "te", "flex", "k", "def"):
        block = weights.get(key) or {}
        factor_w = {
            k: float(v) for k, v in block.items() if k not in _NON_FACTOR_WEIGHT_KEYS
        }
        total = sum(factor_w.values())
        if abs(total - 1.0) > 1e-9:
            raise ConfigError(f"weights.{key} sum to {total}, expected 1.00")
        positions[key] = factor_w
    return positions


def _load_oline_ranks(raw: dict[str, Any], aliases: dict[str, str]) -> dict[str, int]:
    """Load S10 O-line quality ranks. Rank 1 = best. Halt on incomplete/invalid table."""
    block = raw.get("oline_ranks") if isinstance(raw, dict) else None
    if not isinstance(block, dict) or not block:
        raise ConfigError("oline_ranks.yaml missing oline_ranks map")

    canonical = set(NFL_TEAMS)
    out: dict[str, int] = {}
    for team_raw, rank_raw in block.items():
        # YAML 1.1 may coerce NO/YES to bool — reject rather than silently mis-key
        if not isinstance(team_raw, str):
            raise ConfigError(
                f"oline_ranks team key {team_raw!r} must be a quoted string "
                f"(YAML coerced a team code — quote NO/YES/ON/OFF)"
            )
        team = normalize_team(str(team_raw), aliases)
        if team not in canonical:
            raise ConfigError(f"oline_ranks unrecognized team code {team_raw!r} → {team!r}")
        try:
            rank = int(rank_raw)
        except (TypeError, ValueError) as e:
            raise ConfigError(f"oline_ranks[{team}] rank {rank_raw!r} is not an int") from e
        if team in out:
            raise ConfigError(f"oline_ranks duplicate team {team!r}")
        out[team] = rank

    if len(out) != 32:
        raise ConfigError(f"oline_ranks has {len(out)} teams, expected 32")

    ranks = sorted(out.values())
    if ranks != list(range(1, 33)):
        expected = set(range(1, 33))
        got = set(ranks)
        missing = sorted(expected - got)
        dupes = sorted({r for r in ranks if ranks.count(r) > 1})
        raise ConfigError(
            f"oline_ranks ranks must be 1–32 contiguous with no duplicates "
            f"(missing={missing}, duplicates={dupes})"
        )

    missing_teams = sorted(canonical - set(out))
    if missing_teams:
        raise ConfigError(f"oline_ranks missing teams {missing_teams}")

    return out


def _load_qb_calibre_ranks(
    raw: dict[str, Any], aliases: dict[str, str]
) -> list[dict[str, Any]]:
    """Load S12, the authoritative QB calibre ranking. Rank 1 = best.

    Consumed by WR Step 5, TE Step 5, FLEX Step 4 and DEF Step 2 (§7.3, §8.6) — never
    by the QB picker's own scoring. Names resolve to gsis_id at startup; a QB absent
    from this list falls back to ``derive_player_calibre(position="QB")`` (D21).
    """
    block = raw.get("qb_calibre_ranks") if isinstance(raw, dict) else None
    if not isinstance(block, list) or not block:
        raise ConfigError("qb_calibre_ranks.yaml missing a non-empty qb_calibre_ranks list")

    canonical = set(NFL_TEAMS)
    out: list[dict[str, Any]] = []
    seen_ranks: dict[int, str] = {}
    seen_names: dict[str, str] = {}

    for entry in block:
        if not isinstance(entry, dict):
            raise ConfigError(f"qb_calibre_ranks entry {entry!r} must be a mapping")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"qb_calibre_ranks entry {entry!r} missing a name")
        name = name.strip()

        rank = entry.get("rank")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
            raise ConfigError(
                f"qb_calibre_ranks[{name!r}] rank={rank!r} must be an integer >= 1"
            )
        if rank in seen_ranks:
            raise ConfigError(
                f"qb_calibre_ranks duplicate rank {rank}: "
                f"{seen_ranks[rank]!r} and {name!r}"
            )

        team_raw = entry.get("team")
        # YAML 1.1 coerces a bare NO (New Orleans) to False — reject rather than mis-key.
        if not isinstance(team_raw, str):
            raise ConfigError(
                f"qb_calibre_ranks[{name!r}] team {team_raw!r} must be a quoted string "
                f"(YAML coerced a team code — quote NO/YES/ON/OFF)"
            )
        team = normalize_team(team_raw, aliases)
        if team not in canonical:
            raise ConfigError(
                f"qb_calibre_ranks[{name!r}] unrecognized team code {team_raw!r} → {team!r}"
            )

        key = normalize_name(name)
        if key in seen_names:
            raise ConfigError(
                f"qb_calibre_ranks duplicate name {name!r} (also listed as {seen_names[key]!r})"
            )
        seen_names[key] = name
        seen_ranks[rank] = name
        out.append({"rank": rank, "name": name, "team": team})

    ranks = sorted(seen_ranks)
    expected = list(range(1, len(ranks) + 1))
    if ranks != expected:
        got = set(ranks)
        missing = sorted(set(expected) - got)
        raise ConfigError(
            f"qb_calibre_ranks must be 1–{len(ranks)} contiguous with no gaps "
            f"(missing={missing}, highest={ranks[-1]})"
        )

    out.sort(key=lambda e: e["rank"])
    return out


DEPTH_OVERRIDE_POSITIONS = ("RB", "WR", "TE")


def _load_depth_overrides(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Load S11 manual ``pos_rank`` overrides. Names resolve to gsis_id at startup.

    The escape hatch for the one residual risk ``pos_rank`` carries: a late signing or a
    post-cuts chart that has not caught up when Week 1 scores are computed. Checked
    before the published depth chart and always wins.
    """
    if isinstance(raw, dict) and "committee_overrides" in raw:
        raise ConfigError(
            "committee_overrides.yaml still has a 'committee_overrides' block. That rule "
            "is retired (D16, superseded by D19) — the file now holds 'depth_overrides' "
            "entries of {name, team, position, pos_rank, note}."
        )
    block = raw.get("depth_overrides") if isinstance(raw, dict) else None
    if block is None:
        return []
    if not isinstance(block, list):
        raise ConfigError("committee_overrides.yaml depth_overrides must be a list")

    out: list[dict[str, Any]] = []
    for entry in block:
        if not isinstance(entry, dict):
            raise ConfigError(f"depth_overrides entry {entry!r} must be a mapping")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"depth_overrides entry {entry!r} missing a name")
        position = entry.get("position")
        if not isinstance(position, str) or position.upper() not in DEPTH_OVERRIDE_POSITIONS:
            raise ConfigError(
                f"depth_overrides[{name!r}] position={position!r} must be one of "
                f"{', '.join(DEPTH_OVERRIDE_POSITIONS)} — only those positions score pos_rank"
            )
        if "pos_rank" not in entry:
            raise ConfigError(f"depth_overrides[{name!r}] missing 'pos_rank'")
        pos_rank = entry["pos_rank"]
        if not isinstance(pos_rank, int) or isinstance(pos_rank, bool) or pos_rank < 1:
            raise ConfigError(
                f"depth_overrides[{name!r}] pos_rank={pos_rank!r} must be an integer >= 1"
            )
        team = entry.get("team")
        out.append(
            {
                "name": name,
                # A bare NO/ON/OFF team code is coerced to bool by YAML 1.1
                "team": str(team) if isinstance(team, str) else team,
                "position": position.upper(),
                "pos_rank": pos_rank,
                "note": entry.get("note"),
            }
        )
    return out


def load_config(config_dir: Path | None = None) -> AppConfig:
    root = config_dir or CONFIG_DIR
    league_raw = _load_yaml(root / "league.yaml")
    weights_raw = _load_yaml(root / "weights.yaml")
    static_raw = _load_yaml(root / "static_lists.yaml")
    aliases_raw = _load_yaml(root / "team_aliases.yaml")
    oline_raw = _load_yaml(root / "oline_ranks.yaml")
    depth_raw = _load_yaml(root / "committee_overrides.yaml")
    qb_calibre_raw = _load_yaml(root / "qb_calibre_ranks.yaml")

    team_aliases = {str(k).upper(): str(v).upper() for k, v in (aliases_raw or {}).items()}
    oline_ranks = _load_oline_ranks(oline_raw, team_aliases)
    depth_overrides = _load_depth_overrides(depth_raw)
    qb_calibre_ranks = _load_qb_calibre_ranks(qb_calibre_raw, team_aliases)

    league = LeagueConfig(
        raw=league_raw,
        season=int(league_raw.get("league", {}).get("season", 2026)),
        scoring={k: float(v) for k, v in (league_raw.get("scoring") or {}).items()},
        name=str(league_raw.get("league", {}).get("name", "Dhaka Chamber of Football")),
    )
    positions = _validate_weights(weights_raw)
    weights = WeightsConfig(
        raw=weights_raw,
        global_cfg=dict(weights_raw.get("global") or {}),
        positions=positions,
        calibre_denominators={k: int(v) for k, v in (weights_raw.get("calibre_denominators") or {}).items()},
        flex_pool_sizes={k: int(v) for k, v in (weights_raw.get("flex_pool_sizes") or {}).items()},
    )
    return AppConfig(
        league=league,
        weights=weights,
        static_lists={k: list(v or []) for k, v in static_raw.items()},
        team_aliases=team_aliases,
        oline_ranks=oline_ranks,
        depth_overrides=depth_overrides,
        qb_calibre_ranks=qb_calibre_ranks,
    )
