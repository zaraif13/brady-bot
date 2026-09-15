# Lineup Picker — TE

## Context

This file defines the logic Brady Bot uses to select the starting TE each
gameweek for the Dhaka Chamber of Football league. It is one of seven
per-position picker specifications (QB, RB, WR, TE, FLEX, K, D/ST) that together
produce a complete weekly starting lineup.

The league runs a Half-PPR format with a starting lineup of QB, WR, WR, RB, RB,
W/R/T, D/ST, K, plus 6 bench slots and 1 IR slot. The TE slot requires one
starter. A second TE could technically start via the W/R/T flex, but for V1 this
picker selects the best 1 for the dedicated slot.

The TE model prioritizes **situational opportunity over raw talent**. Its defining
feature is that WR teammate injuries carry 25% weight — the joint-heaviest factor
alongside matchup — because TE production is uniquely dependent on the health of
the team's wide receivers. When WRs are out, targets consolidate toward the TE.

Depth chart is a binary gate rather than a weighted component, because TE1s
dominate snap and route share on nearly every team while TE2s are rarely
fantasy-relevant unless the TE1 is injured.

Every factor produces a score between 0.0 and 1.0. The weighted sum of those
factors is the TE Start Score. No projections are used; every input is either a
current-state fact (depth chart, injuries, rankings) or a derived aggregate of
data that already exists.

---

## The Equation

**TE Start Score = (0.15 × Ranking_Score) + (0.15 × QB_Quality_Score) + (0.25 × WRInjury_Score) + (0.25 × Matchup_Score) + (0.15 × SecondaryInjury_Score) + (0.05 × Baseline_Score)**

Weights sum to 1.00. Depth chart position is a binary gate (Step 2), not a
weighted component.

---

## Step-by-Step Logic

### Step 1: Roster Check

- If only 1 TE on the roster → **start him**. Decision ends.
- If more than 1 TE → proceed to evaluate and pick the best one.
- Note: the league lineup means a second TE could technically start in the W/R/T
  flex, but for V1 this picker fills only the dedicated TE slot.

**Data source:** Manual roster entry.

### Step 2: Depth Chart Gate (Binary)

- If the TE is **TE1** on his team's depth chart → proceed to Step 3.
- If the TE is **TE2 or lower** → **do not start**. Decision ends.

**Depth chart scoring confirms this gate rather than replacing it.** Under the
system-wide `pos_rank` tables (`lineup-picker-DEPTH-CHART.md`), TE1 scores 1.00
and TE2+ scores 0.00 — functionally identical to passing or failing this gate.
The gate is retained because it short-circuits scoring entirely rather than
computing six factors for a player who cannot start.

Where those values do real work is the FLEX pool, when a bench TE competes
against RBs and WRs. See the FLEX module.

Unlike WR, where three-receiver sets create multiple starting roles, NFL offenses
typically feature one dominant tight end. The position has one of the biggest
positional advantages in fantasy precisely because reliable production is hard to
find outside the top tier. Only start a TE2 if the TE1 is confirmed out — in which
case the TE2 becomes the de facto TE1 and passes the gate.

**Data source:** *Not specified in V1 — see Open Items.*

### Step 3: Matchup-Proof Check (Hard Coded)

- If a TE is in the **Top 4 expert consensus preseason rankings** → **start him**.
  Decision for the slot ends.
- If not → continue to Step 4.
- For V1 this list is hard coded and does not change during the season.

**2026 Matchup-Proof TEs (Top 4 Consensus):**

| Rank | Player | Team |
|---|---|---|
| 1 | Brock Bowers | LV |
| 2 | Trey McBride | ARI |
| 3 | Tyler Warren | IND |
| 4 | Colston Loveland | CHI |

*Sources: USA Today, PFF, and NFL.com consensus rankings*

### Step 4: Player Calibre (ESPN Ranking)

**Ranking_Score = max(0, 1 − (rank − 1) / 29)**

| ESPN TE Rank | Score |
|---|---|
| 1 | 1.00 |
| 5 | 0.86 |
| 10 | 0.69 |
| 15 | 0.52 |
| 20 | 0.34 |
| 25 | 0.17 |
| 30+ | 0.00 |

**Weight: 15%**

The denominator is 29 (not 59 as for WR) because TE has far fewer startable
options. A TE ranked 10th is roughly equivalent in scarcity to a WR ranked 30th.

**Data source:** ESPN TE PPR rankings.

### Step 5: QB1 Active + QB Quality

First, check whether the TE's QB1 is active:

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

Tight ends are often a young QB's safety valve, but elite QB play still elevates
TE production. The same 32% drop in production between top-tier and bottom-tier QB
play applies at this position.

**Data source:** *Not specified in V1 — see Open Items.*

### Step 6: WR Teammate Injuries

| Situation | Score |
|---|---|
| **WR1 out or limited** | 1.00 |
| **WR2 out or limited** | 0.75 |
| **WR3 out or limited** | 0.60 |
| No significant WR injuries | 0.50 |
| Multiple WRs out | 1.00 (capped) |

**Weight: 25%**

This is the most important TE-specific factor and carries the joint-heaviest
weight alongside matchup. WRs and TEs compete for the same targets; when a WR is
out, the TE absorbs a portion of those targets, raising both floor and ceiling.

Supporting examples from 2025–2026:

- **Isaiah Likely (NYG)** — with Malik Nabers injured or limited, Likely was
  expected to step up as the top target in the passing attack and ranked as TE5
  overall in Week 1.
- **Dalton Schultz (HOU)** — after Jayden Higgins tore his ACL, Schultz had a
  legitimate shot at becoming Houston's second-highest target earner, potentially
  surpassing his 106 targets from 2025.
- **Mike Gesicki (CIN)** — his production outlook remains tied to Tee Higgins's
  health, with his best stretches in Cincinnati coming when Higgins is sidelined.
- **Jonnu Smith (MIA)** — his 2024 spike was driven by injuries to both Tyreek
  Hill and Jaylen Waddle.

**Data source:** *Not specified in V1 — see Open Items.*

### Step 7: Opposing Points Allowed to TEs (Adj. FPA)

**Matchup_Score = max(0.0, min(1.0, (Adj_FPA + 10) / 20))**

| Adj. FPA | Score |
|---|---|
| +10 or higher | 1.00 |
| +5 | 0.75 |
| 0 | 0.50 |
| −5 | 0.25 |
| −10 or lower | 0.00 |

**Weight: 25%**

Adj. FPA is schedule-independent, reflecting how far above or below their weekly
PPR averages a defense held opposing players at this position. For TEs
specifically, matchup quality is as important as WR injuries because the position
is so volatile — some defenses are historically vulnerable to tight ends, others
are not.

**Data source:** *Not specified in V1 — see Open Items.*

### Step 8: Opposing Secondary Injury Status

| Missing DBs | Score |
|---|---|
| 0 | 1.00 |
| 1 | 0.75 |
| 2 | 0.50 |
| 3+ | 0.25 |

**Weight: 15%**

Adjusts the baseline from Step 7. TEs often exploit mismatches against safeties
and slot corners, so a defense missing starting safeties or nickel corners
improves the matchup significantly.

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

Tiebreaker only. A high implied total means more passing volume and more red-zone
opportunities, both of which benefit TEs with strong red-zone usage.

**Data source:** *Not specified in V1 — see Open Items.*

---

## Summary Table

| Step | Factor | Weight | Scoring Mechanism |
|---|---|---|---|
| 1 | Roster check | N/A | If 1 TE, start him; if more, evaluate |
| 2 | Depth chart gate | **Binary** | TE1 = proceed; TE2+ = do not start |
| 3 | Matchup-proof (Top 4) | N/A | If yes, start; if no, continue |
| 4 | Player calibre (ESPN rank) | 15% | Ranking_Score = 1 − (rank−1)/29 |
| 5 | QB1 active + quality | 15% | If QB1 out, cap at 0.50; else tiered by S12 calibre rank |
| 6 | WR teammate injuries | **25%** | WR1 out = 1.00; WR2 out = 0.75; WR3 out = 0.60; none = 0.50 |
| 7 | Opposing Adj. FPA (TE) | **25%** | Normalize (Adj_FPA + 10) / 20 |
| 8 | Opposing secondary injuries | 15% | 0 missing = 1.00; 3+ missing = 0.25 |
| 9 | Baseline (implied total) | 5% | 25+ = 1.00; <19 = 0.00 |

**Total: 100%**

---

## How This Differs from the WR Model

| Factor | WR Model | TE Model | Rationale |
|---|---|---|---|
| **Depth chart** | Weighted (20%) | **Binary gate** | TE1s dominate snaps and routes; TE2s are rarely startable unless the TE1 is out. |
| **Matchup-proof** | Top 5 | **Top 4** | The elite TE tier is smaller. Only two TEs have consistently separated themselves (Bowers, McBride), with two more in Tier 2 (Warren, Loveland). |
| **WR injuries** | Not applicable | **25% weight** | TE production is uniquely dependent on WR health. When WRs are out, the TE absorbs targets. |
| **Matchup weight** | 20% | **25%** | TE scoring is more matchup-dependent due to volatility and the outsized impact of red-zone usage. |
| **Calibre denominator** | 59 | **29** | TE has roughly half as many startable options, so the ranking scale is compressed. |

---

## Open Items

This file names a data source only for Step 4 (ESPN rankings) and the Step 3
consensus list. Every other weighted step needs one before build:

- Step 2 — depth chart position (TE1 vs TE2)
- Step 5 — QB1 status and QB rankings
- Step 6 — WR teammate injuries (the heaviest factor in the model)
- Step 7 — Adj. FPA vs TEs
- Step 8 — opposing secondary injury count
- Step 9 — implied total

---

## Key Principle

The TE model prioritizes **situational opportunity over raw talent**. A TE's
fantasy value is driven by two factors above all else:

1. **Are the team's WRs healthy?** If not, the TE absorbs targets and becomes a
   focal point of the passing game. This is why WR injuries get 25% weight.

2. **Is the matchup favorable?** TE scoring is volatile and heavily dependent on
   red-zone usage. A TE facing a defense that struggles against the position has a
   substantial advantage.

The depth chart gate ensures a TE2 is never started unless the TE1 is injured —
the position simply doesn't produce enough fantasy-relevant players to make TE2s
viable. The matchup-proof check gives a free pass for the truly elite options.

Outside those four, the TE position is essentially a crapshoot: heavily
situational and dependent on weekly variables like WR health, red-zone usage, and
defensive matchup. The four elite TEs are the only ones startable with confidence
regardless of situation. Everyone else is a streaming option evaluated week by
week using this framework.
