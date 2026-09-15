"""Confirmed nflreadpy column names — Step 0 schema probe output.

Do not guess column names in derive/. Import constants from here.
Regenerate assumptions via: ``python scripts/probe_schemas.py``
See ``docs/schema_probe.txt``.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Depth charts (S6) — load_depth_charts()
# Confirmed: no week, position, or depth_chart_order columns.
# ---------------------------------------------------------------------------
DEPTH_DT = "dt"
DEPTH_TEAM = "team"
DEPTH_PLAYER_NAME = "player_name"
DEPTH_GSIS_ID = "gsis_id"
DEPTH_ESPN_ID = "espn_id"
DEPTH_POS_GRP = "pos_grp"
DEPTH_POS_ABB = "pos_abb"
DEPTH_POS_SLOT = "pos_slot"
DEPTH_POS_RANK = "pos_rank"
DEPTH_POS_NAME = "pos_name"

# Starter = pos_rank == 1 within (team, pos_abb)
DEPTH_STARTER_RANK = 1

# ---------------------------------------------------------------------------
# Snap counts (S4) — load_snap_counts()
# Keyed on pfr_player_id; join to gsis via players.pfr_id.
# ---------------------------------------------------------------------------
SNAP_PFR_PLAYER_ID = "pfr_player_id"
SNAP_PLAYER_NAME = "player"
SNAP_TEAM = "team"
SNAP_POSITION = "position"
SNAP_SEASON = "season"
SNAP_WEEK = "week"
SNAP_OFFENSE_SNAPS = "offense_snaps"
SNAP_OFFENSE_PCT = "offense_pct"
SNAP_DEFENSE_SNAPS = "defense_snaps"
SNAP_DEFENSE_PCT = "defense_pct"
SNAP_ST_SNAPS = "st_snaps"
SNAP_ST_PCT = "st_pct"

# Minimum PFR→gsis hit rate before halt (tech spec §4.4)
SNAP_CROSSWALK_MIN_HIT_RATE = 0.95

# ---------------------------------------------------------------------------
# Players (S7) — load_players() crosswalk
# ---------------------------------------------------------------------------
PLAYERS_GSIS_ID = "gsis_id"
PLAYERS_PFR_ID = "pfr_id"
PLAYERS_DISPLAY_NAME = "display_name"
PLAYERS_LATEST_TEAM = "latest_team"
PLAYERS_POSITION = "position"
PLAYERS_HEADSHOT = "headshot"

# ---------------------------------------------------------------------------
# Player stats (S2) — load_player_stats()
# player_id matches gsis_id. Interceptions column is passing_interceptions.
# ---------------------------------------------------------------------------
PS_PLAYER_ID = "player_id"
PS_PLAYER_NAME = "player_display_name"
PS_POSITION = "position"
PS_SEASON = "season"
PS_WEEK = "week"
PS_SEASON_TYPE = "season_type"
PS_TEAM = "team"
PS_OPPONENT_TEAM = "opponent_team"
PS_PASSING_YARDS = "passing_yards"
PS_PASSING_TDS = "passing_tds"
PS_PASSING_INTERCEPTIONS = "passing_interceptions"
PS_PASSING_2PT = "passing_2pt_conversions"
PS_CARRIES = "carries"
PS_RUSHING_YARDS = "rushing_yards"
PS_RUSHING_TDS = "rushing_tds"
PS_RUSHING_FUMBLES_LOST = "rushing_fumbles_lost"
PS_RUSHING_2PT = "rushing_2pt_conversions"
PS_RECEPTIONS = "receptions"
PS_TARGETS = "targets"
# Native per-player-per-week share: targets / team targets, 0-1 scale
PS_TARGET_SHARE = "target_share"
PS_RECEIVING_YARDS = "receiving_yards"
PS_RECEIVING_TDS = "receiving_tds"
PS_RECEIVING_FUMBLES_LOST = "receiving_fumbles_lost"
PS_RECEIVING_2PT = "receiving_2pt_conversions"
PS_FG_MADE = "fg_made"
PS_FG_ATT = "fg_att"
PS_FG_MISSED = "fg_missed"
PS_FG_MADE_0_19 = "fg_made_0_19"
PS_FG_MADE_20_29 = "fg_made_20_29"
PS_FG_MADE_30_39 = "fg_made_30_39"
PS_FG_MADE_40_49 = "fg_made_40_49"
PS_FG_MADE_50_59 = "fg_made_50_59"
PS_FG_MADE_60 = "fg_made_60_"
PS_FG_MISSED_0_19 = "fg_missed_0_19"
PS_FG_MISSED_20_29 = "fg_missed_20_29"
PS_FG_MISSED_30_39 = "fg_missed_30_39"
PS_FG_MISSED_40_49 = "fg_missed_40_49"
PS_FG_MISSED_50_59 = "fg_missed_50_59"
PS_FG_MISSED_60 = "fg_missed_60_"
PS_PAT_MADE = "pat_made"
PS_PAT_ATT = "pat_att"
PS_PAT_MISSED = "pat_missed"

# ---------------------------------------------------------------------------
# Team stats (S3) — load_team_stats()
# No offense_yards / defense_yards / points aggregates — use play-type cols.
# Defense "allowed" metrics: aggregate opponents' offensive rows (fallback).
# ---------------------------------------------------------------------------
TS_SEASON = "season"
TS_WEEK = "week"
TS_TEAM = "team"
TS_OPPONENT_TEAM = "opponent_team"
TS_SEASON_TYPE = "season_type"
TS_PASSING_YARDS = "passing_yards"
TS_RUSHING_YARDS = "rushing_yards"
TS_CARRIES = "carries"
TS_ATTEMPTS = "attempts"
TS_PASSING_TDS = "passing_tds"
TS_RUSHING_TDS = "rushing_tds"
TS_SACKS_SUFFERED = "sacks_suffered"
TS_PASSING_INTERCEPTIONS = "passing_interceptions"
TS_DEF_SACKS = "def_sacks"
TS_DEF_TACKLES_SOLO = "def_tackles_solo"
TS_DEF_INTERCEPTIONS = "def_interceptions"
TS_DEF_QB_HITS = "def_qb_hits"
TS_DEF_TACKLES_FOR_LOSS = "def_tackles_for_loss"
TS_FG_MADE = "fg_made"
TS_PAT_MADE = "pat_made"

# Candidate lists used by derive_team_ranks (real columns only)
TS_OFFENSE_YARDS_COLS = (TS_PASSING_YARDS, TS_RUSHING_YARDS)  # sum for team offense ypg
TS_RUSH_YPA_NUM = TS_RUSHING_YARDS
TS_RUSH_YPA_DEN = TS_CARRIES
TS_SACK_RATE_NUM = TS_SACKS_SUFFERED
TS_SACK_RATE_DEN = TS_ATTEMPTS
TS_DEFENSE_ACTIVITY_COLS = (TS_DEF_SACKS, TS_DEF_TACKLES_SOLO, TS_DEF_INTERCEPTIONS)

# ---------------------------------------------------------------------------
# Injuries (S5)
# ---------------------------------------------------------------------------
INJ_GSIS_ID = "gsis_id"
INJ_WEEK = "week"
INJ_TEAM = "team"
INJ_REPORT_STATUS = "report_status"
INJ_PRACTICE_STATUS = "practice_status"
INJ_POSITION = "position"

# ---------------------------------------------------------------------------
# Schedules (S1)
# ---------------------------------------------------------------------------
SCHED_SEASON = "season"
SCHED_WEEK = "week"
SCHED_HOME_TEAM = "home_team"
SCHED_AWAY_TEAM = "away_team"
SCHED_GAME_ID = "game_id"
SCHED_SPREAD_LINE = "spread_line"
SCHED_TOTAL_LINE = "total_line"
SCHED_GAME_TYPE = "game_type"

# ---------------------------------------------------------------------------
# Depth pos_abb → injury unit sets (tech spec / RB module)
# ---------------------------------------------------------------------------
OL_POS_ABB = frozenset({"LT", "RT", "LG", "RG", "C", "T", "G", "OT", "OG"})
SECONDARY_POS_ABB = frozenset({"LCB", "RCB", "CB", "FS", "SS", "NB", "DB", "S", "LS"})
FRONT_SEVEN_POS_ABB = frozenset(
    {
        "LDE",
        "RDE",
        "LDT",
        "RDT",
        "NT",
        "DE",
        "DT",
        "EDGE",
        "LILB",
        "RILB",
        "MLB",
        "SLB",
        "WLB",
        "LB",
        "OLB",
        "ILB",
    }
)
FRONT_SEVEN_INTERIOR_POS_ABB = frozenset(
    {"LDT", "RDT", "NT", "DT", "LILB", "RILB", "MLB", "ILB", "LB"}
)
DEFENSE_ALL_POS_ABB = SECONDARY_POS_ABB | FRONT_SEVEN_POS_ABB

UNIT_POS_ABB: dict[str, frozenset[str]] = {
    "OL": OL_POS_ABB,
    "SECONDARY": SECONDARY_POS_ABB,
    "FRONT_SEVEN": FRONT_SEVEN_POS_ABB,
    "FRONT_SEVEN_INTERIOR": FRONT_SEVEN_INTERIOR_POS_ABB,
    "DEFENSE_ALL": DEFENSE_ALL_POS_ABB,
}
