# Brady Bot — Lineup Picker Data Pipeline

## Specification, V1

**Version:** 1.0
**Date:** September 12, 2026
**Companion to:** `lineup-picker-tech-spec-v1.md`
**Scope:** Everything between "a week number" and "a fully populated `WeekContext`"

---

## 0. Purpose

The tech spec defines *what each picker scores*. This document defines *how the
data gets there*.

It covers four layers:

```
FETCH  →  NORMALIZE  →  DERIVE  →  ASSEMBLE
```

**The contract this pipeline must satisfy:** by the time any picker runs, a single
immutable `WeekContext` object holds every value those pickers need. Pickers make
zero network calls, read zero files, and perform zero aggregation. If a picker
needs it, the pipeline computed it.

**Primary source: `nflreadpy`.** Eight of the nine data sources are nflverse and
free. Section 3 covers the single potential exception and how to avoid it.

---

## 1. Non-Negotiables

Read these before writing any code. Each corresponds to a specific way this
pipeline fails silently.

| # | Rule | Failure it prevents |
|---|---|---|
| 1 | **`nflreadpy` returns Polars, not pandas.** Do not use pandas idioms. | `AttributeError` on first run, or worse, a `.to_pandas()` scattered inconsistently through the codebase |
| 2 | **Fill nulls with 0 before any arithmetic on stat columns.** | A QB row has null `receiving_yards`. Null propagates through arithmetic and silently drops that player's entire contribution from Adj. FPA |
| 3 | **Divide by games played, never sum across the season.** | Bye weeks. In Week 8 a defense that has had its bye has played 6 games and one that has not has played 7 |
| 4 | **Rank 1 = strongest, always.** One documented exception, flagged in §6.4. | A sign-flipped matchup multiplier produces plausible lineups that are exactly backwards |
| 5 | **Blend rates or cardinal scores. Never average raw ordinal ranks.** Convert `pos_rank` to a score via the lookup in `lineup-picker-DEPTH-CHART.md` *before* any arithmetic. | Ranks are ordinal — `(rank_a + rank_b) / 2` is meaningless. Scores on [0,1] are cardinal and average correctly |
| 6 | **Every team code passes through `TEAM_ALIASES` at the adapter boundary.** | `LA` vs `LAR` vs `RAM` produces silent join misses that drop whole teams |
| 7 | **Unresolved roster player halts the run.** | A silently dropped roster player never appears in a lineup and nobody notices |
| 8 | **Validate 32 teams present after every team-level derivation.** | A partial set produces a wrong 1–32 scale for every team, not just the missing one |
| 8a | **Per-game denominators use games the player was healthy and played.** Exclude inactive/IR/bye/suspended; never count a missed game as zero. | A workhorse who missed 7 games reads as a committee back — an 0.80 swing on RB's heaviest factor |
| 8b | **Depth charts must be pinned to each team's max `dt` before any read.** There is no `week` column. | An unpinned read resolves a stale rank from weeks earlier, silently distorting a 20–40% factor |
| 8c | **`pos_rank` contributes 0% to scoring from Week 5 onward.** It is still read for gates and starter identification. | A leak past Week 4 keeps depth chart position influencing scores after usage data should have fully replaced it |
| 9 | **`ODDS_API_KEY` from env only. Never committed, never logged, never a CLI arg.** | A key in git history or shell history is a key someone else can spend |
| 10 | **Assert the favourite gets the higher implied total.** | An inverted spread sign silently flips the Baseline factor in all seven pickers |

---

## 2. Step 0 — Schema Verification (Do This First)

**This is the first task. Do not write derive functions before completing it.**

The tech spec names columns based on `nflreadpy` documentation, not against a live
pull. Column names, availability, and coverage must be confirmed against the
installed version before anything depends on them.

### 2.1 Probe script

Create `scripts/probe_schemas.py`:

```python
"""Step 0: confirm nflverse schemas before building the derive layer.

Run:  python scripts/probe_schemas.py > docs/schema_probe.txt
Commit the output. Re-run whenever nflreadpy is upgraded.
"""
import nflreadpy as nfl
import polars as pl

SEASON = 2025          # last completed season — guaranteed full data
PROBE_WEEK = 10

def probe(name: str, df: pl.DataFrame, interesting: list[str]) -> None:
    print(f"\n{'=' * 70}\n{name}\n{'=' * 70}")
    print(f"shape: {df.shape}")
    print(f"\nALL COLUMNS ({len(df.columns)}):")
    for c in sorted(df.columns):
        print(f"  {c:<40} {df.schema[c]}")
    print("\nCOLUMNS THE SPEC ASSUMES:")
    for c in interesting:
        status = "PRESENT" if c in df.columns else "*** MISSING ***"
        print(f"  {c:<40} {status}")
    print("\nSAMPLE (3 rows):")
    print(df.head(3))


probe("load_schedules", nfl.load_schedules(seasons=[SEASON]), [
    "game_id", "season", "week", "season_type", "gameday", "gametime",
    "home_team", "away_team", "spread_line", "total_line",
])

probe("load_player_stats", nfl.load_player_stats(seasons=[SEASON]), [
    "player_id", "player_display_name", "position", "team", "opponent_team",
    "season", "week", "season_type",
    "passing_yards", "passing_tds", "interceptions", "sacks",
    "rushing_yards", "rushing_tds", "rushing_fumbles_lost",
    "receptions", "targets", "receiving_yards", "receiving_tds",
    "receiving_fumbles_lost",
    # Kicking — see §3.3. If absent here, kicking lives elsewhere.
    "fg_made", "fg_att", "pat_made",
])

probe("load_team_stats", nfl.load_team_stats(seasons=[SEASON]), [
    "team", "season", "week", "season_type",
    "passing_yards", "rushing_yards", "passing_tds", "rushing_tds",
    "attempts", "carries", "sacks_suffered", "passing_interceptions",
])

probe("load_snap_counts", nfl.load_snap_counts(seasons=[SEASON]), [
    "pfr_player_id", "player", "position", "team", "week", "season",
    "offense_snaps", "offense_pct", "defense_snaps", "defense_pct",
])

probe("load_injuries", nfl.load_injuries(seasons=[SEASON]), [
    "gsis_id", "full_name", "position", "team", "season", "week",
    "report_status", "practice_status", "report_primary_injury",
])

probe("load_depth_charts", nfl.load_depth_charts(seasons=[SEASON]), [
    "gsis_id", "football_name", "position", "depth_position",
    "team", "season", "week", "depth_team",
])

probe("load_players", nfl.load_players(), [
    "gsis_id", "display_name", "football_name", "position",
    "latest_team", "status",
])
```

### 2.2 What to check in the output

| Question | Why it matters | If the answer is bad |
|---|---|---|
| Does `load_player_stats` carry `opponent_team`? | Adj. FPA groups by it. Without it, join to `load_schedules` on `(game_id, team)`. | Fall back to the schedules join |
| Does `load_player_stats` carry kicking columns? | K calibre ranking depends on it | See §3.3 |
| Does `load_team_stats` carry defensive stats, or offense only? | DEF calibre and total defense rank need yards allowed | Derive by aggregating opponents' offensive stats |
| Does `load_depth_charts` cover **defense and O-line**, not just skill positions? | Injury unit counts (§6.5) need OL, DB, LB, DL starters | See §3.4 |
| Does `load_snap_counts` use `pfr_player_id` rather than `gsis_id`? | This is a known join problem — see §5.3 | Requires a crosswalk hop |
| Does `load_schedules` carry `spread_line` and `total_line`, and are they populated for **future** games? | Determines whether the Odds API is needed at all — see §3.2 | Keep the Odds API |
| What is `depth_chart_order` actually called? | Starter identification depends on it | Rename in the adapter |

### 2.3 Deliverable from Step 0

Commit `docs/schema_probe.txt` and update `src/brady_bot/sources/schema.py` with
the confirmed column names as constants:

```python
# Confirmed against nflreadpy X.Y.Z on 2026-09-12 — see docs/schema_probe.txt
class PlayerStatsCols:
    PLAYER_ID = "player_id"
    POSITION = "position"
    TEAM = "team"
    OPPONENT = "opponent_team"
    # ...
```

Every derive function references these constants, never string literals. When a
column name changes upstream, one file changes.

---

## 3. Source Inventory

### 3.1 nflverse sources (primary — 7 of 8)

All free, no key, no quota.

| ID | Call | TTL | Feeds |
|---|---|---|---|
| **S1** | `nfl.load_schedules(seasons=[season])` | 24h | Bye weeks, opponent map, home/away, kickoff time, possibly betting lines (§3.2) |
| **S2** | `nfl.load_player_stats(seasons=[season, season-1])` | 6h | Adj. FPA, player calibre, target share, QB turnover rate |
| **S3** | `nfl.load_team_stats(seasons=[season, season-1])` | 6h | Team offense rank, sack rate allowed, scoring efficiency, defense calibre |
| **S4** | `nfl.load_snap_counts(seasons=[season, season-1])` | 6h | RB snap share |
| **S5** | `nfl.load_injuries(seasons=[season])` | **2h** | Every injury factor in all seven pickers |
| **S6** | `nfl.load_depth_charts(seasons=[season])` | 6h | Starter identification, QB1/TE1, OL/DB/front-seven rosters |
| **S7** | `nfl.load_players()` | 7d | Name → gsis_id crosswalk |

**S5 has the shortest TTL by design.** Injury designations change through Friday
and Saturday, and a stale designation is the most damaging staleness this system
can have — it produces a confidently-started player who does not play.

### 3.2 S8 — The Odds API (betting lines)

The Baseline factor across every picker is a **Vegas-derived** view of what the
game is expected to look like. That is the point of the factor: the betting market
is the single best available consensus on game environment, and no nflverse
aggregate substitutes for it.

**S8 is a confirmed primary source, not a conditional one.**

#### 3.2.1 Host and authentication

```
Host:        https://api.the-odds-api.com
IPv6 host:   https://ipv6-api.the-odds-api.com     (use only if IPv6 is required)
Auth:        apiKey query parameter on every request
```

**The API key is read from the `ODDS_API_KEY` environment variable and is never
committed.** `.env` is gitignored; `.env.example` carries the variable name with
no value.

```bash
# .env.example
ODDS_API_KEY=
```

```python
import os
ODDS_API_KEY = os.environ["ODDS_API_KEY"]   # KeyError at startup if unset — deliberate
```

Never accept the key as a CLI argument (it lands in shell history) and never log
it. When constructing request URLs for logging or error messages, redact it:

```python
def redact(url: str) -> str:
    return re.sub(r"apiKey=[^&]+", "apiKey=***", url)
```

#### 3.2.2 Endpoints used

| Purpose | Endpoint | Quota cost |
|---|---|---|
| **Key validation / health check** | `GET /v4/sports/?apiKey={key}` | **0 — free** |
| **Odds fetch (the real one)** | `GET /v4/sports/americanfootball_nfl/odds?apiKey={key}&regions=us&markets=spreads,totals&oddsFormat=american` | **2** |

**Health check.** The `/v4/sports` endpoint does not count against the usage
quota, which makes it the correct way to verify the key works. Call it in
`brady-bot lineup validate` and at the start of any run where the odds cache has
expired — a bad key surfaces immediately rather than after burning credits.

Expected shape of a successful `/v4/sports` response:

```json
[
  {"key": "americanfootball_nfl", "group": "American Football",
   "title": "NFL", "description": "US Football", "active": true, "has_outrights": false}
]
```

Assert that `americanfootball_nfl` is present and `active` is true. If the NFL is
between rounds or out of season, the odds endpoint may legitimately return an
empty array — see §3.2.5.

#### 3.2.3 Quota arithmetic

**Cost is markets × regions, not one credit per request.**

```
cost = len(markets) × len(regions)
```

The odds call specifies `markets=spreads,totals` (2) and `regions=us` (1), so
**each odds refresh costs 2 credits**.

```
2 credits × 4 refreshes/week × 18 weeks = 144 credits per season
Free tier = 500 credits/month
```

Comfortable, but the headroom is half what a naive per-request count suggests.

**Do not add regions.** Adding `uk` or `eu` doubles or triples the cost and adds
nothing — this is a US league and US books set the lines that matter.

**Do not add markets.** `h2h` (moneyline) is not used by any factor. Adding it
raises the cost to 3 per refresh for no benefit.

#### 3.2.4 Quota tracking

Every successful response carries usage headers:

| Header | Meaning |
|---|---|
| `x-requests-remaining` | Credits left until quota reset |
| `x-requests-used` | Credits used since last reset |
| `x-requests-last` | Cost of the call just made |

**Log all three after every odds call** and persist `x-requests-remaining` to
`data/cache/S8_quota.json`. Surface it in CLI output when it drops below 100:

```
⚠ Odds API: 84 credits remaining this month
```

Note that these headers are **omitted on error responses**, so parse them
defensively — treat absence as unknown rather than zero.

#### 3.2.5 Error handling

| HTTP / condition | Meaning | Behaviour |
|---|---|---|
| `401` + `INVALID_KEY` | Key wrong, or placeholder never replaced | **Halt.** "ODDS_API_KEY rejected — verify at the-odds-api.com." Do not fall through to neutral baselines; a bad key is a fixable config error, not an outage. |
| `401` + `MISSING_KEY` | `apiKey` param absent | **Halt** with the same class of message. |
| `429` | Quota exhausted or rate limited | Degrade: all Baseline factors → 0.50, flag `odds_quota_exhausted`, print banner naming the reset date. |
| `5xx` / timeout | Service down | Retry 3× (1s, 2s, 4s), then fall back to cached odds regardless of TTL, flag `stale_cache:S8`. If no cache, degrade to neutral. |
| `200` with `[]` | Between rounds or off-season | **Not an error.** This request does not count against quota. Fall back to cache; if none, degrade to neutral with `odds_no_events`. |

The `INVALID_KEY` response body looks like this — match on `error_code`, not the
message string:

```json
{
  "message": "API key is not valid. Get an API key at https://the-odds-api.com",
  "error_code": "INVALID_KEY",
  "details_url": "https://the-odds-api.com/liveapi/guides/v4/api-error-codes.html#invalid-key"
}
```

#### 3.2.6 Response parsing

Each element of the odds array is one game:

```json
{
  "id": "...",
  "commence_time": "2026-10-05T17:00:00Z",
  "home_team": "Kansas City Chiefs",
  "away_team": "Jacksonville Jaguars",
  "bookmakers": [
    {"key": "draftkings", "markets": [
      {"key": "spreads", "outcomes": [
        {"name": "Kansas City Chiefs", "point": -6.5},
        {"name": "Jacksonville Jaguars", "point": 6.5}]},
      {"key": "totals", "outcomes": [
        {"name": "Over", "point": 47.5}, {"name": "Under", "point": 47.5}]}
    ]}
  ]
}
```

**Parsing rules:**

1. **Team names are full names, not codes.** `"Kansas City Chiefs"`, not `"KC"`.
   This needs a full-name → nflverse-code map, maintained alongside
   `TEAM_ALIASES` in `config/team_aliases.yaml` under a `full_names:` key. All 32
   entries required; an unmapped name halts.
2. **Average across bookmakers.** Take the median `point` across all books for
   each of spreads and totals. Median rather than mean, so one stale book doesn't
   drag the line.
3. **Spread sign convention here is per-team**, not per-game: each outcome carries
   its own `point`, negative for the favourite. This is *different* from
   nflverse's `spread_line`, which is a single signed number per game. Do not
   share a parser between the two.
4. Skip any bookmaker missing either market rather than discarding the game.

#### 3.2.7 Implied total derivation

```python
def implied_totals(game_total: float, home_spread: float) -> tuple[float, float]:
    """Returns (home_implied, away_implied).

    home_spread: negative when the home team is favoured (Odds API
    convention, taken from the home team's own `point` value in the
    spreads market).
    """
    half = game_total / 2.0
    edge = -home_spread / 2.0     # home favoured (-6.5) → home gets +3.25
    return (half + edge, half - edge)
```

**Sign convention is the most likely bug in this whole module.** Write a test
using a known game with a clear favourite and assert the favourite receives the
higher implied total. Getting this backwards silently inverts the Baseline factor
in all seven pickers.

#### 3.2.8 nflverse as a free fallback

`load_schedules()` (S1) is documented to carry `spread_line` and `total_line`.
Check coverage for upcoming games in the Step 0 probe.

If populated, wire it as a **zero-cost fallback** ahead of neutral degradation:

```
1. Odds API (S8)              — primary, live market
2. nflverse spread_line/total_line (S1)  — free fallback, possibly stale
3. Neutral 0.50 baselines     — last resort
```

This makes a quota exhaustion or outage in Week 14 a non-event instead of a
degraded lineup. Note the differing spread conventions (§3.2.6 rule 3) — the two
paths need separate parsers feeding a common `GameContext`.

#### 3.2.9 Quota protection in development

`--no-cache` must **not** bypass the S8 cache. Only `--no-cache=odds` does.

A dev loop re-running `pick --week 5 --no-cache` twenty times would spend 40
credits. Ten such sessions exhausts the month. The health-check endpoint is free,
so use it for connectivity testing during development, never the odds endpoint.

### 3.3 Kicking statistics — verify availability

K calibre ranking (tech spec §5.6) needs per-kicker fantasy production. Whether
`load_player_stats()` carries kicking columns needs confirming in Step 0.

**Fallback ladder if kicking stats are absent:**

1. Check for a dedicated kicking dataset in the installed `nflreadpy` version
2. Derive from `load_team_stats()` — team field goals made/attempted, attributed
   to the team's depth-chart K from S6
3. Last resort: rank kickers by their team's `scoring_efficiency_rank`, and flag
   `k_calibre_proxy` on every kicker score

Option 3 degrades the 15% KickerCalibre factor to a team-quality proxy. Acceptable
for V1 — it is the lightest-weighted factor in the lightest-stakes slot — but it
must be flagged in output rather than passing silently.

### 3.4 Depth chart coverage — verify defense and O-line

Injury unit counts (tech spec §5.8) need starter identification at OL, DB, LB, and
DL. nflverse depth charts are documented to include defense and special teams, but
coverage and consistency vary by team and season.

**Fallback if defensive depth charts are unreliable:**

Define "starter" by **snap share** instead of depth chart order — for each team and
position group, the players with the highest defensive snap percentage over the
trailing 4 games are the starters. Source: S4 `defense_pct`.

This is arguably more robust than depth charts anyway, since it reflects actual
usage. Take it if the probe shows gaps.

### 3.5 Non-API inputs

| Input | Location | Nature |
|---|---|---|
| Roster | `data/roster.yaml` | Manual entry |
| Matchup-proof tiers, elite lists, mobile QBs | `config/static_lists.yaml` | Human/consensus judgment, hard coded for the season |
| League scoring | `config/league.yaml` | From Yahoo league settings |
| Weights and thresholds | `config/weights.yaml` | Judgment-set |
| Team aliases | `config/team_aliases.yaml` | Static mapping |
| Manual ID overrides | `data/id_overrides.json` | Escape hatch for resolution failures |

**These are not data sources.** They are configuration and are not fetched,
cached, or refreshed.

---

## 4. Fetch Layer

`src/brady_bot/sources/`

### 4.1 Contract

```python
class Source(Protocol):
    source_id: str          # "S1".."S8"
    ttl_seconds: int

    def fetch(self, season: int, force: bool = False) -> pl.DataFrame:
        """Return the raw frame. Cached unless force=True."""
```

Every source implements this. No source performs derivation — fetch returns raw
data, normalized only for team codes and dtypes.

### 4.2 Cache

```
data/cache/
├── S1_schedules_2026.parquet
├── S1_schedules_2026.meta.json          {"fetched_at": "...", "source_id": "S1", "rows": 285}
├── S2_player_stats_2026.parquet
├── S2_player_stats_2025.parquet
├── S5_injuries_2026.parquet
├── S8_odds_2026_w05.json
└── ...
```

- Parquet for nflverse frames, JSON for the Odds response
- One `.meta.json` per file carrying `fetched_at`
- Cache hit when `now - fetched_at < ttl_seconds`
- `--no-cache` forces refresh on all sources **except S8** (see §3.2.1)

### 4.3 Retry and degradation

```python
def fetch_with_retry(fn, source_id: str, max_attempts: int = 3) -> pl.DataFrame:
    """Exponential backoff: 1s, 2s, 4s.

    On exhaustion, fall back to the cached copy regardless of TTL and
    flag `stale_cache:{source_id}`. Halt only if no cache exists.
    """
```

An 8-hour-old injury file with a loud warning beats a crash on Sunday morning.

### 4.4 Fetch order

S1 through S7 are independent and can run concurrently. S8 depends on nothing.
Sequential is fine at this scale — the whole fetch should complete in under 20
seconds cold.

**S8 exception:** run the free `/v4/sports` health check (§3.2.2) before the paid
odds call whenever the odds cache has expired. A rejected key then costs 0 credits
instead of 2.

---

## 5. Normalize Layer

`src/brady_bot/normalizer.py`

This layer runs immediately after fetch, before anything else touches the data.

### 5.1 Team codes

Every team column in every frame passes through `TEAM_ALIASES`:

```python
TEAM_ALIASES = {
    "LA": "LAR", "RAM": "LAR", "STL": "LAR", "SL": "LAR",
    "JAC": "JAX", "WSH": "WAS", "ARZ": "ARI", "BLT": "BAL",
    "CLV": "CLE", "HST": "HOU", "SD": "LAC", "OAK": "LV",
}

def normalize_teams(df: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    for c in cols:
        if c in df.columns:
            df = df.with_columns(
                pl.col(c).replace(TEAM_ALIASES).alias(c)
            )
    return df
```

Apply to `team`, `opponent_team`, `home_team`, `away_team`, `recent_team`,
`latest_team` — whichever exist in that frame.

**Validation:** after normalization, assert every team value is in the canonical
32-code set. An unrecognized code halts the run naming the value and the frame.

### 5.2 Player identity

**Canonical ID: `gsis_id`.** Team defenses use the synthetic `DEF-{TEAM}`.

Resolution order for any external name (roster entries, static lists):

1. `data/id_overrides.json` — `{"Player Name|TEAM": "00-0033873"}`
2. Exact match on `display_name` in S7, filtered by team and position
3. Exact match on `football_name` in S7, same filters
4. Normalized match: strip suffixes (Jr., Sr., II, III, IV) → remove punctuation
   and apostrophes → collapse whitespace → casefold

```python
def normalize_name(name: str) -> str:
    name = re.sub(r"\s+(Jr\.?|Sr\.?|I{2,3}|IV)$", "", name, flags=re.I)
    name = re.sub(r"[^\w\s]", "", name)
    return re.sub(r"\s+", " ", name).strip().casefold()
```

**Two or more candidates → `AmbiguousPlayerError`, halt**, listing every candidate
and instructing the user to add an override. Never pick one silently.

**Roster player unresolvable → `UnresolvedPlayerError`, halt.** A non-roster player
in a bulk frame may be skipped silently at DEBUG level. The distinction is roster
membership.

### 5.3 The snap counts join problem

`load_snap_counts()` is keyed on `pfr_player_id` (Pro Football Reference), not
`gsis_id`. Confirm in Step 0.

If so, `load_players()` (S7) carries both identifiers and provides the hop:

```python
crosswalk = (
    players.select(["gsis_id", "pfr_id"])
           .filter(pl.col("pfr_id").is_not_null())
)
snaps = snaps.join(crosswalk, left_on="pfr_player_id", right_on="pfr_id", how="left")
```

**Validation:** log the join hit rate. If more than 5% of snap rows for rostered
players fail to resolve, halt — snap share is the RB model's heaviest factor at
30%, and a silent miss produces a workhorse back scored as a backup.

If S7 has no `pfr_id`, fall back to normalized-name-plus-team matching, with the
same 5% threshold.

### 5.4 Dtypes

Cast stat columns to `Float64` and week/season to `Int32` at the boundary. Mixed
dtypes across seasons cause silent join failures when concatenating current and
prior season frames.

### 5.5 Null policy

**Fill nulls with 0 on stat columns only**, and only after filtering to the
relevant position. Never fill nulls on identity columns (`player_id`, `team`,
`position`) — a null there is a data problem that must surface, not be papered
over.

```python
STAT_COLS = [...]  # from schema.py
df = df.with_columns([pl.col(c).fill_null(0.0) for c in STAT_COLS if c in df.columns])
```

---

## 6. Derive Layer

`src/brady_bot/derive/`

Each function is pure: source frames plus config in, plain dict out. No network,
no file I/O, no hidden state. This is what makes them unit-testable without
fixtures larger than a few rows.

### 6.1 Adjusted Fantasy Points Allowed

`derive/adj_fpa.py`

**Input:** S2 (player stats), S1 (schedules), `cfg.scoring`, `position`,
`through_week`
**Output:** `dict[team, float]` — points allowed per game above/below league mean

```
1. Filter S2: season_type == "REG", week <= through_week
2. Filter to position. Map FB → RB.
3. Fill stat nulls with 0                                    ← Non-negotiable #2
4. Score each player-game with cfg.scoring
5. Group by opponent_team, sum fantasy points
6. Count distinct weeks per opponent_team → games_played
7. points_per_game = total / games_played                    ← Non-negotiable #3
8. league_mean = mean(points_per_game) across all 32
9. adj_fpa[team] = points_per_game[team] - league_mean
10. Assert len(adj_fpa) == 32                                ← Non-negotiable #8
```

**Positive = allows more than average = soft matchup.**

If `opponent_team` is absent from S2, join to S1 on `(game_id, team)` and take the
other team.

**Test with a hand-built 6-row frame.** Two defenses, one with a bye. Assert the
bye team is not advantaged.

### 6.2 Matchup score

`derive/adj_fpa.py`

Two modes, config-selected via `global.matchup_normalization`:

```python
# percentile (V1 default)
def_rank = rank(adj_fpa, ascending=True)      # rank 1 = lowest FPA = strongest D
score    = (def_rank - 1) / 31                # rank 1 → 0.00, rank 32 → 1.00

# linear (position-doc formula)
score = max(0.0, min(1.0, (adj_fpa + 10) / 20))
```

Percentile is default because the fixed ±10 window in `linear` is calibrated for
QB scoring volume and compresses TE matchup scores into a narrow band around 0.50,
neutralizing the TE model's 25% matchup weight.

### 6.3 Team ranks

`derive/team_ranks.py`

**Input:** S3 (team stats) — plus opponent aggregation if S3 is offense-only
**Output:** `dict[team, TeamStats]`

| Rank field | Metric | Direction |
|---|---|---|
| `offense_rank` | Total yards per game | Descending (most yards = rank 1) |
| `total_defense_rank` | Total yards allowed per game | Ascending (fewest = rank 1) |
| `scoring_efficiency_rank` | Points per 100 offensive yards | Descending |
| `run_block_rank` | Rushing yards per attempt | Descending |
| `sack_rate_allowed_rank` | Sacks allowed ÷ pass attempts | Ascending |
| `defense_calibre_rank` | Yards allowed per play | Ascending |
| `qb_turnover_rank` | INTs + fumbles lost per game | Ascending |

All per-game or per-attempt. Never season totals.

**`rz_inefficiency_rank` is derived here but inverted** — see §6.4.

### 6.4 The one deliberate rank inversion

`rz_inefficiency_rank` ranks by `scoring_efficiency` **ascending**, so **rank 1 =
least efficient = best for the kicker**. A team that gains yards without scoring
touchdowns generates field goal attempts.

This is the only place in the system where rank 1 does not mean "strongest." Put
it in the docstring, put it in a comment at the call site in `pickers/kicker.py`,
and write a test asserting the direction explicitly.

### 6.5 Injury unit counts

`derive/injuries.py`

**Input:** S5 (injuries), S6 (depth charts) — or S4 snap share if §3.4 applies
**Output:** `dict[team, dict[unit, int]]`

**Unavailability table — implement exactly:**

| `report_status` | `practice_status` | Unavailable? |
|---|---|---|
| `Out` | any | **Yes** |
| `Doubtful` | any | **Yes** |
| `Questionable` | `DNP` or `Limited` | **Yes** |
| `Questionable` | `Full` | No |
| `Questionable` | null | **Yes** (conservative) |
| null / absent | any | No |

`Doubtful` was unhandled in all seven position documents. A Doubtful player
scoring identically to a healthy one is the most likely single-week catastrophic
failure in the system.

**Unit position groups:**

```python
UNITS = {
    "OL":                    {"T","OT","LT","RT","G","OG","LG","RG","C"},
    "SECONDARY":             {"CB","DB","S","FS","SS","NB"},
    "FRONT_SEVEN":           {"DT","NT","DE","EDGE","OLB","ILB","MLB","LB"},
    "FRONT_SEVEN_INTERIOR":  {"DT","NT","ILB","MLB","LB"},   # RB Step 8 only
    "DEFENSE_ALL":           SECONDARY | FRONT_SEVEN,
}
```

`FRONT_SEVEN_INTERIOR` excludes edge rushers, per the RB model's note that
interior linemen and middle linebackers matter for run defense while edge rushers
matter more for pass rush.

**Normalize position strings before matching** — nflverse position labels vary
(`OLB` vs `LB`, `EDGE` vs `DE`). Build the mapping from the Step 0 probe output,
not from assumption.

### 6.6 Player roles

`derive/roles.py`

**WR1/WR2/WR3 — from target share, not depth chart.**

nflverse depth charts list receivers by formation position (X/Y/Z, slot) rather
than target priority, making them unreliable for fantasy role.

```
1. Trailing-4-game targets per player (S2), grouped by team
2. target_share = player targets / team total targets
3. Rank descending within team → WR1, WR2, WR3, WR4+
4. Tiebreak within 1 percentage point: S6 depth chart order
5. Weeks 1-4: blend prior-season target share per §6.7
```

**RB snap share — from S4:**

```
snap_share = offense_snaps / team_total_offense_snaps
```

Use `offense_pct` directly if the probe confirms it is already a share.

**TE1 — from S6 depth chart order, with effective-start promotion.** If the TE1 is
unavailable per §6.5, promote the TE2 for the week. The TE picker's binary gate
then passes him.

**QB1 — same pattern.** Depth chart order 1 at QB, with promotion.

### 6.7 Early-season blending

`derive/blending.py`

| Week | Prior season | Current season |
|---|---|---|
| 1 | 100% | 0% |
| 2 | 75% | 25% |
| 3 | 50% | 50% |
| 4 | 25% | 75% |
| 5+ | 0% | 100% |

**Blend the underlying rates, then rank once.** Never blend ranks — Non-negotiable
#5.

```python
def blend(prior_rate: float, current_rate: float, week: int) -> float:
    w = {1: 1.00, 2: 0.75, 3: 0.50, 4: 0.25}.get(week, 0.0)
    return (w * prior_rate) + ((1 - w) * current_rate)
```

Applies to: Adj. FPA, all team ranks, target share, snap share.

**RB snap share exception:** its prior-season component uses **only Weeks 10–18**
of the prior season, per the RB position document — late-season backfield roles are
more predictive than full-season averages. The weighting schedule is otherwise
identical.

**Committee change exception.** When `derive_committee_changed()` returns True,
the prior-season component is replaced by a neutral **score of 0.50** and the
blend happens at score level rather than rate level:

```
# unflagged — the standard path
depth_score = tier((w_prior x prior_rate) + (w_current x current_rate))

# flagged — no prior rate exists to blend
depth_score = (w_prior x 0.50) + (w_current x tier(current_rate))
```

This is a **scoped exception to non-negotiable #5** (blend rates, never scores),
valid only because the prior rate has been replaced by a constant. Committee
definitions, triggers, and the override file are in
`lineup-picker-COMMITTEE.md`. Affects RB depth (30%), WR depth (20%), FLEX
opportunity (40%). Inert from Week 5.

Anything produced with blending sets `blended = True`, surfaced in CLI output
until Week 5.

### 6.8 Player calibre

`derive/calibre.py`

**Input:** S2, `cfg.scoring`, `position`
**Output:** `dict[player_id, int]` — rank 1 = best

```
1. Score every player-game with cfg.scoring (nulls filled)
2. fantasy_points_per_game = total / games_played
3. Require >= cfg.calibre_min_games (default 3) this season
4. Below threshold → prior-season per-game average, flag calibre_prior_season
5. Neither available (rookie) → worst rank in position, flag calibre_unknown
6. Rank descending
```

Rookies are **not eliminated** — they receive the worst calibre rank and every
other factor still applies. Calibre is 10–15% weight; a rookie workhorse RB should
still start.

---

## 7. Assemble Layer

`src/brady_bot/context.py`

```python
def build_week_context(season: int, week: int, cfg: Config) -> WeekContext:
    # 1. FETCH
    schedules   = sources.nflverse.schedules(season)
    player_st   = sources.nflverse.player_stats(season)
    team_st     = sources.nflverse.team_stats(season)
    snaps       = sources.nflverse.snap_counts(season)
    injuries    = sources.nflverse.injuries(season)
    depth       = sources.nflverse.depth_charts(season)
    players     = sources.nflverse.players()

    # 2. NORMALIZE
    frames = normalizer.normalize_all(
        [schedules, player_st, team_st, snaps, injuries, depth, players]
    )
    roster = normalizer.resolve_roster(cfg.roster, players)      # halts on failure
    statics = normalizer.resolve_static_lists(cfg.static, players)  # halts on failure

    # 3. BETTING LINES  (§3.2 — nflverse first)
    games = derive.games.build(schedules, week)
    if games.needs_external_odds():
        games = games.merge(sources.odds.fetch(season, week))

    # 4. DERIVE
    ctx = WeekContext(
        season=season, week=week, fetched_at=utcnow_iso(),
        roster=roster,
        bye_teams=derive.schedule.bye_teams(schedules, week),
        injuries=derive.injuries.records(injuries),
        injury_counts=derive.injuries.unit_counts(injuries, depth),
        team_stats=derive.team_ranks.build(team_st, week),
        adj_fpa={p: derive.adj_fpa.build(player_st, schedules, p, week, cfg)
                 for p in ("QB", "RB", "WR", "TE")},
        calibre_rank={p: derive.calibre.build(player_st, p, week, cfg)
                      for p in ("QB", "RB", "WR", "TE", "K")},
        roles=derive.roles.build(player_st, snaps, depth, injuries, week),
        snap_share=derive.roles.snap_shares(snaps, week),
        target_share=derive.roles.target_shares(player_st, week),
        games=games,
        blended=(week <= 4),
    )

    # 5. VALIDATE
    validate_context(ctx)      # §8 — halts on any failure
    return ctx
```

**`WeekContext` is frozen after construction.** No picker mutates it.

---

## 8. Validation Gates

`src/brady_bot/validate.py`. Runs before any picker. **Every failure halts.**

| # | Gate | Check |
|---|---|---|
| V1 | Team coverage | Every `adj_fpa[position]` and `team_stats` contains exactly 32 teams |
| V2 | Rank bounds | Every rank field is in [1, 32] with no duplicates and no gaps |
| V3 | Rank direction | For a known-strong defense from the fixture, `total_defense_rank` < 16. Catches wholesale inversion. |
| V4 | Roster resolution | Every roster player has a gsis_id; every DEF has `DEF-{TEAM}` |
| V5 | Static lists | Every entry in `static_lists.yaml` resolved |
| V6 | Weight sums | Every position's weights sum to 1.00 ± 1e-9 |
| V7 | Score bounds | Every factor score in [0.0, 1.0] |
| V8 | Snap join rate | ≥95% of rostered RBs have a snap share |
| V9 | Games coverage | Every non-bye rostered player's team has a `GameContext` |
| V10 | Injury freshness | S5 `fetched_at` within 24h of earliest kickoff, else **warn** (not halt) |
| V11 | Implied total sanity | Every implied total in [10, 40]; **favourite > underdog** |
| V12 | Odds team mapping | Every Odds API full team name maps to an nflverse code; unmapped halts |
| V13 | Odds quota | `x-requests-remaining` logged; warn below 100 (warn, not halt) |

V10 is the only warn-level gate. Everything else halts.

---

## 9. Failure Handling

| Condition | Behaviour |
|---|---|
| nflverse fetch fails after 3 retries | Fall back to cache regardless of TTL, flag `stale_cache:{id}`. Halt only if no cache. |
| Odds API `401 / INVALID_KEY` | **Halt.** Bad key is a fixable config error, not an outage. |
| Odds API `429` (quota exhausted) | Try nflverse `spread_line`/`total_line` (§3.2.8). If unavailable, all Baseline factors → 0.50, flag `odds_quota_exhausted`. |
| Odds API 5xx / timeout / empty array | Retry 3×, then cached odds, then nflverse fallback, then neutral 0.50. |
| Roster player unresolvable | **Halt.** `UnresolvedPlayerError` naming the player and pointing at `id_overrides.json`. |
| Name resolves to 2+ candidates | **Halt.** `AmbiguousPlayerError` listing candidates. |
| Static list entry unresolvable | **Halt** at startup. A silently unresolved matchup-proof name changes lineups with no visible error. |
| `adj_fpa` returns <32 teams | **Halt.** Partial sets produce a wrong scale for every team. |
| Snap join rate <95% | **Halt.** Snap share is the RB model's 30% factor. |
| Kicking stats unavailable | Fallback ladder §3.3, flag `k_calibre_proxy`. |
| Defensive depth charts unreliable | Snap-share starter definition §3.4, flag `starters_from_snaps`. |
| Player <3 games | Prior-season average, flag `calibre_prior_season`. |
| Rookie, no history | Worst calibre rank, flag `calibre_unknown`. Not eliminated. |
| Weeks 1–4 | Blend per §6.7, `blended=True`, surface in output. |

---

## 10. Testing the Pipeline

### 10.1 Fixtures over mocks

Commit small real frames captured from a completed week:

```
tests/fixtures/raw/
├── S1_schedules_2025_w10.parquet     # ~16 rows
├── S2_player_stats_2025_w10.parquet  # ~400 rows
├── S3_team_stats_2025_w10.parquet    # 32 rows
├── S4_snap_counts_2025_w10.parquet
├── S5_injuries_2025_w10.parquet
├── S6_depth_charts_2025_w10.parquet
├── S7_players_sample.parquet         # rostered players only
└── S8_odds_2025_w10.json
```

Generated by `scripts/capture_fixtures.py`. Real data catches schema drift that
hand-written mocks never will.

### 10.2 Required derive tests

| Function | Cases |
|---|---|
| `derive_adj_fpa` | Nulls filled before arithmetic; bye-week team not advantaged by per-game division; halts on <32 teams; positive = soft matchup |
| `matchup_score` | Percentile: rank 1 → 0.00, rank 32 → 1.00. Linear matches the doc formula. |
| `derive_injury_counts` | Every row of the §6.5 table, including `Questionable` + null practice |
| `derive_roles` | WR ordering by target share; 1pp depth-chart tiebreak; TE and QB effective-start promotion |
| `blend_early_season` | Weeks 1–5 weights; blends rates not ranks; RB uses prior W10–18 only |
| `derive_player_calibre` | Min-games threshold; prior-season fallback; rookie gets worst rank, not elimination |
| `normalize_name` | Suffixes, apostrophes (`Ja'Marr`), periods (`D.J.`), casefold |
| `normalize_teams` | Every alias maps; unknown code halts |

### 10.3 Pipeline integration test

```python
def test_full_pipeline_from_fixtures():
    ctx = build_week_context_from_fixtures(season=2025, week=10)
    validate_context(ctx)                    # all gates pass
    assert len(ctx.adj_fpa["WR"]) == 32
    assert all(1 <= s.offense_rank <= 32 for s in ctx.team_stats.values())
    assert all(p.player_id for p in ctx.roster)
```

### 10.4 Determinism

```python
def test_pipeline_deterministic():
    a = build_week_context_from_fixtures(2025, 10)
    b = build_week_context_from_fixtures(2025, 10)
    assert a.model_dump_json() == b.model_dump_json()
```

Sort every collection before it enters `WeekContext`. Dict iteration order and
unsorted ties are the usual culprits.

---

## 11. Build Order

```
1. scripts/probe_schemas.py          → docs/schema_probe.txt      ← DO FIRST
2. sources/schema.py                 → confirmed column constants
3. models.py                         → WeekContext and friends
4. normalizer.py                     → teams, names, dtypes, nulls
5. sources/nflverse.py + cache.py    → S1-S7
6. sources/odds.py                   → S8 health check first, then odds fetch
7. derive/adj_fpa.py                 → the highest-value metric
8. derive/team_ranks.py
9. derive/injuries.py
10. derive/roles.py
11. derive/calibre.py
12. derive/blending.py
13. context.py                       → assembly
14. validate.py                      → gates
15. scripts/capture_fixtures.py      → test fixtures
16. tests/                           → §10
```

Steps 1 and 2 gate everything else. Do not skip them — the derive layer is written
against confirmed column names, not assumed ones.

---

## Appendix A — Factor to Source Traceability

Every factor in every picker, mapped to its source and derive function.

| Picker | Factor | Weight | Source | Derive function |
|---|---|---|---|---|
| QB | Depth chart gate | Binary | S6 | `derive_roles.qb1()` |
| QB | Style | 15% | S2 | `derive_calibre.rush_att_per_game()` |
| QB | Pass-catcher quality | 20% | S5, S6, S9 | `derive_roles` + `derive_injuries` |
| QB | O-line injuries | 10% | S5, S6 | `derive_injuries.unit_counts("OL")` |
| QB | Matchup | 30% | S2, S1 | `derive_adj_fpa("QB")` |
| QB | Secondary injuries | 15% | S5, S6 | `derive_injuries.unit_counts("SECONDARY")` |
| QB | Baseline | 10% | S1 or S8 | `derive_games.implied_total()` |
| RB | Matchup-proof tiers | Gate | S9 | `resolve_static_lists()` |
| RB | Snap share | 30% | S4 | `derive_roles.snap_share()` |
| RB | Calibre | 15% | S2 | `derive_calibre("RB")` |
| RB | O-line quality | 15% | S3, S5, S6 | `derive_team_ranks.run_block()` + injuries |
| RB | Teammate RB injuries | 10% | S5, S6 | `derive_injuries` + `derive_roles.rb_depth()` |
| RB | Matchup | 20% | S2, S1 | `derive_adj_fpa("RB")` |
| RB | Front seven injuries | 5% | S5, S6 | `unit_counts("FRONT_SEVEN_INTERIOR")` |
| RB | Baseline | 5% | S1 or S8 | `derive_games.implied_total()` |
| WR | Matchup-proof | Gate | S9 | `resolve_static_lists()` |
| WR | Depth chart position | 20% | S2, S6 | `derive_roles.wr_role()` |
| WR | Calibre | 15% | S2 | `derive_calibre("WR")` |
| WR | QB quality | 15% | S2, S5, S6 | `qb_quality_score()` |
| WR | Teammate injuries | 15% | S5, S6, S9 | `derive_injuries` + `derive_roles` |
| WR | Matchup | 20% | S2, S1 | `derive_adj_fpa("WR")` |
| WR | Secondary injuries | 10% | S5, S6 | `unit_counts("SECONDARY")` |
| WR | Baseline | 5% | S1 or S8 | `derive_games.implied_total()` |
| TE | Depth chart gate | Binary | S6, S5 | `derive_roles.te1()` |
| TE | Matchup-proof | Gate | S9 | `resolve_static_lists()` |
| TE | Calibre | 15% | S2 | `derive_calibre("TE")` |
| TE | QB quality | 15% | S2, S5, S6 | `qb_quality_score()` |
| TE | WR injuries | 25% | S5, S2 | `derive_injuries` + `derive_roles.wr_role()` |
| TE | Matchup | 25% | S2, S1 | `derive_adj_fpa("TE")` |
| TE | Secondary injuries | 15% | S5, S6 | `unit_counts("SECONDARY")` |
| TE | Baseline | 5% | S1 or S8 | `derive_games.implied_total()` |
| K | Team offense | 30% | S3 | `derive_team_ranks.offense()` |
| K | Red-zone inefficiency | 25% | S3 | `derive_team_ranks.rz_inefficiency()` ⚠ inverted |
| K | Opposing defense | 15% | S3 | `derive_team_ranks.total_defense()` |
| K | Game environment | 15% | S1 or S8 | `derive_games.game_total()` |
| K | Kicker calibre | 15% | S2 (see §3.3) | `derive_calibre("K")` |
| DEF | Opposing QB | 30% | S2, S5, S6, S9 | `derive_calibre("QB")` + injuries + statics |
| DEF | Opposing skill injuries | 15% | S5, S2 | `derive_injuries` + `derive_roles` |
| DEF | Opposing O-line | 15% | S3, S5, S6 | `sack_rate_allowed()` + `unit_counts("OL")` |
| DEF | Own defensive injuries | 15% | S5, S6 | `unit_counts("DEFENSE_ALL")` |
| DEF | Baseline | 15% | S1 or S8 | Opponent implied total |
| DEF | Defense calibre | 10% | S3 | `derive_team_ranks.defense_calibre()` |
| FLEX | Opportunity | 40% | S2, S4, S5 | `derive_roles` (all) |
| FLEX | Matchup | 25% | S2, S1 | `derive_adj_fpa(player.position)` |
| FLEX | Situation | 15% | S5, S6 | `derive_injuries` + `qb_quality_score()` |
| FLEX | Player calibre | 10% | S2 | `derive_calibre(player.position)` |
| FLEX | Baseline | 10% | S1 or S8 | `derive_games.implied_total()` |

**Source count: 7 nflverse (free) + 1 static config + 1 external (S8, The Odds API free tier, 144 credits/season against a 500/month quota).**
