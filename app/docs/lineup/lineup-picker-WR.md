# Lineup Picker — WR

## Context

This file defines the logic Brady Bot uses to select the two starting WRs each
gameweek for the Dhaka Chamber of Football league. It is one of seven
per-position picker specifications (QB, RB, WR, TE, FLEX, K, D/ST) that together
produce a complete weekly starting lineup.

The league runs a Half-PPR format with a starting lineup of QB, WR, WR, RB, RB,
W/R/T, D/ST, K, plus 6 bench slots and 1 IR slot. The WR slot requires two
starters. A third WR can start via the W/R/T flex, but for V1 this picker selects
the best 2 for the dedicated slots and passes the remainder to the FLEX pool.

The WR model treats **depth chart position and matchup quality as equally
important** at 20% each. Where a receiver sits on the depth chart determines his
target floor; the opposing defense determines how efficiently those targets
convert. Unlike TE, depth chart is a weighted factor rather than a binary gate,
because three-receiver sets create multiple legitimate starting roles.

Every factor produces a score between 0.0 and 1.0. The weighted sum of those
factors is the WR Start Score. No projections are used; every input is either a
current-state fact (depth chart, injuries, rankings) or a derived aggregate of
data that already exists.

---

## The Equation

**WR Start Score = (0.20 × DepthChart_Score) + (0.15 × QB_Quality_Score) + (0.15 × Ranking_Score) + (0.15 × TeammateInjury_Score) + (0.20 × Matchup_Score) + (0.10 × SecondaryInjury_Score) + (0.05 × Baseline_Score)**

Weights sum to 1.00.

---

## Step-by-Step Logic

### Step 1: Roster Check

- If exactly 2 WRs on the roster → **start both**. Decision ends.
- If more than 2 WRs → proceed to evaluate and pick the best 2.
- Note: the league lineup allows a third WR via the W/R/T flex, but for V1 this
  picker fills only the two dedicated WR slots.

**Data source:** Manual roster entry.

### Step 2: Matchup-Proof Check (Hard Coded)

- If a WR is in the **Top 5 expert consensus preseason rankings** → **start him**.
  Decision for that slot ends.
- If not → continue to Step 3.
- For V1 this list is hard coded and does not change during the season.

**2026 Matchup-Proof WRs (Top 5 Consensus):**

| Rank | Player | Team |
|---|---|---|
| 1 | Ja'Marr Chase | CIN |
| 2 | Puka Nacua | LAR |
| 3 | Jaxon Smith-Njigba | SEA |
| 4 | Amon-Ra St. Brown | DET |
| 5 | CeeDee Lamb | DAL |

### Step 3: Depth Chart Position

| Depth Chart Position | Score |
|---|---|
| WR1 | 1.00 |
| WR2 | 0.60 |
| WR3 | 0.25 |
| WR4+ | 0.00 |

**Weight: 20%**

**Data source:** Role derived from trailing target share via
`nflreadpy.load_player_stats()`, with `nflreadpy.load_depth_charts()`
(`pos_rank`) as the tiebreak when two receivers are within 1 percentage point.

### Depth chart position — the early-season component

**Weeks 1–4 the role comes from `pos_rank`; from Week 5 it comes from trailing
target share.** Both sources map to the identical score table above, so the
transition introduces no scale discontinuity — only the *source* of the role
changes.

| Week | pos_rank | Current target share |
|---|---|---|
| 1 | 100% | 0% |
| 2 | 75% | 25% |
| 3 | 50% | 50% |
| 4 | 25% | 75% |
| **5+** | **0%** | **100%** |

This is unusually clean compared with RB, where the two components are different
measures on the same scale. Here they are the same measure derived two ways: a
published depth order early, a realized target order later.

Ladd McConkey is the case that makes the change worthwhile. Keenan Allen left
LAC for IND, so McConkey's prior-season target share was earned in a room that
no longer exists — but LAC's current depth chart reflects the departure
directly. No neutral substitution is needed; the depth chart already tells the
truth.

Full tables and rationale in `lineup-picker-DEPTH-CHART.md`.

### Denominator — games healthy and played

**Target share averages divide by games the player was healthy and actually
played.** Inactive, IR, bye, and suspended games are **excluded from the
denominator**, never counted as zero — counting a missed game as a zero drags a
WR1's average toward a WR3's, which says nothing about his role when healthy.

### Step 4: Player Calibre (ESPN Ranking)

**Ranking_Score = max(0, 1 − (rank − 1) / 59)**

| ESPN WR Rank | Score |
|---|---|
| 1 | 1.00 |
| 10 | 0.85 |
| 20 | 0.68 |
| 30 | 0.51 |
| 40 | 0.34 |
| 50 | 0.17 |
| 60+ | 0.00 |

**Weight: 15%**

**Data source:** ESPN WR PPR rankings.

### Step 5: QB1 Active + QB Quality

First, check whether the WR's QB1 is active:

| QB Status | Adjustment |
|---|---|
| QB1 active | No adjustment; proceed to the quality score |
| QB1 out/injured | Cap QB_Quality_Score at **0.50** regardless of the backup's ranking |


**Calibre source.** `qb1_rank` is read from the authoritative static ranking in
`lineup-picker-QB-CALIBRE.md` — the identical rank consumed by TE Step 5, FLEX
Step 4, and D/ST Step 2, so every factor that depends on QB quality agrees on
the same number for the same quarterback. A QB not on that list (8 deep-bench
names, or a mid-season arrival) falls back to realized fantasy points per game,
flagged `qb_calibre_derived_fallback`. This ranking is never used to score the
QB picker's own factors — QB has no self-calibre component.

If QB1 is active, score on the QB calibre rank:

| QB Calibre Rank | Score |
|---|---|
| 1–5 | 1.00 |
| 6–12 | 0.75 |
| 13–20 | 0.50 |
| 21–28 | 0.25 |
| 29+ | 0.00 |

**Weight: 15%**

**Data source:** *Not specified in V1 — see Open Items.*

### Step 6: Teammate Pass-Catcher Injuries (WRs and TEs)

| Situation | Score |
|---|---|
| Primary competitor out (other starting WR or elite TE) | 1.00 |
| Secondary competitor out (WR3 or non-elite TE) | 0.75 |
| No significant injuries | 0.50 |
| Multiple competitors out | 1.00 (capped) |

**Weight: 15%**

**Data source:** *Not specified in V1 — see Open Items.*

### Step 7: Opposing Points Allowed to WRs (Adj. FPA)

**Matchup_Score = max(0.0, min(1.0, (Adj_FPA + 10) / 20))**

| Adj. FPA | Score |
|---|---|
| +10 or higher | 1.00 |
| +5 | 0.75 |
| 0 | 0.50 |
| −5 | 0.25 |
| −10 or lower | 0.00 |

**Weight: 20%**

Adj. FPA is schedule-independent, reflecting how far above or below their weekly
PPR averages a defense held opposing players at this position.

**Data source:** *Not specified in V1 — see Open Items.*

### Step 8: Opposing Secondary Injury Status

| Missing DBs | Score |
|---|---|
| 0 | 1.00 |
| 1 | 0.75 |
| 2 | 0.50 |
| 3+ | 0.25 |

**Weight: 10%**

**Data source:** *Not specified in V1 — see Open Items.*

### Step 9: Baseline (Game Environment)

| Implied Total | Score |
|---|---|
| 25+ | 1.00 |
| 23–24 | 0.75 |
| 21–22 | 0.50 |
| 19–20 | 0.25 |
| <19 | 0.00 |

**Weight: 5%**

**Data source:** *Not specified in V1 — see Open Items.*

---

## Summary Table

| Step | Factor | Weight | Scoring Mechanism |
|---|---|---|---|
| 1 | Roster check | N/A | If 2 WRs, start both; if more, evaluate |
| 2 | Matchup-proof (Top 5) | N/A | If yes, start; if no, continue |
| 3 | Depth chart position | **20%** | WR1 = 1.00; WR2 = 0.60; WR3 = 0.25; WR4+ = 0.00 |
| 4 | Player calibre (ESPN rank) | 15% | Ranking_Score = 1 − (rank−1)/59 |
| 5 | QB1 active + quality | 15% | If QB1 out, cap at 0.50; else tiered by S12 calibre rank |
| 6 | Teammate injuries (WRs + TEs) | 15% | Primary competitor out = 1.00; none = 0.50 |
| 7 | Opposing Adj. FPA (WR) | **20%** | Normalize (Adj_FPA + 10) / 20 |
| 8 | Opposing secondary injuries | 10% | 0 missing = 1.00; 3+ missing = 0.25 |
| 9 | Baseline (implied total) | 5% | 25+ = 1.00; <19 = 0.00 |

**Total: 100%**

---

## Open Items

This file names a data source only for Step 4 (ESPN rankings). Every other
weighted step needs one before build:

- Step 3 — depth chart position
- Step 5 — QB1 status and QB rankings
- Step 6 — teammate pass-catcher injuries
- Step 7 — Adj. FPA vs WRs
- Step 8 — opposing secondary injury count
- Step 9 — implied total

---

## Key Principle

The weights reflect a clear hierarchy for WR start/sit decisions:

1. **Depth chart position (20%) and matchup quality (20%)** are tied as the most
   important factors. Depth chart determines the target floor; the opposing
   defense determines how efficiently those targets convert to fantasy points.

2. **Player calibre (15%), QB quality (15%), and teammate injuries (15%)** form
   the second tier. Talent matters, but it can be neutralized by a crowded target
   room or poor QB play. Teammate injuries are the great equalizer — they can turn
   a WR3 into a weekly starter overnight.

3. **Secondary injuries (10%) and game environment (5%)** are tiebreakers. They
   adjust the baseline but shouldn't drive the decision on their own.

The core insight: **opportunity (depth chart + teammate injuries = 35%) matters
more than talent (calibre = 15%).** A WR with a clear path to targets will
outproduce a more talented WR stuck behind too many mouths to feed.
