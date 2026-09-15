# V2 Roadmap — Deferred Elements from V1

This document catalogs every element we deliberately simplified, replaced, or omitted when building V1 of the lineup picker. Each item is a candidate for V2 or beyond.

---

## Cross-Cutting V2 Elements (Apply to All Positions)

### 1. Exponential Decay for Current-Season Data

**What V1 does:** From Week 5 onward, current-season data is a simple average of all games played. A game from Week 1 counts the same as a game from Week 5.

**What V2 should do:** Apply exponential decay so recent games carry more weight. The formula we defined: `weight = 0.5 ^ (weeks_ago / 4)` with a 4-week half-life.

**Example (Week 8):**
| Game | Weeks Ago | Weight |
|------|-----------|--------|
| Week 8 | 0 | 1.00 |
| Week 7 | 1 | 0.84 |
| Week 6 | 2 | 0.71 |
| Week 5 | 3 | 0.59 |
| Week 4 | 4 | 0.50 |
| Week 3 | 5 | 0.42 |
| Week 2 | 6 | 0.35 |
| Week 1 | 7 | 0.30 |

Then normalize so all weights sum to 1.0.

**Affects:** Snap share weighting (RB), target share / red-zone share (WR, TE), defensive metrics (all positions).

---

### 2. Dynamic Elite Marker Recalculation

**What V1 does:** Elite status is a static, hard-coded list defined before the season (Top 5 matchup-proof WRs, Top 10 elite WRs, Top 4 elite TEs, Top 6 Tier 1 RBs, Top 10 Tier 2 RBs).

**What V2 should do:** Recalculate elite status weekly based on current-season performance metrics. A player who consistently meets the target share / YPRR thresholds for 3+ consecutive weeks gets promoted.

**Suggested rule:**
```
IF a non-elite player has 3+ consecutive games with 25%+ target share (WR) 
   OR 2.0+ YPRR
   THEN promote to elite status
```

**Affects:** WR, TE, RB matchup-proof tiers.

---

### 3. Mid-Season Breakout Detection

**What V1 does:** A rookie WR who emerges as a true alpha by Week 8 stays non-elite all season because the list is static.

**What V2 should do:** Add a promotion mechanism based on sustained production. Could use a rolling 3-game window of target share, YPRR, or opportunity share.

**Affects:** WR, TE, RB elite tiers.

---

### 4. League-Specific Weight Tuning

**What V1 does:** Weights are set based on general fantasy research and your personal preferences.

**What V2 should do:** Track your actual start/sit decisions and their outcomes, then adjust weights based on what actually predicted scoring in your league's specific scoring format and roster construction.

**Affects:** All positions.

---

## QB — V2 Elements

### 1. Designed Run Rate (Replaced by Dual-Threat Binary in V1)

**What V1 does:** Simply classifies QB as "dual-threat" or "pocket passer" and scores 1.0 or 0.0.

**What V2 should do:** Measure actual designed run rate — the percentage of dropbacks that result in a designed run.

**Reference data points:**
| QB | Designed Run Rate |
|----|-------------------|
| Jalen Hurts | 16.4% |
| Justin Fields | 16.3% |
| Anthony Richardson | 15.9% |
| Lamar Jackson | 12.9% |
| **League average** | **4.0%** |

**Why:** Designed runs are schematically guaranteed opportunities, unlike scrambles which depend on defensive coverage. This is more predictive than the binary classification.

**Data source:** PFF Premium Stats, nflreadpy play-by-play filtering.

### 2. Red-Zone Rushing Attempts / Goal-Line Usage

**What V1 does:** Implicitly captured in the dual-threat classification.

**What V2 should do:** Count actual red-zone rushing attempts and goal-line carries.

**Why:** Josh Allen scored 14 rushing TDs on 112 carries in 2025. Jalen Hurts has scored 34 of his 59 career rushing TDs using the tush push, with 30 coming from exactly 1 yard out. This is where QB rushing TDs accumulate — a QB with high red-zone usage has a much higher TD ceiling.

**Data source:** nflreadpy play-by-play (filter `yardline_100 <= 10` for green zone, `<= 5` for goal line).

### 3. Pressure-to-Sack Rate (Advanced O-Line Metric)

**What V1 does:** O-line injuries weighted at 10% using tiered penalty.

**What V2 should do:** Incorporate pressure-to-sack rate, which correlates -0.42 to fantasy production (vs. -0.06 for raw pressures). Adjusted sack rate explains 13.9% of QB fantasy output.

**Data source:** PFF Premium Stats, nflreadpy play-by-play aggregation.

---

## WR — V2 Elements

### 1. Target Share % (Replaced by ESPN Ranking in V1)

**What V1 does:** Uses ESPN's WR PPR ranking as a proxy for opportunity.

**What V2 should do:** Calculate actual target share — the percentage of team pass attempts aimed at the WR.

**WR1 threshold:** 25%+ target share

**Why:** The single most predictive WR metric. A receiver commanding 25%+ of targets is the clear alpha. This separates true WR1s from volume-dependent players.

**Data source:** nflreadpy via `calculate_stats()` — outputs `target_share` as a built-in variable.

### 2. Red Zone Target Share % (Replaced by ESPN Ranking in V1)

**What V1 does:** Implicitly captured in ESPN ranking.

**What V2 should do:** Calculate the percentage of red-zone targets going to the WR.

**Threshold:** 25%+ red-zone target share for elite.

**Why:** Red-zone targets are worth 1.5 to 4.0 PPR points depending on distance. A target outside the red zone is worth 34.1% less for fantasy. Directly correlates with TD upside.

**Data source:** nflreadpy play-by-play (filter `yardline_100 <= 20`).

### 3. Yards Per Route Run (YPRR)

**What V1 does:** Not included.

**What V2 should do:** Calculate YPRR = receiving yards ÷ routes run.

**Elite threshold:** 2.0–2.50+ YPRR

**Why:** Best metric for pure efficiency. Weeds out players who get high yardage simply because their team throws a lot.

**Data source:** PFF Premium Stats (route participation data required).

### 4. Air Yards Share / WOPR

**What V1 does:** Not included.

**What V2 should do:** Calculate WOPR = (1.5 × Target Share) + (0.7 × Air Yards Share).

**Elite threshold:** 35%+ air yards share or WOPR above 0.60.

**Why:** Separates deep threats from check-down receivers. Identifies regression candidates — a player with stable, high WOPR but low recent fantasy output is due for positive regression.

**Data source:** nflreadpy (WOPR is a built-in output variable).

### 5. Route Participation

**What V1 does:** Not included.

**What V2 should do:** Track route participation rate — the percentage of passing plays where the receiver runs a route.

**Threshold:** 90%+ route participation rate.

**Why:** More precise than snap share. A player can have 85% snap share but much lower route participation if used primarily as a run blocker.

**Data source:** PFF Premium Stats.

---

## TE — V2 Elements

### 1. Target Share % and YPRR

**What V1 does:** Uses ESPN TE ranking.

**What V2 should do:** Same as WR — calculate target share and YPRR.

**TE thresholds:** 20%+ target share, 2.0+ YPRR (lower than WR because TEs share targets with receivers).

**Data source:** nflreadpy, PFF Premium Stats.

### 2. Red-Zone Target Share %

**What V1 does:** Implicitly captured in ESPN ranking.

**What V2 should do:** Calculate TE red-zone target share.

**Why:** TE scoring is heavily TD-dependent. A TE with high red-zone usage has a much higher ceiling.

**Data source:** nflreadpy play-by-play.

### 3. Dynamic Matchup-Proof Tier

**What V1 does:** Static Top 4 TE list.

**What V2 should do:** Recalculate based on current-season production. A TE who emerges mid-season as a target hog should be promoted.

---

## RB — V2 Elements

### 1. Opportunity Share (Replaced by Snap Share in V1)

**What V1 does:** Uses snap share as a proxy for committee vs. workhorse.

**What V2 should do:** Calculate Opportunity Share = (carries + targets) ÷ (team RB carries + team RB targets).

**RB1 threshold:** 70%+ opportunity share.

**Why:** Snap share captures playing time, but opportunity share captures actual touches. A back who plays 60% of snaps but only gets 40% of touches is less valuable than one who plays 55% but gets 65% of touches.

**Data source:** nflreadpy play-by-play aggregation.

### 2. High-Value Touches (HVT)

**What V1 does:** Not included — a major omission.

**What V2 should do:** Count High-Value Touches = receptions + green-zone rushes (inside the 10-yard line).

**Why this is critical:** HVT has the **highest correlation to PPR fantasy points** of any simple opportunity metric:

| Stat | R-squared (correlation to PPR points) |
|------|---------------------------------------|
| Snaps | 0.694 |
| All touches | 0.618 |
| **High-Value Touches** | **0.732** |

HVT make up just under 25% of all RB touches but account for **57.9% of all RB fantasy scoring**.

**Data source:** nflreadpy play-by-play (filter `yardline_100 <= 10` for green-zone rushes; count receptions separately).

### 3. Elusive Rating

**What V1 does:** Not included.

**What V2 should do:** Use PFF's Elusive Rating, which combines missed tackles forced and yards after contact.

**Why:** Measures how difficult a runner is to bring down. Particularly valuable for identifying backs who create yards independent of their offensive line.

**Data source:** PFF Premium Stats.

### 4. Exponential Decay in Snap Share Weighting

**What V1 does:** Simple average of current-season games from Week 5 onward.

**What V2 should do:** Apply the same exponential decay formula as other positions.

### 5. Workhorse vs. Committee Classification via HVT Distribution

**What V1 does:** Classifies based on snap share alone.

**What V2 should do:** Classify based on HVT distribution across the backfield. If two backs split red-zone work, it's a committee regardless of overall snap counts.

**Real example:** The 2025 Bears — D'Andre Swift had 43% route share while Kyle Monangai had 28.8%, but Monangai led in red-zone rushing attempts (19 vs. 18). True committee where snap share alone would mislead.

---

## FLEX — V2 Elements

### 1. More Sophisticated Cross-Position Normalization

**What V1 does:** Uses percentile-based PlayerCalibre_Score to make cross-position comparison fair.

**What V2 should do:** Potentially build a unified expected-points model that projects each player's fantasy output in the flex spot, then compares those projections directly.

### 2. Projected Fantasy Points Integration

**What V1 does:** Explicitly avoided — the system is designed to beat projections.

**What V2 should do:** Use projections as a **baseline**, then apply your model's adjustments as multipliers. This would let you measure whether your system is actually outperforming the market consensus.

---

## D/ST — V2 Elements

### 1. Ceiling Score (Sacks + INTs)

**What V1 does:** Replaced with a simple defensive player injury count.

**What V2 should do:** Add back the Ceiling_Score:

**Ceiling_Score = (0.50 × Sack_Rate_Percentile) + (0.50 × INT_Rate_Percentile)**

| Metric | Calculation |
|--------|-------------|
| Sack Rate | D/ST sacks ÷ opponent dropbacks, ranked across all 32 defenses |
| INT Rate | D/ST interceptions ÷ opponent pass attempts, ranked across all 32 defenses |

**Why:** Sacks correlate at r = 0.51 and interceptions at r = 0.60 with D/ST fantasy points per game. These are the most direct and predictable paths to D/ST scoring.

**Weight allocation options:**
- Option A: Replace DefensiveInjury_Score entirely with Ceiling_Score (15%)
- Option B: Split — 10% Ceiling + 5% Injuries

**Data source:** nflreadpy `load_team_stats()` or play-by-play aggregation.

### 2. Pressure Rate Allowed by Opposing O-Line

**What V1 does:** Uses general O-line weakness tiers.

**What V2 should do:** Calculate precise pressure rate = (QB hits + hurries + sacks) ÷ dropbacks allowed by the opposing O-line.

**Why:** Yahoo's BOD system weights Pressure Rate × 2 as one of the two heaviest components. Pressure is the engine that drives D/ST scoring.

**Data source:** nflreadpy play-by-play, NFL Savant.

### 3. Drives Ending in Turnover / Score Rate

**What V1 does:** Not included.

**What V2 should do:** Track the percentage of opponent drives ending in turnovers and the percentage ending in scores. The Yahoo BOD formula weights `%Drives ending in a Turnover × 2` and subtracts `%Drives ending in a Score × 2`.

**Data source:** nflreadpy play-by-play aggregation.

### 4. Defensive Touchdown Regression Modeling

**What V1 does:** Not included.

**What V2 should do:** Track defensive TDs and model regression. Defensive TDs correlate at r = 0.74 with D/ST fantasy points, but they are highly variable year-to-year. A D/ST that scored 4 defensive TDs in the first half of the season is likely to regress.

---

## Kicker — V2 Elements

### 1. Leg Strength Quantification

**What V1 does:** Uses ESPN kicker ranking as a proxy.

**What V2 should do:** Track kicker distance distribution — how many attempts from 50+, 40-49, 30-39 yards. A kicker with a stronger leg gets more long-range attempts, which are worth more fantasy points.

**Data source:** Pro Football Reference kicking splits, PFF kicker grades.

### 2. Coach Trust / Attempt Rate

**What V1 does:** Not included.

**What V2 should do:** Measure how often the coach trusts the kicker in key situations (4th-and-short in opponent territory, end-of-half scenarios). Some coaches aggressively go for it on 4th down; others take the points.

**Data source:** nflreadpy play-by-play (4th down decision tracking).

### 3. Weather Adjustments

**What V1 does:** Not included.

**What V2 should do:** Factor in wind speed, precipitation, and temperature. Heavy wind or rain can decrease kicking accuracy and range by 15-20%.

**Data source:** OpenWeatherMap API, NFL weather reports.

### 4. Home/Road Splits

**What V1 does:** Not included.

**What V2 should do:** Some kickers perform significantly better at home or in domes. Track kicking accuracy by venue type (dome, outdoor, altitude).

**Data source:** Pro Football Reference kicking splits.

---

## Summary Table of All V2 Elements

| Position | V1 Simplification | V2 Element |
|----------|-------------------|------------|
| All | Simple average of current-season data from Week 5 | Exponential decay with 4-week half-life |
| All | Static elite lists | Dynamic elite recalculation |
| All | No breakout detection | 3-game rolling window promotion |
| All | Fixed weights | League-specific weight tuning |
| QB | Dual-threat binary | Designed run rate (%) |
| QB | No goal-line tracking | Red-zone rushing attempts |
| QB | O-line injuries only | Pressure-to-sack rate |
| WR | ESPN ranking proxy | Target share %, red-zone share %, YPRR, WOPR, route participation |
| TE | ESPN ranking proxy | Target share %, red-zone share %, YPRR |
| TE | Static Top 4 | Dynamic matchup-proof tier |
| RB | Snap share proxy | Opportunity share, High-Value Touches, Elusive Rating |
| RB | Simple average | Exponential decay in snap share weighting |
| RB | Snap share classification | HVT distribution-based committee detection |
| FLEX | Percentile calibre | Unified expected-points model |
| FLEX | No projections | Baseline projection + model adjustments |
| D/ST | Injury count proxy | Ceiling_Score (sack rate + INT rate) |
| D/ST | General O-line weakness | Pressure rate allowed, drives ending in turnover/score |
| D/ST | No regression modeling | Defensive TD regression tracking |
| K | ESPN ranking proxy | Leg strength distribution, coach trust, weather, venue splits |