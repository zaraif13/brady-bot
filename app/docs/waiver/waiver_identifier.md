# Waiver Identifier — Tech Spec

## Context

`true_depth_chart.md` (`lineup-picker/plan/V2`) already defines, **per team**,
which WR/TE/RB players sit higher in a team's *true* pecking order (ranked by
real opportunity share) than they do on that team's *published* depth chart
(ESPN's stated intent) — that's its Step 6 movement indicator, rendered as a
green up-arrow for a player who's outproducing his nominal slot.

**This document runs that same comparison across all 32 teams at once, and
turns the result into a single, prioritized watchlist.** The idea:

- A player who is genuinely earning more usage than his published depth-chart
  slot implies is a **market inefficiency** — public depth charts (and, by
  extension, the fantasy managers who skim them instead of the underlying
  stats) are undervaluing him relative to his real role.
- An undervalued-but-productive player is exactly the profile that's **more
  likely to still be sitting unclaimed on a given league's waiver wire**,
  because the people who'd normally grab a rising player are going by the
  same stale/incomplete signal (the depth chart) that this whole `brady-bot`
  effort is built to see past.

**The process is explicitly two stages:**

1. **Identify the inefficiency** — every "moved up" WR/TE/RB, league-wide,
   ranked by how big and how real the discrepancy is. **This document fully
   specifies this stage.**
2. **Check real-world availability** — is that specific player actually a
   free agent / on waivers in a specific league (Yahoo, ESPN, Sleeper, etc.)?
   **Explicitly out of scope for this version.** No platform integration is
   built here. Step 6 below stubs out exactly where that plugs in later, so
   this document doesn't need to be re-architected when it does.

Nothing here is a new data pipeline — it composes `true_depth_chart.md` and
`lineup-picker-depth-chart.md` (both `lineup-picker/plan/`) exactly as
written, plus one clarification (Step 1) needed to make the "moved up" signal
mean what it's supposed to mean.

---

## Step 1 — Build both charts per team, with injuries applied to *both*

Follow `true_depth_chart.md` Steps 1–5 exactly as written, per team, to get:

- The **true** chart (opportunity-share ranked, with `lineup-picker-depth-chart.md`'s
  injury-demotion logic already applied on top, per `true_depth_chart.md` Step 5).
- The **published** chart, but — and this is the one clarification this
  document adds — **also with `lineup-picker-depth-chart.md`'s injury-demotion
  logic applied**, producing the same *effective* published rank that
  `lineup-picker-depth-chart.md`'s own "Scoring Tables" section already
  requires everywhere else in that document. Do **not** compare against the
  raw, un-demoted published `pos_rank`.

**Why this matters specifically for a waiver tool:** if the published side is
left raw (un-adjusted for injury), a backup who's simply next-in-line because
the guy ahead of him got hurt will show up as "moved up" in the true-vs-
published comparison — but that promotion is already public, already in the
injury report, and already reflected the instant anyone accounts for it. It
is not a market inefficiency; it's the single most obvious, already-claimed
waiver move there is. Applying the identical injury demotion to **both**
sides of the comparison makes that kind of promotion cancel out — the
injured player drops to the bottom of both charts, the backup rises in both
charts by the same amount, and the discrepancy between the two charts is
unaffected. What survives the comparison after that is only genuine usage-
vs-stated-order disagreement: the real signal this tool exists to surface.

## Step 2 — Compute flat ranks per team, per position group

For each team, using the (now injury-adjusted on both sides) charts:

- `published_flat_rank` — the effective published chart, flattened
  column-major exactly as `true_depth_chart.md` Step 6 describes.
- `true_flat_rank` — the true chart, already in column-major fill order by
  construction.

Computed **within position group only** — WR vs. WR, TE vs. TE, RB vs. RB —
never across positions, same rule as `true_depth_chart.md`.

## Step 3 — Pool every team and keep only the movers

Concatenate every team's WR/TE/RB players (all 32 teams, or however many
have published-chart and opportunity-share data available) into one league-
wide list. Keep a player only if:

```
true_flat_rank < published_flat_rank
```

i.e. a numerically better (lower) true rank than published rank — moved up,
in `true_depth_chart.md` Step 6's terms. Discard everyone else (moved down or
unchanged) — this document only ever produces a "buy" list, not a full diff.

For each surviving player, compute:

```
movement_delta = published_flat_rank - true_flat_rank
```

A positive integer — the number of slots the player has outgrown his
published billing by. Bigger = a larger disagreement between stated role and
real usage.

## Step 4 — Prioritize the league-wide watchlist

Sort the pooled "moved up" list:

1. **Primary: `movement_delta` descending.** The bigger the gap between
   nominal and true slot, the more mispriced the player is likely to be.
2. **Secondary (tiebreak, and a sanity check on primary): the driving share
   itself** — `target_share_pct` (WR/TE) or `rush_share_pct` (RB), All view,
   descending. This matters beyond breaking ties: a player who jumped from
   true-WR4 to true-WR3 while sitting at 28% target share is a much more
   real signal than one who jumped from true-WR7 to true-WR6 at 6% share —
   `movement_delta` alone can't tell those apart, and both belong on the
   list, but the second one should rank lower.

**Carry `GP` (games played, from `opportunity_share.md`'s All view) through
to the output and consider a minimum-`GP` floor before treating a mover as
actionable** (e.g. `GP >= 2` as a starting default, adjustable) — a "mover"
built on a single game's share is exactly the small-sample noise
`opportunity_share.md` itself warns about, and a one-week spike is a much
weaker waiver signal than a multi-week trend. This is a judgment call, not a
hard rule; state whatever floor is actually used alongside the output so a
reader can tell how much to trust a given entry.

## Step 5 — Watchlist output fields

One row per mover:

| Field | Source |
|---|---|
| `player`, `team`, `position` | From the true/published chart build |
| `published_slot` | e.g. `"WR3"` — human-readable form of `published_flat_rank` |
| `true_slot` | e.g. `"WR1"` — human-readable form of `true_flat_rank` |
| `movement_delta` | Step 3 |
| `driving_share_pct` | `target_share_pct` or `rush_share_pct` (All view), whichever applies to that position |
| `qty` | The raw season-to-date count behind the share (`targets` or `carries`, All view) |
| `gp` | Games played the average is built on (All view) — see Step 4's floor |
| `injury_mark` | Whatever current `O`/`D`/`Q` mark the player carries, **shown for information only** — a genuine mover can still be independently banged up; this field does not gate inclusion, since Step 1 already neutralized injury-*driven* movement at the comparison stage |

## Step 6 — Waiver availability (explicitly deferred)

**Not built in this version.** The Step 5 watchlist is a **global** list of
undervalued players — it says nothing yet about whether any given name is
actually pickupable in a specific league, since that depends entirely on who
else in that league already rostered him.

When platform integration is built, it plugs in here as a filter on top of
the Step 5 output, not a redesign of it:

1. Resolve each watchlist player's `gsis_id` to the target platform's own
   player id. `nflreadpy.load_ff_playerids()` already provides this bridge —
   confirmed to include a `yahoo_id` column alongside `gsis_id` (and
   `sleeper_id`, `espn_id`, `mfl_id`, and others), so no new ID-mapping table
   needs to be built when this step is implemented.
2. Query that league's roster/free-agent data (via whatever the platform's
   API exposes — out of scope here) for each resolved player's ownership
   status in that specific league.
3. Filter the Step 5 watchlist down to players whose status comes back
   Free Agent / Waivers (exact terminology varies by platform).

**Until step 6 exists, every name in the Step 5 output must be manually
checked against a given league's actual free-agent pool before acting on
it** — this document produces candidates, not confirmed availability.
