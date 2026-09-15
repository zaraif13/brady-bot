# Lineup Picker — Offensive Line Rankings

## Context

This file is the **single authoritative source for offensive line quality**
across the entire Brady Bot Lineup Picker module. It is a companion reference
to the seven per-position picker specifications, in the same role that the
Quarterback Playing Style Reference table in `lineup-picker-QB.md` serves for
QB mobility.

Two pickers consume it:

| Module | Factor | Weight | How it reads the ranking |
|---|---|---|---|
| **RB** | Step 5, O-line quality | 15% | Rank 1 = best run blocking → highest score |
| **D/ST** | Step 4, opposing O-line weakness | 15% | Rank 1 = best pass protection → **lowest** score (a strong opposing line is bad for your defense) |

Both read the same 32-row table. There is no second O-line list.

**This ranking replaces the derived proxies used in V1's first build.** The RB
picker previously approximated run-blocking quality from team rushing yards per
attempt, and the D/ST picker approximated pass protection from team sack rate
allowed. Both were free stand-ins for PFF grades, which were ruled out on cost.
This ESPN-sourced ranking supersedes both — see Deviations, below.

**This ranking covers line quality only, not line health.** Injury counts remain
a completely separate input, derived live from `nflreadpy.load_injuries()` and
`nflreadpy.load_depth_charts()`. The RB picker multiplies quality by an injury
penalty; the D/ST picker reads both independently. A top-ranked line missing two
starters is not a top-ranked line that week, and the injury layer is what
captures that.

---

## The Rankings (2026 Preseason, ESPN)

Rank 1 = best offensive line. Rank 32 = worst. This matches the system-wide rank
convention: **rank 1 is always strongest**.

| Rank | Team | Rank | Team |
|---|---|---|---|
| 1 | DEN | 17 | DET |
| 2 | PHI | 18 | NYG |
| 3 | CHI | 19 | IND |
| 4 | BUF | 20 | NO |
| 5 | LAR | 21 | LV |
| 6 | SF | 22 | CAR |
| 7 | TB | 23 | JAX |
| 8 | SEA | 24 | KC |
| 9 | BAL | 25 | GB |
| 10 | LAC | 26 | TEN |
| 11 | MIN | 27 | MIA |
| 12 | ATL | 28 | CLE |
| 13 | DAL | 29 | PIT |
| 14 | NE | 30 | CIN |
| 15 | NYJ | 31 | WAS |
| 16 | ARI | 32 | HOU |

### Coverage

| Check | Result |
|---|---|
| Teams listed | 32 of 32 |
| Ranks | 1–32, contiguous, no duplicates |
| Source | ESPN preseason O-line rankings, 2026 |
| Update cadence | Static for V1 — see Maintenance |

### Team code normalization

**ESPN publishes Washington as `WSH`. The system canonical code is `WAS`.**

That one substitution is applied in the table above and must be applied wherever
this ranking is loaded. The team code passes through `TEAM_ALIASES` in
`config/team_aliases.yaml` like every other team reference in the system — see
the data pipeline's team-code normalization rule. An unmapped or unnormalized
code halts the run.

No other team in this list needs remapping.

---

## Consumer 1 — RB Picker, Step 5

The RB model uses this ranking for the **run-blocking quality** component, then
applies a live injury penalty on top.

**Quality tiers (rank 1 = best):**

| Rank Band | Teams | Score |
|---|---|---|
| **1–5** (Elite) | DEN, PHI, CHI, BUF, LAR | 1.00 |
| **6–12** (Above average) | SF, TB, SEA, BAL, LAC, MIN, ATL | 0.75 |
| **13–20** (Average) | DAL, NE, NYJ, ARI, DET, NYG, IND, NO | 0.50 |
| **21–28** (Below average) | LV, CAR, JAX, KC, GB, TEN, MIA, CLE | 0.25 |
| **29–32** (Poor) | PIT, CIN, WAS, HOU | 0.00 |

**Injury multiplier**, from live data, applied on top:

| Missing OL starters | Multiplier |
|---|---|
| 0 | 1.00 |
| 1 | 0.75 |
| 2 | 0.50 |
| 3+ | 0.25 |

**OLine_Score = Quality_Tier_Score × Injury_Multiplier**

Worked: a Bills RB (rank 4 → 1.00) with one starter out scores 1.00 × 0.75 =
**0.75**. A Texans RB (rank 32 → 0.00) scores **0.00** regardless of health —
the multiplier can't rescue a floor of zero, which is intentional.

---

## Consumer 2 — D/ST Picker, Step 4

The D/ST model reads the **opponent's** O-line rank, inverted: a strong opposing
line means fewer sacks and pressures for your defense.

Evaluate top-down; first match wins.

| Situation | Score |
|---|---|
| Opponent O-line rank **29–32** AND 2+ OL starters out | 1.00 |
| Opponent O-line rank **23–32** OR 2+ OL starters out | 0.85 |
| Opponent O-line rank **23–32** | 0.70 |
| Opponent has **1** OL starter out | 0.60 |
| Opponent O-line rank **13–22** (average) | 0.50 |
| Opponent O-line rank **6–12** | 0.25 |
| Opponent O-line rank **1–5** (elite) | 0.10 |

### Note: a coverage gap has been closed here

The original D/ST specification defined its average band as ranks **13–20** and
its weak band as **23–32**, leaving ranks **21 and 22** — LV and CAR under this
ranking — falling through every condition with no score assigned.

The average band is therefore widened to **13–22** in the table above. Any
implementation must use 13–22, not 13–20. A D/ST facing the Raiders or Panthers
would otherwise produce an undefined or silently-defaulted O-line score.

### Note: one ranking, two different questions

RB Step 5 asks "how well does this line **run block**?" D/ST Step 4 asks "how
well does this line **pass protect**?" Those are genuinely different skills, and
the two factors previously used different proxies (rush yards per attempt vs.
sack rate allowed) precisely because of that.

This single ESPN ranking is a composite line-quality measure and now answers
both questions. That is a deliberate simplification: one authoritative,
human-verified list beats two derived proxies of uncertain accuracy. But it does
mean a line that is excellent at run blocking and poor at pass protection —
or the reverse — is scored identically for both purposes.

Splitting into separate run-block and pass-protect rankings is a candidate for a
future version, if a reliable free source for both becomes available.

---

## Where injuries come from (not this file)

To be unambiguous, since this file governs quality only:

| Input | Source | Static or live |
|---|---|---|
| O-line **quality rank** | This file → `config/oline_ranks.yaml` | **Static**, preseason |
| O-line **injury count** | `nflreadpy.load_injuries()` + `nflreadpy.load_depth_charts()` | **Live**, refreshed every run |

The injury count uses the `OL` unit position group — T, OT, LT, RT, G, OG, LG,
RG, C — counting only unavailable **starters** (depth chart rank 1), per the
availability rules in the tech spec. `Doubtful` counts as unavailable.

---

## Configuration

Stored as `config/oline_ranks.yaml`, its own file rather than a key inside
`config/static_lists.yaml`.

**Why a separate file:** `static_lists.yaml` holds player names that must be
resolved to `gsis_id` at startup via `nflreadpy.load_players()`. This ranking is
team-keyed and needs no player resolution at all — only team-code normalization.
Different resolution path, different file.

```yaml
# ESPN preseason O-line rankings, 2026. Rank 1 = best line.
# Team codes are canonical (WSH normalized to WAS).
# Consumed by: RB picker Step 5, D/ST picker Step 4.
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

### Required validation at load

| Check | On failure |
|---|---|
| Exactly 32 teams present | **Halt** — a partial ranking produces wrong scores for every team, not just the missing one |
| Ranks are 1–32, contiguous, no duplicates | **Halt** — naming the duplicate or gap |
| Every team code is canonical after `TEAM_ALIASES` | **Halt** — naming the unrecognized code |
| Every canonical NFL team appears exactly once | **Halt** — naming the missing team |

These mirror the 32-team assertions already enforced for Adj. FPA and team ranks.

---

## Maintenance

Static for V1. Review before Week 1 and, optionally, after the trade deadline.

**Two things this static ranking deliberately does not capture:**

1. **In-season performance change.** A line that gels or collapses mid-season
   keeps its preseason rank. The live injury multiplier is the only in-season
   adjustment.
2. **Personnel change.** A team that loses a starting tackle for the season
   shows up through the injury count, not through a rank change.

If a rank becomes indefensible mid-season, edit `config/oline_ranks.yaml`
directly and note the change and date here. Do not add a second ranking source.

---

## Deviations resolved

This file closes two open deviations recorded in the master tech spec:

| ID | Was | Now |
|---|---|---|
| **D3** | RB O-line quality from PFF run-block grades → substituted with team rushing yards per attempt rank, because PFF is paid. Flagged as the weakest substitution, since YPA conflates back quality with line quality. | **Resolved.** ESPN ranking is a direct line-quality measure. The YPA proxy is retired. |
| **D4** | D/ST O-line weakness from PFF pressure rate → substituted with team sack rate allowed rank. | **Resolved.** ESPN ranking replaces the sack-rate proxy. |

Two derived metrics become unused as a result: `run_block_rank` and
`sack_rate_allowed_rank` in `derive/team_ranks.py`. Remove them rather than
leaving them computed-but-unread — a derived value nothing consumes is a
maintenance cost and a future source of confusion about which one is
authoritative.

---

## Key Principle

One list, one number per team, two consumers reading it in opposite directions.

The RB picker wants a strong line and scores rank 1 highest. The D/ST picker
wants a weak opposing line and scores rank 1 lowest. Both read the same
`oline_ranks[team]` value — the inversion lives in each picker's scoring table,
never in the data.

Quality is static and human-sourced. Health is live and derived. Keeping those
two inputs separate is what lets a preseason ranking stay useful in Week 14.
