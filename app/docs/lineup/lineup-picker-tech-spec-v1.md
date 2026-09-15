# Brady Bot — Lineup Picker Module

## Technical Specification, V1

**Version:** 1.0
**Date:** September 12, 2026
**League:** Dhaka Chamber of Football, 2026 season
**Status:** Ready to build

---

## 0. TL;DR

The Lineup Picker selects a complete weekly starting lineup — QB, RB, RB, WR, WR,
W/R/T, K, D/ST — from the user's Yahoo roster.

It is a **deterministic factor-scoring engine**, not a projection engine. Each
position has its own weighted equation. Every factor is normalized to a 0.0–1.0
score, multiplied by a fixed weight, and summed. The highest score at each slot
starts. There is no machine learning, no forecasting, and no purchased
projections.

**Every input is either a current-state fact** (who is on the depth chart, who is
injured, what the betting market implies) **or an aggregate derived from data that
has already happened** (snap share to date, fantasy points a defense has allowed
to a position so far this season).

**Data sourcing:** 8 of 9 sources are nflverse via `nflreadpy` and cost nothing.
The single external dependency is The Odds API for implied team totals, used on
its free tier (500 requests/month; this system needs roughly 72). There are no
paid subscriptions, no scrapers, and no API keys other than the free Odds key.

**Deliverable:** `brady-bot lineup pick --week N` prints a starting lineup with a
per-factor breakdown for every decision, in under 30 seconds.

---

## 1. Scope

### 1.1 In scope for V1

- Weekly starting lineup selection for all 8 starting slots
- Seven per-position scoring models (QB, RB, WR, TE, FLEX, K, D/ST)
- All derived metrics computed from nflverse
- Manual roster entry via CLI
- Full reasoning output — every factor, score, and weight shown per player
- Append-only prediction logging for V2 calibration
- Deterministic, reproducible output given fixed inputs

### 1.2 Out of scope for V1

- Yahoo API integration (read or write). Roster is entered manually.
- Waiver wire, trades, draft — these are separate Brady Bot modules
- Any machine learning or fitted weights. All weights are judgment-set.
- Play-by-play derivation. V1 uses season and game-level aggregates only.
- Weather. None of the seven position models use it.
- Purchased data of any kind (FantasyPros, PFF, Draft Sharks, Rotoviz)

### 1.3 Design principles

1. **nflverse first.** If a data point can come from `nflreadpy`, it does.
2. **Free only.** No paid tier is a hard dependency.
3. **No projections.** Facts and historical aggregates only.
4. **Explainable.** Every score decomposes into named, inspectable factors.
5. **Deterministic.** Same inputs, same output, byte for byte.
6. **Documented deviations.** Where this spec departs from the position
   documents, Section 15 records what changed and why.

---

## 2. Glossary and Conventions

| Term | Definition |
|---|---|
| **Rank** | **Always 1 = strongest / best, 32 = weakest.** A defense ranked 1 is the BEST defense (hardest matchup). An offense ranked 1 is the BEST offense. This convention is universal across every picker, config key, and derived stat. Any source using the opposite convention is inverted inside its adapter, never inside a picker. |
| **Adj. FPA** | Adjusted Fantasy Points Allowed. How far above or below the league average a defense has held opposing players at a given position, per game. Positive = soft matchup. See §5.2. |
| **Factor score** | A value in [0.0, 1.0] produced by one scoring factor. |
| **Start Score** | The weighted sum of a position's factor scores. Also in [0.0, 1.0]. |
| **gsis_id** | nflverse canonical player identifier. The only player ID used in this system. |
| **Slot** | A lineup position to be filled: QB, RB1, RB2, WR1, WR2, FLEX, K, DEF. |
| **Candidate** | A rostered player eligible for a given slot in a given week. |
| **Effective start** | A player treated as a starter for depth-chart purposes because the player ahead of him is unavailable. |
| **Season-to-date (STD)** | Aggregated across all completed weeks of the current season. |
| **Trailing-N** | Aggregated across the last N completed games for that team or player. |

### 2.1 Scoring scale

All factor scores are in [0.0, 1.0] where **higher is always better for the
player being evaluated**.

**Start Scores are hard-capped at 1.00 at every position, without exception.**
Any intermediate value that would exceed 1.00 — the QB pass-catcher elite boost
(§8.1), the RB Tier 2 bonus (§8.2.1) — is clamped before the score is used for
anything. There is no uncapped score anywhere in the system.

```
start_score = min(1.00, weighted_sum + bonus)
```

Capping creates the possibility of ties at exactly 1.00. Those are resolved by
the tiebreak ladder in §8, not by allowing scores above the ceiling. This holds even where the underlying stat is
"bad-is-good" — a kicker's team being *inefficient* in the red zone produces a
*high* RedZone_Score, because inefficiency generates field goal attempts.

### 2.2 Position codes

`QB`, `RB`, `WR`, `TE`, `K`, `DEF`. The league UI calls the defense slot "D/ST";
internally it is `DEF`. FLEX is a slot, not a position.

---

## 3. Architecture

### 3.1 Pipeline

```
  ┌─────────────────┐
  │  CLI: pick      │  brady-bot lineup pick --week 5
  │  --week N       │
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │  Roster loader  │  data/roster.yaml → resolve names to gsis_id
  └────────┬────────┘
           │
           ▼
  ┌─────────────────────────────────────────────┐
  │  Source layer  (src/brady_bot/sources/)     │
  │  nflverse ×7 fetches + Odds API ×1          │
  │  All cached to data/cache/ with TTL         │
  └────────┬────────────────────────────────────┘
           │  raw polars DataFrames
           ▼
  ┌─────────────────────────────────────────────┐
  │  Derive layer  (src/brady_bot/derive/)      │
  │  → Adj. FPA per position per defense        │
  │  → Team ranks (offense, defense, RZ)        │
  │  → Player roles (WR1/2/3, RB snap share)    │
  │  → Injury counts by unit                    │
  │  → Player calibre ranks                     │
  │  → Implied totals                           │
  └────────┬────────────────────────────────────┘
           │  WeekContext (one immutable object)
           ▼
  ┌─────────────────────────────────────────────┐
  │  Picker layer  (src/brady_bot/pickers/)     │
  │  QB → RB → WR → TE → K → DEF → FLEX         │
  │  Each: gate → score factors → weight → rank │
  └────────┬────────────────────────────────────┘
           │  Lineup
           ▼
  ┌─────────────────┐     ┌──────────────────────┐
  │  Renderer       │     │  Prediction log      │
  │  Rich CLI table │     │  predictions.jsonl   │
  └─────────────────┘     └──────────────────────┘
```

### 3.2 Key architectural rule

**Pickers never touch a data source.** They read only from `WeekContext`, which is
fully materialized before any picker runs. This is what makes the system testable
— every picker test constructs a `WeekContext` fixture directly, with no network.

### 3.3 Technology

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | |
| Data frames | **Polars** | `nflreadpy` returns `polars.DataFrame`, not pandas. Do not mix. |
| nflverse client | `nflreadpy` | |
| Models | `pydantic` v2 | Validation at construction catches rank-direction bugs |
| Config | `pyyaml` | |
| CLI | `typer` + `rich` | |
| HTTP | `httpx` | Odds API only |
| Testing | `pytest` | |
| Caching | Local parquet + JSON under `data/cache/` | |

---

## 4. Data Source Registry

**Nine sources. Eight are nflverse and free. One is a free-tier external API.**

| ID | Source | Fetch call | Auth | Cost | Cache TTL | Feeds |
|---|---|---|---|---|---|---|
| **S1** | nflverse schedules | `nflreadpy.load_schedules(seasons=[season])` | None | Free | 24h | Bye weeks, opponent mapping, home/away |
| **S2** | nflverse player stats | `nflreadpy.load_player_stats(seasons=[season, season-1])` | None | Free | 6h | Adj. FPA, player calibre, target share, QB turnover rate |
| **S3** | nflverse team stats | `nflreadpy.load_team_stats(seasons=[season, season-1])` | None | Free | 6h | Team offense rank, sack rate allowed, scoring efficiency, defense calibre |
| **S4** | nflverse snap counts | `nflreadpy.load_snap_counts(seasons=[season, season-1])` | None | Free | 6h | RB snap share, WR/TE snap participation |
| **S5** | nflverse injuries | `nflreadpy.load_injuries(seasons=[season])` | None | Free | **2h** | Every injury factor across all seven pickers |
| **S6** | nflverse depth charts | `nflreadpy.load_depth_charts(seasons=[season])` | None | Free | 6h | Depth chart position, starter identification |
| **S7** | nflverse players | `nflreadpy.load_players()` | None | Free | 7d | Name → gsis_id crosswalk for roster and static lists |
| **S8** | The Odds API | `GET https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds` `?apiKey={ODDS_API_KEY}&regions=us&markets=spreads,totals&oddsFormat=american` | API key | **Free tier, 500/mo** | 6h | Implied team totals, game totals |
| **S9** | Static config | `config/static_lists.yaml` | None | Free | n/a | Matchup-proof tiers, elite pass-catchers, QB playing styles |
| **S10** | O-line rankings | `config/oline_ranks.yaml` | None | Free | n/a | Team O-line **quality** rank 1–32 (ESPN preseason). See `lineup-picker-OLINE.md`. Quality only — injury counts stay live via S5/S6. |
| **S11** | Depth overrides | `config/committee_overrides.yaml` | None | Free | n/a | Manual `pos_rank` override when a published depth chart is known stale. See `lineup-picker-DEPTH-CHART.md`. |
| **S12** | QB calibre ranking | `config/qb_calibre_ranks.yaml` | None | Free | n/a | Authoritative 99-QB calibre rank, used by WR/TE/FLEX/D-ST only. See `lineup-picker-QB-CALIBRE.md`. Never consumed by QB's own scoring. |

### 4.1 Notes on S5 (injuries)

Shortest TTL in the system at 2 hours. Injury designations change through
Friday and Saturday, and a stale designation is the most damaging kind of stale
data this system can have — it produces a confidently-started player who does not
play.

If the S5 fetch timestamp is more than 24 hours before the earliest kickoff in the
week, emit a `stale_injury_data` warning listing every Questionable player and
advise re-running closer to kickoff.

### 4.2 Notes on S8 (The Odds API)

The only external dependency and the only quota-limited one.

One request returns all NFL games for the week, so one refresh costs 1 request.
At 4 active days per week × 18 weeks that is roughly 72 requests/month against a
500 limit.

**Quota protection:** `--no-cache` must NOT bypass the S8 cache unless
`--no-cache=odds` is passed explicitly. Every other source bypasses normally. A
development loop that re-fetches odds on every run will exhaust the free tier.

**Implied total derivation:**

```
implied_total(favourite) = (game_total / 2) + (abs(spread) / 2)
implied_total(underdog)  = (game_total / 2) - (abs(spread) / 2)
```

Average `spread` and `total` across all returned books before computing.

### 4.3 What is deliberately NOT a source

| Not used | Why |
|---|---|
| FantasyPros API | Requires a paid HOF subscription for production use. Every data point it would supply is derivable from nflverse. |
| PFF | Paid. Its two uses (O-line run-block grade, pressure rate) have free nflverse proxies. See §5.7 and §15. |
| ESPN rankings | Not in nflverse; undocumented endpoints. Player calibre is derived from nflverse instead. See §5.6 and §15. |
| Play-by-play (`load_pbp`) | Large download, and V1 deliberately stays at game/season aggregate granularity. |
| Weather (Open-Meteo) | No position model in this set uses weather. |

---

### 4.4 Data completeness status

Every scoring factor in every picker now names a source. Two categories of work
remain, and they are different in kind.

**Resolved — static config is complete.** All hard-coded lists are fully
populated and require no further research:

| List | Entries | Status |
|---|---|---|
| `qb_styles` | 107 QBs, all 32 teams | Complete — see §10.3 |
| `rb_tier1` | 6 | Complete |
| `rb_tier2` | 4 | Complete |
| `wr_top5` | 5 | Complete |
| `elite_wrs` | 10 | Complete |
| `te_top4` / `elite_tes` | 4 | Complete |
| `oline_ranks` (S10) | 32 teams | Complete — see `lineup-picker-OLINE.md` |
| `depth_overrides` (S11) | As needed | Optional — published depth charts are primary; overrides correct stale preseason listings |

**Outstanding — schema verification, not sourcing.** Every factor has a named
source; what is not yet confirmed is that those sources contain the assumed
columns with the assumed coverage. This is the Step 0 probe in the data pipeline
spec, and it must complete before the derive layer is written.

| Assumption | Affects | Fallback if false |
|---|---|---|
| `load_player_stats()` carries kicking columns | K calibre (15% of K) | Team FG data via depth chart, then team scoring efficiency, flagged `k_calibre_proxy` |
| `load_depth_charts()` covers OL, DB, LB, DL | Every injury unit count across all 7 pickers | Define starters by trailing defensive snap share (S4), flagged `starters_from_snaps` |
| `load_snap_counts()` joins to `gsis_id` | RB snap share (30% of RB) | Crosswalk via `load_players().pfr_id`; halt if <95% hit rate |
| `load_team_stats()` carries defensive aggregates | DEF calibre, K opposing defense | Aggregate opponents' offensive stats instead |
| `load_schedules()` carries usable `spread_line` / `total_line` | Odds fallback only | None needed — S8 is primary |

None of these are design gaps. The logic is fully specified regardless of column
naming; a miss is a local fix inside one derive function.

---

## 5. Derived Metrics

This section is the heart of the spec. Every factor in every picker traces back to
one of these functions. **Each is a pure function of source data plus config — no
network calls, no hidden state.**

All live in `src/brady_bot/derive/`.

### 5.1 League scoring (used for derivation and backfill only)

`config/league.yaml` holds the full league scoring table. It is used in exactly
two places:

1. Computing fantasy points allowed for Adj. FPA (§5.2)
2. Computing realized scores when backfilling the prediction log (§12)

It is **not** used to score players in any picker — the pickers are factor-based.

```yaml
scoring:
  passing_yards_per_point: 30
  passing_td: 5
  interception: -2
  pick_six: -2
  rushing_yards_per_point: 10
  rushing_td: 6
  receiving_yards_per_point: 10
  receiving_td: 6
  reception: 0.5          # half-PPR
  fumble_lost: -2
  two_point_conversion: 2
```

> **Verify before first run.** These values were captured from the league
> settings; confirm against Yahoo before Week 1. A wrong value here silently
> distorts every Adj. FPA in the system.

### 5.2 Adjusted Fantasy Points Allowed — `derive_adj_fpa()`

**The single most important derived metric.** It feeds the matchup factor in QB
(30%), RB (20%), WR (20%), TE (25%), and FLEX (25%).

```python
def derive_adj_fpa(
    player_stats: pl.DataFrame,   # S2
    schedules: pl.DataFrame,      # S1
    position: str,                # "QB" | "RB" | "WR" | "TE"
    season: int,
    through_week: int,
    cfg: LeagueConfig,
) -> dict[str, float]:
    """Team -> Adj. FPA against `position`, in fantasy points per game.

    Positive = this defense allows MORE than league average = soft matchup.
    """
```

**Algorithm:**

1. Filter S2 to `season_type == "REG"` and `week <= through_week`.
2. Filter to `position`. Map `FB` → `RB`. Take nflverse's position designation as
   given; do not reclassify hybrids manually.
3. **Fill nulls with 0 on every stat column before any arithmetic.** A QB row has
   a null `receiving_yards`, not a zero. Null propagates through arithmetic and
   would silently drop that player's entire contribution.
4. Score each player-game with `cfg.scoring`.
5. Group by `opponent_team` (the defense) and sum fantasy points.
6. Divide by that defense's count of **distinct weeks played**, giving points
   allowed per game.
7. Compute the league-wide mean across all 32 defenses.
8. `AdjFPA[team] = points_allowed_per_game[team] − league_mean`

**Step 6 is not optional.** Summing across the season penalises teams that have
played more games. In Week 8 a defense that has had its bye has played 6 games and
one that has not has played 7. Summing makes the bye team look meaningfully
stronger for reasons unrelated to its defense. The bias peaks mid-season, exactly
when these ranks start driving decisions.

**Validation:** if the result contains fewer than 32 teams, **halt**. A missing
team means a filter or join dropped rows silently, and ranking a partial set
produces a wrong 1–32 scale for every team.

### 5.3 Matchup score — `matchup_score()`

Converts Adj. FPA into a [0.0, 1.0] factor score.

```python
def matchup_score(adj_fpa: dict[str, float], team: str, mode: str) -> float:
    """mode: "percentile" (default) | "linear" """
```

**Default mode — `percentile`:**

```
def_rank    = rank of team by adj_fpa ASCENDING   # rank 1 = lowest FPA = strongest D
score       = (def_rank - 1) / 31                  # rank 1 → 0.00, rank 32 → 1.00
```

**Alternate mode — `linear`** (the literal formula in the position documents):

```
score = max(0.0, min(1.0, (adj_fpa + 10) / 20))
```

**Why percentile is the V1 default.** The `linear` formula uses a fixed ±10 point
window for every position. That window is calibrated for QB, where players score
roughly 18 points per game and a ±10 swing is meaningful. It is badly miscalibrated
for TE, where players score roughly 7 points per game and a defense will
essentially never be ±10 off league average. Under `linear`, every TE matchup
score would compress into a narrow band around 0.50, and the TE model's 25% matchup
weight would do almost nothing.

Percentile ranking is scale-free, preserves the full ordering, and behaves
identically well at every position.

Set via `config/weights.yaml → global.matchup_normalization`. This is a documented
deviation — see §15.

### 5.4 Team ranks — `derive_team_ranks()`

All from S3. All follow the rank 1 = strongest convention.

| Rank | Metric | Used by |
|---|---|---|
| `offense_rank` | Total yards per game, descending | K Step 2, DEF Step 4 (as opponent) |
| `total_defense_rank` | Total yards allowed per game, ascending | K Step 4 |
| `scoring_efficiency_rank` | Points per 100 offensive yards, descending | K Step 3 (see §5.5) |

O-line quality ranks are **not** derived here — they load from S10, see §5.7.
| `defense_calibre_rank` | Yards allowed per play, ascending | DEF Step 7 |
| `qb_turnover_rank` | Team INTs + fumbles lost per game, ascending | DEF Step 2 |

### 5.5 Red-zone inefficiency proxy — `derive_rz_inefficiency()`

The K model wants "teams that move the ball but stall in the red zone." True
red-zone TD rate requires drive-level or play-by-play data, which V1 excludes.

**Free proxy, computable entirely from S3:**

```
scoring_efficiency = offensive_points_per_game / (offensive_yards_per_game / 100)
```

A team with high yardage and low points is, by definition, stalling before the end
zone. That is precisely the kicker-friendly profile.

```
rz_inefficiency_rank = rank by scoring_efficiency ASCENDING   # rank 1 = least efficient
```

Note that this proxy also picks up turnovers and failed fourth downs, not only
red-zone stalls. Both of those also suppress touchdowns without suppressing
yardage, so the directional signal holds. It is a coarser instrument than true RZ
TD%, and §16 flags the upgrade.

### 5.6 Player calibre ranks — `derive_player_calibre()`

**QB is the one exception.** QB calibre is not derived by this function — it is
loaded from the static ranking in `lineup-picker-QB-CALIBRE.md` (S12), because
every consumer of QB calibre (WR, TE, FLEX, D/ST) must agree on the same
number for the same quarterback, and a human-verified single source guarantees
that. `derive_player_calibre()` remains the mechanism for RB, WR, TE, and K
calibre exactly as below, and serves as the **fallback** for any QB absent from
S12 — see `lineup-picker-QB-CALIBRE.md` for the 8 quarterbacks this applies to.

QB calibre is never used to score the QB picker itself — its equation has no
self-calibre factor.


The position documents specify ESPN positional rankings. ESPN rankings are not in
nflverse and are only available through undocumented endpoints.

**V1 derives calibre from nflverse instead:**

```python
def derive_player_calibre(
    player_stats: pl.DataFrame,   # S2
    position: str,
    season: int,
    through_week: int,
    cfg: LeagueConfig,
) -> dict[str, int]:
    """gsis_id -> calibre rank within position. Rank 1 = best."""
```

**Algorithm:**

1. Score every player-game with `cfg.scoring`, nulls filled with 0.
2. Compute **fantasy points per game played** for each player at the position.
3. Require a minimum of 3 games played this season to qualify. Players below the
   threshold fall back to their prior-season per-game average.
4. Rank descending. Rank 1 = highest per-game scorer.

Then apply the position-specific denominators from the position documents:

```
Ranking_Score = max(0, 1 - (rank - 1) / denominator)
```

| Position | Denominator | Rationale (from the position docs) |
|---|---|---|
| WR | 59 | Deepest startable pool |
| RB | 39 | Fewer startable options than WR |
| TE | 29 | Roughly half as many as WR |
| DEF | 31 | All 32 defenses |

This is a documented deviation — see §15. Note the substitution is arguably
*better* suited to the model: expert rankings are forward-looking and already
embed matchup expectations, whereas the factor-score architecture wants a
matchup-agnostic measure of how good the player has actually been.

### 5.7 O-line quality — authoritative ranking (S10)

**O-line quality is not derived. It is loaded from `config/oline_ranks.yaml`**,
sourced from the ESPN preseason rankings and documented in full in
`lineup-picker-OLINE.md`.

```python
def load_oline_ranks(cfg) -> dict[str, int]:
    """Team -> O-line quality rank. Rank 1 = best line, 32 = worst.

    Static, preseason. Quality only — line HEALTH is a separate live
    input via derive_injury_counts(team, "OL"). See §5.8.
    """
```

**Two consumers, opposite directions, one number:**

| Consumer | Reads | Direction |
|---|---|---|
| RB Step 5 (15%) | Own team's rank | Rank 1 → 1.00 (a strong line helps the back) |
| DEF Step 4 (15%) | **Opponent's** rank | Rank 1 → 0.10 (a strong opposing line hurts your defense) |

The inversion lives in each picker's scoring table, never in the data.

**Validation at load — all four halt on failure:** exactly 32 teams present;
ranks 1–32 contiguous with no duplicates; every code canonical after
`TEAM_ALIASES`; every NFL team appearing exactly once. These mirror the 32-team
assertions already enforced for Adj. FPA (§5.2) and team ranks (§5.4).

**Team code note.** ESPN publishes Washington as `WSH`; the canonical code is
`WAS`. Normalization happens at load like every other team reference.

**Retired derived metrics.** `run_block_rank` (team rushing YPA) and
`sack_rate_allowed_rank` (team sacks allowed ÷ pass attempts) were the V1 free
proxies for PFF grades. Both are superseded by S10 and should be **removed**
from `derive/team_ranks.py` — a derived value nothing consumes is a maintenance
cost and a future source of confusion about which figure is authoritative.

### 5.8 Injury unit counts — `derive_injury_counts()`

Several factors count "missing starters" in a unit. One function handles all.

```python
def derive_injury_counts(
    injuries: pl.DataFrame,      # S5
    depth_charts: pl.DataFrame,  # S6
    team: str,
    unit: str,                   # "OL" | "SECONDARY" | "FRONT_SEVEN" | "DEFENSE_ALL"
    week: int,
) -> int:
    """Count of unavailable STARTERS in the given unit."""
```

**Starter definition:** `depth_chart_order == 1` at that position in S6 for the
current week.

**Unavailable definition:**

| `report_status` | `practice_status` | Counts as unavailable? |
|---|---|---|
| `Out` | any | **Yes** |
| `Doubtful` | any | **Yes** |
| `Questionable` | `DNP` or `Limited` | **Yes** (counts as "limited") |
| `Questionable` | `Full` | No |
| `Questionable` | null | **Yes** (conservative default) |
| null / none | any | No |

**Unit position mappings:**

| Unit | Positions counted |
|---|---|
| `OL` | T, OT, LT, RT, G, OG, LG, RG, C |
| `SECONDARY` | CB, DB, S, FS, SS, NB |
| `FRONT_SEVEN` | DT, NT, DE, EDGE, OLB, ILB, MLB, LB |
| `DEFENSE_ALL` | Union of SECONDARY and FRONT_SEVEN |

**RB Step 8 refinement.** The RB model states that for run defense, interior
linemen and middle linebackers matter most while edge rushers matter less. V1
implements this by counting only `DT, NT, ILB, MLB, LB` for the RB front-seven
factor, excluding `DE, EDGE, OLB`. This is captured as unit `FRONT_SEVEN_INTERIOR`.

### 5.9 Player role resolution — `derive_roles()`

Determines WR1/WR2/WR3, RB snap share tier, and TE1/TE2.

**WR role.** nflverse depth charts are known to be unreliable for wide receiver
ordering, because teams list receivers by formation position (X/Y/Z, slot) rather
than by target priority.

V1 therefore determines WR role by **trailing-4-game target share within team**,
ranked descending:

| Target share rank on team | Role |
|---|---|
| 1 | WR1 |
| 2 | WR2 |
| 3 | WR3 |
| 4+ | WR4+ |

Weeks 1–4 blend prior-season target share per the schedule in §5.10. Source: S2.
S6 depth chart is used only as a tiebreak when two receivers are within 1
percentage point of target share.

This is a documented deviation — see §15.

**RB snap share.** Direct from S4:

```
snap_share = player offensive snaps / team total offensive snaps
```

Tiered per the RB model: 60%+ = 1.00, 50–60% = 0.80, 30–50% = 0.20, <30% = 0.10,
inactive = 0.00.

**TE1 identification.** S6 depth chart order at TE, with **effective start**
promotion: if the TE1 is unavailable per §5.8, the TE2 is promoted to TE1 for the
week. The TE model's binary gate then passes him.

### 5.9a Depth chart position scoring — `posrank_score()`

Full tables, rationale, and consumers in `lineup-picker-DEPTH-CHART.md`.

**Depth chart position is a primary scoring input, not bookkeeping.** It is the
early-season anchor for opportunity, fading to zero influence by Week 5 as real
usage data takes over.

```python
def posrank_score(pos_rank: int | None, position: str) -> float:
    """Depth chart rank -> cardinal score on [0.0, 1.0].

    Applies to RB, WR, TE only. None (no depth entry) -> 0.00 with a
    `no_depth_entry` flag.
    """
```

| Depth | RB | WR | TE |
|---|---|---|---|
| Rank 1 | **1.00** | **1.00** | **1.00** |
| Rank 2 | **0.30** | **0.60** | **0.00** |
| Rank 3 | 0.00 | **0.25** | 0.00 |
| Rank 4+ | 0.00 | 0.00 | 0.00 |
| No entry | 0.00 | 0.00 | 0.00 |

The RB1→RB2 drop of 0.70 is the steepest in the system, matching the position
document's "cliff, not a slope" premise. WR falls off more gently because
three-receiver sets give WR2 and WR3 recurring roles.

**Not applicable to QB, K, or D/ST.** QB uses a binary `pos_rank == 1` gate; K
and D/ST have no depth-based factor. `pos_rank` is still read for those
positions to identify starters for gates and injury unit counts, but never
scored.

**Two cases resolved here** that the source tables left open: RB3+ scores 0.00
(consistent with WR4+ and TE2+), and a player absent from the depth chart scores
0.00 with a `no_depth_entry` flag — visible because absence can mean a data gap
rather than a real demotion.

**Pinning is mandatory.** `load_depth_charts()` has no `week` column, so every
read filters to each team's max `dt` first. An unpinned read can resolve a stale
rank from weeks earlier.

### 5.9b RETIRED — Committee change detection

Full rule, rationale, and worked examples in `lineup-picker-COMMITTEE.md`.

**Status: retired. Superseded by §5.9a.**

The committee change rule substituted a neutral 0.50 for the prior-season
component when a player's committee had changed, because prior-season usage from
a different team or a different supporting cast was misleading.

`pos_rank` makes that substitution unnecessary. It reads from the player's
**current** team's **current** depth chart, so it already reflects the new
situation — Kansas City's depth chart states Kenneth Walker III's role in Kansas
City; no Seattle data is involved. Forcing 0.50 on top would discard good
current-team data in favor of an artificial neutral.

**What survives:** the per-game denominator rule (§5.10.2) is unaffected and
remains in force. `config/committee_overrides.yaml` is retained but repurposed
as a manual `pos_rank` override for stale depth charts — see §5.9a.

The original rule is preserved below for the record.

```python
def derive_committee_changed(
    player_stats_prior: pl.DataFrame,   # S2, season-1
    depth_charts: pl.DataFrame,         # S6, current
    overrides: dict[str, bool],         # S11
    player_id: str,
    position: str,                      # "RB" | "WR"
) -> bool:
    """True when this player's opportunity committee changed between seasons."""
```

**Committee definitions:**

| Position | Committee | Size |
|---|---|---|
| RB | RB1, RB2 | 2 |
| WR | WR1, WR2, TE1 | 3 |

The player is a member of his own committee. Sets are compared **unordered**, so
an internal promotion with identical personnel does not trigger the flag.

**Trigger — any one is sufficient:** player changed teams; any committee member
departed; any committee member newly arrived; player has no prior-season data
(rookie).

**Membership derivation:**

- Prior committee — top N by prior-season **realized share** (snap share for RB,
  target share for WR/TE) on the player's **prior-season team**
- Current committee — `pos_rank` 1..N from S6 depth charts on the current team

These are different instruments and can disagree, which can produce false
positives. `config/committee_overrides.yaml` (S11) is checked **first** and
always wins. See the asymmetry note in `lineup-picker-COMMITTEE.md`.

### 5.10 Early-season blending — `blend_early_season()`

`load_team_stats()` returns nothing usable in Week 1 and very little through Week
3. Without blending, every rank-based factor silently collapses to neutral for the
first month.

| Week | Prior season | Current season |
|---|---|---|
| 1 | 100% | 0% |
| 2 | 75% | 25% |
| 3 | 50% | 50% |
| 4 | 25% | 75% |
| 5+ | 0% | 100% |

**Blend the underlying per-game rates, then rank once.** Do NOT blend ranks.
Ranks are ordinal; `(rank_prior × 0.5) + (rank_current × 0.5)` is not a meaningful
operation.

Any `TeamStats` or Adj. FPA object produced with blending carries
`blended = True`, and the CLI surfaces it until Week 5.

**RB snap share is the exception.** Per the RB position document, its prior-season
component uses **only Weeks 10–18 of the prior season**, not the full year,
because late-season backfield roles are more predictive than early-season ones.
The weighting schedule is otherwise identical.

#### 5.10.1 Depth chart blending

`pos_rank` occupies the **early component** of the blend, replacing
prior-season usage data in that slot.

```
depth_score = (w_posrank × posrank_score) + (w_usage × usage_score)
```

| Week | pos_rank weight | Current usage weight |
|---|---|---|
| 1 | 100% | 0% |
| 2 | 75% | 25% |
| 3 | 50% | 50% |
| 4 | 25% | 75% |
| **5+** | **0%** | **100%** |

Both terms are cardinal scores on [0.0, 1.0], so the result is too.

Affected factors: **RB Step 3** (30%), **WR Step 3** (20%), **FLEX Step 2**
(40%). TE's depth handling stays a binary gate; QB, K and D/ST are unaffected.

**This is a score-level blend, and it does not violate non-negotiable #5.** That
rule forbids averaging **ordinals** — the midpoint of rank 1 and rank 3 is not
"rank 2's worth of value." Here `pos_rank` is converted to a cardinal score
through the §5.9a lookup *before* any arithmetic. Averaging two cardinal scores
on the same scale is well-defined. Rule #5 is reworded accordingly: blend rates
or scores, never raw ordinal ranks.

**From Week 5, `pos_rank` contributes nothing to any score.** It continues to be
read for role identification — QB1/TE1 gates, starter identification for injury
unit counts — but its scoring weight is zero.

**Prior-season snap share is retired from RB Step 3.** The Weeks 10–18 rule no
longer applies there; `pos_rank` fills that slot. Prior-season data remains in
use elsewhere, notably player calibre.

#### 5.10.2 Per-game denominator

**Every per-game rate in the system divides by games the player was healthy and
actually played.** Applies to snap share, target share, and fantasy points per
game, in both prior- and current-season components.

| Situation | In denominator? |
|---|---|
| Played, ≥1 offensive snap | Yes |
| Active, 0 offensive snaps | Yes — a healthy scratch from the rotation is real signal |
| Inactive / IR / did not travel | **No** |
| Bye week | **No** |
| Suspended | **No** |

A missed game is **excluded**, never counted as a zero. Counting it as zero drags
a workhorse's average toward a backup's — a back at 70% across 10 games played
who missed 7 reads as 41.2% ("1B in committee", 0.20) instead of 70.0% ("clear
workhorse", 1.00). That is a 0.80 swing on the RB model's heaviest factor.

### 5.11 Static list resolution — `resolve_static_lists()`

`config/static_lists.yaml` holds hard-coded player names (matchup-proof tiers,
elite pass-catchers, QB playing styles). These resolve to gsis_id **once at
startup** via S7.

**Resolution order:** exact `display_name` match filtered by team and position →
normalized-name match (strip suffixes Jr./Sr./II/III/IV, remove punctuation and
apostrophes, collapse whitespace, casefold).

**Ambiguity or failure to resolve is a hard halt**, naming the unresolved entry.
A silently unresolved "Ja'Marr Chase" means the matchup-proof gate never fires for
him, which changes lineups without any visible error.

**Same-team surname collisions are real in `qb_styles`.** Josh Allen (BUF, QB1)
and Kyle Allen (BUF, QB2) share a team; several Johnsons and Jones appear
league-wide. Resolution must filter on team **and** position, never name alone.

---

## 6. Data Models

All pydantic v2. `src/brady_bot/models.py`.

```python
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
    QB = "QB"
    RB1 = "RB1"
    RB2 = "RB2"
    WR1 = "WR1"
    WR2 = "WR2"
    FLEX = "FLEX"
    K = "K"
    DEF = "DEF"
    BENCH = "BN"


class Player(BaseModel):
    player_id: str          # gsis_id; "DEF-{TEAM}" for team defenses
    name: str
    team: str               # nflverse team code, normalized via TEAM_ALIASES
    position: Position
    bye_week: Optional[int] = None

    @property
    def is_team_defense(self) -> bool:
        return self.position == Position.DEF


class InjuryRecord(BaseModel):
    player_id: str
    report_status: Optional[Literal["Out", "Doubtful", "Questionable"]] = None
    practice_status: Optional[Literal["DNP", "Limited", "Full"]] = None

    @property
    def is_unavailable(self) -> bool:
        """See the table in §5.8."""
        if self.report_status in ("Out", "Doubtful"):
            return True
        if self.report_status == "Questionable":
            return self.practice_status in ("DNP", "Limited", None)
        return False


class TeamStats(BaseModel):
    team: str
    season: int
    through_week: int
    blended: bool = False

    # Ranks: 1 = strongest, 32 = weakest (§2). Bounds are deliberate —
    # an inverted or off-by-one rank fails loudly at construction.
    offense_rank: int = Field(ge=1, le=32)
    total_defense_rank: int = Field(ge=1, le=32)
    scoring_efficiency_rank: int = Field(ge=1, le=32)
    defense_calibre_rank: int = Field(ge=1, le=32)
    qb_turnover_rank: int = Field(ge=1, le=32)


class GameContext(BaseModel):
    game_id: str
    home_team: str
    away_team: str
    game_total: float
    spread: float                 # negative = home favoured
    home_implied_total: float
    away_implied_total: float

    def implied_total_for(self, team: str) -> float: ...
    def opponent_of(self, team: str) -> str: ...


class WeekContext(BaseModel):
    """Fully materialized before any picker runs. Pickers read only this."""
    season: int
    week: int
    fetched_at: str                                # ISO 8601 UTC

    roster: list[Player]
    injuries: dict[str, InjuryRecord]              # player_id -> record
    team_stats: dict[str, TeamStats]               # team -> stats
    games: dict[str, GameContext]                  # team -> that team's game

    adj_fpa: dict[str, dict[str, float]]           # position -> team -> Adj. FPA
    calibre_rank: dict[str, dict[str, int]]        # position -> player_id -> rank
    roles: dict[str, str]                          # player_id -> "WR1" | "RB_LEAD" | ...
    snap_share: dict[str, float]                   # player_id -> 0.0-1.0
    target_share: dict[str, float]                 # player_id -> 0.0-1.0
    injury_counts: dict[str, dict[str, int]]       # team -> unit -> count
    bye_teams: list[str]

    blended: bool = False                          # True through Week 4


class FactorScore(BaseModel):
    name: str
    raw_value: Optional[str] = None    # human-readable input, e.g. "snap share 64%"
    score: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0, le=1.0)

    @property
    def contribution(self) -> float:
        return self.score * self.weight


class ScoredPlayer(BaseModel):
    player: Player
    weighted_sum: float = Field(ge=0.0, le=1.0)   # factors only, always [0,1]
    bonus: float = 0.0                            # RB Tier 2 only (§8.2.1)
    start_score: float = Field(ge=0.0, le=1.0)    # min(1.0, weighted_sum + bonus)
    factors: list[FactorScore]
    gate_result: Literal["passed", "auto_start", "eliminated"] = "passed"
    gate_reason: Optional[str] = None
    flags: list[str] = []                         # "score_capped" when the cap binds

    # start_score is hard-capped at 1.00 everywhere. Ties at the ceiling are
    # broken by weighted_sum, then player_id — see the sort key in §8.


class Lineup(BaseModel):
    season: int
    week: int
    run_id: str
    starters: dict[Slot, ScoredPlayer]
    bench: list[ScoredPlayer]
    warnings: list[str] = []
```

### 6.1 Weight validation

Every position's weights must sum to exactly 1.00. Assert this at config load with
a tolerance of 1e-9 and **halt** on failure. `rb.tier2_bonus` is explicitly
excluded from that sum — it is an additive bonus applied after weighting, not a
factor weight. A weights file that sums to 0.95
produces plausible-looking scores that are silently wrong.

---

## 7. Shared Scoring Components

Several factors appear identically across positions. Implement once in
`src/brady_bot/scoring/shared.py`.

### 7.1 Baseline / implied total

Used by QB (10%), RB (5%), WR (5%), TE (5%), FLEX (10%).

| Implied Total | Score |
|---|---|
| 25+ | 1.00 |
| 23–24 | 0.75 |
| 21–22 | 0.50 |
| 19–20 | 0.25 |
| <19 | 0.00 |

Source: S8 via `GameContext.implied_total_for(team)`.

### 7.2 Tiered injury penalty

Used by QB Step 5 and 7, WR Step 8, TE Step 8, RB Step 8, DEF Step 5.

| Missing starters | Score |
|---|---|
| 0 | 1.00 |
| 1 | 0.75 |
| 2 | 0.50 |
| 3+ | 0.25 |

Source: `derive_injury_counts()` (§5.8).

### 7.3 QB quality score

Used by WR Step 5, TE Step 5, FLEX Step 4.

```
if QB1 is unavailable (§5.8):
    score = min(0.50, tier_score(backup_qb_rank))    # hard cap at 0.50
else:
    score = tier_score(qb1_rank)
```

| QB calibre rank | Score |
|---|---|
| 1–5 | 1.00 |
| 6–12 | 0.75 |
| 13–20 | 0.50 |
| 21–28 | 0.25 |
| 29+ | 0.00 |

`qb1_rank` comes from **S12, the static QB calibre ranking**
(`lineup-picker-QB-CALIBRE.md`), not from `derive_player_calibre()`. A QB absent
from S12 falls back to `derive_player_calibre(position="QB")`, flagged
`qb_calibre_derived_fallback`. The team's QB1 is identified from S6 depth chart
with effective-start promotion, exactly as before — only the calibre lookup
changed.

This is the same rank read by D/ST's opposing-QB factor (§8.6) — one ranking,
shared, so every consumer agrees on the same QB's quality.

### 7.4 Rank-to-score normalization

```python
def rank_to_score(rank: int, denominator: int) -> float:
    return max(0.0, 1.0 - (rank - 1) / denominator)
```

---

## 8. Position Pickers

Each picker follows the same contract:

```python
class Picker(ABC):
    position: Position
    slots: int

    def select(self, ctx: WeekContext, candidates: list[Player])
        -> tuple[list[ScoredPlayer], list[ScoredPlayer]]:
        """Returns (starters, bench). Bench feeds the FLEX pool."""
```

Universal order of operations, applied by `pickers/base.py`:

1. **Bye filter** — drop players whose team is in `ctx.bye_teams` (S1)
2. **Availability filter** — drop players who are unavailable per §5.8
3. **Position gate** — binary eliminations (QB1 check, TE1 check)
4. **Auto-start check** — matchup-proof tiers
5. **Factor scoring** — compute each factor, weight, sum
6. **Cap** — `start_score = min(1.00, weighted_sum + bonus)`
7. **Rank and select** — sort by
   `(start_score DESC, weighted_sum DESC, player_id ASC)`

**The three-level sort key matters.** Capping at 1.00 means two strong candidates
can arrive at an identical `start_score`. `weighted_sum` — the pre-bonus factor
score, always uncapped-safe because weights sum to 1.00 — breaks that tie on
merit rather than arbitrarily. `player_id` is the final fallback and exists only
to guarantee determinism.

Without the middle key, two Tier 2 RBs both clamping to 1.00 would be separated
by alphabetical accident. With it, the one whose factors actually scored higher
wins the slot.

---

### 8.1 QB Picker

**Equation:**

```
QB Start Score = (0.15 × Style)
               + (0.20 × PassCatcher)
               + (0.10 × OLine)
               + (0.30 × Matchup)
               + (0.15 × SecondaryInjury)
               + (0.10 × Baseline)
```

**Slots:** 1. **Not FLEX-eligible.**

| Step | Factor | Weight | Computation | Source |
|---|---|---|---|---|
| 1 | Roster check | — | If 1 QB rostered, auto-start | Roster |
| 2 | Depth chart gate | Binary | `depth_chart_order == 1` at QB, with effective-start promotion. Else **eliminate**. | S6 |
| 3 | Style | 15% | Mobile → 1.00, not mobile → 0.00. Lookup in `static_lists.qb_styles` (107 QBs, all 32 teams). Unlisted QB → derive from S2 rushing attempts/game ≥ `config.qb_dual_threat_rush_att_threshold` (default **4.0**), flag `style_derived`. | S9, S2 fallback |
| 4 | Pass-catcher quality | 20% | `base_health[n_healthy] + 0.10 × n_elite`, uncapped. Healthy = WR1/WR2/WR3/TE1 available per §5.8. Elite = in `static_lists.elite_wrs` (top 10) or `elite_tes` (top 4). | S5, S6, S9 |
| 5 | O-line injuries | 10% | `tiered_injury_penalty(injury_counts[team]["OL"])` | §5.8 |
| 6 | Matchup | **30%** | `matchup_score(adj_fpa["QB"], opponent)` | §5.2, §5.3 |
| 7 | Secondary injuries | 15% | `tiered_injury_penalty(injury_counts[opponent]["SECONDARY"])` | §5.8 |
| 8 | Baseline | 10% | Implied total tier (§7.1) | S8 |

**Step 4 base health map:** `{4: 0.90, 3: 0.70, 2: 0.50, 1: 0.25, 0: 0.00}`

**Note on Step 4:** the elite boost is uncapped by design, so a QB with four
healthy pass-catchers including two elites scores `0.90 + 0.20 = 1.10`. This
exceeds the [0,1] range of every other factor. **Clamp `PassCatcher_Score` to
1.00** before weighting, to keep the Start Score in [0,1] and comparable across
positions. Record the pre-clamp value in `FactorScore.raw_value`.

**Note on Step 3:** playing style is now a **lookup, not a derivation**. The QB
position document carries a definitive 107-quarterback table classifying every
rostered QB on all 32 teams as mobile or not mobile. That table is the source of
truth and is loaded into `static_lists.qb_styles`.

The rushing-attempts threshold survives only as a fallback for quarterbacks not
in the table — mid-season signings, practice-squad elevations, waiver claims. Any
QB classified that way carries a `style_derived` flag so the output shows the
value was inferred rather than looked up.

**The same table drives the DEF picker's mobile flag (§8.6).** One boolean, two
consumers, no second list to keep in sync.

---

### 8.2 RB Picker

**Equation:**

```
Weighted_Sum   = (0.30 × DepthChart)
               + (0.15 × Ranking)
               + (0.15 × OLine)
               + (0.10 × TeammateInjury)
               + (0.20 × Matchup)
               + (0.05 × FrontSevenInjury)
               + (0.05 × Baseline)

RB Start Score = min(1.00, Weighted_Sum + Tier2_Bonus)
```

Weights sum to 1.00, so `Weighted_Sum` is in [0.0, 1.0]. `Tier2_Bonus` is +0.30
for a Tier 2 RB and 0.00 otherwise — see §8.2.1.

**RB is the only position with an additive bonus**, but the result is capped at
1.00 like every other position. A Tier 2 RB with a weighted sum of 0.70 or better
lands on the ceiling.

**Slots:** 2. Bench RBs pass to the FLEX pool.

| Step | Factor | Weight | Computation | Source |
|---|---|---|---|---|
| 1 | Roster check | — | If exactly 2 RBs rostered, start both | Roster |
| 2 | Matchup-proof tiers | — | Tier 1 (`static_lists.rb_tier1`, top 6) → **auto-start**, equation never runs. Tier 2 (`rb_tier2`, 7–10) → score normally, then **+0.30** added to the weighted sum. See §8.2.1. | S9 |
| 3 | Depth chart position | **30%** | Weeks 1–4 blend of `posrank_score` (RB1 **1.00**, RB2 **0.30**, RB3+ 0.00) with current snap share tiers (≥0.60 → 1.00; 0.50–0.60 → 0.80; 0.30–0.50 → 0.20; <0.30 → 0.10; inactive → 0.00). Weights 100/0 → 0/100 across weeks 1–5 per §5.10.1. Prior-season W10–18 snap share **retired** from this factor. | S6, S4 |
| 4 | Player calibre | 15% | `rank_to_score(calibre_rank["RB"][pid], 39)` | §5.6 |
| 5 | O-line quality | 15% | `oline_tier(oline_ranks[team]) × injury_multiplier(injury_counts[team]["OL"])` | **S10**, §5.8 |
| 6 | Teammate RB injuries | 10% | See table below | S5, S6 |
| 7 | Matchup | 20% | `matchup_score(adj_fpa["RB"], opponent)` | §5.2 |
| 8 | Front seven injuries | 5% | `tiered_injury_penalty(injury_counts[opponent]["FRONT_SEVEN_INTERIOR"])` | §5.8 |
| 9 | Baseline | 5% | Implied total tier (§7.1) | S8 |

**Step 5 injury multiplier:** `{0: 1.00, 1: 0.75, 2: 0.50, 3+: 0.25}`

**Step 6 teammate injury table:**

| Situation | Score |
|---|---|
| Player is RB1 and the RB2 is unavailable | 0.75 |
| Player is RB2 and the RB1 is unavailable | 1.00 |
| Player is RB3 and both RB1 and RB2 unavailable | 1.00 |
| Healthy committee (all active) | 0.50 |
| No relevant RB injuries | 0.50 |

RB depth order comes from S6 `depth_chart_order` at RB.

#### 8.2.1 The Tier 2 Bonus

A Tier 2 RB receives **+0.30 added to his weighted sum**, applied once after all
seven factors are scored.

```
Tier2_Bonus = 0.30 if pid in static_lists.rb_tier2 else 0.00
Start_Score = min(1.00, Weighted_Sum + Tier2_Bonus)
```

**Three rules, all load-bearing:**

1. **Additive, not multiplicative.** Applied once to the final weighted sum,
   never to an individual factor.

2. **Hard-capped at 1.00.** A Tier 2 RB with a weighted sum of 0.70 or better
   lands exactly on the ceiling. There is no uncapped score — the [0.0, 1.0]
   invariant holds at every position, which keeps scores readable and comparable
   and keeps the prediction log on one scale.

   The cost is that two Tier 2 RBs above 0.70 both sit at 1.00. That tie is
   resolved by the `weighted_sum` level of the sort key (§8), which orders them
   on the factors they actually earned. Ceiling-clamped candidates are flagged
   `score_capped` so a tie at the top is visible rather than silent.

3. **Recorded, not hidden.** Every Tier 2 RB carries a `tier2_bonus` flag, and
   the output shows weighted sum, bonus, and capped score as separate lines. A
   0.30 swing must be visible in the reasoning.

**On the magnitude.** +0.30 equals the entire DepthChart weight, the heaviest
factor in the model. A rival needs a weighted sum roughly 0.30 higher to take the
slot, which requires a genuinely bad Tier 2 situation against a genuinely good
alternative. That is the intended reading of "strong consideration" — start him
unless the case against is overwhelming.

Tier 1 RBs receive no bonus because they auto-start at Step 2 and their factors
are never computed.

Bonus value lives in `config/weights.yaml → rb.tier2_bonus`.

---

### 8.3 WR Picker

**Equation:**

```
WR Start Score = (0.20 × DepthChart)
               + (0.15 × QBQuality)
               + (0.15 × Ranking)
               + (0.15 × TeammateInjury)
               + (0.20 × Matchup)
               + (0.10 × SecondaryInjury)
               + (0.05 × Baseline)
```

**Slots:** 2. Bench WRs pass to the FLEX pool.

| Step | Factor | Weight | Computation | Source |
|---|---|---|---|---|
| 1 | Roster check | — | If exactly 2 WRs rostered, start both | Roster |
| 2 | Matchup-proof | — | In `static_lists.wr_top5` → **auto-start** | S9 |
| 3 | Depth chart position | **20%** | WR1 → 1.00; WR2 → 0.60; WR3 → 0.25; WR4+ → 0.00. Weeks 1–4 the role comes from `posrank_score` (§5.9a); from Week 5 from target share via `derive_roles()` (§5.9). **Both sources use the identical score table**, so the transition introduces no scale discontinuity — only the source of the role changes. | S6, S2 |
| 4 | Player calibre | 15% | `rank_to_score(calibre_rank["WR"][pid], 59)` | §5.6 |
| 5 | QB quality | 15% | `qb_quality_score(team)` (§7.3) | S5, S6, §5.6 |
| 6 | Teammate pass-catcher injuries | 15% | See table below | S5, S6, S9 |
| 7 | Matchup | **20%** | `matchup_score(adj_fpa["WR"], opponent)` | §5.2 |
| 8 | Secondary injuries | 10% | `tiered_injury_penalty(injury_counts[opponent]["SECONDARY"])` | §5.8 |
| 9 | Baseline | 5% | Implied total tier (§7.1) | S8 |

**Step 6 teammate injury table:**

| Situation | Score |
|---|---|
| Primary competitor unavailable (another starting WR, or an elite TE) | 1.00 |
| Secondary competitor unavailable (WR3, or a non-elite TE) | 0.75 |
| Multiple competitors unavailable | 1.00 (capped) |
| No significant injuries | 0.50 |

"Elite TE" = present in `static_lists.elite_tes`. "Starting WR" = role WR1 or WR2
per §5.9.

---

### 8.4 TE Picker

**Equation:**

```
TE Start Score = (0.15 × Ranking)
               + (0.15 × QBQuality)
               + (0.25 × WRInjury)
               + (0.25 × Matchup)
               + (0.15 × SecondaryInjury)
               + (0.05 × Baseline)
```

**Slots:** 1. A bench TE passes to the FLEX pool.

| Step | Factor | Weight | Computation | Source |
|---|---|---|---|---|
| 1 | Roster check | — | If 1 TE rostered, auto-start | Roster |
| 2 | Depth chart gate | Binary | TE1 (with effective-start promotion) → proceed. TE2+ → **eliminate**. | S6 |
| 3 | Matchup-proof | — | In `static_lists.te_top4` → **auto-start** | S9 |
| 4 | Player calibre | 15% | `rank_to_score(calibre_rank["TE"][pid], 29)` | §5.6 |
| 5 | QB quality | 15% | `qb_quality_score(team)` (§7.3) | S5, S6, §5.6 |
| 6 | WR teammate injuries | **25%** | See table below | S5, §5.9 |
| 7 | Matchup | **25%** | `matchup_score(adj_fpa["TE"], opponent)` | §5.2 |
| 8 | Secondary injuries | 15% | `tiered_injury_penalty(injury_counts[opponent]["SECONDARY"])` | §5.8 |
| 9 | Baseline | 5% | Implied total tier (§7.1) | S8 |

**Step 6 WR injury table** — the heaviest factor in the model, tied with matchup:

| Situation | Score |
|---|---|
| Team's WR1 unavailable | 1.00 |
| Multiple WRs unavailable | 1.00 (capped) |
| Team's WR2 unavailable | 0.75 |
| Team's WR3 unavailable | 0.60 |
| No significant WR injuries | 0.50 |

WR1/2/3 identity comes from `derive_roles()` (§5.9). Evaluate top-down and take
the first match, so a team missing both WR1 and WR3 scores 1.00, not 0.60.

---

### 8.5 K Picker

**Equation:**

```
Kicker Start Score = (0.30 × TeamOffense)
                   + (0.25 × RedZone)
                   + (0.15 × OppDefense)
                   + (0.15 × GameEnvironment)
                   + (0.15 × KickerCalibre)
```

**Slots:** 1. **Not FLEX-eligible.**

| Step | Factor | Weight | Computation | Source |
|---|---|---|---|---|
| 1 | Roster check | — | If 1 K rostered, auto-start | Roster |
| 2 | Team offense | **30%** | `offense_rank` tiers: 1–5 → 1.00; 6–10 → 0.85; 11–16 → 0.70; 17–22 → 0.50; 23–28 → 0.30; 29–32 → 0.10 | S3 |
| 3 | Red-zone inefficiency | **25%** | `rz_inefficiency_rank` tiers: 1–5 → 1.00; 6–10 → 0.85; 11–16 → 0.65; 17–22 → 0.45; 23–28 → 0.25; 29–32 → 0.10 | §5.5 |
| 4 | Opposing defense | 15% | Non-monotonic; see table below | S3 |
| 5 | Game environment | 15% | Game total: <40 → 1.00; 40–43 → 0.75; 44–47 → 0.50; 48–51 → 0.30; 52+ → 0.10 | S8 |
| 6 | Kicker calibre | 15% | `calibre_rank["K"]`: 1–3 → 1.00; 4–8 → 0.80; 9–16 → 0.55; 17–24 → 0.35; 25+ → 0.15 | §5.6 |

**Step 3 rank direction.** `rz_inefficiency_rank` is ranked ascending by scoring
efficiency, so **rank 1 = least efficient = best for the kicker**. This is the one
place in the system where rank 1 does not mean "strongest." It is called out
explicitly here and in the function's docstring because it is the most likely
place for a sign-flip bug.

**Step 4 opposing defense — deliberately non-monotonic:**

| `total_defense_rank` | Description | Score |
|---|---|---|
| 1–4 | Elite (stifles the offense entirely) | 0.30 |
| 5–12 | Above-average (forces punts, good field position) | 0.85 |
| 13–20 | Average | 0.65 |
| 21–28 | Below-average | 0.45 |
| 29–32 | Bottom-tier (shootout risk, TDs not FGs) | 0.20 |

Both extremes hurt a kicker: an elite defense prevents the offense from reaching
scoring range at all, while a bottom-tier defense invites touchdowns instead of
field goals. The position document gives these five bands as labels without
numeric rank boundaries; the boundaries above are a documented deviation (§15).

**Step 5 uses the game total**, not the implied team total. This differs from the
Baseline factor in the offensive models and is intentional.

---

### 8.6 DEF Picker

**Equation:**

```
DEF Start Score = (0.30 × OppQB)
                + (0.15 × OppSkill)
                + (0.15 × OppOLine)
                + (0.15 × DefensiveInjury)
                + (0.15 × Baseline)
                + (0.10 × DefenseCalibre)
```

**Slots:** 1. **Not FLEX-eligible.**

Opponent quality drives 60% of this model across Steps 2–4. The defense's own
talent carries only 10%.

| Step | Factor | Weight | Computation | Source |
|---|---|---|---|---|
| 1 | Roster check | — | If 1 DEF rostered, auto-start | Roster |
| 2 | Opposing QB | **30%** | See table below | **S12**, S5, S6, S9 |
| 3 | Opposing skill injuries | 15% | See table below | S5, §5.9 |
| 4 | Opposing O-line | 15% | See table below | §5.7, §5.8 |
| 5 | Own defensive injuries | 15% | `tiered_injury_penalty(injury_counts[team]["DEFENSE_ALL"])` | §5.8 |
| 6 | Baseline (avoid shootout) | 15% | **Opponent's** implied total: <17 → 1.00; 17–19 → 0.85; 20–22 → 0.65; 23–25 → 0.40; 26–28 → 0.20; 29+ → 0.00 | S8 |
| 7 | Defense calibre | 10% | `rank_to_score(defense_calibre_rank[team], 31)` | S3 |

**Step 2 opposing QB table** — evaluate top-down, first match wins:

| Situation | Score |
|---|---|
| Opposing QB1 unavailable, backup calibre rank 29+ or unranked | 1.00 |
| Opposing QB1 unavailable, backup calibre rank 15–28 | 0.85 |
| QB1 playing, team in top-10 `qb_turnover_rank` (worst turnover rates) | 0.80 |
| QB1 playing, calibre rank 21–28 | 0.65 |
| QB1 playing, calibre rank 13–20 | 0.50 |
| QB1 playing, calibre rank 6–12 | 0.35 |
| QB1 playing, calibre rank 1–5 | 0.15 |
| QB1 playing, calibre rank 1–5 **and** `static_lists.qb_styles[pid] == mobile` | 0.00 |

The elite-and-mobile row is checked before the plain elite row.

The mobile flag comes from the same 107-quarterback `qb_styles` table that drives
the QB picker's Style factor (§8.1). There is no separate `mobile_qbs` list.

**Calibre rank comes from S12** (`lineup-picker-QB-CALIBRE.md`), the same static
ranking consumed by WR Step 5, TE Step 5, and FLEX Step 4 — never a
separately-derived number, so this factor and those three factors always agree
on how good a given QB is. A QB absent from S12 falls back to
`derive_player_calibre(position="QB")`, flagged `qb_calibre_derived_fallback`.

**Step 3 opposing skill injuries** — evaluate top-down, first match wins:

| Situation | Score |
|---|---|
| Opposing WR1, WR2, and TE1 all unavailable | 1.00 |
| Opposing WR1 and one of (WR2, TE1) unavailable | 0.85 |
| Opposing WR1 unavailable | 0.70 |
| Opposing RB1 unavailable | 0.65 |
| One of (WR2, WR3, TE1) unavailable | 0.55 |
| No significant injuries | 0.50 |
| Opponent fully healthy **and** rosters an elite WR or elite TE | 0.25 |

The final row is checked only when no injuries are present.

**Step 4 opposing O-line:**

Evaluate top-down; first match wins. `oline_rank` is the **opponent's** rank
from S10.

| Situation | Score |
|---|---|
| Opponent `oline_rank` 29–32 **and** 2+ OL starters out | 1.00 |
| Opponent `oline_rank` 23–32 **or** 2+ OL starters out | 0.85 |
| Opponent `oline_rank` 23–32 | 0.70 |
| Opponent has 1 OL starter out | 0.60 |
| Opponent `oline_rank` **13–22** (average) | 0.50 |
| Opponent `oline_rank` 6–12 | 0.25 |
| Opponent `oline_rank` 1–5 (elite) | 0.10 |

Note the rank direction: rank 1 = best O-line = worst matchup for your defense.

**Coverage gap closed.** The original D/ST specification used 13–20 for the
average band and 23–32 for the weak band, leaving ranks **21 and 22** matching no
condition at all. The average band is widened to **13–22**. Under the current
ranking that gap would have caught LV (21) and CAR (22), producing an undefined
O-line score for any defense facing them.

---

### 8.7 FLEX Picker

**Equation:**

```
Flex Score = (0.40 × Opportunity)
           + (0.25 × Matchup)
           + (0.15 × Situation)
           + (0.10 × PlayerCalibre)
           + (0.10 × Baseline)
```

**Slots:** 1. **Runs last**, after every dedicated slot is locked.

The FLEX picker **recomputes** scores from its own equation. It does not reuse the
RB/WR/TE Start Scores, because those equations are position-specific and not
comparable across positions.

| Step | Factor | Weight | Computation | Source |
|---|---|---|---|---|
| 1 | Pool assembly | — | All bench RB/WR/TE not in a dedicated slot | Picker outputs |
| 2 | Opportunity | **40%** | Weeks 1–4 blend of `posrank_score` (RB1/WR1/TE1 **1.00**, WR2 **0.60**, RB2 **0.30**, WR3 **0.25**, else 0.00) with the usage table below. Weights 100/0 → 0/100 across weeks 1–5 per §5.10.1. The usage table is the Week 5+ component. | S6, S2, S4, S5 |
| 3 | Matchup | 25% | `matchup_score(adj_fpa[player.position], opponent)` — always the player's own position | §5.2 |
| 4 | Situation | 15% | Position-dependent; see below | S5, S6 |
| 5 | Player calibre | 10% | Within-position percentile; see below | §5.6 |
| 6 | Baseline | 10% | Implied total tier (§7.1) | S8 |
| 7 | Select | — | Highest Flex Score starts | — |

**Step 2 opportunity table:**

| Position | Situation | Score |
|---|---|---|
| RB | Workhorse (snap share ≥ 60%) | 1.00 |
| WR | WR1 on team | 1.00 |
| TE | TE1 with an unavailable WR1 or WR2 | 1.00 |
| RB | Lead in soft committee (50–60%) | 0.80 |
| TE | TE1 with healthy WRs | 0.70 |
| WR | WR2 on team | 0.65 |
| RB | 1B in committee (30–50%) | 0.40 |
| WR | WR3 on team | 0.30 |
| RB | Backup (<30%) | 0.10 |

**Step 4 situation — RB candidates (QB health does NOT apply):**

| Situation | Score |
|---|---|
| O-line intact | 1.00 |
| 1 OL starter out | 0.75 |
| 2+ OL starters out | 0.50 |
| Plus: multiple fellow RBs unavailable | +0.25, capped at 1.00 |

**Step 4 situation — WR and TE candidates (QB health DOES apply):**

| Situation | Score |
|---|---|
| QB1 available and no injury designation | 1.00 |
| QB1 playing but Questionable | 0.75 |
| QB1 unavailable, backup calibre rank ≤ 20 | 0.50 |
| QB1 unavailable, backup calibre rank 21+ | 0.25 |
| Plus: multiple pass-catchers unavailable | +0.25, capped at 1.00 |

Running backs get touches from handoffs, not passes. A backup QB still hands off
on early downs and still checks down on third. There is no scenario where a QB
injury meaningfully suppresses RB opportunity, so RB candidates are not penalized
for it.

**Step 5 player calibre — within-position percentile:**

```
percentile = 1.0 - (calibre_rank[position][pid] - 1) / position_pool_size
```

Pool sizes: WR = 60, RB = 40, TE = 30 (per the position document).

| Percentile | Score |
|---|---|
| > 0.95 | 1.00 |
| 0.90–0.95 | 0.90 |
| 0.75–0.90 | 0.75 |
| 0.50–0.75 | 0.50 |
| 0.25–0.50 | 0.25 |
| 0.10–0.25 | 0.10 |
| < 0.10 | 0.00 |

Percentiles are computed **within position**, which is what makes cross-position
comparison meaningful: a 75th-percentile WR and a 75th-percentile RB both score
0.75.

---

## 9. Orchestration

`src/brady_bot/optimizer.py`

### 9.1 Execution order

```
1. QB      → 1 starter
2. RB      → 2 starters, remainder to FLEX pool
3. WR      → 2 starters, remainder to FLEX pool
4. TE      → 1 starter, remainder to FLEX pool
5. K       → 1 starter
6. DEF     → 1 starter
7. FLEX    → 1 starter from the pooled remainder
8. BENCH   → everyone else
```

### 9.2 Slot integrity

The FLEX picker does **not** re-evaluate dedicated slots. If a bench RB outscores
a starting RB under the FLEX equation, that is expected — the two equations weight
different things — and is not a reason to swap. Slot integrity is preserved.

Persistent large gaps between a bench player's Flex Score and a starter's Start
Score are a signal to revisit the position model's weights, not to reshuffle at
runtime. The prediction log (§12) is where that signal accumulates.

### 9.3 Insufficient candidates

If a slot has no eligible candidate after filtering (all rostered players at that
position are on bye, out, or gated), the slot is left **EMPTY** with an explicit
warning naming every excluded player and the reason. The run does not halt — an
8-of-9 lineup with a clear warning is more useful than a crash.

---

## 10. Configuration

### 10.1 `config/league.yaml`

```yaml
league:
  name: "Dhaka Chamber of Football"
  season: 2026
  scoring_format: "half_ppr"

roster:
  starters:
    QB: 1
    RB: 2
    WR: 2
    FLEX: 1        # W/R/T
    K: 1
    DEF: 1
  bench: 6
  ir: 1

flex_eligible: [RB, WR, TE]

# Used ONLY for Adj. FPA derivation (§5.2) and prediction-log
# backfill (§12). NOT used to score players in any picker.
scoring:
  passing_yards_per_point: 30
  passing_td: 5
  interception: -2
  pick_six: -2
  rushing_yards_per_point: 10
  rushing_td: 6
  receiving_yards_per_point: 10
  receiving_td: 6
  reception: 0.5
  fumble_lost: -2
  two_point_conversion: 2
```

### 10.2 `config/weights.yaml`

```yaml
global:
  matchup_normalization: percentile    # percentile | linear  (§5.3)
  qb_dual_threat_rush_att_threshold: 4.0
  calibre_min_games: 3

qb:
  style: 0.15
  pass_catcher: 0.20
  oline: 0.10
  matchup: 0.30
  secondary_injury: 0.15
  baseline: 0.10

rb:
  depth_chart: 0.30
  ranking: 0.15
  oline: 0.15
  teammate_injury: 0.10
  matchup: 0.20
  front_seven_injury: 0.05
  baseline: 0.05
  # Additive, applied AFTER the weighted sum. Excluded from the
  # weights-sum-to-1.00 validation in §6.1 — it is a bonus, not a weight.
  tier2_bonus: 0.30

wr:
  depth_chart: 0.20
  qb_quality: 0.15
  ranking: 0.15
  teammate_injury: 0.15
  matchup: 0.20
  secondary_injury: 0.10
  baseline: 0.05

te:
  ranking: 0.15
  qb_quality: 0.15
  wr_injury: 0.25
  matchup: 0.25
  secondary_injury: 0.15
  baseline: 0.05

flex:
  opportunity: 0.40
  matchup: 0.25
  situation: 0.15
  player_calibre: 0.10
  baseline: 0.10

k:
  team_offense: 0.30
  red_zone: 0.25
  opp_defense: 0.15
  game_environment: 0.15
  kicker_calibre: 0.15

def:
  opp_qb: 0.30
  opp_skill: 0.15
  opp_oline: 0.15
  defensive_injury: 0.15
  baseline: 0.15
  defense_calibre: 0.10

calibre_denominators:
  WR: 59
  RB: 39
  TE: 29
  DEF: 31

flex_pool_sizes:
  WR: 60
  RB: 40
  TE: 30
```

### 10.3 `config/static_lists.yaml`

Hard coded for V1; does not change during the season. Resolved to gsis_id at
startup per §5.11.

```yaml
rb_tier1:      # Top 6 consensus — auto-start, equation never runs
  - {name: "Jahmyr Gibbs",        team: DET}
  - {name: "Bijan Robinson",      team: ATL}
  - {name: "Jonathan Taylor",     team: IND}
  - {name: "James Cook III",      team: BUF}
  - {name: "Christian McCaffrey", team: SF}
  - {name: "Saquon Barkley",      team: PHI}

rb_tier2:      # Consensus 7-10 — +0.30 bonus (§8.2.1)
  - {name: "Derrick Henry",       team: BAL}
  - {name: "Chase Brown",         team: CIN}
  - {name: "Kenneth Walker III",  team: KC}
  - {name: "Omarion Hampton",     team: LAC}

wr_top5:       # Matchup-proof
  - {name: "Ja'Marr Chase",       team: CIN}
  - {name: "Puka Nacua",          team: LAR}
  - {name: "Jaxon Smith-Njigba",  team: SEA}
  - {name: "Amon-Ra St. Brown",   team: DET}
  - {name: "CeeDee Lamb",         team: DAL}

elite_wrs:     # Top 10 — QB pass-catcher boost
  - {name: "Ja'Marr Chase",       team: CIN}
  - {name: "Puka Nacua",          team: LAR}
  - {name: "Jaxon Smith-Njigba",  team: SEA}
  - {name: "Amon-Ra St. Brown",   team: DET}
  - {name: "CeeDee Lamb",         team: DAL}
  - {name: "Justin Jefferson",    team: MIN}
  - {name: "A.J. Brown",          team: NE}
  - {name: "Drake London",        team: ATL}
  - {name: "George Pickens",      team: DAL}
  - {name: "Chris Olave",         team: NO}

te_top4:       # Matchup-proof AND elite TE marker
  - {name: "Brock Bowers",     team: LV}
  - {name: "Trey McBride",     team: ARI}
  - {name: "Tyler Warren",     team: IND}
  - {name: "Colston Loveland", team: CHI}

# Playing style for all 107 rostered QBs across all 32 teams.
# Source of truth: the Quarterback Playing Style Reference table in
# docs/lineup-picker-QB.md. Consumed by BOTH the QB picker's Style
# factor (§8.1) and the DEF picker's opposing-QB factor (§8.6).
# There is no separate mobile_qbs list.
qb_styles:
  - {name: "Josh Allen",       team: BUF, mobile: true}
  - {name: "Kyle Allen",       team: BUF, mobile: false}
  - {name: "Shane Buechele",   team: BUF, mobile: false}
  - {name: "Malik Willis",     team: MIA, mobile: true}
  # ... 107 entries total — see docs/lineup-picker-QB.md for the full table
  - {name: "Jalen Milroe",     team: SEA, mobile: true}
```

**`qb_styles` coverage:** 107 quarterbacks, all 32 teams, 32 × QB1 / 32 × QB2 /
32 × QB3 / 11 × QB4. 42 classified mobile (39%); 16 of 32 QB1s mobile (50%).

> The QB reference table also carries a preseason Depth column. It is **reference
> only** and must never feed the §8.1 Step 2 depth chart gate — wiring it in would
> freeze every team's QB1 at its Week 1 value for the whole season, silently. Live
> depth chart always comes from `nflreadpy.load_depth_charts()`.

### 10.3a `config/oline_ranks.yaml`

Team-keyed O-line quality ranks, 1 = best. Full table and rationale in
`lineup-picker-OLINE.md`. Kept as its own file rather than a key inside
`static_lists.yaml` because it needs no player resolution — only team-code
normalization.

```yaml
oline_ranks:
  DEN: 1
  PHI: 2
  CHI: 3
  BUF: 4
  LAR: 5
  SF: 6
  TB: 7
  SEA: 8
  BAL: 9
  LAC: 10
  MIN: 11
  ATL: 12
  DAL: 13
  NE: 14
  NYJ: 15
  ARI: 16
  DET: 17
  NYG: 18
  IND: 19
  NO: 20
  LV: 21
  CAR: 22
  JAX: 23
  KC: 24
  GB: 25
  TEN: 26
  MIA: 27
  CLE: 28
  PIT: 29
  CIN: 30
  WAS: 31
  HOU: 32
```

> `WAS` is `WSH` in the ESPN source. Normalized at load.

### 10.3b `config/committee_overrides.yaml` — depth overrides

Repurposed. Previously forced the committee-change flag; now provides a manual
`pos_rank` override for cases where the published depth chart is known to be
stale or wrong. Full rule in `lineup-picker-DEPTH-CHART.md`.

```yaml
depth_overrides:
  - {name: "Example Player", team: KC, position: RB, pos_rank: 1,
     note: "Signed post-cuts; depth chart not yet updated"}
```

Names resolve to `gsis_id` at startup via S7; unresolved or ambiguous halts.
Checked **before** the published depth chart and always wins.

This is the residual risk `pos_rank` carries: depth charts can lag in the
preseason, and a late free-agent signing may not appear correctly when Week 1
scores are computed. From Week 5 the risk disappears, since `pos_rank` no longer
affects scoring.

### 10.4 `config/team_aliases.yaml`

Every team code passes through this before use. At minimum:

```yaml
LA:  LAR
RAM: LAR
JAC: JAX
WSH: WAS
ARZ: ARI
BLT: BAL
CLV: CLE
HST: HOU
STL: LAR
SL:  LAR
SD:  LAC
OAK: LV
```

### 10.5 `data/roster.yaml`

```yaml
roster:
  - {name: "Patrick Mahomes", team: KC,  position: QB}
  - {name: "Bijan Robinson",  team: ATL, position: RB}
  # ...
  - {name: "San Francisco",   team: SF,  position: DEF}
```

---

## 11. CLI

```bash
# Primary command
brady-bot lineup pick --week 5

# Show every candidate's full factor breakdown, not just starters
brady-bot lineup pick --week 5 --verbose

# Explain one player's score in detail
brady-bot lineup explain --week 5 --player "Sam LaPorta"

# Force-refresh sources (note: does NOT refresh odds — see §4.2)
brady-bot lineup pick --week 5 --no-cache

# Refresh odds too, spending an API request
brady-bot lineup pick --week 5 --no-cache=odds

# Backfill actual scores after results are final
brady-bot lineup backfill --week 5

# Validate config and roster without running
brady-bot lineup validate
```

### 11.1 Output format

```
Brady Bot — Week 5 Lineup
Data as of 2026-10-03T14:22:31Z  |  run_id: 8f3a...

SLOT  PLAYER                POS  TEAM  OPP   SCORE  DRIVERS
────────────────────────────────────────────────────────────────────────
QB    Patrick Mahomes       QB   KC    @JAX  0.781  matchup 0.87, catchers 1.00
RB1   Bijan Robinson        RB   ATL   vsTB  AUTO   Tier 1 matchup-proof
RB2   Chase Brown           RB   CIN   @BAL  0.924  0.624 + 0.300 Tier 2 bonus
WR1   Ja'Marr Chase         WR   CIN   @BAL  AUTO   Top-5 matchup-proof
WR2   Jaxon Smith-Njigba    WR   SEA   vsSF  AUTO   Top-5 matchup-proof
TE    Sam LaPorta           TE   DET   @HOU  0.643  WR injury 0.75, matchup 0.68
FLEX  DK Metcalf            WR   PIT   vsCLE 0.612  opportunity 1.00
K     Chase McLaughlin      K    TB    @ATL  0.702  RZ ineff 0.85, offense 0.85
DEF   San Francisco         DEF  SF    @SEA  0.688  opp QB 0.65, own injuries 1.00

BENCH  Rachaad White (0.541) · Jerry Jeudy (0.498) · Tyler Higbee (0.402)

WARNINGS
  · Ranks are blended with prior season through Week 4 (currently Week 5: no blending)
  · Injury data fetched 2026-10-03T14:22Z — re-run closer to kickoff for final designations
```

For `--verbose`, print a per-factor table for every candidate:

```
Sam LaPorta (TE, DET @ HOU) — Start Score 0.643

  FACTOR                   INPUT                    SCORE  WEIGHT  CONTRIB
  ─────────────────────────────────────────────────────────────────────────
  Player calibre           TE rank 6 of 29           0.83    0.15    0.124
  QB quality               Goff, QB rank 9           0.75    0.15    0.113
  WR teammate injuries     St. Brown QUESTIONABLE    0.75    0.25    0.188
  Matchup (Adj. FPA)       HOU allows +2.1 vs TE     0.68    0.25    0.170
  Opposing secondary       1 starter out             0.75    0.15    0.113
  Baseline                 Implied total 21.5        0.50    0.05    0.025
  ─────────────────────────────────────────────────────────────────────────
                                                             TOTAL   0.643
```

---

## 12. Prediction Logging

Every run appends one JSON object **per scored player** — starters and bench — to
`data/predictions.jsonl`. Append-only; never rewritten.

```json
{
  "run_id": "8f3a...",
  "run_timestamp": "2026-10-03T14:22:31Z",
  "season": 2026,
  "week": 5,
  "player_id": "00-0036389",
  "name": "Sam LaPorta",
  "position": "TE",
  "slot": "TE",
  "start_score": 0.643,
  "factors": {
    "ranking":          {"score": 0.83, "weight": 0.15},
    "qb_quality":       {"score": 0.75, "weight": 0.15},
    "wr_injury":        {"score": 0.75, "weight": 0.25},
    "matchup":          {"score": 0.68, "weight": 0.25},
    "secondary_injury": {"score": 0.75, "weight": 0.15},
    "baseline":         {"score": 0.50, "weight": 0.05}
  },
  "gate_result": "passed",
  "flags": [],
  "blended": false,
  "matchup_normalization": "percentile",
  "actual_score": null
}
```

**Backfill.** `brady-bot lineup backfill --week N` fetches realized stat lines from
S2, applies `config/league.yaml → scoring`, and populates `actual_score` in place,
matched on `(run_id, player_id)`. It must not mutate any other field.

### 12.1 Why this is V1 and not V2

Every weight in `config/weights.yaml` is judgment-set. Every threshold boundary is
judgment-set. That is a defensible V1 position **only if** the outcome data needed
to replace them with fitted values is accumulating from Week 1. A season without
this log is a season of unrecoverable calibration data.

**Separation of concerns:** this log records what was predicted and what happened.
It does not fit anything. Predictions are features, backfilled actuals are labels,
and they are never written in the same operation. Fitting is explicitly V2.

---

## 13. Testing

### 13.1 Unit tests — derive layer

| Function | Required cases |
|---|---|
| `derive_adj_fpa` | Nulls filled before arithmetic; per-game not per-season (bye-week case); halts on <32 teams; positive = soft matchup |
| `matchup_score` | Percentile mode: rank 1 → 0.00, rank 32 → 1.00. Linear mode matches the doc formula. |
| `derive_injury_counts` | Every row of the §5.8 availability table, including `Questionable` + null practice |
| `derive_roles` | WR ordering by target share; depth-chart tiebreak; TE effective-start promotion |
| `blend_early_season` | Weeks 1–5 weights; blends rates not ranks; RB uses prior W10–18 only |
| `resolve_static_lists` | Suffix stripping, apostrophes, halt on ambiguity |

### 13.2 Unit tests — every picker

| Test | Assertion |
|---|---|
| Weights sum | Each position's weights sum to 1.00 ± 1e-9 |
| Rank direction | A rank-1 opponent defense yields a LOWER score than rank-32, all else equal (offensive pickers). For K Step 3, assert the documented inversion explicitly. |
| Bye filter | A player on bye never appears in starters |
| Doubtful filter | A `Doubtful` player never appears in starters |
| Auto-start | A Tier 1 RB starts regardless of every other factor |
| Gate | A TE2 with an available TE1 is eliminated; promoted when the TE1 is out |
| Score bounds | Every `start_score` is in [0.0, 1.0], including the QB pass-catcher clamp case |
| RB Tier 2 bonus | Weighted sum 0.52 → start_score 0.82. Weighted sum 0.85 → start_score 1.00 with a `score_capped` flag. |
| Universal cap | No `start_score` at any position ever exceeds 1.00 |
| Cap tiebreak | Two Tier 2 RBs at weighted sums 0.78 and 0.72 both cap to 1.00; the 0.78 back is selected first via the `weighted_sum` sort level |
| pos_rank — Week 1 exact | A Week 1 RB1 scores exactly 1.00 and an RB2 exactly 0.30 on DepthChart_Score; a WR2 scores 0.60, a WR3 0.25 |
| pos_rank — blend arithmetic | Week 3, RB1 with 35% current snap share → `(0.50 × 1.00) + (0.50 × 0.20) = 0.60` |
| pos_rank — inert from Week 5 | Two players with identical usage score identically from Week 5 regardless of `pos_rank` |
| pos_rank — RB3 floor | An RB3 scores 0.00, not an interpolation between RB2 and nothing |
| pos_rank — missing entry | A player absent from the depth chart scores 0.00 and carries `no_depth_entry` |
| pos_rank — pinning | A player whose rank changed mid-season resolves to the latest `dt`, never an earlier snapshot |
| FLEX cross-position | Week 1, an RB2 (0.30) loses the FLEX slot to a WR2 (0.60), all else equal |
| Depth override precedence | A manual `pos_rank` override beats the published depth chart |
| Denominator excludes missed games | A back at 70% across 10 games played who missed 7 scores as a workhorse (1.00), not a committee back (0.20) |
| RB Tier 2 beatable | A non-tier RB with a weighted sum 0.31 higher still wins the slot |
| RB Tier 1 no bonus | A Tier 1 RB auto-starts and never receives a bonus |
| QB style lookup | A QB in `qb_styles` uses the table; one absent falls back to the rush-attempt threshold and is flagged `style_derived` |
| QB style shared | The DEF picker's mobile check reads the same `qb_styles` entry as the QB picker's Style factor |
| Determinism | Two identical runs over a fixture produce identical output |

### 13.3 Integration tests

- Full lineup from a fixture `WeekContext`, no network
- Insufficient candidates at a slot → EMPTY with warning, no crash
- FLEX pool receives exactly the bench RB/WR/TE and nothing else
- Tie-break stability: equal scores always resolve by `player_id` ascending

### 13.4 Golden file

One committed `tests/fixtures/week5_golden.json` with expected output. Fixtures
must avoid players sitting within 1 rank or 1 percentage point of any tier
boundary — boundary-adjacent fixtures make the golden file brittle against
upstream data revisions. Boundary behaviour is covered by dedicated tests instead.

### 13.5 Coverage

Minimum 90% line coverage on `derive/`, `scoring/`, and `pickers/`.

---

## 14. Failure Modes

| Condition | Behaviour |
|---|---|
| Roster player not resolvable to gsis_id | **Halt.** `UnresolvedPlayerError` naming the player. Never silently exclude a roster player. |
| Name resolves to 2+ candidates | **Halt.** `AmbiguousPlayerError` listing all candidates. |
| Static list entry unresolvable | **Halt** at startup. A silently unresolved matchup-proof name changes lineups with no visible error. |
| Weights do not sum to 1.00 | **Halt** at config load. |
| `derive_adj_fpa` returns <32 teams | **Halt.** A partial set produces a wrong 1–32 scale for every team. |
| S8 (Odds API) unreachable | Continue. Set every Baseline factor to 0.50 (neutral), flag `odds_unavailable`, print a banner. Baseline is 5–15% weight, so the lineup remains usable. |
| S8 quota exhausted (HTTP 429) | Same as unreachable, with a distinct message naming the quota. |
| Insufficient current-season data (Weeks 1–4) | Blend per §5.10, set `blended = True`, surface in output. |
| Player has <3 games this season | Calibre falls back to prior-season per-game average; flag `calibre_prior_season`. |
| Player has no prior-season data either (rookie) | Calibre rank = worst in position. Flag `calibre_unknown`. The player is not eliminated — other factors still apply. |
| Injury data older than 24h before kickoff | Warn, list every Questionable player, advise re-run. |
| No eligible candidate for a slot | Slot = EMPTY with warning naming every excluded player and reason. Do not halt. |
| nflverse fetch fails | Retry 3× with exponential backoff, then fall back to the cached copy regardless of TTL, flagging `stale_cache`. Halt only if no cache exists. |

---

## 15. Deviations from the Position Documents

**This section exists for V2.** Every place where this spec departs from the seven
position documents is recorded here with the reason, so a future revision can
reverse the decision knowingly rather than rediscover it.

Four original deviations (D3, D4, D7, D8) have since been **resolved** by updates
to the position documents themselves and are struck through below rather than
deleted, so the history stays legible.

| # | Position doc says | V1 does | Why |
|---|---|---|---|
| D1 | Player calibre from **ESPN positional rankings** | Derived from nflverse trailing fantasy points per game | ESPN rankings are not in nflverse and only reachable via undocumented endpoints. The substitution is arguably better suited: expert rankings are forward-looking and embed matchup expectations, while a factor-score model wants a matchup-agnostic measure of realized quality. |
| D2 | `Matchup_Score = (Adj_FPA + 10) / 20` | Percentile rank across 32 defenses | The fixed ±10 window is calibrated for QB (≈18 pts/game) and badly miscalibrated for TE (≈7 pts/game), where it would compress every score near 0.50 and neutralize the TE model's 25% matchup weight. `linear` remains available via config. |
| ~~D3~~ | ~~RB O-line quality from PFF run-block grades, proxied by team rushing YPA~~ | **RESOLVED.** Loaded from `config/oline_ranks.yaml` (S10), the ESPN preseason ranking. The YPA proxy is retired and `run_block_rank` removed. | No longer a deviation. |
| ~~D4~~ | ~~DEF O-line weakness from PFF pressure rate, proxied by team sack rate allowed~~ | **RESOLVED.** Same S10 ranking. `sack_rate_allowed_rank` removed. | No longer a deviation. |
| D14 | Position docs treat RB run-blocking and DEF pass-protection as different questions, measured by different proxies | One composite ESPN ranking answers both | A single authoritative human-sourced list beats two derived proxies of uncertain accuracy. Cost: a line strong at run blocking but weak at pass protection scores identically for both. Splitting is a future candidate if a free source for both becomes available. |
| D15 | D/ST O-line band coverage | Average band widened from 13–20 to **13–22** | The original bands left ranks 21–22 matching no condition, producing an undefined score. |
| ~~D16~~ | ~~Prior component replaced by a neutral 0.50 when the committee changed~~ | **RETIRED.** Superseded by D19. `pos_rank` reads the current team's current depth chart, so it already reflects the new situation — forcing 0.50 on top would discard good current-team data for an artificial neutral. | No longer in force. |
| D17 | Pipeline non-negotiable #5 said blend rates, never scores | Rule **reworded**: blend rates or scores, never raw ordinal ranks. RB/WR/FLEX depth factors blend at score level for all players. | `pos_rank` is converted to a cardinal score on [0,1] before any arithmetic, so averaging is well-defined. The original rule guarded against averaging ordinals, which this never does. |
| **D19** | Position docs score RB depth from snap share and WR depth from target share, with `pos_rank` as bookkeeping or a tiebreak only | `pos_rank` becomes the **early-season scoring anchor** for RB Step 3, WR Step 3 and FLEX Step 2, fading 100%→0% across Weeks 1–4. Prior-season W10–18 snap share retired from RB Step 3. | A published depth chart is the best available statement of intent before snaps are played, and reflects the current team rather than a prior one. Usage replaces it entirely from Week 5. Full tables in `lineup-picker-DEPTH-CHART.md`. |
| **D20** | Source tables specify RB1/RB2 but not RB3+, and are silent on players absent from the depth chart | RB3+ → 0.00; no depth entry → 0.00 with a `no_depth_entry` flag | Consistent with WR4+ and TE2+ scoring 0.00. The flag distinguishes a real demotion from a data gap. |
| D18 | Per-game denominators were unspecified about missed games | Denominator is **games the player was healthy and played** — missed games excluded, never counted as zero | Counting a missed game as zero drags a workhorse's average toward a backup's. Worked example in §5.10.2 shows a 0.80 swing on RB's heaviest factor. |
| D5 | K red-zone factor from **team red-zone TD rate** | Points per 100 offensive yards | True RZ TD% needs drive-level data, excluded from V1. The proxy captures the same "moves the ball, doesn't finish" signal, though it also picks up turnovers and failed fourth downs. |
| D6 | WR depth chart position from depth chart | Trailing-4-game target share rank within team | nflverse depth charts list receivers by formation position (X/Y/Z, slot) rather than target priority, making them unreliable for WR1/2/3. Depth chart retained as a tiebreak. |
| ~~D7~~ | ~~QB style has no numeric boundary~~ | **RESOLVED.** The QB document now carries a definitive 107-QB table classifying every rostered quarterback. The 4.0 rushing-attempt threshold survives only as a fallback for unlisted QBs, flagged `style_derived`. | No longer a deviation. |
| ~~D8~~ | ~~RB Tier 2 "strong consideration" has no mechanics~~ | **RESOLVED.** Tier 2 now receives an explicit +0.30 additive bonus (§8.2.1), superseding the two-Tier-2-auto-start rule. | No longer a deviation. |
| D13 | Position docs are silent on what happens when a bonus or boost pushes a score past 1.00 | Hard cap at 1.00 everywhere; ties at the ceiling broken on `weighted_sum`, then `player_id` | Keeps the [0.0, 1.0] invariant universal so scores stay comparable across positions and on one scale in the prediction log. The tiebreak recovers the ordering the cap would otherwise lose. |
| D9 | K opposing-defense bands given as labels | Mapped to explicit rank boundaries (§8.5) | The document gives five descriptive bands without numeric ranges. |
| D10 | Injury factors reference "out or limited" | Formalized in the §5.8 availability table, with `Doubtful` treated as unavailable | `Doubtful` was unhandled in every position document. A Doubtful player would otherwise score identically to a healthy one — the most likely single-week catastrophic failure. |
| D11 | QB pass-catcher elite boost is "uncapped" | Clamped to 1.00 after summation | An uncapped 1.10 breaks the [0,1] invariant every other factor holds and makes Start Scores incomparable. Pre-clamp value is preserved in the output. |
| D12 | Sources named per step, inconsistently | Every factor mapped to a source ID in §4 and a derive function in §5 | WR, TE, and FLEX named almost no sources; RB named three of seven. |

---

## 16. V2 Roadmap

Ordered by expected value.

1. **Fit the weights.** After one season of `predictions.jsonl` with backfilled
   actuals, replace judgment-set weights with fitted values. This is the single
   highest-value change and the reason §12 is in V1 scope.
2. **Yahoo API integration.** Read rosters automatically; optionally write
   lineups. Removes manual roster entry and enables full-auto mode.
3. **True red-zone data** for the K model, replacing the D5 proxy. Requires
   play-by-play.
4. **Split run-block and pass-protect O-line rankings.** S10 is a single
   composite serving both the RB and DEF pickers (deviation D14). If a free
   source publishing both separately becomes available, split
   `config/oline_ranks.yaml` into two keyed sets.
5. **Continuous curves** replacing step-function tiers. Every threshold in §8 is a
   cliff: rank 10 → 0.85 and rank 11 → 0.70 is a large swing on a one-rank
   difference well inside the noise of the underlying stat. Fit against the
   prediction log.
6. **DEF disruptive-play ceiling.** The DEF model's V1 roadmap note specifies
   `Ceiling_Score = (0.50 × Sack_Rate_Percentile) + (0.50 × INT_Rate_Percentile)`,
   replacing or splitting the 15% DefensiveInjury weight.
7. **Non-monotonic K implied-total response.** Very high totals mean touchdowns
   rather than field goals; the current model treats the relationship as
   monotonic.
8. **Rest-risk detection** for Weeks 17–18, flagging players on teams that have
   clinched.
9. **Exponential decay** on snap share and target share, replacing the V1 simple
   average from Week 5 onward.

---

## 17. Acceptance Criteria

1. `brady-bot lineup pick --week N` outputs a complete 8-slot lineup, or names
   every empty slot with a reason.
2. Runs in under 30 seconds on a cold cache; under 5 seconds warm.
3. Every starter's score decomposes into named factors whose weighted
   contributions sum to the displayed Start Score.
4. Every roster player resolves to a gsis_id, or the run halts with an actionable
   error naming the player.
5. Every position's weights sum to 1.00; validated at config load.
6. Determinism: given a fixed fixture set with no network, two consecutive runs
   produce byte-identical output.
7. No player on bye, `Out`, or `Doubtful` ever appears in a starting slot.
7a. No `start_score` at any position exceeds 1.00. Where the cap binds, the
    player carries a `score_capped` flag and ties are resolved on `weighted_sum`.
8. Rank direction is verified by test at every position, including the deliberate
   inversion at K Step 3.
9. Every run appends one row per scored player to `data/predictions.jsonl` with
   the full factor breakdown.
10. `brady-bot lineup backfill --week N` populates `actual_score` without mutating
    any other field.
11. The system runs to completion with only a free Odds API key configured, and no
    other credentials.
12. Test coverage ≥90% on `derive/`, `scoring/`, and `pickers/`.

---

## 18. Repository Structure

```
brady-bot/
├── pyproject.toml
├── .env.example                   # ODDS_API_KEY=
├── README.md
├── config/
│   ├── league.yaml
│   ├── weights.yaml
│   ├── static_lists.yaml
│   └── team_aliases.yaml
├── data/
│   ├── roster.yaml
│   ├── cache/                     # gitignored
│   ├── id_overrides.json          # manual name → gsis_id escapes
│   └── predictions.jsonl          # gitignored, append-only
├── src/brady_bot/
│   ├── __init__.py
│   ├── models.py                  # §6
│   ├── config.py                  # loading + weight-sum validation
│   ├── normalizer.py              # §5.11 identity resolution, team aliases
│   ├── sources/
│   │   ├── nflverse.py            # S1-S7
│   │   ├── odds.py                # S8
│   │   └── cache.py
│   ├── derive/
│   │   ├── adj_fpa.py             # §5.2, §5.3
│   │   ├── team_ranks.py          # §5.4, §5.5, §5.7
│   │   ├── calibre.py             # §5.6
│   │   ├── injuries.py            # §5.8
│   │   ├── roles.py               # §5.9
│   │   └── blending.py            # §5.10
│   ├── scoring/
│   │   └── shared.py              # §7
│   ├── pickers/
│   │   ├── base.py                # gate → score → rank contract
│   │   ├── qb.py
│   │   ├── rb.py
│   │   ├── wr.py
│   │   ├── te.py
│   │   ├── kicker.py
│   │   ├── defense.py
│   │   └── flex.py
│   ├── optimizer.py               # §9
│   ├── predictions.py             # §12
│   ├── render.py                  # §11.1
│   └── cli.py                     # §11
└── tests/
    ├── fixtures/
    │   ├── week5_context.json
    │   └── week5_golden.json
    ├── test_derive_*.py
    ├── test_picker_*.py
    ├── test_normalizer.py
    └── test_integration.py
```

### 18.1 Build order

`normalizer.py` and `pickers/base.py` are the two nodes everything downstream
depends on. Build and test both before any individual picker.

```
models.py + config.py
  └→ normalizer.py                      # everything joins through this
      └→ sources/                       # nflverse ×7, odds ×1
          └→ derive/                    # adj_fpa, ranks, calibre, injuries, roles
              └→ scoring/shared.py
                  └→ pickers/base.py
                      └→ pickers/{qb,rb,wr,te,kicker,defense}.py
                          └→ pickers/flex.py
                              └→ optimizer.py + predictions.py
                                  └→ render.py + cli.py
```
