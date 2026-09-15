# Lineup Picker — RB

## Context

This file defines the logic Brady Bot uses to select the two starting RBs each
gameweek for the Dhaka Chamber of Football league. It is one of seven
per-position picker specifications (QB, RB, WR, TE, FLEX, K, D/ST) that together
produce a complete weekly starting lineup.

The league runs a Half-PPR format with a starting lineup of QB, WR, WR, RB, RB,
W/R/T, D/ST, K, plus 6 bench slots and 1 IR slot. The RB slot requires two
starters. A third RB can start via the W/R/T flex, but for V1 this picker selects
the best 2 for the dedicated slots and passes the remainder to the FLEX pool.

The RB model prioritizes **opportunity above all else**. Depth chart position
carries 30% — the highest single-factor weight in any of the seven models —
because a workhorse RB's volume is the most reliable predictor of fantasy
production. The RB1/RB2 gap is a cliff, not a slope, and snap share is the V1
proxy for where a back sits on that cliff.

RB is also the only position with a **tiered matchup-proof structure**: Tier 1
backs auto-start, and Tier 2 backs receive a large flat bonus rather than an
automatic start. See Step 2.

Every factor produces a score between 0.0 and 1.0. The weighted sum of those
factors, plus any tier bonus, is the RB Start Score. No projections are used;
every input is either a current-state fact (depth chart, snap share, injuries,
rankings) or a derived aggregate of data that already exists.

---

## The Equation

**Weighted_Sum = (0.30 × DepthChart_Score) + (0.15 × Ranking_Score) + (0.15 × OLine_Score) + (0.10 × TeammateInjury_Score) + (0.20 × Matchup_Score) + (0.05 × FrontSevenInjury_Score) + (0.05 × Baseline_Score)**

Weights sum to 1.00, so `Weighted_Sum` is in [0.0, 1.0].

**RB Start Score = min(1.00, Weighted_Sum + Tier2_Bonus)**

Where `Tier2_Bonus` = **+0.30** for a Tier 2 RB, and 0.00 for everyone else.
The total is hard-capped at 1.00, exactly as at every other position. See
Step 2.1.

---

## Step-by-Step Logic

### Step 1: Roster Check

- If exactly 2 RBs on the roster → **start both**. Decision ends.
- If more than 2 RBs → proceed to evaluate and pick the best 2.
- Note: the league lineup allows a third RB via the W/R/T flex, but for V1 this
  picker fills only the two dedicated RB slots.

**Data source:** Manual roster entry (`data/roster.yaml`).

### Step 2: Matchup-Proof Tier Check (Hard Coded)

| Tier | Criteria | Action |
|---|---|---|
| **Tier 1: Locked-In** | Top 6 consensus preseason RBs | **Auto-start.** Skip scoring entirely. Decision for that slot ends. |
| **Tier 2: Strong Consideration** | Consensus RBs 7–10 | Score normally through Steps 3–9, then add a **+0.30 bonus** to the weighted sum. See Step 2.1. |
| **Non-Tier** | Outside top 10 | Score normally through Steps 3–9. No bonus. |

**2026 Tier 1 Locked-In RBs (Top 6 Consensus):**

| Rank | Player | Team |
|---|---|---|
| 1 | Jahmyr Gibbs | DET |
| 2 | Bijan Robinson | ATL |
| 3 | Jonathan Taylor | IND |
| 4 | James Cook III | BUF |
| 5 | Christian McCaffrey | SF |
| 6 | Saquon Barkley | PHI |

**2026 Tier 2 Strong Consideration RBs (Consensus 7–10):**

| Rank | Player | Team |
|---|---|---|
| 7 | Derrick Henry | BAL |
| 8 | Chase Brown | CIN |
| 9 | Kenneth Walker III | KC |
| 10 | Omarion Hampton | LAC |

**Data source:** `config/static_lists.yaml` (`rb_tier1`, `rb_tier2`). Names
resolve to `gsis_id` at startup via `nflreadpy.load_players()`; an unresolved or
ambiguous name **halts the run**.

### Step 2.1: The Tier 2 Bonus

A Tier 2 RB receives **+0.30 added to his weighted sum**, applied after all seven
factors are scored and summed.

```
Tier2_Bonus = 0.30 if player is in rb_tier2 else 0.00
Start_Score = min(1.00, Weighted_Sum + Tier2_Bonus)
```

**Three rules govern this bonus. All three matter.**

**1. The bonus is additive, not a multiplier.** It is applied once, to the final
weighted sum — never to an individual factor. A Tier 2 back with a weighted sum
of 0.52 scores 0.82.

**2. The total is hard-capped at 1.00.** A Tier 2 RB with a weighted sum of 0.70
or better lands exactly on the ceiling. There is no uncapped score: the
[0.0, 1.0] invariant holds at RB just as it does at the other six positions, so
scores stay readable, comparable, and on a single scale in the prediction log.

The cap does mean two Tier 2 RBs above 0.70 both sit at 1.00. That tie is broken
by the **weighted sum** — the pre-bonus factor score — before falling through to
`player_id`. The back whose factors actually scored higher wins the slot. Any
player whose score hit the ceiling carries a `score_capped` flag so a tie at the
top is visible rather than silent.

**3. The bonus is recorded, not hidden.** Every Tier 2 RB carries a `tier2_bonus`
flag, and the output shows the weighted sum, the bonus, and the capped score as
separate lines. A 0.30 swing is large enough that it must be visible in the
reasoning, not buried in a total.

**On the magnitude.** +0.30 is deliberately large — equal to the entire
DepthChart_Score weight, the heaviest factor in the model. In practice it makes a
Tier 2 start near-automatic: a Tier 2 back would need a weighted sum roughly 0.30
below a rival's to lose the slot, which requires a genuinely bad situation
(committee role, brutal matchup, depleted line) against a rival in a genuinely
good one. That is the intended reading of "strong consideration" — start him
unless the case against is overwhelming.

This supersedes the earlier rule that two rostered Tier 2 RBs both auto-start.
The bonus achieves the same outcome in almost every case while still letting an
exceptional non-tier back win the slot when the gap is large enough.

**Tier 1 RBs receive no bonus** because they never reach the equation — they
auto-start at Step 2 and their factors are never computed.

### Step 3: Depth Chart Position — Snap Share Based

This is where the RB model diverges most sharply from WR and TE. Snap share is
the proxy for committee vs. workhorse.

| Snap Share | Classification | Score |
|---|---|---|
| **60%+** | Clear workhorse | 1.00 |
| **50–60%** | Lead back in a soft committee | 0.80 |
| **30–50%** | 1B in a committee | 0.20 |
| **Under 30%** | Backup | 0.10 |
| **0% (inactive)** | Not startable | 0.00 |

**Weight: 30%**

**Data source:** `nflreadpy.load_snap_counts()` — snap share as player offensive
snaps ÷ team total offensive snaps. Joins to `gsis_id` via
`nflreadpy.load_players()`, since snap counts are keyed on `pfr_player_id`.

See the Snap Share Weightage Schedule below for how last season and current
season are blended.

### Depth chart position — the early-season component

**`pos_rank` from the current depth chart is the Weeks 1–4 anchor**, replacing
prior-season snap share entirely in this factor.

| Depth | Score |
|---|---|
| RB1 | **1.00** |
| RB2 | **0.30** |
| RB3+ | **0.00** |
| Not on depth chart | **0.00** |

The RB1 → RB2 drop of 0.70 is the steepest in the system, matching this model's
"cliff, not a slope" premise.

**Blend schedule:**

| Week | pos_rank | Current snap share |
|---|---|---|
| 1 | 100% | 0% |
| 2 | 75% | 25% |
| 3 | 50% | 50% |
| 4 | 25% | 75% |
| **5+** | **0%** | **100%** |

```
depth_score = (w_posrank × posrank_score) + (w_usage × snap_share_tier)
```

Worked: a Week 3 RB1 taking 35% of snaps scores
`(0.50 × 1.00) + (0.50 × 0.20) = 0.60`.

**Prior-season snap share is retired from this factor.** The Weeks 10–18 rule no
longer applies here — `pos_rank` occupies that slot, and it has the decisive
advantage of describing the player's *current* team. Kenneth Walker III's
Seattle snap share said nothing about Kansas City; KC's depth chart says
everything.

Prior-season data remains in use elsewhere, notably player calibre.

Full tables and rationale in `lineup-picker-DEPTH-CHART.md`.


### Step 4: Player Calibre

**Ranking_Score = max(0, 1 − (rank − 1) / 39)**

| RB Rank | Score |
|---|---|
| 1 | 1.00 |
| 5 | 0.90 |
| 10 | 0.77 |
| 20 | 0.51 |
| 30 | 0.26 |
| 40+ | 0.00 |

**Weight: 15%**

The denominator is 39 (not 59 as for WR) because RB has fewer startable options.
An RB ranked 10th is roughly equivalent in scarcity to a WR ranked 20th.

**Data source:** Derived from `nflreadpy.load_player_stats()` — fantasy points
per game played, scored with `config/league.yaml → scoring`, ranked descending
within position. Minimum 3 games this season; below that, prior-season per-game
average with a `calibre_prior_season` flag. Rookies with no history take the
worst rank in position and are flagged `calibre_unknown` — they are not
eliminated, since calibre is only 15% and a rookie workhorse should still start.

### Step 5: Offensive Line Quality

First, assess run-blocking quality:

| O-Line Run-Block Rank | Score |
|---|---|
| Elite (Top 5) | 1.00 |
| Above-average (6–12) | 0.75 |
| Average (13–20) | 0.50 |
| Below-average (21–28) | 0.25 |
| Poor (29–32) | 0.00 |

Then apply an injury penalty for missing starters:

| Missing O-Linemen | Multiplier |
|---|---|
| 0 | 1.00 |
| 1 | 0.75 |
| 2 | 0.50 |
| 3+ | 0.25 |

**OLine_Score = Run_Block_Rank_Score × Injury_Multiplier**

**Weight: 15%**

**Data source:**
- Run-block quality — `nflreadpy.load_team_stats()`, team rushing yards per
  attempt, ranked descending (rank 1 = best). This is a free proxy for PFF
  run-block grades; it conflates back quality with line quality, which is a known
  weakness flagged for V2.
- Injury count — `nflreadpy.load_injuries()` + `nflreadpy.load_depth_charts()`,
  counting unavailable starters at T/OT/LT/RT, G/OG/LG/RG, C.

### Step 6: Teammate RB Injuries (Backfield Consolidation)

This factor captures what happens when a **fellow running back** is injured — not
WRs, not TEs, only other RBs.

| Situation | Score |
|---|---|
| You are the RB1, and the RB2 is out | 0.75 |
| You are the RB2, and the RB1 is out | 1.00 (de facto RB1) |
| You are in a healthy committee (both active) | 0.50 |
| You are the RB3, and both RB1 and RB2 are out | 1.00 (lead back) |
| No relevant RB injuries | 0.50 |

**Weight: 10%**

Weighted lower than the equivalent factor for WR or TE because RB opportunity is
tied more directly to depth chart position than to teammate health. When an RB1
goes down, the RB2 doesn't just get a boost — he **becomes** the RB1, and that is
already captured in the DepthChart_Score.

**Data source:** `nflreadpy.load_injuries()` + `nflreadpy.load_depth_charts()`
for RB depth order on the same team.

### Step 7: Opposing Points Allowed to RBs (Adj. FPA)

**Matchup_Score** = percentile rank of the opposing defense by Adj. FPA against
RBs, across all 32 defenses.

```
def_rank = rank of opponent by Adj. FPA ASCENDING    # rank 1 = stingiest defense
score    = (def_rank - 1) / 31                        # rank 1 → 0.00, rank 32 → 1.00
```

The literal formula remains available via
`config/weights.yaml → global.matchup_normalization: linear`:

**Matchup_Score = max(0.0, min(1.0, (Adj_FPA + 10) / 20))**

| Adj. FPA | Score (linear mode) |
|---|---|
| +10 or higher | 1.00 |
| +5 | 0.75 |
| 0 | 0.50 |
| −5 | 0.25 |
| −10 or lower | 0.00 |

**Weight: 20%**

Adj. FPA reflects how far above or below the league average a defense has held
opposing players at this position, per game.

**Data source:** Derived from `nflreadpy.load_player_stats()` +
`nflreadpy.load_schedules()`, scored with `config/league.yaml → scoring`.

### Step 8: Opposing Front Seven Injury Status

| Missing Front Seven Starters | Score |
|---|---|
| 0 | 1.00 |
| 1 | 0.75 |
| 2 | 0.50 |
| 3+ | 0.25 |

**Weight: 5%**

For RBs the key positions are **interior defensive linemen (DT/NT)** and
**linebackers**. A great safety doesn't affect an RB much; a missing middle
linebacker does. Edge rusher injuries matter less for run defense than for pass
rush, so this count uses the `FRONT_SEVEN_INTERIOR` unit — DT, NT, ILB, MLB, LB —
**excluding** DE, EDGE, and OLB.

**Data source:** `nflreadpy.load_injuries()` + `nflreadpy.load_depth_charts()`.

### Step 9: Baseline (Game Environment)

| Implied Total | Score |
|---|---|
| 25+ | 1.00 |
| 23–24 | 0.75 |
| 21–22 | 0.50 |
| 19–20 | 0.25 |
| <19 | 0.00 |

**Weight: 5%**

Tiebreaker only. A high implied total means more red-zone opportunities. A low
total suggests a defensive struggle where neither team runs enough plays to
sustain RB volume.

**Data source:** The Odds API —
`GET /v4/sports/americanfootball_nfl/odds?regions=us&markets=spreads,totals`.
Implied total derived as `(game_total / 2) ± (spread / 2)`. Falls back to
`nflreadpy.load_schedules()` `spread_line` / `total_line`, then to a neutral 0.50.

---

## Summary Table

| Step | Factor | Weight | Scoring Mechanism | Data Source |
|---|---|---|---|---|
| 1 | Roster check | N/A | If 2 RBs, start both; if more, evaluate | Manual roster |
| 2 | Matchup-proof tiers | N/A | Tier 1 (top 6) = auto-start; Tier 2 (7–10) = **+0.30 bonus** | `static_lists.yaml` |
| 3 | Depth chart position (snap share) | **30%** | 60%+ = 1.00; 50–60% = 0.80; 30–50% = 0.20; <30% = 0.10; inactive = 0.00 | `load_snap_counts()`, `load_players()` |
| 4 | Player calibre | 15% | Ranking_Score = 1 − (rank−1)/39 | `load_player_stats()` |
| 5 | Offensive line quality | **15%** | Run-block rank score × injury multiplier | `load_team_stats()`, `load_injuries()`, `load_depth_charts()` |
| 6 | Teammate RB injuries | 10% | RB1 out → 1.00; healthy committee → 0.50 | `load_injuries()`, `load_depth_charts()` |
| 7 | Opposing Adj. FPA (RB) | 20% | Percentile rank of opposing defense | `load_player_stats()`, `load_schedules()` |
| 8 | Opposing front seven injuries | 5% | 0 missing = 1.00; 3+ missing = 0.25 | `load_injuries()`, `load_depth_charts()` |
| 9 | Baseline (implied total) | 5% | 25+ = 1.00; <19 = 0.00 | The Odds API |

**Weighted total: 100%**, plus the Tier 2 bonus where applicable.

---

## Worked Example — The Tier 2 Bonus in Action

Roster has three non-Tier-1 RBs competing for two slots.

**Chase Brown (CIN) — Tier 2, 1B in a committee, tough matchup:**

| Factor | Score | Weight | Contribution |
|---|---|---|---|
| Depth chart (38% snaps) | 0.20 | 0.30 | 0.060 |
| Calibre (RB rank 11) | 0.74 | 0.15 | 0.111 |
| O-line (rank 14, 1 out) | 0.50 × 0.75 = 0.375 | 0.15 | 0.056 |
| Teammate RB injuries | 0.50 | 0.10 | 0.050 |
| Matchup (def rank 6) | 0.16 | 0.20 | 0.032 |
| Front seven injuries | 1.00 | 0.05 | 0.050 |
| Baseline (21.5 total) | 0.50 | 0.05 | 0.025 |
| **Weighted sum** | | | **0.384** |
| **Tier 2 bonus** | | | **+0.300** |
| **Raw score** | | | **0.684** |

**Rhamondre Stevenson (NE) — non-tier, workhorse, good matchup:**

| Factor | Score | Weight | Contribution |
|---|---|---|---|
| Depth chart (67% snaps) | 1.00 | 0.30 | 0.300 |
| Calibre (RB rank 18) | 0.56 | 0.15 | 0.084 |
| O-line (rank 9, healthy) | 0.75 × 1.00 = 0.75 | 0.15 | 0.113 |
| Teammate RB injuries | 0.50 | 0.10 | 0.050 |
| Matchup (def rank 27) | 0.84 | 0.20 | 0.168 |
| Front seven injuries | 0.75 | 0.05 | 0.038 |
| Baseline (24.0 total) | 0.75 | 0.05 | 0.038 |
| **Weighted sum** | | | **0.789** |
| **Tier 2 bonus** | | | **0.000** |
| **Raw score** | | | **0.789** |

**Result:** Stevenson (0.789) starts ahead of Brown (0.684).

This is the bonus working as intended rather than failing. Brown in a committee
against a top-6 run defense produced a weighted sum of 0.384 — a genuinely bad
week. Stevenson's 0.789 clears it even after Brown's +0.30. The gap needed was
0.405, and it was there.

Had Brown been in his normal lead role (snap share 60%+, weighted sum ≈ 0.624),
his score would be 0.924 and he would start comfortably. The bonus is overcome
only by a large, well-evidenced gap.

Note that a Tier 2 back with a weighted sum of 0.70 or above caps at 1.00. Two
such backs on the same roster both display 1.00 and are separated by their
weighted sums, not by the displayed score.

---

## Snap Share Weightage Schedule — RETIRED

**Superseded by the `pos_rank` blend in Step 3.**

The prior-season Weeks 10–18 snap share rule is no longer part of this model.
`pos_rank` from the current depth chart fills that slot, using the same
100/75/50/25/0 weighting across Weeks 1–5.

The original rationale — that late-season backfield roles predict the following
season better than full-season averages — was sound, but it shares a fatal flaw
with all prior-season usage data: it describes the wrong team for any player who
moved, and the wrong supporting cast for any player whose room changed. A
current depth chart has neither problem.

Recorded here rather than deleted so the reasoning stays legible. See
`lineup-picker-DEPTH-CHART.md` for the replacement.

**Note:** Exponential decay is deferred to V2. For V1, current-season snap share
from Week 5 onward is a simple average.

### Denominator — games healthy and played

**Snap share averages divide by games the player was healthy and actually
played**, in both the prior- and current-season components.

| Situation | In denominator? |
|---|---|
| Played, ≥1 offensive snap | Yes |
| Active, 0 offensive snaps | Yes — a healthy scratch from the rotation is real signal |
| Inactive / IR / did not travel | **No** |
| Bye week | **No** |
| Suspended | **No** |

A missed game is **excluded**, never counted as a zero. A back at 70% snap share
across 10 games played who missed 7 through injury reads as:

| Method | Result |
|---|---|
| Sum ÷ 17 team games | 41.2% → 1B in committee → **0.20** |
| Sum ÷ 10 games played | 70.0% → clear workhorse → **1.00** |

An 0.80 swing on this model's heaviest factor. Missing time through injury says
nothing about role when healthy.

---

## How This Differs from the QB, WR, and TE Models

| Factor | QB | WR | TE | RB | Rationale |
|---|---|---|---|---|---|
| **Depth chart** | Binary gate | Weighted 20% | Binary gate | **Weighted 30%** (snap share) | RB opportunity is the most concentrated and predictable. The RB1/RB2 gap is a cliff. |
| **Matchup-proof** | Not included | Top 5 (binary) | Top 4 (binary) | **Tiered: top 6 auto-start, 7–10 get +0.30** | RB has a deeper elite tier than TE but a steeper drop-off than WR. The bonus is the only graded matchup-proof mechanism in the system. |
| **Offensive line** | 10% (injuries only) | Not included | Not included | **15% (quality + injuries)** | RBs depend on their line for every carry; no scrambling equivalent. |
| **Calibre denominator** | N/A | 59 | 29 | **39** | RB has fewer startable options than WR but more than TE. |
| **Teammate injuries** | Not included | 15% (WR/TE competition) | 25% (WR health) | **10% (fellow RBs only)** | Backfield consolidation is tied more to depth chart than teammate health. |
| **Matchup weight** | 30% | 20% | 25% | **20%** | RB matchup matters, but opportunity matters more. |
| **Score range** | [0.0, 1.0] | [0.0, 1.0] | [0.0, 1.0] | **[0.0, 1.0] capped** | Only RB has an additive tier bonus, but the total is hard-capped at 1.00 like everywhere else. Ties at the ceiling break on weighted sum. |

---

## Implementation Notes

```python
TIER2_BONUS = 0.30      # config/weights.yaml → rb.tier2_bonus
SCORE_CAP   = 1.00


def rb_start_score(factors: dict, weights: dict, is_tier2: bool) -> dict:
    weighted_sum = sum(factors[k] * weights[k] for k in weights)

    bonus = TIER2_BONUS if is_tier2 else 0.0
    uncapped = weighted_sum + bonus
    start_score = min(SCORE_CAP, uncapped)

    flags = []
    if is_tier2:
        flags.append("tier2_bonus")
    if uncapped > SCORE_CAP:
        flags.append("score_capped")

    return {
        "weighted_sum": weighted_sum,   # always [0.0, 1.0] — also the tiebreak key
        "tier2_bonus": bonus,
        "start_score": start_score,     # always [0.0, 1.0]
        "flags": flags,
    }


# Selection. The middle sort key is what recovers the ordering the cap loses:
# two Tier 2 RBs can both sit at 1.00, and weighted_sum separates them on merit.
starters = sorted(
    candidates,
    key=lambda c: (-c["start_score"], -c["weighted_sum"], c["player_id"]),
)[:2]
```

**Required tests:**

- A Tier 2 RB with weighted sum 0.52 scores 0.82, no `score_capped` flag
- A Tier 2 RB with weighted sum 0.85 scores 1.00 and carries `score_capped`
- Two Tier 2 RBs at weighted sums 0.78 and 0.72 both cap to 1.00; the 0.78 back
  is selected first, via the `weighted_sum` sort level
- A non-tier RB with a weighted sum 0.31 above a Tier 2 RB's still wins the slot
- A Tier 1 RB auto-starts and never receives a bonus
- `start_score` never exceeds 1.00 under any input

---

## Open Items

- **De'Von Achane appears in neither tier.** He was in the previous Tier 1 list
  and has been replaced by Saquon Barkley. Confirm this is intentional — if he is
  rostered, he will be scored as a non-tier back with no bonus.
- **Kenneth Walker III is listed at KC** and **Omarion Hampton at LAC.** Confirm
  both team assignments before Week 1, since static-list resolution filters on
  team and a wrong code halts the run.

---

## Key Principle

The RB model prioritizes **opportunity above all else**. Depth chart position gets
30% because a workhorse RB's volume is the most reliable predictor of fantasy
production. Unlike WR, where target competition creates uncertainty, or TE, where
the position is a crapshoot outside the elite four, RB production is concentrated
in one player per backfield.

The O-line is the second pillar (15%) because every carry depends on it.

The Tier 1 / Tier 2 structure encodes two different confidence levels. Tier 1 is
absolute: those six start regardless of anything the equation would say, so the
equation never runs. Tier 2 is strong but not absolute: +0.30 on a 0–1 scale means
those four start unless the weekly evidence against them is overwhelming, which is
exactly what "strong consideration" should mean in a scoring system rather than a
sentence.

**Teammate injuries here refer exclusively to fellow RBs.** A WR or TE injury does
not affect an RB's score. The core insight: **a healthy RB1 with a clean O-line
and a favorable matchup is the safest bet in fantasy football.** An RB2, no matter
how talented, is a lottery ticket waiting for an injury.
