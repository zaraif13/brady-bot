from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import polars as pl

from brady_bot.models import Position
from brady_bot.normalizer import normalize_name, normalize_team
from brady_bot.sources.cache import CacheStore
from brady_bot.sources.nflverse import load_players_cached, load_teams_cached, team_logo_map

NFL_TEAMS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
]

TEAM_NAMES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs", "LAC": "Los Angeles Chargers", "LAR": "Los Angeles Rams",
    "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings",
    "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
}

SLOT_POSITIONS: dict[str, set[str]] = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "FLEX": {"RB", "WR", "TE"},
    "K": {"K"},
    "DEF": {"DEF"},
    "BN": {"QB", "RB", "WR", "TE", "K", "DEF"},
    "IR": {"QB", "RB", "WR", "TE", "K", "DEF"},
}


@dataclass
class PlayerHit:
    player_id: str
    name: str
    position: str
    team: str
    headshot: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "position": self.position,
            "team": self.team,
            "headshot": self.headshot,
        }


class PlayersIndex:
    def __init__(
        self,
        df: pl.DataFrame,
        aliases: dict[str, str],
        logos: dict[str, str] | None = None,
    ):
        self.aliases = aliases
        self.df = df
        self.logos = logos or {}
        self._rows: list[dict[str, Any]] = []
        for r in df.to_dicts():
            pos = (r.get("position") or "").upper()
            if pos == "FB":
                pos = "RB"
            if pos not in {"QB", "RB", "WR", "TE", "K"} and pos:
                continue
            team = normalize_team(str(r.get("latest_team") or ""), aliases)
            name = str(r.get("display_name") or "")
            self._rows.append(
                {
                    "player_id": str(r.get("gsis_id") or ""),
                    "name": name,
                    "norm": normalize_name(name),
                    "short": normalize_name(str(r.get("short_name") or "")),
                    "position": pos,
                    "team": team,
                    "headshot": r.get("headshot"),
                    "last_season": r.get("last_season") or 0,
                    "status": str(r.get("status") or ""),
                }
            )
        for team in NFL_TEAMS:
            self._rows.append(
                {
                    "player_id": f"DEF-{team}",
                    "name": TEAM_NAMES.get(team, f"{team} Defense"),
                    "norm": normalize_name(TEAM_NAMES.get(team, team)),
                    "short": normalize_name(team),
                    "position": "DEF",
                    "team": team,
                    "headshot": self.logos.get(team),
                    "last_season": 9999,
                    "status": "ACT",
                }
            )

    @classmethod
    def build(cls, cache: CacheStore, aliases: dict[str, str], no_cache: bool = False) -> "PlayersIndex":
        df = load_players_cached(cache, no_cache=no_cache)
        try:
            teams_df = load_teams_cached(cache, no_cache=no_cache)
            logos = team_logo_map(teams_df, aliases)
        except Exception:
            logos = {}
        return cls(df, aliases, logos=logos)

    def search(self, q: str, slot: str, limit: int = 12) -> list[PlayerHit]:
        qn = normalize_name(q)
        if not qn:
            return []
        allowed = SLOT_POSITIONS.get(slot.upper(), SLOT_POSITIONS["BN"])
        hits: list[tuple[int, dict]] = []
        for row in self._rows:
            if row["position"] not in allowed:
                continue
            name_n = row["norm"]
            short_n = row["short"]
            if not (name_n.startswith(qn) or qn in name_n or short_n.startswith(qn) or qn in short_n):
                if row["position"] == "DEF" and (
                    qn.upper() in row["team"].lower() or row["team"].lower().startswith(qn)
                ):
                    pass
                else:
                    continue
            score = 0
            if name_n.startswith(qn):
                score += 100
            if qn == name_n:
                score += 50
            if str(row.get("status", "")).upper() in ("ACT", "ACTIVE", ""):
                score += 10
            score += int(row.get("last_season") or 0) % 100
            hits.append((score, row))
        hits.sort(key=lambda x: (-x[0], x[1]["name"]))
        out = []
        for _, row in hits[:limit]:
            out.append(
                PlayerHit(
                    player_id=row["player_id"],
                    name=row["name"],
                    position=row["position"],
                    team=row["team"],
                    headshot=row.get("headshot"),
                )
            )
        return out

    def get(self, player_id: str) -> Optional[PlayerHit]:
        for row in self._rows:
            if row["player_id"] == player_id:
                return PlayerHit(
                    player_id=row["player_id"],
                    name=row["name"],
                    position=row["position"],
                    team=row["team"],
                    headshot=row.get("headshot"),
                )
        return None

    def to_player(self, player_id: str) -> Optional[Any]:
        from brady_bot.models import Player

        hit = self.get(player_id)
        if not hit:
            return None
        return Player(
            player_id=hit.player_id,
            name=hit.name,
            team=hit.team,
            position=Position(hit.position),
            headshot=hit.headshot,
        )
