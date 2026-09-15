# Lineup Picker — FLEX (W/R/T)

## Context

This file defines the logic Brady Bot uses to select the single FLEX (W/R/T)
starter each gameweek for the Dhaka Chamber of Football league. It is one of seven
per-position picker specifications (QB, RB, WR, TE, FLEX, K, D/ST) that together
produce a complete weekly starting lineup.

The league runs a Half-PPR format with a starting lineup of QB, WR, WR, RB, RB,
W/R/T, D/ST, K, plus 6 bench slots and 1 IR slot. The FLEX slot accepts one RB,
WR, or TE and is filled after the mandatory slots are locked, drawing from the
remaining RB/WR/TE pool.

The FLEX model exists to solve one problem the other pickers don't face:
**comparing players across positions on a single scale.** It does this three ways
— by prioritizing opportunity (40%), the one factor that matters regardless of
position; by always applying the position-appropriate Adj. FPA; and by scoring
player calibre on within-position percentiles so a 75th-percentile WR and a
75th-percentile RB score identically.

The model's other distinguishing feature is that **Situation_Score is
position-dependent**. QB health affects WR and TE candidates but not RB
candidates, because running backs generate their own touches through handoffs and
check-downs.

Every factor produces a score between 0.0 and 1.0. The weighted sum of those
factors is the Flex Score. No projections are used.

---

## The Equation

**Flex Score = (0.40 × Opportunity_Score) + (0.25 × Matchup_Score) + (0.15 × Situation_Score) + (0.10 × PlayerCalibre_Score) + (0.10 × Baseline_Score)**

Weights sum to 1.00.

---

## Step-by-Step Logic

### Step 1: Pool Assembly

Collect every RB, WR, and TE not already starting at a dedicated slot. This pool
is produced as a side effect of the RB, WR, and TE pickers.

**Data source:** RB, WR, and TE picker outputs.

### Step 2: Opportunity

The single most important factor in a FLEX decision: how many touches or targets
will this player get?

| Position | Situation | Score |
|---|---|---|
| RB | Workhorse (60%+ snap share) | 1.00 |
| WR | WR1 on team (clear top target) | 1.00 |
| TE | TE1 with injured WRs | 1.00 |
| RB | Lead in soft committee (50–60%) | 0.80 |
| TE | TE1 with healthy WRs | 0.70 |
| WR | WR2 on team | 0.65 |
| RB | 1B in committee (30–50%) | 0.40 |
| WR | WR3 on team | 0.30 |
| RB | Backup (<30%) | 0.10 |

**Weight: 40%**

**Data source:** `nflreadpy.load_snap_counts()` for RB snap share;
`nflreadpy.load_player_stats()` target share for WR role;
`nflreadpy.load_injuries()` for the TE-with-injured-WRs condition.

### Depth chart position — the early-season component

**The `pos_rank` lookup replaces the Opportunity table above for Weeks 1–4.**
That table is not deleted — it becomes the Week 5+ usage component.

**Early component — `pos_rank`, cross-position:**

| Depth | Score |
|---|---|
| RB1 | **1.00** |
| WR1 | **1.00** |
| TE1 | **1.00** |
| WR2 | **0.60** |
| RB2 | **0.30** |
| WR3 | **0.25** |
| RB3+ / WR4+ / TE2+ | **0.00** |

| Week | pos_rank | Usage table (above) |
|---|---|---|
| 1 | 100% | 0% |
| 2 | 75% | 25% |
| 3 | 50% | 50% |
| 4 | 25% | 75% |
| **5+** | **0%** | **100%** |

Because Opportunity is 40% — the heaviest single factor anywhere in the system —
this makes depth chart position the dominant driver of Week 1 FLEX decisions. A
Week 1 WR2 (0.60) beats a Week 1 RB2 (0.30) on this factor before any other
consideration.

**The two tables differ for TE, deliberately.** `pos_rank` scores TE1 at a flat
1.00; the usage table splits TE1 into 1.00 (injured WRs) and 0.70 (healthy WRs).
WR health is a live in-season condition that a preseason depth chart cannot
express, so it only enters once the usage component has weight.

Full tables and rationale in `lineup-picker-DEPTH-CHART.md`.

### Denominator — games healthy and played

Snap share and target share averages divide by games the player was healthy and
actually played. Inactive, IR, bye, and suspended games are excluded from the
denominator, never counted as zero.

### Step 3: Matchup (Position-Appropriate Adj. FPA)

Use the Adj. FPA matching the candidate's own position:

- WR candidate → opposing team's Adj. FPA against WRs
- RB candidate → opposing team's Adj. FPA against RBs
- TE candidate → opposing team's Adj. FPA against TEs

**Matchup_Score = max(0.0, min(1.0, (Adj_FPA + 10) / 20))**

**Weight: 25%**

**Data source:** *Not specified in V1 — see Open Items.*

### Step 4: Situation (Position-Dependent)

**For RB candidates — QB health does NOT apply:**

| Situation | Score |
|---|---|
| O-line intact, no significant injuries | 1.00 |
| O-line banged up (1 starter out) | 0.75 |
| O-line significantly depleted (2+ starters out) | 0.50 |
| Multiple fellow RBs injured (backfield consolidation) | +0.25 bonus, capped at 1.00 |

Running backs get their touches from handoffs, not passes. A backup QB still hands
off on first and second down and still checks down on third. If anything, a backup
QB may lean *more* on the run game and check-downs, slightly boosting RB volume.
There is no scenario where a QB injury meaningfully suppresses RB opportunity.

**For WR and TE candidates — QB health DOES apply:**

| Situation | Score |
|---|---|
| QB1 active and healthy | 1.00 |
| QB1 active but limited (injury designation but playing) | 0.75 |
| QB1 out, competent backup (top-20 QB ranking) | 0.50 |
| QB1 out, weak backup (21+ QB ranking) | 0.25 |
| Multiple pass-catchers injured (target consolidation) | +0.25 bonus, capped at 1.00 |

Receivers and tight ends depend entirely on the QB to get them the ball. A backup
QB may lack chemistry with the starters, have a weaker arm, or check down more
frequently to RBs instead of pushing downfield. The 32% production drop between
top-tier and bottom-tier QB play is the core evidence.

**Weight: 15%**

**Calibre source.** `qb1_rank` is read from the authoritative static ranking in
`lineup-picker-QB-CALIBRE.md` — the identical rank consumed by TE Step 5, FLEX
Step 4, and D/ST Step 2, so every factor that depends on QB quality agrees on
the same number for the same quarterback. A QB not on that list (8 deep-bench
names, or a mid-season arrival) falls back to realized fantasy points per game,
flagged `qb_calibre_derived_fallback`. This ranking is never used to score the
QB picker's own factors — QB has no self-calibre component.

**Data source:** `nflreadpy.load_injuries()` and `nflreadpy.load_depth_charts()`
for QB1 availability and O-line/teammate injury counts;
`lineup-picker-QB-CALIBRE.md` (S12) for the QB calibre rank behind "top-20 QB
ranking" / "21+ QB ranking" in the table above.

### Step 5: Player Calibre (Percentile Based)

Percentiles are computed **within position**, against all fantasy-relevant players
at that position (roughly the top 60 WRs, top 40 RBs, top 30 TEs on fantasy
rosters).

| Percentile Band | Score | Meaning |
|---|---|---|
| **Above 95th** | 1.00 | Elite, top-tier at position |
| 90th–95th | 0.90 | Near-elite |
| 75th–90th | 0.75 | Strong starter |
| 50th–75th | 0.50 | Average starter / flex-worthy |
| 25th–50th | 0.25 | Below-average starter / bench |
| 10th–25th | 0.10 | Deep bench |
| Below 10th | 0.00 | Not fantasy-relevant |

**Weight: 10%**

Within-position percentiles are what make cross-position comparison meaningful —
a 75th-percentile WR and a 75th-percentile RB both score 0.75.

**Data source:** *Not specified in V1 — see Open Items.*

### Step 6: Baseline (Game Environment)

| Implied Total | Score |
|---|---|
| 25+ | 1.00 |
| 23–24 | 0.75 |
| 21–22 | 0.50 |
| 19–20 | 0.25 |
| <19 | 0.00 |

**Weight: 10%**

**Data source:** *Not specified in V1 — see Open Items.*

### Step 7: Select

Highest Flex Score starts at FLEX.

---

## Summary Table

| Step | Factor | Weight | Scoring Mechanism |
|---|---|---|---|
| 1 | Pool assembly | N/A | All RB/WR/TE not in a dedicated slot |
| 2 | Opportunity | **40%** | RB workhorse = 1.00; WR1 = 1.00; TE1 with injured WRs = 1.00; RB soft committee = 0.80; TE1 healthy WRs = 0.70; WR2 = 0.65; RB 1B = 0.40; WR3 = 0.30; RB backup = 0.10 |
| 3 | Matchup (position-appropriate Adj. FPA) | 25% | Normalize (Adj_FPA + 10) / 20 |
| 4 | Situation | 15% | RB: O-line + backfield only. WR/TE: QB health + teammate consolidation |
| 5 | Player calibre (percentile) | 10% | >95th = 1.00; 50–75th = 0.50; <10th = 0.00 |
| 6 | Baseline (implied total) | 10% | 25+ = 1.00; <19 = 0.00 |
| 7 | Select | N/A | Highest Flex Score starts |

**Total: 100%**

---

## Worked Example

Bench contains: 1 WR (WR2 on his team, QB1 active but limited), 2 RBs (one
workhorse, one 1B in a committee), 1 TE (TE1 with injured WRs, QB1 out with a weak
backup).

**RB1 — workhorse, O-line intact:**

| Factor | Score | Weight | Contribution |
|---|---|---|---|
| Opportunity | 1.00 | 0.40 | 0.400 |
| Matchup | 0.60 | 0.25 | 0.150 |
| Situation | 1.00 | 0.15 | 0.150 (QB health irrelevant) |
| Calibre | 0.75 | 0.10 | 0.075 |
| Baseline | 0.50 | 0.10 | 0.050 |
| **Total** | | | **0.825** |

**RB2 — 1B committee, O-line intact:**

| Factor | Score | Weight | Contribution |
|---|---|---|---|
| Opportunity | 0.40 | 0.40 | 0.160 |
| Matchup | 0.60 | 0.25 | 0.150 |
| Situation | 1.00 | 0.15 | 0.150 (QB health irrelevant) |
| Calibre | 0.50 | 0.10 | 0.050 |
| Baseline | 0.50 | 0.10 | 0.050 |
| **Total** | | | **0.560** |

**WR2 — QB1 active but limited:**

| Factor | Score | Weight | Contribution |
|---|---|---|---|
| Opportunity | 0.65 | 0.40 | 0.260 |
| Matchup | 0.70 | 0.25 | 0.175 |
| Situation | 0.75 | 0.15 | 0.1125 |
| Calibre | 0.50 | 0.10 | 0.050 |
| Baseline | 0.50 | 0.10 | 0.050 |
| **Total** | | | **0.6475** |

**TE1 — injured WRs, QB1 out with weak backup:**

| Factor | Score | Weight | Contribution |
|---|---|---|---|
| Opportunity | 1.00 | 0.40 | 0.400 |
| Matchup | 0.50 | 0.25 | 0.125 |
| Situation | 0.25 | 0.15 | 0.0375 |
| Calibre | 0.75 | 0.10 | 0.075 |
| Baseline | 0.50 | 0.10 | 0.050 |
| **Total** | | | **0.6875** |

**Decision:** start the **workhorse RB** (0.825). Even with the TE's target
consolidation and the WR's matchup advantage, the RB's guaranteed volume
dominates.

---

## Open Items

This file names no data sources. Every weighted step needs one before build:

- Step 2 — opportunity classification (snap share, depth chart position, WR health)
- Step 3 — Adj. FPA vs RB, WR, and TE
- Step 4 — O-line injuries, fellow-RB injuries, QB1 status, QB rankings, pass-catcher injuries
- Step 5 — the population and metric used to compute within-position percentiles
- Step 6 — implied total

Step 5 needs the most definition: the percentile is computed against
"fantasy-relevant players at that position," but the metric being ranked is not
specified.

---

## Key Principle

The QB health factor is **position-dependent**: it affects WR and TE candidates
because those positions rely on the QB to deliver the ball, but not RB candidates
because running backs generate their own touches. This keeps the cross-position
comparison fair — a workhorse RB isn't penalized for a QB injury that has nothing
to do with his volume, while a WR or TE correctly absorbs the downgrade.

The Flex Score puts all three positions on the same scale by:

1. **Prioritizing opportunity (40%)** — the one factor that matters most
   regardless of position. A workhorse RB and a target-hog WR1 both score 1.00.
2. **Using position-appropriate matchups (25%)** — always the correct Adj. FPA for
   that player's position.
3. **Capturing situation (15%)** — QB health for WR/TE, O-line health for RB,
   teammate consolidation for all.
4. **Standardizing calibre via percentiles (10%)** — making the comparison
   apples-to-apples.

The core insight: **the flex spot should go to the player with the best
combination of opportunity and matchup, regardless of position.**
