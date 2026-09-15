# Lineup Picker — D/ST

## Context

This file defines the logic Brady Bot uses to select the starting D/ST each
gameweek for the Dhaka Chamber of Football league. It is one of seven
per-position picker specifications (QB, RB, WR, TE, FLEX, K, D/ST) that together
produce a complete weekly starting lineup.

The league runs a Half-PPR format with a starting lineup of QB, WR, WR, RB, RB,
W/R/T, D/ST, K, plus 6 bench slots and 1 IR slot. The D/ST slot requires one
starter and defenses are not FLEX-eligible.

The D/ST model is **the inverse of the offensive models**. For QB, WR, RB, and TE
the question is how good your player is and how favorable his matchup is. For
D/ST the question is how bad the *opponent* is, whether the game will be a
shootout, and whether your defense is healthy enough to capitalize. Opponent
quality carries 60% combined across three factors; the defense's own calibre
carries only 10%.

D/ST scoring is driven by disruptive plays — sacks and turnovers — more than by
simply being a good defense. V1 does not model sack and interception rates
directly; that is deferred to V2. Instead, **defensive player injuries serve as
the V1 proxy** for a defense's ability to generate pressure and force turnovers. A
unit missing its top pass rushers or starting linebackers is materially less
likely to produce sacks and INTs even against a weak opponent.

Every factor produces a score between 0.0 and 1.0. The weighted sum of those
factors is the D/ST Start Score. No projections are used.

---

## The Equation

**D/ST Start Score = (0.30 × OppQB_Score) + (0.15 × OppSkill_Score) + (0.15 × OppOLine_Score) + (0.15 × DefensiveInjury_Score) + (0.15 × Baseline_Score) + (0.10 × DefenseCalibre_Score)**

Weights sum to 1.00.

---

## Step-by-Step Logic

### Step 1: Roster Check

- If only 1 D/ST on the roster → **start it**. Decision ends.
- If more than 1 D/ST → proceed to evaluate and pick the best for the gameweek.

**Data source:** Manual roster entry.

### Step 2: Opposing QB Quality and Health

The single most important factor. A bad or injured opposing QB1 is the D/ST
equivalent of a smash spot.

| Situation | Score |
|---|---|
| **Opposing QB1 out, backup is weak (ranked 29+ or career backup)** | 1.00 |
| **Opposing QB1 out, backup is competent (ranked 15–28)** | 0.85 |
| **Opposing QB1 playing, high turnover rate (top-10 in INTs or fumbles)** | 0.80 |
| **Opposing QB1 playing, below-average (ranked 21–28)** | 0.65 |
| **Opposing QB1 playing, average (ranked 13–20)** | 0.50 |
| **Opposing QB1 playing, above-average (ranked 6–12)** | 0.35 |
| **Opposing QB1 elite (ranked 1–5)** | 0.15 |
| **Opposing QB1 elite and mobile (per the QB Playing Style Reference table)** | 0.00 |

**Weight: 30%**

**Calibre source.** `qb1_rank` is read from the authoritative static ranking in
`lineup-picker-QB-CALIBRE.md` — the identical rank consumed by WR Step 5, TE
Step 5, and FLEX Step 4, so every factor that depends on QB quality agrees on
the same number for the same quarterback. A QB not on that list (8 deep-bench
names, or a mid-season arrival) falls back to realized fantasy points per game,
flagged `qb_calibre_derived_fallback`. This ranking is never used to score the
QB picker's own factors — QB has no self-calibre component.

**Data source:** `lineup-picker-QB-CALIBRE.md` (S12) for the calibre rank —
the identical number WR Step 5, TE Step 5, and FLEX Step 4 read for the same
quarterback. `nflreadpy.load_injuries()` and `nflreadpy.load_depth_charts()`
for availability and effective-start promotion. The mobility check in the
final row reads the separate QB Playing Style Reference table in
`lineup-picker-QB.md` — same rank, unrelated lookup.

### Step 3: Opposing Skill Player Quality and Injuries

A weak or depleted supporting cast makes life easier for the defense.

| Situation | Score |
|---|---|
| **Opposing WR1, WR2, and TE1 all out or significantly limited** | 1.00 |
| **Opposing WR1 and one other starter (WR2 or TE1) out** | 0.85 |
| **Opposing WR1 out or limited** | 0.70 |
| **Opposing RB1 out (opponent becomes one-dimensional)** | 0.65 |
| **One secondary starter (WR2, WR3, or TE1) out or limited** | 0.55 |
| **No significant skill player injuries** | 0.50 |
| **Opposing offense fully healthy with elite skill players** | 0.25 |

**Weight: 15%**

**Data source:** nflverse via `nflreadpy` — `load_injuries()` and
`load_depth_charts()`; FantasyPros injury reports.

### Step 4: Opposing Offensive Line Weakness

A weak O-line is the most direct path to sacks, which score points and create
fumble opportunities.

| Situation | Score |
|---|---|
| **Bottom-5 in pressure rate allowed AND 2+ starters injured** | 1.00 |
| **Bottom-10 in pressure rate allowed OR 2+ starters injured** | 0.85 |
| **Bottom-10 in pressure rate allowed** | 0.70 |
| **1 starter injured** | 0.60 |
| **Average (ranked 13–20)** | 0.50 |
| **Top-10 in pressure rate allowed** | 0.25 |
| **Elite (top-5)** | 0.10 |

**Weight: 15%**

**Data source:** nflverse play-by-play data — calculate pressure rate as
(QB hits + hurries + sacks) ÷ dropbacks; PFF O-line grades.

### Step 5: Defensive Player Injuries

The V1 proxy for disruptive-play generation. Rather than modeling sack and INT
rates, count how many of the defense's **starting players** are unavailable.

| Situation | Score |
|---|---|
| **All defensive starters healthy** | 1.00 |
| **1 starting defensive player out or limited** | 0.75 |
| **2 starting defensive players out or limited** | 0.50 |
| **3+ starting defensive players out or limited** | 0.25 |

**Weight: 15%**

**What counts as a starting defensive player:** edge rushers (DE/OLB), defensive
tackles (DT/NT), middle linebackers (MLB), cornerbacks (CB1, CB2), and safeties
(FS, SS). Prioritize injuries to **pass rushers and linebackers** — they affect
sack and turnover generation most directly.

A defense missing its top edge rusher, middle linebacker, or CB1 is significantly
less likely to generate sacks and turnovers. If the opponent is weak but the D/ST
is also depleted, the advantage is neutralized.

**Data source:** nflverse via `nflreadpy` — `load_injuries()` and
`load_depth_charts()`; FantasyPros injury reports; ESPN NFL injuries.

### Step 6: Baseline — Avoid Shootouts

Uses the **opponent's** implied total, not the defense's own team total.

| Opponent Implied Total | Score |
|---|---|
| Under 17 | 1.00 |
| 17–19 | 0.85 |
| 20–22 | 0.65 |
| 23–25 | 0.40 |
| 26–28 | 0.20 |
| 29+ | 0.00 |

**Weight: 15%**

Weighted higher than the equivalent baseline factor in the offensive models (5–10%)
because avoiding shootouts matters more for D/ST than game environment does for
any individual offensive player.

**Data source:** Betting odds API (Apify, ESPN public feeds) for implied team
totals.

### Step 7: Defense Calibre

**DefenseCalibre_Score = max(0, 1 − (rank − 1) / 31)**

| ESPN D/ST Rank | Score |
|---|---|
| 1 | 1.00 |
| 5 | 0.87 |
| 10 | 0.71 |
| 15 | 0.55 |
| 20 | 0.39 |
| 25 | 0.23 |
| 30+ | 0.00 |

**Weight: 10%**

Use ESPN's D/ST rankings, or a composite of DVOA, PFF grades, and yards per play
allowed.

**Data source:** ESPN D/ST rankings; FTN Fantasy DVOA; PFF team defense grades.

---

## Summary Table

| Step | Factor | Weight | Scoring Mechanism |
|---|---|---|---|
| 1 | Roster check | N/A | If 1 D/ST, start it; if more, evaluate |
| 2 | **Opposing QB quality/health** | **30%** | QB1 out + weak backup = 1.00; elite mobile QB = 0.00 |
| 3 | Opposing skill player injuries | 15% | Multiple starters out = 1.00; healthy elite offense = 0.25 |
| 4 | Opposing O-line weakness | 15% | Bottom-5 pressure rate + injuries = 1.00; elite O-line = 0.10 |
| 5 | **Defensive player injuries** | **15%** | All healthy = 1.00; 3+ out = 0.25 |
| 6 | Baseline (avoid shootout) | 15% | Opponent implied total under 17 = 1.00; 29+ = 0.00 |
| 7 | Defense calibre | 10% | DefenseCalibre_Score = 1 − (rank−1)/31 |

**Total: 100%**

---

## How This Differs from the Offensive Position Models

| Factor | QB/WR/TE/RB Models | D/ST Model | Rationale |
|---|---|---|---|
| **Primary driver** | The player's own role and opportunity | **The opponent's weakness** | D/ST scoring is almost entirely matchup-dependent. |
| **Matchup weight** | 20–30% | **60% combined** | The opponent *is* the matchup. |
| **Game environment** | 5–10% (tiebreaker) | **15%** | Avoiding shootouts matters more for D/ST. |
| **Player calibre** | 10–25% | **10%** | The defense's own talent matters less than the opponent's incompetence. |
| **Injury factor** | Teammate injuries on offense | **Defensive player injuries** | A depleted D/ST can't capitalize on a weak opponent. |

---

## Key Principle

For QB, WR, RB, and TE you evaluate **how good your player is** and **how
favorable the matchup is**. For D/ST you evaluate **how bad the opponent is**,
**whether the game will be a shootout**, and **whether your defense is healthy
enough to capitalize**.

For V1, DefensiveInjury_Score stands in for the more complex Ceiling_Score of
sacks and INTs. The logic is simple: a defense missing its top pass rushers and
linebackers is less likely to generate the disruptive plays that drive D/ST
scoring.

The core insight: **a healthy, mediocre D/ST facing a backup QB behind a battered
O-line in a low-scoring game will outscore an elite but injured D/ST facing a
competent QB in a shootout.** The weights reflect this, with opponent quality at
60% dominating the equation.

---

## V2 Roadmap

Add back the Ceiling_Score:

**Ceiling_Score = (0.50 × Sack_Rate_Percentile) + (0.50 × INT_Rate_Percentile)**

- **Sack rate** — D/ST sacks ÷ opponent dropbacks, ranked across all 32 defenses
- **INT rate** — D/ST interceptions ÷ opponent pass attempts, ranked across all 32
  defenses

This either replaces DefensiveInjury_Score entirely, or splits the 15% weight
between them (for example 10% Ceiling + 5% Injuries).

**Data source:** nflverse via `nflreadpy` — `load_team_stats()` or play-by-play
aggregation.
