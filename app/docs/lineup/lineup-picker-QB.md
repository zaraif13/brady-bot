# Lineup Picker — QB

## Context

This file defines the logic Brady Bot uses to select the starting QB each
gameweek for the Dhaka Chamber of Football league. It is one of seven
per-position picker specifications (QB, RB, WR, TE, FLEX, K, D/ST) that together
produce a complete weekly starting lineup.

The league runs a Half-PPR format with a starting lineup of QB, WR, WR, RB, RB,
W/R/T, D/ST, K, plus 6 bench slots and 1 IR slot. The QB slot is a single
mandatory starter and, unlike RB and WR, QBs are not FLEX-eligible.

The QB model is built around a single insight: **matchup quality is the dominant
gameweek-specific factor** for this position, carrying the highest year-to-year
correlation of any position (r = 0.27). Everything else adjusts around it. Depth
chart is handled as a binary gate rather than a weighted factor, because a QB2 is
never startable — either he is the confirmed QB1 or he is eliminated.

Every factor produces a score between 0.0 and 1.0. The weighted sum of those
factors is the QB Start Score. No projections are used; every input is either a
current-state fact (depth chart, injuries, rankings) or a derived aggregate of
data that already exists.

**This file is also the system-wide reference for quarterback playing style.**
The table in the Quarterback Playing Style Reference section below is the single
source of truth for whether a QB is mobile, and is consumed both by this module
(Step 3) and by the D/ST module (its opposing-QB factor).

---

## The Equation

**QB Start Score = (0.15 × Style_Score) + (0.20 × PassCatcher_Score) + (0.10 × OLine_Score) + (0.30 × Matchup_Score) + (0.15 × SecondaryInjury_Score) + (0.10 × Baseline_Score)**

Weights sum to 1.00.

---

## Step-by-Step Logic

### Step 1: Roster Check

- If only one QB on the roster → **start him**. Decision ends.
- If more than one QB → proceed to evaluate and pick the best for the gameweek.

**Data source:** Manual roster entry (`data/roster.yaml`).

### Step 2: Depth Chart Gate (Binary)

- If the QB is the **confirmed QB1** on his team's depth chart → proceed to Step 3.
- If not → **eliminate**. Decision ends.
- Effective-start promotion applies: if the QB1 is unavailable, the QB2 is
  promoted for that week and passes the gate.

**Data source:** `nflreadpy.load_depth_charts()`, cross-referenced with
`nflreadpy.load_injuries()` for promotion.

> Do **not** use the Depth column in the Playing Style Reference table for this
> gate. That column is preseason reference only and does not update during the
> season. See the note in that section.

### Step 3: Playing Style

Binary classification on rushing involvement.

| Style | Score |
|---|---|
| Mobile / dual-threat | 1.00 |
| Not mobile / pocket passer | 0.00 |

**Weight: 15%**

**HPPR note:** Rushing yards are worth 2.5× passing yards and rushing TDs 1.5×
passing TDs. Half-PPR slightly reduces pure rushing-QB value relative to standard
scoring but does not eliminate it, which is why this sits at 15% rather than 20%.

**Data source:** The Quarterback Playing Style Reference table below is the
primary and authoritative source. For any QB not in that table (a mid-season
signing, a practice-squad elevation), fall back to
`nflreadpy.load_player_stats()` — classify as mobile if trailing rushing attempts
per game ≥ 4.0, and flag `style_derived` on the output.

### Step 4: Pass-Catcher Quality (WR1, WR2, WR3, TE1)

A base health score plus a boost for elite weapons.

**Base_Health:**

| Healthy pass-catchers | Score |
|---|---|
| 4 | 0.90 |
| 3 | 0.70 |
| 2 | 0.50 |
| 1 | 0.25 |
| 0 | 0.00 |

**Elite_Boost:** +0.10 per elite pass-catcher.

**Elite marker:** WR = Top 10 preseason consensus; TE = Top 4 preseason consensus.
See the reference lists below.

**PassCatcher_Score = min(1.00, Base_Health + Elite_Boost)**

The clamp is required. Four healthy pass-catchers including two elites would
otherwise produce 1.10, breaking the [0.0, 1.0] invariant every other factor
holds and making Start Scores incomparable across positions. Record the pre-clamp
value in the output for transparency.

**Weight: 20%**

**HPPR note:** Half-PPR increases the value of receptions, so a QB throwing to
high-volume receivers benefits. The elite markers capture target share and YPRR
thresholds rather than name recognition.

**Data source:** `nflreadpy.load_injuries()` and `nflreadpy.load_depth_charts()`
for health; `config/static_lists.yaml` (`elite_wrs`, `elite_tes`) for the elite
markers.

### Step 5: Offensive Line Injuries

| Missing O-linemen | Score |
|---|---|
| 0 | 1.00 |
| 1 | 0.75 |
| 2 | 0.50 |
| 3+ | 0.25 |

**Weight: 10%**

Left tackle is the most critical position for pass protection. Pressure-to-sack
rate correlates −0.42 to fantasy production.

Counts unavailable **starters** only (depth chart order 1 at T/OT/LT/RT, G/OG/LG/RG, C).

**Data source:** `nflreadpy.load_injuries()` + `nflreadpy.load_depth_charts()`.

### Step 6: Opposing Points Allowed to QBs (Adj. FPA)

**Matchup_Score** = percentile rank of the opposing defense by Adj. FPA against
QBs, across all 32 defenses.

```
def_rank = rank of opponent by Adj. FPA ASCENDING    # rank 1 = stingiest defense
score    = (def_rank - 1) / 31                        # rank 1 → 0.00, rank 32 → 1.00
```

The literal formula from the original specification remains available via
`config/weights.yaml → global.matchup_normalization: linear`:

**Matchup_Score = max(0.0, min(1.0, (Adj_FPA + 10) / 20))**

| Adj. FPA | Score (linear mode) |
|---|---|
| +10 or higher | 1.00 |
| +5 | 0.75 |
| 0 | 0.50 |
| −5 | 0.25 |
| −10 or lower | 0.00 |

Percentile is the default because the fixed ±10 window is calibrated for QB
scoring volume and misbehaves badly at TE. Since the same normalization function
serves all four offensive pickers, the QB module uses percentile for consistency.

**Weight: 30%**

Adj. FPA reflects how far above or below the league average a defense has held
opposing players at this position, per game. This is the highest year-to-year
correlation of any position (r = 0.27) and the most predictive gameweek factor in
the model.

**Data source:** Derived from `nflreadpy.load_player_stats()` +
`nflreadpy.load_schedules()`, scored with `config/league.yaml → scoring`.

### Step 7: Opposing Secondary Injury Status

| Missing DBs | Score |
|---|---|
| 0 | 1.00 |
| 1 | 0.75 |
| 2 | 0.50 |
| 3+ | 0.25 |

**Weight: 15%**

Adjusts the baseline from Step 6. Counts unavailable **starters** at CB, DB, S,
FS, SS, NB. Two or more missing creates a significant downgrade for the opposing
defense.

**Data source:** `nflreadpy.load_injuries()` + `nflreadpy.load_depth_charts()`.

### Step 8: Baseline (Game Environment)

| Implied Total | Score |
|---|---|
| 25+ | 1.00 |
| 23–24 | 0.75 |
| 21–22 | 0.50 |
| 19–20 | 0.25 |
| <19 | 0.00 |

**Weight: 10%**

Tiebreaker only. Should not override role and matchup.

**Data source:** The Odds API —
`GET /v4/sports/americanfootball_nfl/odds?regions=us&markets=spreads,totals`.
Implied total derived as `(game_total / 2) ± (spread / 2)`. Falls back to
`nflreadpy.load_schedules()` `spread_line` / `total_line`, then to a neutral 0.50.

---

## Summary Table

| Step | Factor | Weight | Scoring Mechanism | Data Source |
|---|---|---|---|---|
| 1 | Roster check | N/A | If 1 QB, start him; if more, evaluate | Manual roster |
| 2 | Depth chart gate | **Binary** | Confirmed QB1 = proceed; otherwise eliminate | `load_depth_charts()`, `load_injuries()` |
| 3 | Playing style | 15% | Mobile = 1.00; not mobile = 0.00 | **Playing Style Reference table (below)** |
| 4 | Pass-catcher quality | **20%** | Base health + 0.10 per elite, clamped to 1.00 | `load_injuries()`, `load_depth_charts()`, `static_lists.yaml` |
| 5 | O-line injuries | 10% | 0 missing = 1.00; 3+ missing = 0.25 | `load_injuries()`, `load_depth_charts()` |
| 6 | Opposing Adj. FPA (QB) | **30%** | Percentile rank of opposing defense | `load_player_stats()`, `load_schedules()` |
| 7 | Opposing secondary injuries | 15% | 0 missing = 1.00; 3+ missing = 0.25 | `load_injuries()`, `load_depth_charts()` |
| 8 | Baseline (implied total) | 10% | 25+ = 1.00; <19 = 0.00 | The Odds API |

**Total: 100%**

---

## Quarterback Playing Style Reference (2026 Season)

**This table is the authoritative source of truth for QB playing style across the
entire Brady Bot system.** Hard coded for V1; does not change during the season.

### Consumers

| Module | Factor | How it uses this table |
|---|---|---|
| **QB** (this file) | Step 3, Playing Style, 15% | Mobile → `Style_Score` 1.00. Not mobile → 0.00. |
| **D/ST** | Step 2, Opposing QB Quality, 30% | An opposing QB who is both calibre rank 1–5 **and** mobile scores 0.00 — the worst possible D/ST matchup. A top-5 pocket passer scores 0.15. |

Both consumers read the same `mobile` boolean. There is no second list to keep in
sync.

### Important: the Depth column is reference only

The Depth column records **preseason** depth chart position. It exists to make the
table readable and to show that all 32 QB1s are accounted for.

**It must never be used for the Step 2 depth chart gate**, or for identifying a
team's QB1 anywhere else in the system. Depth charts change weekly through
injuries, benchings, and trades; this column does not. Live depth chart position
always comes from `nflreadpy.load_depth_charts()`.

Wiring this column into the gate would freeze every team's QB1 at its Week 1
value for the whole season, which would be both wrong and silent.

### Coverage

| Metric | Value |
|---|---|
| Quarterbacks listed | 107 |
| Teams covered | 32 of 32 |
| Depth spread | 32 × QB1, 32 × QB2, 32 × QB3, 11 × QB4 |
| Classified mobile | 42 (39%) |
| QB1s classified mobile | 16 of 32 (50%) |

### The table

#### AFC East

| Player | Team | Depth | Style |
|---|---|---|---|
| Josh Allen | BUF | QB1 | **Mobile** |
| Kyle Allen | BUF | QB2 | Not mobile |
| Shane Buechele | BUF | QB3 | Not mobile |
| Malik Willis | MIA | QB1 | **Mobile** |
| Kyle McCord | MIA | QB2 | Not mobile |
| Brady Cook | MIA | QB3 | Not mobile |
| Drake Maye | NE | QB1 | **Mobile** |
| Behren Morton | NE | QB2 | Not mobile |
| Tommy DeVito | NE | QB3 | Not mobile |
| Geno Smith | NYJ | QB1 | Not mobile |
| Cade Klubnik | NYJ | QB2 | **Mobile** |
| Bailey Zappe | NYJ | QB3 | Not mobile |

#### AFC North

| Player | Team | Depth | Style |
|---|---|---|---|
| Lamar Jackson | BAL | QB1 | **Mobile** |
| Tyler Huntley | BAL | QB2 | **Mobile** |
| Joe Fagnano | BAL | QB3 | Not mobile |
| Skylar Thompson | BAL | QB4 | Not mobile |
| Joe Burrow | CIN | QB1 | Not mobile |
| Joe Flacco | CIN | QB2 | Not mobile |
| Josh Johnson | CIN | QB3 | **Mobile** |
| Sean Clifford | CIN | QB4 | Not mobile |
| Deshaun Watson | CLE | QB1 | **Mobile** |
| Shedeur Sanders | CLE | QB2 | Not mobile |
| Taylen Green | CLE | QB3 | **Mobile** |
| Dillon Gabriel | CLE | QB4 | **Mobile** |
| Aaron Rodgers | PIT | QB1 | Not mobile |
| Mason Rudolph | PIT | QB2 | Not mobile |
| Drew Allar | PIT | QB3 | Not mobile |
| Will Howard | PIT | QB4 | **Mobile** |

#### AFC South

| Player | Team | Depth | Style |
|---|---|---|---|
| C.J. Stroud | HOU | QB1 | Not mobile |
| Davis Mills | HOU | QB2 | Not mobile |
| Mark Gronowski | HOU | QB3 | Not mobile |
| Graham Mertz | HOU | QB4 | Not mobile |
| Daniel Jones | IND | QB1 | Not mobile |
| Anthony Richardson | IND | QB2 | **Mobile** |
| Riley Leonard | IND | QB3 | **Mobile** |
| Trevor Lawrence | JAX | QB1 | **Mobile** |
| Quinn Ewers | JAX | QB2 | Not mobile |
| Nick Mullens | JAX | QB3 | Not mobile |
| Joey Aguilar | JAX | QB4 | Not mobile |
| Cam Ward | TEN | QB1 | Not mobile |
| Mitchell Trubisky | TEN | QB2 | **Mobile** |
| Hendon Hooker | TEN | QB3 | **Mobile** |

#### AFC West

| Player | Team | Depth | Style |
|---|---|---|---|
| Bo Nix | DEN | QB1 | **Mobile** |
| Jarrett Stidham | DEN | QB2 | Not mobile |
| Sam Ehlinger | DEN | QB3 | **Mobile** |
| Patrick Mahomes | KC | QB1 | Not mobile |
| Justin Fields | KC | QB2 | **Mobile** |
| Garrett Nussmeier | KC | QB3 | Not mobile |
| Fernando Mendoza | LV | QB1 | Not mobile |
| Kirk Cousins | LV | QB2 | Not mobile |
| Aidan O'Connell | LV | QB3 | Not mobile |
| Justin Herbert | LAC | QB1 | **Mobile** |
| Trey Lance | LAC | QB2 | **Mobile** |
| DJ Uiagalelei | LAC | QB3 | Not mobile |

#### NFC East

| Player | Team | Depth | Style |
|---|---|---|---|
| Dak Prescott | DAL | QB1 | **Mobile** |
| Sam Howell | DAL | QB2 | **Mobile** |
| Joe Milton III | DAL | QB3 | **Mobile** |
| Jaxson Dart | NYG | QB1 | **Mobile** |
| Jameis Winston | NYG | QB2 | Not mobile |
| Jake Haener | NYG | QB3 | Not mobile |
| Jalen Hurts | PHI | QB1 | **Mobile** |
| Andy Dalton | PHI | QB2 | Not mobile |
| Tanner McKee | PHI | QB3 | Not mobile |
| Cole Payton | PHI | QB4 | **Mobile** |
| Jayden Daniels | WAS | QB1 | **Mobile** |
| Marcus Mariota | WAS | QB2 | **Mobile** |
| Athan Kaliakmanis | WAS | QB3 | Not mobile |
| Sam Hartman | WAS | QB4 | Not mobile |

#### NFC North

| Player | Team | Depth | Style |
|---|---|---|---|
| Caleb Williams | CHI | QB1 | **Mobile** |
| Tyson Bagent | CHI | QB2 | **Mobile** |
| Case Keenum | CHI | QB3 | Not mobile |
| Jared Goff | DET | QB1 | Not mobile |
| Joshua Dobbs | DET | QB2 | **Mobile** |
| Luke Altmyer | DET | QB3 | Not mobile |
| Jordan Love | GB | QB1 | Not mobile |
| Tyrod Taylor | GB | QB2 | **Mobile** |
| Kedon Slovis | GB | QB3 | Not mobile |
| Kyler Murray | MIN | QB1 | **Mobile** |
| J.J. McCarthy | MIN | QB2 | Not mobile |
| Carson Wentz | MIN | QB3 | Not mobile |
| Max Brosmer | MIN | QB4 | Not mobile |

#### NFC South

| Player | Team | Depth | Style |
|---|---|---|---|
| Michael Penix Jr. | ATL | QB1 | Not mobile |
| Tua Tagovailoa | ATL | QB2 | Not mobile |
| Jack Strand | ATL | QB3 | Not mobile |
| Cooper Rush | ATL | QB4 | Not mobile |
| Bryce Young | CAR | QB1 | **Mobile** |
| Kenny Pickett | CAR | QB2 | Not mobile |
| Haynes King | CAR | QB3 | **Mobile** |
| Tyler Shough | NO | QB1 | **Mobile** |
| Zach Wilson | NO | QB2 | **Mobile** |
| Spencer Rattler | NO | QB3 | **Mobile** |
| Baker Mayfield | TB | QB1 | Not mobile |
| Jalon Daniels | TB | QB2 | **Mobile** |
| Easton Stick | TB | QB3 | **Mobile** |

#### NFC West

| Player | Team | Depth | Style |
|---|---|---|---|
| Jacoby Brissett | ARI | QB1 | Not mobile |
| Gardner Minshew II | ARI | QB2 | Not mobile |
| Carson Beck | ARI | QB3 | Not mobile |
| Matthew Stafford | LAR | QB1 | Not mobile |
| Ty Simpson | LAR | QB2 | Not mobile |
| Stetson Bennett IV | LAR | QB3 | Not mobile |
| Matthew Caldwell | LAR | QB4 | Not mobile |
| Brock Purdy | SF | QB1 | Not mobile |
| Mac Jones | SF | QB2 | Not mobile |
| Kurtis Rourke | SF | QB3 | Not mobile |
| Sam Darnold | SEA | QB1 | Not mobile |
| Drew Lock | SEA | QB2 | Not mobile |
| Jalen Milroe | SEA | QB3 | **Mobile** |

### Configuration

Stored in `config/static_lists.yaml` under a `qb_styles` key. Names resolve to
`gsis_id` at startup via `nflreadpy.load_players()`; an unresolved or ambiguous
name **halts the run** rather than silently defaulting.

```yaml
qb_styles:
  - {name: "Josh Allen",     team: BUF, mobile: true}
  - {name: "Kyle Allen",     team: BUF, mobile: false}
  # ... 107 entries total
```

Note the duplicate-surname hazard in this list: `Josh Allen` (BUF, QB1) and
`Kyle Allen` (BUF, QB2) are on the same team, as are `Josh Johnson` (CIN) against
several other Johnsons league-wide. Resolution must filter on team **and**
position, not name alone.

### Fallback for unlisted quarterbacks

A QB not in this table — a mid-season signing, a practice-squad elevation, a
waiver claim — is classified from `nflreadpy.load_player_stats()`:

```
mobile = (trailing rushing attempts per game >= 4.0)
```

Threshold lives in `config/weights.yaml → global.qb_dual_threat_rush_att_threshold`.
Any QB scored this way carries a `style_derived` flag so the output shows the
classification was inferred, not looked up.

### Maintenance

Review before Week 1 and after the trade deadline. A QB who changes teams keeps
his mobility classification; only the `team` field needs updating, and only
because resolution filters on it.

---

## Elite Pass-Catcher Reference Lists (2026 Season)

Hard coded for V1; does not change during the season. Stored in
`config/static_lists.yaml`.

### Elite WRs (Top 10 Preseason Consensus)

| Rank | Player | Team |
|---|---|---|
| 1 | Ja'Marr Chase | CIN |
| 2 | Puka Nacua | LAR |
| 3 | Jaxon Smith-Njigba | SEA |
| 4 | Amon-Ra St. Brown | DET |
| 5 | CeeDee Lamb | DAL |
| 6 | Justin Jefferson | MIN |
| 7 | A.J. Brown | NE |
| 8 | Drake London | ATL |
| 9 | George Pickens | DAL |
| 10 | Chris Olave | NO |

*Sources: FantasyPros expert consensus rankings, Sleeper cheat sheet*

### Elite TEs (Top 4 Preseason Consensus)

| Rank | Player | Team |
|---|---|---|
| 1 | Brock Bowers | LV |
| 2 | Trey McBride | ARI |
| 3 | Tyler Warren | IND |
| 4 | Colston Loveland | CHI |

*Sources: 4for4 cheat sheets, FantasyPros rankings*

> These four are also the `te_top4` matchup-proof list used by the TE picker.
> Keep them as separate config keys even though the values match today — the gate
> ("start regardless of matchup") and the marker ("raises his QB's ceiling") could
> legitimately diverge, exactly as `wr_top5` and `elite_wrs` already do.

---

## HPPR-Specific Considerations

Half-PPR awards 0.5 points per reception, sitting between standard (0) and full
PPR (1). Implications for QB evaluation:

| Factor | HPPR Impact |
|---|---|
| **Pass-catcher quality** | Slightly amplified — QBs throwing to high-volume receivers benefit from 0.5 per catch. The 20% weight reflects this. |
| **Dual-threat QBs** | Rushing production remains valuable but slightly less dominant than in standard. The 15% weight (down from 20%) reflects this. |
| **Elite WR/TE boost** | HPPR rewards target share more than standard, so the elite marker is well-calibrated. |
| **Matchup quality** | Unchanged — defensive performance against QBs is scoring-format agnostic. The 30% weight holds. |

---

## Reference Implementation

```python
def qb_start_score(is_mobile, pass_catchers_healthy, elite_count,
                   oline_missing, matchup_score, secondary_missing, implied_total):
    """All inputs are facts or derived aggregates. No projections."""

    # Step 3: Style — from the Playing Style Reference table
    style_score = 1.0 if is_mobile else 0.0

    # Step 4: Pass-catchers (base health + elite boost, CLAMPED to 1.0)
    pc_map = {4: 0.90, 3: 0.70, 2: 0.50, 1: 0.25, 0: 0.00}
    base_health = pc_map.get(pass_catchers_healthy, 0.0)
    pc_score = min(1.0, base_health + elite_count * 0.10)

    # Step 5: O-line
    ol_map = {0: 1.0, 1: 0.75, 2: 0.50, 3: 0.25}
    ol_score = ol_map.get(min(oline_missing, 3), 0.25)

    # Step 6: Matchup — precomputed percentile rank, passed in
    #         matchup_score = (opponent_def_rank - 1) / 31

    # Step 7: Secondary injuries
    db_map = {0: 1.0, 1: 0.75, 2: 0.50, 3: 0.25}
    db_score = db_map.get(min(secondary_missing, 3), 0.25)

    # Step 8: Baseline (implied total)
    if implied_total >= 25:   base_score = 1.0
    elif implied_total >= 23: base_score = 0.75
    elif implied_total >= 21: base_score = 0.50
    elif implied_total >= 19: base_score = 0.25
    else:                     base_score = 0.0

    return (0.15 * style_score +
            0.20 * pc_score +
            0.10 * ol_score +
            0.30 * matchup_score +
            0.15 * db_score +
            0.10 * base_score)


# Loaded from config/static_lists.yaml, resolved to gsis_id at startup.
# Shown here as literals for reference only — never hard code in production.

ELITE_WRS = ["Ja'Marr Chase", "Puka Nacua", "Jaxon Smith-Njigba",
             "Amon-Ra St. Brown", "CeeDee Lamb", "Justin Jefferson",
             "A.J. Brown", "Drake London", "George Pickens", "Chris Olave"]

ELITE_TES = ["Brock Bowers", "Trey McBride", "Tyler Warren", "Colston Loveland"]


def is_elite(player_id: str, position: str, statics) -> bool:
    """Resolve by gsis_id, never by name string."""
    if position == "WR":
        return player_id in statics.elite_wrs
    if position == "TE":
        return player_id in statics.elite_tes
    return False


def is_mobile(player_id: str, statics, stats=None) -> bool:
    """Playing Style Reference table first; derived fallback for unlisted QBs."""
    if player_id in statics.qb_styles:
        return statics.qb_styles[player_id]
    if stats is not None:
        return stats.rush_att_per_game(player_id) >= statics.qb_dual_threat_threshold
    return False
```

---

## Weight Hierarchy

| Weight | Component | Rationale |
|---|---|---|
| **30%** | Matchup (Adj. FPA) | Highest year-to-year correlation (r = 0.27); most predictive gameweek factor |
| **20%** | Pass-catcher quality | Missing targets caps ceiling; elite talent elevates the QB |
| **15%** | Style (mobile vs pocket) | Rushing worth 2.5× passing yards; floor-raiser, not ceiling-setter |
| **15%** | Secondary injuries | Adjusts baseline; 2+ missing DBs is a significant downgrade |
| **10%** | O-line injuries | Pressure matters, but elite QBs mitigate; sacks correlate −0.42 |
| **10%** | Baseline (implied total) | Tiebreaker only; separates close calls |

---

## Key Principle

The weights reflect a deliberate hierarchy: **matchup quality (30%) is the
dominant gameweek-specific factor**, followed by **pass-catcher quality and
health (20%)** including elite talent boosts. Style and O-line are secondary
considerations that adjust the baseline rather than drive the decision.

A pocket passer with an elite WR1, a clean pocket, and a favorable matchup will
outscore a mobile QB with injured weapons and a tough secondary. The elite boost
ensures a Justin Jefferson is properly valued — not merely as "a healthy starter"
but as a genuine ceiling-raiser for his quarterback.
