# Lineup Picker — Committee Change Rule

## Status: RETIRED (scoring), denominator rule still in force

**The 0.50 neutral substitution described in this document is no longer part of
the model.** It was superseded by `pos_rank` depth chart scoring — see
`lineup-picker-DEPTH-CHART.md`.

### Why it was retired

The rule substituted a neutral 0.50 for the prior-season component when a
player's committee had changed, because prior-season usage earned on a different
team or alongside a different cast is misleading.

`pos_rank` solves the same problem more directly. It reads from the player's
**current** team's **current** depth chart, so it already reflects the new
situation:

- Kenneth Walker III (SEA → KC) — Kansas City's depth chart states his role in
  Kansas City. No Seattle data is involved, so there is nothing to neutralize.
- Ladd McConkey (LAC, Keenan Allen departed) — LAC's depth chart reorganizes to
  reflect the departure. The new order *is* the signal.

Stacking a forced 0.50 on top of `pos_rank` would discard good current-team data
in favour of an artificial neutral. Strictly worse.

### What survives

| Element | Status |
|---|---|
| **Per-game denominator rule** (games healthy and played) | **In force** — see below, and tech spec §5.10.2 |
| Committee definitions (RB1/RB2; WR1/WR2/TE1) | Still referenced by the RB and WR teammate-injury factors |
| `config/committee_overrides.yaml` | **Repurposed** as a manual `pos_rank` override for stale preseason depth charts |
| 0.50 neutral substitution | **Retired** |
| Automatic committee-change detection | **Retired** — no longer computed |

Recorded as deviation D16 (retired) in the tech spec, superseded by D19.

The original rule follows, preserved so the reasoning stays legible.

---

## Original rule — Context

This file defines the **committee change rule**, which governs how the Lineup
Picker handles opportunity-based factors for a player whose situation changed
between seasons.

It exists because of a specific failure mode in the early-season blending
schedule. Weeks 1–4 lean on prior-season snap share and target share, on the
reasonable assumption that last year's role predicts this year's role. That
assumption breaks completely when the player's surrounding cast has changed.

**Kenneth Walker III** carried a known snap share in Seattle's backfield. He is
now in Kansas City. His 2025 snap share tells us nothing about how KC will
divide carries in 2026 — different coach, different scheme, different backs
competing for the same touches.

**Ladd McConkey** did not change teams, but Keenan Allen left the Chargers for
Indianapolis. McConkey's target share from last season was earned in a room
that no longer exists. The vacated targets may flow to him, or to someone else,
or the offense may change shape entirely.

**RJ Harvey** is the control case. Same team, same backfield, same competition.
His prior-season snap share is exactly the signal the blending schedule was
designed to use.

The rule: **when the committee has changed, substitute a neutral 0.5 for the
prior-season component instead of using data earned under different
conditions.** We don't know how the mouths will be fed, so the model should say
so rather than pretend last year's answer still applies.

---

## Committee Definitions

A player's **committee** is the set of teammates competing for the same
opportunity pool.

| Position | Committee | Size |
|---|---|---|
| **RB** | RB1, RB2 | 2 |
| **WR** | WR1, WR2, TE1 | 3 |

**RB committee excludes RB3 and below.** Third-string backs do not meaningfully
compete for the lead role's touches, and including them would make the flag fire
on routine practice-squad churn.

**WR committee includes the TE.** Receivers and tight ends compete for the same
targets — this is the same premise behind the TE picker's 25% WR-injury factor
and the WR picker's teammate-injury factor counting elite TEs as primary
competitors. A team that swaps its starting tight end has changed its receivers'
target environment.

**The player himself is a member of his own committee.** Sets are compared
unordered, so an internal promotion with no personnel change — a back moving
from RB2 to RB1 while the same two players occupy the room — does **not** trigger
the flag. The competition is unchanged even though the pecking order isn't.

---

## The Trigger

The flag fires when **one or more** of the following is true:

| Condition | Example |
|---|---|
| Player changed teams between seasons | Kenneth Walker III, SEA → KC |
| Any committee member departed | Keenan Allen leaving LAC, affecting Ladd McConkey |
| Any committee member is newly arrived | A free-agent WR1 signing, affecting the incumbent WR2 |
| Player has no prior-season data (rookie) | Any 2026 rookie |

The flag does **not** fire for:

| Condition | Why |
|---|---|
| Internal role change, same personnel | Same competition, different order |
| RB3+ or WR4+ churn | Outside the committee definition |
| In-season injuries to committee members | Handled live by the TeammateInjury factors, not this rule |
| Coaching or scheme change with no personnel change | Real, but not observable through roster comparison — out of scope for V1 |

**Rookies are included deliberately.** A rookie has no prior-season component at
all, so without this rule his Week 1 depth score would be built on missing or
zero data. A neutral 0.5 is both more accurate and consistent with the rule's
logic — his situation is, by definition, entirely new.

---

## The Substitution

**A flagged player's prior-season component is replaced with a score of 0.5,
not a share of 50%.**

This distinction is the single most important implementation detail in this
document.

| Interpretation | RB result | Correct? |
|---|---|---|
| Snap **share** = 0.50 → tier lookup → 0.80 | Strong score, near "lead back in soft committee" | **No** |
| Depth **score** = 0.50 directly | Neutral midpoint of the 0–1 scale | **Yes** |

Substituting at the rate level and then running the tier table would produce
0.80 for an RB — a confident, favorable score. That is the opposite of the
rule's intent. The point is to express *uncertainty*, so the substitution
happens at the score level, where 0.5 is the true midpoint.

### Effect on the blending schedule

For an unflagged player, the existing schedule blends **rates**, then tiers once:

```
blended_rate  = (w_prior × prior_rate) + (w_current × current_rate)
depth_score   = tier(blended_rate)
```

For a flagged player, there is no usable prior rate, so the blend happens at
**score** level:

```
prior_component   = 0.50                        # neutral, fixed
current_component = tier(current_rate)
depth_score       = (w_prior × 0.50) + (w_current × current_component)
```

Weights are unchanged from the standard schedule:

| Week | Prior weight | Current weight | Flagged player's depth score |
|---|---|---|---|
| 1 | 100% | 0% | **exactly 0.50** |
| 2 | 75% | 25% | 0.375 + 0.25 × tier(current) |
| 3 | 50% | 50% | 0.250 + 0.50 × tier(current) |
| 4 | 25% | 75% | 0.125 + 0.75 × tier(current) |
| **5+** | 0% | 100% | tier(current) — **flag has no effect** |

**The flag stops mattering entirely from Week 5.** By then the model runs on
current-season data only, which reflects the new situation directly. This rule
is a Weeks 1–4 correction, nothing more.

### Documented exception to a standing rule

The data pipeline's non-negotiable #5 states: *blend rates, then rank once —
never blend scores.* This rule is a deliberate, scoped exception. It applies
**only** when the prior-season rate has been replaced by a neutral constant,
because there is no rate left to blend. Unflagged players continue to blend
rates exactly as before.

---

## Affected Factors

| Picker | Factor | Weight | Metric |
|---|---|---|---|
| **RB** | Step 3, DepthChart_Score | 30% | Snap share |
| **WR** | Step 3, DepthChart_Score | 20% | Target share (WR1/2/3 role) |
| **FLEX** | Step 2, Opportunity_Score | 40% | Snap share (RB) or target share (WR) |

**TE is not directly affected.** The TE picker's depth chart handling is a binary
gate (TE1 or eliminate), not a share-weighted score, and its Opportunity
treatment in FLEX keys off WR health rather than target share. A TE who changed
teams still triggers the flag for his **new teammates'** WR committee — he is a
committee member even though the rule doesn't score him.

**Player calibre is not affected.** Calibre measures how good the player is, not
how much opportunity he'll get. A back who was excellent in Seattle is still an
excellent back in Kansas City. The existing `calibre_prior_season` and
`calibre_unknown` handling covers missing calibre data separately.

---

## Denominator Rule

**For every per-game rate in the system, the denominator is games the player was
healthy and actually played.**

This applies to snap share, target share, and fantasy points per game, in both
the prior-season and current-season components.

| Situation | Counted in denominator? |
|---|---|
| Played, recorded ≥1 offensive snap | **Yes** |
| Active but recorded 0 offensive snaps | **Yes** — a healthy scratch from the rotation is real signal |
| Inactive (game-day inactive list) | **No** |
| On IR / did not travel | **No** |
| Team bye week | **No** |
| Suspended | **No** |

A missed game must be **excluded from the denominator**, never counted as a zero.
Counting it as a zero drags a workhorse back's average toward a backup's, which
is precisely backwards: missing time through injury says nothing about role when
healthy.

Worked example — a back with 70% snap share across 10 games played, who missed
7 through injury:

| Method | Result | Correct? |
|---|---|---|
| Sum ÷ 17 team games | 41.2% → "1B in committee" (0.20) | **No** |
| Sum ÷ 10 games played | 70.0% → "clear workhorse" (1.00) | **Yes** |

The difference is a 0.80 swing on the RB model's heaviest factor.

---

## Determining Committee Membership

### Prior-season committee

Derived from **actual prior-season usage**, not depth charts:

- **RB1, RB2** — top 2 by prior-season snap share on that team
- **WR1, WR2** — top 2 by prior-season target share
- **TE1** — top TE by prior-season target share

Uses the player's **prior-season team**, which may differ from his current team.

### Current committee

Before Week 1 there is no current-season usage data, so membership comes from
the **current depth chart** (`nflreadpy.load_depth_charts()`, `pos_rank`):

- **RB1, RB2** — `pos_rank` 1 and 2 at RB
- **WR1, WR2** — `pos_rank` 1 and 2 at WR
- **TE1** — `pos_rank` 1 at TE

### The known asymmetry

Prior committee comes from realized share; current committee comes from a
published depth chart. Those are different instruments, and they can disagree —
a depth chart may list an RB2 who never actually took the second-most snaps.

That asymmetry can produce **false positives**: the flag fires when nothing
really changed. A false positive is the safer error (it substitutes neutrality
for possibly-stale data), but it is still wrong, and it is why the override file
below exists.

From Week 5 the flag is inert, so the asymmetry has a four-week blast radius.

### Manual override

`config/committee_overrides.yaml`, same pattern as `data/id_overrides.json`:

```yaml
# Force the committee-change flag on or off for specific players.
# Checked BEFORE auto-derivation. Use to correct false positives or
# to capture changes the roster comparison can't see.
committee_overrides:
  - {name: "Kenneth Walker III", team: KC,  changed: true,
     note: "SEA -> KC, entirely new backfield and scheme"}
  - {name: "Ladd McConkey",      team: LAC, changed: true,
     note: "Keenan Allen departed for IND"}
  - {name: "RJ Harvey",          team: DEN, changed: false,
     note: "DEN backfield unchanged — control case"}
```

Names resolve to `gsis_id` at startup via `nflreadpy.load_players()`. An
unresolved or ambiguous name halts the run, consistent with every other static
list.

**Override is also the escape hatch for scheme change.** A team that kept every
skill player but hired a new offensive coordinator has genuinely changed how
touches get distributed, and no roster comparison will detect it. Set
`changed: true` manually with a note.

---

## Output Requirements

A flagged player must be visibly flagged, not silently adjusted.

- Every flagged player carries a `committee_changed` flag on his `ScoredPlayer`.
- Where the flag is active (Weeks 1–4), the CLI shows the substitution in the
  factor breakdown rather than a bare number:

```
  FACTOR              INPUT                                  SCORE  WEIGHT  CONTRIB
  ──────────────────────────────────────────────────────────────────────────────────
  Depth chart         committee changed (SEA->KC);            0.50    0.30    0.150
                      prior=0.50 neutral, current=n/a (wk 1)
```

- The lineup summary lists every flagged starter, so the reason a Week 1 lineup
  looks conservative is legible at a glance.

A 0.30-weight factor pinned to neutral is a large intervention. It should never
be invisible.

---

## Validation

| Check | On failure |
|---|---|
| Every override name resolves to a `gsis_id` | **Halt**, naming the entry |
| A player is not both auto-flagged and overridden to `false` without the override winning | Override always wins; log at INFO |
| Committee derivation returns the expected size (2 for RB, 3 for WR) | Warn and flag `committee_incomplete`; treat as changed |
| Flag is never applied from Week 5 onward | Assert in tests — a flag leaking past Week 4 silently neutralizes a live factor |

---

## Key Principle

Prior-season data is only useful when the conditions that produced it still
hold. The blending schedule assumes continuity; the committee change rule
detects where that assumption fails and replaces borrowed certainty with honest
neutrality.

The rule is deliberately narrow. It touches three factors, lasts four weeks,
and expires automatically. It does not attempt to guess what the new share will
be — 0.5 is not a prediction, it is an admission that the model doesn't know
yet.
