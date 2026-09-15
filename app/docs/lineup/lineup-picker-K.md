# Lineup Picker — K

## Context

This file defines the logic Brady Bot uses to select the starting K each gameweek
for the Dhaka Chamber of Football league. It is one of seven per-position picker
specifications (QB, RB, WR, TE, FLEX, K, D/ST) that together produce a complete
weekly starting lineup.

The league runs a Half-PPR format with a starting lineup of QB, WR, WR, RB, RB,
W/R/T, D/ST, K, plus 6 bench slots and 1 IR slot. The K slot requires one starter
and kickers are not FLEX-eligible.

The kicker model is the simplest of the seven and rests on one idea: **the ideal
kicker plays for a team that moves the ball well but stalls in the red zone.**
Team offense quality (30%) and red-zone inefficiency (25%) together account for
more than half the score. A team ranked top-10 in yards but bottom-10 in red-zone
TD rate is the target profile — drives that reach scoring range but end in field
goal attempts rather than touchdowns.

The opposing defense and game total are secondary considerations. The kicker's own
leg is the tiebreaker.

Every factor produces a score between 0.0 and 1.0. The weighted sum of those
factors is the Kicker Start Score. No projections are used; every input is a
season-to-date team aggregate, a market line, or a published ranking.

---

## The Equation

**Kicker Start Score = (0.30 × TeamOffense_Score) + (0.25 × RedZone_Score) + (0.15 × OppDefense_Score) + (0.15 × GameEnvironment_Score) + (0.15 × KickerCalibre_Score)**

Weights sum to 1.00.

---

## Step-by-Step Logic

### Step 1: Roster Check

- If only 1 K on the roster → **start him**. Decision ends.
- If more than 1 K → proceed to evaluate and pick the best for the gameweek.

**Data source:** Manual roster entry.

### Step 2: Team Offense Quality

Team yards per game, ranked 1–32.

| Team Offensive Rank (Yards Per Game) | Score |
|---|---|
| Top 5 | 1.00 |
| 6–10 | 0.85 |
| 11–16 | 0.70 |
| 17–22 | 0.50 |
| 23–28 | 0.30 |
| 29–32 | 0.10 |

**Weight: 30%**

**Data source:** Pro Football Reference team stats; ESPN team stats.

### Step 3: Red Zone Inefficiency

Team red-zone touchdown rate. Note the inversion: **worse** red-zone conversion
scores **higher**, because stalled drives become field goal attempts.

| Team Red Zone TD Rate | Score |
|---|---|
| Bottom 5 (most inefficient) | 1.00 |
| 6–10 | 0.85 |
| 11–16 | 0.65 |
| 17–22 | 0.45 |
| 23–28 | 0.25 |
| Top 5 (most efficient) | 0.10 |

**Weight: 25%**

**Data source:** Pro Football Reference red-zone stats; Team Rankings.

### Step 4: Opposing Defense Quality

Opponent total defense ranking (yards allowed per game).

| Opposing Defense | Score |
|---|---|
| Above-average (forces turnovers, good field position) | 0.85 |
| Average | 0.65 |
| Below-average | 0.45 |
| Elite (stifles the offense entirely) | 0.30 |
| Bottom-tier (shootout risk) | 0.20 |

**Weight: 15%**

Note this factor is non-monotonic by design. Both extremes are bad for a kicker: an
elite defense prevents the offense from reaching scoring range at all, while a
bottom-tier defense invites touchdowns rather than field goals.

**Data source:** Pro Football Reference defensive rankings; ESPN defensive stats.

### Step 5: Game Environment

Game total (over/under). Lower totals score higher, for the same reason as Step 4.

| Game Total | Score |
|---|---|
| Under 40 | 1.00 |
| 40–43 | 0.75 |
| 44–47 | 0.50 |
| 48–51 | 0.30 |
| 52+ | 0.10 |

**Weight: 15%**

**Data source:** ESPN odds page; any sportsbook.

### Step 6: Kicker Calibre

| Kicker Quality | Score |
|---|---|
| Elite (top 3) | 1.00 |
| Above-average (top 8) | 0.80 |
| Average (top 16) | 0.55 |
| Below-average (top 24) | 0.35 |
| Replacement-level (bottom 8) | 0.15 |

**Weight: 15%**

**Data source:** ESPN K rankings; FantasyPros K rankings.

---

## Summary Table

| Step | Factor | Weight | Scoring Mechanism | Data Source |
|---|---|---|---|---|
| 1 | Roster check | N/A | If 1 K, start him; if more, evaluate | Manual |
| 2 | Team offense quality | **30%** | Top 5 yards/game = 1.00; bottom 5 = 0.10 | PFR, ESPN |
| 3 | Red zone inefficiency | **25%** | Bottom 5 RZ TD rate = 1.00; top 5 = 0.10 | PFR, Team Rankings |
| 4 | Opposing defense quality | 15% | Above-average = 0.85; shootout risk = 0.20 | PFR, ESPN |
| 5 | Game environment | 15% | Total under 40 = 1.00; 52+ = 0.10 | ESPN odds, sportsbook |
| 6 | Kicker calibre | 15% | Elite top 3 = 1.00; replacement-level = 0.15 | ESPN, FantasyPros |

**Total: 100%**

---

## Key Principle

The ideal kicker plays for a team that moves the ball well but stalls in the red
zone. No complicated analysis is needed — team yards per game and red-zone
touchdown rate carry 55% of the score between them. A team ranked top-10 in yards
but bottom-10 in red-zone TD rate is the best available profile.

The opposing defense and game total are secondary considerations, and both work in
the same counterintuitive direction: environments that suppress touchdowns without
suppressing drives are what generate field goal attempts. The kicker's own leg
strength is the tiebreaker.
