# Lineup Picker — Depth Chart Position Scoring (`pos_rank`)

## Context

This file is the **authoritative source for how depth chart position converts
into a score** across the Lineup Picker module. It sits alongside
`lineup-picker-OLINE.md` and the QB playing-style table in
`lineup-picker-QB.md` as one of the system's definitive reference documents.

**Depth chart position is a primary scoring input, not bookkeeping.** Where a
player sits on his team's published depth chart is one of the strongest
available signals about how much opportunity he will get — especially early in
a season, before usage data exists.

The model uses it as the **early-season anchor**. Weeks 1–4 lean on depth chart
position, fading progressively as real usage data accumulates. From Week 5
onward, actual snap share and target share take over completely.

```
Week 1        Week 2        Week 3        Week 4        Week 5+
pos_rank      75/25         50/50         25/75         usage only
100%                                                    pos_rank inert
```

The logic: a published depth chart is the best available statement of intent
before any snaps are played, and the worst available statement of reality once
they have been. Usage beats intent as soon as usage exists.

---

## Data Source

`nflreadpy.load_depth_charts()`, cached 6h.

| Field | Meaning |
|---|---|
| `gsis_id` | Canonical player ID |
| `pos_abb` | Specific position slot — `QB`, `RB`, `WR`, `TE`, `LT`, `RCB`, etc. |
| `pos_rank` | Order at that slot. **1 = starter**, 2 = backup, 3 = third string |
| `dt` | Snapshot timestamp — **there is no `week` column** |
| `team` | Team code, normalized via `TEAM_ALIASES` |

**Pinning is mandatory.** Because there is no `week` field, every read must first
filter to each team's **maximum `dt`** via `pin_depth_to_latest_week()`. Without
pinning, historical snapshots leak in and a player can resolve to a stale rank
from weeks earlier.

**Depth charts are static for the season, not a weekly document.** ESPN
publishes each team's depth chart once, before that season's Week 1, and it
stays the same afterward **except when an injury moves a player up** — the
backup in front of whom the injured player sat gets promoted, and everyone
below shifts up one slot. There is no routine weekly re-publication independent
of injuries. This is why `dt` updates near-daily in the raw feed (it's a
continuous scrape) while the actual **ranks themselves barely move** — most
`dt` snapshots for a team are identical to the one before; a rank changes only
around an injury designation, not on a fixed weekly cadence. Two implications:

- **"Pin to max `dt`" is really "pin to the latest injury-driven state,"** not
  "pin to this week's fresh chart" — there usually is no fresh chart for the
  current week distinct from last week's, unless someone got hurt in between.
- A `pos_rank` promotion is a **signal an injury happened**, not routine week-
  to-week noise. If a player's rank improves between two pinned reads, treat
  that as corroborating evidence for whatever the injury report says, not as
  an independent, unexplained fluctuation to be smoothed over.

---

## Depth Chart Table Format (Display)

**This section did not previously exist in this document.** Everything above
this point describes how `pos_rank` is converted into a *score*. Nothing above
it said anything about how an actual depth chart *table* — the human-readable
artifact, not the scoring pipeline — should be laid out when one is
constructed or displayed. This section makes that explicit.

**Rule: any depth chart table this module produces must be organized exactly
the way ESPN organizes it on their own team depth chart pages** — e.g.
`https://www.espn.com/nfl/team/depth/_/name/buf` for Buffalo. This is not
arbitrary: `nflreadpy.load_depth_charts()` is itself sourced from ESPN's depth
charts, so the raw data already carries ESPN's own structure end to end. Confirmed
directly against BUF's page and the matching rows in `load_depth_charts()`:

- **Three sections per team, in this fixed order: Offense, Defense, Special
  Teams.** ESPN's BUF page renders in exactly that order.
- **Each row is one position slot** (e.g. `QB`, `RB`, `WR`, `WR`, `WR`, `TE`,
  `LT`, `LG`, `C`, `RG`, `RT` for BUF's offense; `LDE`, `NT`, `RDE`, `WLB`,
  `LILB`, `RILB`, `SLB`, `LCB`, `SS`, `FS`, `RCB`, `NB` for BUF's defense —
  note this is a 3-4 front; a 4-3 team's defensive rows will use a different
  label set, e.g. ARI's `LDE`/`LDT`/`RDT`/`RDE`/`WLB`/`MLB`/`SLB`). **The row
  set is team-specific and must be read from the data, never hard-coded to one
  scheme** — this is exactly why `nflreadpy` carries `pos_grp` per team.
- **Each column is a depth level** — Starter (1st), 2nd, 3rd, and (where
  present) 4th string — populated left to right.

**How this maps onto the `load_depth_charts()` fields** (all already present,
no new data source needed):

| Field | Role in the table |
|---|---|
| `pos_grp` | Which of the three sections a row belongs to — e.g. `"3WR 1TE"` or another offensive personnel label → **Offense**; `"Base 3-4 D"` or another defensive front label → **Defense**; `"Special Teams"` → **Special Teams**. This is ESPN's own per-team scheme label, already section-specific and already correct — do not replace it with a hand-written offense/defense keyword map. |
| `pos_slot` | Row order **within** a section — sort ascending. This reproduces ESPN's exact row order (e.g. `QB` before `RB` before `WR`) without needing a hard-coded position ordering. |
| `pos_abb` | The row label (`QB`, `LT`, `WLB`, `PK`, etc.) — display as-is. |
| `pos_rank` | Column index — sort ascending, 1 = leftmost (Starter). |
| `player_name` | The cell content at `(pos_abb row, pos_rank column)`. |

**Construction steps:**

1. Start from the same pinned, max-`dt`-per-team snapshot required by the
   Pinning rule above — the display table must be built from the identical
   snapshot the scoring pipeline reads, so the two can never disagree.
2. Group that team's rows by `pos_grp`.
3. Order the three groups as Offense, Defense, Special Teams. Classify each
   team's `pos_grp` value by pattern, not by matching a fixed list of exact
   names (checked across all 32 teams' current `pos_grp` values):
   - Literal `"Special Teams"` → **Special Teams**.
   - Ends in `" D"` (e.g. `"Base 4-3 D"`, `"Base 3-4 D"`) → **Defense**.
   - Everything else — an offensive personnel grouping (e.g. `"3WR 1TE"`,
     `"2WR 2TE"`) → **Offense**.
   Never hard-code a specific scheme string like `"Base 3-4 D"` as *the*
   defensive label — a team can run a different front, and the personnel
   grouping for offense varies by team and can change within a season.
4. Within each group, sort rows by `pos_slot` ascending.
5. Within each row, sort by `pos_rank` ascending and place each player in
   that rank's column.
6. Leave a cell blank if no player is listed at that `(pos_abb, pos_rank)` —
   do not collapse or reflow columns; a gap is real information (e.g. a team
   carrying only two rostered players at a slot).

One table per team, three sections stacked in that table, matching one
ESPN team depth-chart page per team. This is a **presentation concern only**
and is independent of the scoring tables below — the same `pos_rank` value
feeds both, but building this table is not a substitute for, and should never
be conflated with, the RB/WR/TE scoring lookups that follow.

---

## Injury Marks

Every player cell in the depth chart table must carry an injury mark when one
applies — matching how ESPN's own depth chart page marks players (e.g. a
`Q` next to a questionable starter). This uses the exact same abbreviation
scheme already defined in `injury_status.md` in this folder — reuse those four
letters verbatim rather than inventing a second scheme:

| Mark | Meaning | Rendered in the depth chart? |
|---|---|---|
| `O` | Out | Yes — **and** triggers demotion (see below) |
| `D` | Doubtful | Yes — mark only, no demotion |
| `Q` | Questionable | Yes — mark only, no demotion |
| `P` | Probable | **Never.** `report_status` can still return `"Probable"` from the data, but it is deliberately suppressed here — no mark, no demotion, the player is displayed exactly as if uninjured. |

**Yes, `nflreadpy` has this: `nflreadpy.load_injuries(seasons=[SEASON])`.**
Confirmed live for the 2026 season. Relevant fields:

| Field | Role |
|---|---|
| `gsis_id`, `team` | Join key back to the depth chart's `gsis_id`/`team`. |
| `week` | The injury report's week — filter to the **latest available week**, same "most recent published state" principle as the depth chart's own `dt` pinning. |
| `report_status` | **This is the mark's source**, filtered to `Out` / `Doubtful` / `Questionable` only — `Probable` is read but never surfaced (see table above); `Note` is not a game-status designation and is never surfaced either. `null` means the player was not on that week's injury report at all, or was on it but cleared with no final designation — **no mark** in either case. |
| `report_primary_injury` / `report_secondary_injury` | Body part (e.g. `"Knee"`, `"Achilles"`) — not needed for the mark itself, but available if a fuller injury note is ever wanted alongside it. |
| `practice_status` | Day-by-day practice participation (`Full Participation in Practice`, `Limited Participation in Practice`, `Did Not Participate In Practice`, plus a distinct `Out (Definitely Will Not Play)` value). This is the **leading indicator through the week**, but `report_status` is the field that drives the displayed mark — `practice_status` alone, without an eventual qualifying `report_status`, is not sufficient to mark a player. |

**Construction:** for each player placed in the depth chart table (Depth Chart
Table Format section above), look up their `(gsis_id, team)` in that week's
`load_injuries` rows. If a row exists and `report_status` is `Out`,
`Doubtful`, or `Questionable`, append the corresponding one-letter mark
immediately after the player's name in that cell (e.g. `Josh Sweat (Q)`). If
`report_status` is `Probable`, `null`, or `Note`, or no row exists at all,
render the name with no mark.

### Depth chart effect: mark-only vs. demotion

Not every mark changes the chart's ordering. There are exactly two outcomes:

- **`Q` or `D` → mark only, no reordering.** The player stays in their
  currently pinned `pos_rank` slot exactly as published. The mark is purely
  informational at this level — questionable and doubtful players still start
  where the depth chart says they start.
- **`O`, or anything more severe than `O` (the IR/PUP/NFI roster designations,
  once/if a reliable source for them is confirmed — see below) → demotion.**
  The player is removed from their current `pos_rank` slot and placed at the
  **absolute bottom** of that position's pecking order at that `pos_abb` —
  below every other player currently listed there, regardless of how low
  their published rank already was. Every player who was ranked below the
  demoted player **in the original, published depth chart** moves up exactly
  one slot, in exactly the order the original chart already had them in. This
  is a pure removal-and-close-the-gap operation — it is **not** a re-sort by
  any other criteria (usage, recency, etc.), and the player who was next in
  line for that vacated slot is, by definition, whoever the original chart
  had directly below the demoted player.

  Example: a published `WR1`/`WR2`/`WR3`/`WR4` order where `WR1` is marked
  `O`. Result: `WR2` becomes the effective `WR1`, `WR3` becomes the effective
  `WR2`, `WR4` becomes the effective `WR3`, and the originally-`O`-marked
  player becomes the effective `WR4` (bottom of the group) — still displayed
  with their `O` mark, just relocated to the bottom row for that position.

This produces an **effective rank**, distinct from the raw published
`pos_rank`. This is the same mechanic this document already gestures at
elsewhere without spelling out — "TE1 unavailable and the TE2 is promoted to
effective TE1" (TE Picker) and the QB gate's "effective-start promotion" both
describe special cases of exactly this rule. **This section is the general
algorithm behind both.** Consequently: **The Scoring Tables** below, and
every consumer listed under **Consumers**, must score against the *effective*
rank, not the raw published one — an `O`-marked player must never score as
if they were still the starter just because their `pos_rank` field hasn't
been rewritten.

### Front-end requirement

**If a front end is ever built on top of this data, the injury mark must be
rendered in red, immediately next to the player's name, wherever a mark
applies** (`O`, `D`, or `Q` — never `P`, which is never shown at all). This
applies uniformly whether or not the mark also triggers a demotion — a
merely-marked (`Q`/`D`) player in their original slot gets the same red
treatment as a demoted (`O`) player now sitting at the bottom of the group.

**Roster designations (IR / PUP / NFI) are not covered by `load_injuries`.**
Those are longer-term reserve-list statuses (see `injury_status.md`), and
`load_injuries`'s `report_status` only carries the three weekly game-status
values that actually get surfaced above (`Out`/`Doubtful`/`Questionable`).
`load_rosters()` has a `status` field (`ACT`, `RES`, `CUT`, `DEV`, `INA`,
`EXE`, `RET`) and a finer `status_description_abbr` field (NFL transaction
codes like `R01`, `R48`), but this session did not verify a reliable
code-to-label mapping from those codes to `IR` vs. `PUP` vs. `NFI`
specifically — **do not assume `status == "RES"` means `IR`.** Until that
mapping is confirmed, treat IR/PUP/NFI marking (and therefore the "anything
more severe than `O`" half of the demotion rule above) as an open item:
either resolve the official transaction-code mapping before relying on it, or
handle qualifying players through `config/committee_overrides.yaml` (already
established elsewhere in this document as the manual-override mechanism) on a
case-by-case basis. The `O` half of the demotion rule is fully specified and
usable today regardless.

---

## The Scoring Tables

**Every lookup below reads the effective rank (post injury-demotion, per the
Injury Marks section above), never the raw published `pos_rank`.** An
`O`-marked RB1 must score as whatever he becomes after demotion (RB-bottom,
i.e. 0.00), not as RB1 — the demotion rule exists specifically so this table
never has to special-case injuries itself.

`pos_rank` scoring applies to **RB, WR, and TE only**. It does not apply to QB,
K, or D/ST — QB uses a binary gate, and K and D/ST have no depth-based factor.

### RB

| Depth | Score |
|---|---|
| RB1 | **1.00** |
| RB2 | **0.30** |
| RB3+ | **0.00** |
| Not on depth chart | **0.00** |

The RB1→RB2 drop of 0.70 is the steepest in the system, and deliberately so. The
RB1/RB2 gap is a cliff, not a slope: lead backs get goal-line work, third-down
work, and the bulk of the carries, while an RB2 is largely waiting for an
injury.

### WR

| Depth | Score |
|---|---|
| WR1 | **1.00** |
| WR2 | **0.60** |
| WR3 | **0.25** |
| WR4+ | **0.00** |
| Not on depth chart | **0.00** |

Shallower drop-off than RB. Three-receiver sets are standard, so a WR2 and even
a WR3 hold real, recurring roles rather than sitting behind one player.

### TE

| Depth | Score |
|---|---|
| TE1 | **1.00** |
| TE2+ | **0.00** |
| Not on depth chart | **0.00** |

Effectively binary, which matches how the TE picker already treats the position.
See "TE and the binary gate" below.

### Unspecified cases

Two cases were not in the original specification and are resolved here:

- **RB3 and below → 0.00.** Consistent with WR4+ and TE2+ both scoring 0.00 —
  once a player is outside the meaningful rotation, depth position carries no
  positive signal.
- **No depth chart entry → 0.00**, with a `no_depth_entry` flag on the output.
  An unlisted player is treated as outside the rotation, but the flag makes it
  visible that the score came from absence rather than from a low rank. This
  matters because a missing entry can also mean a data gap rather than a real
  demotion.

---

## The Blending Schedule

`pos_rank` occupies the **prior/early component** of the existing early-season
blend. It replaces prior-season usage data in that slot.

| Week | pos_rank weight | Current usage weight |
|---|---|---|
| **1** | 100% | 0% |
| **2** | 75% | 25% |
| **3** | 50% | 50% |
| **4** | 25% | 75% |
| **5+** | **0%** | **100%** |

```
depth_score = (w_posrank × posrank_score) + (w_usage × usage_score)
```

Both terms are scores on [0.0, 1.0], so the result is too.

**From Week 5 `pos_rank` has no effect on scoring at all.** It continues to be
read for role identification — QB1/TE1 gates, starter identification for injury
unit counts — but contributes nothing to any weighted factor.

### Why this is a score-level blend

The data pipeline's non-negotiable #5 says *blend rates, then rank once — never
average ranks*. That rule guards against averaging **ordinals**, where the
arithmetic is meaningless: the midpoint of rank 1 and rank 3 is not "rank 2's
worth of value."

This blend does not violate it. `pos_rank` is converted to a **cardinal score on
[0.0, 1.0]** through the lookup tables above *before* any arithmetic happens.
Averaging two cardinal scores on the same scale is well-defined. What is
forbidden is averaging the raw ranks themselves — which this never does.

Rule #5 has been reworded accordingly: blend rates or scores, never raw ordinal
ranks.

---

## Consumers

### RB Picker — Step 3, DepthChart_Score, 30%

The heaviest single factor in any position model.

| Component | Weeks 1–4 | Week 5+ |
|---|---|---|
| Early | `pos_rank` score (1.00 / 0.30 / 0.00) | — |
| Usage | Snap share tier | Snap share tier, 100% |

Snap share tiers (unchanged):

| Snap Share | Score |
|---|---|
| 60%+ | 1.00 |
| 50–60% | 0.80 |
| 30–50% | 0.20 |
| <30% | 0.10 |
| Inactive | 0.00 |

**Prior-season snap share is retired from this factor.** The Weeks 10–18
prior-season rule no longer applies to RB Step 3 — `pos_rank` occupies that slot
now. Prior-season data remains in use elsewhere, notably player calibre.

### WR Picker — Step 3, DepthChart_Score, 20%

| Component | Weeks 1–4 | Week 5+ |
|---|---|---|
| Early | `pos_rank` score (1.00 / 0.60 / 0.25 / 0.00) | — |
| Usage | Target-share-derived role score | Target-share role, 100% |

**Both sources map to the same scale.** The target-share role table already
scores WR1 = 1.00, WR2 = 0.60, WR3 = 0.25, WR4+ = 0.00 — identical to the
`pos_rank` table. Only the *source* of the role changes across the season:
published depth chart early, realized target share later.

This makes the WR blend unusually clean — the two components are the same
measure derived two ways, so the transition introduces no scale discontinuity.

### FLEX Picker — Step 2, Opportunity_Score, 40%

The heaviest factor anywhere in the system.

The `pos_rank` lookup **replaces** the previous Opportunity_Score table for the
early component. That table is not deleted — it moves to the usage slot.

| Component | Weeks 1–4 | Week 5+ |
|---|---|---|
| Early | `pos_rank` score, all positions | — |
| Usage | Previous Opportunity_Score table | Same, 100% |

**Early component — `pos_rank`, cross-position:**

| Depth | Score |
|---|---|
| RB1 | 1.00 |
| WR1 | 1.00 |
| TE1 | 1.00 |
| WR2 | 0.60 |
| RB2 | 0.30 |
| WR3 | 0.25 |
| TE2+ / RB3+ / WR4+ | 0.00 |

**Usage component (Week 5+) — unchanged from the existing table:**

| Position | Situation | Score |
|---|---|---|
| RB | Workhorse (60%+ snap share) | 1.00 |
| WR | WR1 on team | 1.00 |
| TE | TE1 with injured WRs | 1.00 |
| RB | Lead in soft committee (50–60%) | 0.80 |
| TE | TE1 with healthy WRs | 0.70 |
| WR | WR2 on team | 0.65 |
| RB | 1B in committee (30–50%) | 0.40 |
| WR | WR3 on team | 0.30 |
| RB | Backup (<30%) | 0.10 |

Note the two tables differ for TE: `pos_rank` scores TE1 at a flat 1.00, while
the usage table splits it into 1.00 (injured WRs) and 0.70 (healthy WRs). That
is intentional — WR health is a live in-season condition that a preseason depth
chart cannot express.

### TE Picker — the gate, unchanged

The TE picker has **no weighted depth factor**. Depth is a binary gate: TE1
proceeds to scoring, TE2 or lower is eliminated, unless the TE1 is unavailable
and the TE2 is promoted to effective TE1.

The TE1 = 1.00 / TE2 = 0.00 values in this document **confirm that gate rather
than replacing it**. A TE2 scoring 0.00 on depth is functionally identical to
being eliminated, and the gate is retained because it short-circuits scoring
entirely rather than computing six factors for a player who cannot start.

Where TE scores actually matter is the FLEX pool, where a bench TE competes
against RBs and WRs — and there the 1.00 / 0.00 split applies as written.

### QB, K, D/ST — not applicable

- **QB** — binary gate on `pos_rank == 1`, with effective-start promotion. No
  weighted depth factor.
- **K, D/ST** — no depth-based factor exists.

`pos_rank` is still read for these positions to identify starters (QB1 for the
gate, OL/DB/LB/DL starters for injury unit counts), but never scored.

---

## What This Change Retired

### Prior-season snap share, in RB Step 3 only

The Weeks 10–18 prior-season snap share rule no longer feeds RB Step 3.
`pos_rank` fills that slot. Rationale: a published current-season depth chart is
a better statement of a player's current role than last season's snap counts,
particularly for anyone whose situation changed.

### The committee-change 0.50 substitution

The committee change rule substituted a neutral 0.50 for the prior-season
component when a player's committee had changed — because prior-season usage
from a different team, or a different supporting cast, was misleading.

**`pos_rank` makes that substitution unnecessary for RB Step 3, WR Step 3, and
FLEX Step 2.** The reason is direct: `pos_rank` is read from the player's
**current** team's **current** depth chart. It already reflects the new
situation.

- Kenneth Walker III (SEA → KC): KC's depth chart states his role in KC. No
  Seattle data is involved, so nothing needs neutralizing.
- Ladd McConkey (LAC, Keenan Allen departed): LAC's depth chart reorganizes to
  reflect the departure. The new order is the signal.

Stacking a forced 0.50 on top would **discard good current-team data in favor of
an artificial neutral** — strictly worse.

See `lineup-picker-COMMITTEE.md` for the full retirement record. The
**denominator rule** from that document (per-game rates divide by games the
player was healthy and played) is **unaffected and remains in force**.

### One residual risk

`pos_rank` can lag in the preseason. A late free-agent signing or a post-cuts
depth chart may not yet reflect reality when Week 1 scores are computed.

`config/committee_overrides.yaml` is retained as the escape hatch for this, but
its meaning changes: it no longer forces a 0.50 substitution. It now allows a
**manual `pos_rank` override** for a specific player, for cases where the
published depth chart is known to be wrong or stale.

```yaml
depth_overrides:
  - {name: "Example Player", team: KC, position: RB, pos_rank: 1,
     note: "Signed post-cuts; depth chart not yet updated"}
```

---

## Validation

| Check | On failure |
|---|---|
| Depth charts pinned to max `dt` per team before any read | **Halt** — unpinned reads can resolve stale ranks |
| Every rostered RB/WR/TE resolves to a `pos_rank` or is explicitly flagged `no_depth_entry` | Warn and score 0.00; never silently omit |
| `pos_rank` scores are in [0.0, 1.0] | **Halt** |
| `pos_rank` contributes 0% from Week 5 onward | Assert in tests — a leak past Week 4 silently distorts a 20–40% factor |
| Depth override names resolve to `gsis_id` | **Halt**, naming the entry |

---

## Required Tests

- A Week 1 RB1 scores exactly 1.00 on DepthChart_Score; an RB2 scores exactly 0.30
- A Week 1 WR2 scores exactly 0.60; a WR3 scores 0.25
- Week 3 blend: an RB1 with a 35% current snap share scores
  `(0.50 × 1.00) + (0.50 × 0.20) = 0.60`
- From Week 5, two players with identical usage score identically regardless of
  `pos_rank`
- A player absent from the depth chart scores 0.00 and carries `no_depth_entry`
- RB3 scores 0.00, not an interpolation between RB2 and nothing
- FLEX: a Week 1 RB2 (0.30) loses the FLEX slot to a Week 1 WR2 (0.60), all else
  equal
- Depth charts are pinned: a player whose rank changed mid-season resolves to
  the latest `dt`, not an earlier one

---

## Key Principle

Depth chart position is the best available statement of a team's **intent**, and
usage is the best available statement of **reality**. The model trusts intent
when reality doesn't exist yet, and abandons it the moment reality does.

That transition is complete by Week 5. After that, `pos_rank` identifies who the
starters are for gating and injury counting, and contributes nothing to any
score.
