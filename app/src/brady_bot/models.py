from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Position(str, Enum):
    QB = "QB"
    RB = "RB"
    WR = "WR"
    TE = "TE"
    K = "K"
    DEF = "DEF"


class Slot(str, Enum):
    """Opaque lineup indices for API/saved roster — NOT NFL depth-chart roles.

    Display as QB, RB, RB, WR, WR, TE, D/ST, K, FLEX (see display_slot / slotLabel).
    """

    QB = "QB"
    RB1 = "RB1"
    RB2 = "RB2"
    WR1 = "WR1"
    WR2 = "WR2"
    TE = "TE"
    FLEX = "FLEX"
    K = "K"
    DEF = "DEF"
    BENCH = "BN"
    IR = "IR"


class Player(BaseModel):
    player_id: str
    name: str
    team: str
    position: Position
    bye_week: Optional[int] = None
    headshot: Optional[str] = None

    @property
    def is_team_defense(self) -> bool:
        return self.position == Position.DEF


class InjuryRecord(BaseModel):
    """Game-status + roster designations from injury_status.md / tech spec §5.8."""

    player_id: str
    report_status: Optional[
        Literal["Out", "Doubtful", "Questionable", "Probable", "IR", "PUP", "NFI"]
    ] = None
    practice_status: Optional[Literal["DNP", "Limited", "Full"]] = None

    @property
    def is_unavailable(self) -> bool:
        # Roster designations: multi-week unavailable (injury_status.md)
        if self.report_status in ("Out", "Doubtful", "IR", "PUP", "NFI"):
            return True
        # Probable → expected to play
        if self.report_status == "Probable":
            return False
        if self.report_status == "Questionable":
            return self.practice_status in ("DNP", "Limited", None)
        return False


class TeamStats(BaseModel):
    team: str
    season: int
    through_week: int
    blended: bool = False
    offense_rank: int = Field(ge=1, le=32)
    total_defense_rank: int = Field(ge=1, le=32)
    scoring_efficiency_rank: int = Field(ge=1, le=32)
    defense_calibre_rank: int = Field(ge=1, le=32)
    qb_turnover_rank: int = Field(ge=1, le=32)


class GameContext(BaseModel):
    game_id: str
    home_team: str
    away_team: str
    game_total: float = 44.0
    spread: float = 0.0
    home_implied_total: float = 22.0
    away_implied_total: float = 22.0

    def implied_total_for(self, team: str) -> float:
        if team == self.home_team:
            return self.home_implied_total
        if team == self.away_team:
            return self.away_implied_total
        raise KeyError(team)

    def opponent_of(self, team: str) -> str:
        if team == self.home_team:
            return self.away_team
        if team == self.away_team:
            return self.home_team
        raise KeyError(team)


class WeekContext(BaseModel):
    season: int
    week: int
    fetched_at: str
    roster: list[Player]
    injuries: dict[str, InjuryRecord] = Field(default_factory=dict)
    team_stats: dict[str, TeamStats] = Field(default_factory=dict)
    games: dict[str, GameContext] = Field(default_factory=dict)
    adj_fpa: dict[str, dict[str, float]] = Field(default_factory=dict)
    calibre_rank: dict[str, dict[str, int]] = Field(default_factory=dict)
    roles: dict[str, str] = Field(default_factory=dict)
    player_teams: dict[str, str] = Field(default_factory=dict)  # player_id -> team abbr
    rush_att_pg: dict[str, float] = Field(default_factory=dict)  # QB trailing rush att/game
    # Current-season snap share. Prior-season W10–18 snap share was retired from RB
    # Step 3 by D19 — pos_rank occupies that slot now — so this is current-only in
    # every week and forms the usage half of the depth blend (§5.10.1).
    snap_share: dict[str, float] = Field(default_factory=dict)
    target_share: dict[str, float] = Field(default_factory=dict)
    # Current-season-only WR roles. `roles` stays blended for identification (teammate
    # injury, WR-health checks); this supplies the usage half of the depth blend, and
    # equals `roles` from Week 5 by construction.
    roles_current: dict[str, str] = Field(default_factory=dict)
    injury_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    bye_teams: list[str] = Field(default_factory=list)
    # Position-scoped depth order for gates: {"QB"|"RB"|"WR"|"TE": {gsis_id: rank}}.
    # Flat last-row-wins maps let a KR/PR row overwrite a starter's rank — do not flatten.
    depth_chart_order: dict[str, dict[str, int]] = Field(default_factory=dict)
    # §5.9a — pinned pos_rank per scored position: {"RB"|"WR"|"TE": {gsis_id: rank}}.
    # Position-scoped so a player charted at two slots cannot contaminate the other.
    pos_rank: dict[str, dict[str, int]] = Field(default_factory=dict)
    # Rostered RB/WR/TE with no pinned depth entry, while pos_rank still has weight
    no_depth_entry: list[str] = Field(default_factory=list)
    qb1_by_team: dict[str, str] = Field(default_factory=dict)
    static_ids: dict[str, set[str]] = Field(default_factory=dict)
    qb_styles: dict[str, bool] = Field(default_factory=dict)  # gsis_id -> mobile
    # D21 — QBs whose calibre_rank["QB"] came from derive_player_calibre rather than the
    # S12 static list. Consumed only to flag the factor breakdown, never to alter a score.
    qb_calibre_fallback: set[str] = Field(default_factory=set)
    oline_ranks: dict[str, int] = Field(default_factory=dict)  # S10 team -> quality rank 1–32
    blended: bool = False
    odds_unavailable: bool = False
    warnings: list[str] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


class FactorScore(BaseModel):
    name: str
    raw_value: Optional[str] = None
    # May exceed 1.0 for uncapped boosts (e.g. QB pass-catcher elite); finalize_score clamps.
    score: float = Field(ge=0.0)
    weight: float = Field(ge=0.0, le=1.0)

    @property
    def contribution(self) -> float:
        return self.score * self.weight


class ScoredPlayer(BaseModel):
    player: Player
    # Pre-bonus factor sum; may exceed 1.0 when a factor boost is uncapped (§8.1).
    weighted_sum: float = Field(default=0.0, ge=0.0)
    bonus: float = 0.0  # RB Tier 2 only (§8.2.1)
    start_score: float = Field(ge=0.0, le=1.0)
    factors: list[FactorScore] = Field(default_factory=list)
    gate_result: Literal["passed", "auto_start", "eliminated"] = "passed"
    gate_reason: Optional[str] = None
    flags: list[str] = Field(default_factory=list)
    headshot: Optional[str] = None
    opponent: Optional[str] = None
    explanation: Optional[str] = None
    injury_status: Optional[str] = None  # O/D/Q/P/IR/PUP/NFI
    injury_label: Optional[str] = None  # Out / Doubtful / …
    is_unavailable: bool = False
    # Prior positional evaluation for FLEX leftovers who lost both the dedicated
    # RB/WR/TE slot and FLEX. Primary factors/start_score remain the FLEX equation.
    prior_label: Optional[str] = None  # "RB" | "WR" | "TE"
    prior_start_score: Optional[float] = None
    prior_weighted_sum: Optional[float] = None
    prior_bonus: float = 0.0
    prior_flags: list[str] = Field(default_factory=list)
    prior_factors: list[FactorScore] = Field(default_factory=list)


class Lineup(BaseModel):
    season: int
    week: int
    run_id: str
    fetched_at: str = ""
    blended: bool = False
    matchup_normalization: str = "percentile"
    starters: dict[str, Optional[ScoredPlayer]]
    bench: list[ScoredPlayer] = Field(default_factory=list)
    ir: list[ScoredPlayer] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    opponents: dict[str, str] = Field(default_factory=dict)
    injuries_by_player: dict[str, str] = Field(default_factory=dict)  # pid -> abbrev
