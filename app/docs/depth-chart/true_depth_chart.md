# True Depth Chart

## Context

A **published depth chart** (see `lineup-picker-depth-chart.md`, V1) is a
team's own stated intent — ESPN's estimate of who they'd start, which can lag
reality, reflect politics/experience over production, or simply not have
caught up with a hot rookie yet.

A **true depth chart** is a different object: the same visual shape as the
published depth chart, but with WR, TE, and RB pecking order **re-derived from
who is actually earning the opportunities**, using the share metrics already
defined in `opportunity_share.md` (`waiver-wire/V1`). Everywhere the data
supports it, usage overrides stated intent. This is the natural companion to
`lineup-picker-depth-chart.md`'s own "usage beats intent as soon as usage
exists" principle (see that doc's Key Principle) — the true depth chart is
what that principle looks like applied to the chart itself, not just to
scoring.

**This document specifies how to construct that object. It does not build an
artifact or a front end** — only what a front end would need to render one
correctly, if and when one is built.

**Built entirely on top of two existing documents, not a new data pipeline:**

- `lineup-picker-depth-chart.md` (V1) — supplies the table skeleton (three
  sections, row/column grid per team) and the injury-mark/demotion logic,
  reused here verbatim.
- `opportunity_share.md` (`waiver-wire/V1`) — supplies the share metrics.
  Specifically the **"All" (season-to-date) view**: `target_share_pct` for
  WR/TE, `rush_share_pct` for RB, each averaged only over the games that
  player actually qualified in (per that doc's Step 7 — a missed week is
  excluded from the average, never counted as 0%). A single week's share is
  exactly the kind of noise `opportunity_share.md` itself warns about
  (Notes/Known Limitations); a *true* pecking order should reflect an
  established role, not one game's script. Early in a season, when only one
  week is complete, "All" and "Week 1" are numerically identical — that's
  expected, not a bug (see `opportunity_share.md`'s own Week-1 convergence
  note).
- **RZ Target Share / RZ Rush Share are explicitly out of scope for this
  version.** Pecking order here is driven only by season-wide Target Share
  (WR/TE) and Rush Share (RB) — the two metrics named directly. A red-zone
  weighted version is a plausible future extension, not attempted here.

---

## Step 1 — Start from the published grid

For a given team, take the published depth chart's WR, TE, and RB rows
exactly as `lineup-picker-depth-chart.md`'s Depth Chart Table Format section
already constructs them: some number of rows at `pos_abb == "WR"` (one row
per personnel slot — e.g. 3 rows for a team in "3WR 1TE" personnel), some
number at `"TE"`, some number at `"RB"`, each row with however many depth
(`pos_rank`) columns that team's published chart actually has. **The true
depth chart reuses this exact grid shape — same row count, same column
depth, per team, per position** — only the occupant of each cell changes.
Everything outside WR/TE/RB (QB, OL, defense, special teams, and `FB`, which
`opportunity_share.md`'s RB population explicitly excludes — see its Step
5/3c: population is `position == "RB"` only) is carried over from the
published chart completely unchanged. A true depth chart is a partial
reordering, not a full team rebuild.

## Step 2 — Pool the candidates per team, per position

For each team, build three separate candidate pools from `opportunity_share.md`'s
"All" view:

- **WR pool** = that team's rows in the Target Share table (All view) where
  `position == "WR"`.
- **TE pool** = same table, `position == "TE"`.
- **RB pool** = that team's rows in the Rush Share table (All view), where
  `position == "RB"` (already the table's own population — no extra filter
  needed).

Note the WR/TE split matters here in a way it doesn't in
`opportunity_share.md` itself: that doc's Target Share table is one combined
pass-catcher list. Split it by `position` before ranking — a TE's target
share does not compete against a WR's for WR pecking order, and vice versa.
A running back who catches passes (shows up in the Target Share table with
`position == "RB"`) does **not** enter the WR pool either — his receiving
usage is real, but it doesn't make him a wide receiver on the depth chart.

## Step 3 — Rank each pool

Within each pool, sort descending by the relevant share:

- WR pool → `target_share_pct` (All view) descending.
- TE pool → `target_share_pct` (All view) descending.
- RB pool → `rush_share_pct` (All view) descending.

**Tie-break, in order:** (1) higher raw `Qty` (the summed season-to-date
count behind the share — `targets` for WR/TE, `carries` for RB) wins; (2) if
still tied, fall back to the player's published `pos_rank` (lower wins) to
keep the ordering stable rather than arbitrary.

**Players with no qualifying data this season** (rostered at that position
on the published chart, but zero recorded targets/carries all year — a
healthy scratch, a rookie who hasn't debuted, a deep practice-squad body)
are **not rankable** and go to the bottom of the pool, below every ranked
player, in their original published `pos_rank` order among themselves. This
mirrors the injury-demotion convention in V1 exactly (remove, append at the
bottom, preserve original relative order for whoever's left) — a player with
no data is not "ranked last by 0% share," they're simply unranked and placed
after everyone who has a real number.

## Step 4 — Redistribute the ranked pool into the grid

Fill the position's grid **column-major**, not row-major: the top `N` ranked
players (where `N` = the number of rows for that position, e.g. 3 for a
3-WR-personnel team) fill column 1 (the "starters" column) across all `N`
rows, the next `N` fill column 2, and so on.

**This is a deliberate choice, not an arbitrary one.** Column 1 is, by both
ESPN's convention and V1's own spec, "the players who'd start" — filling it
row-major would instead cram the top few ranked players into one row's
columns while other rows sat stocked with lower-ranked players despite
`pos_rank` = 1, which breaks the "leftmost column = who starts" semantic the
whole chart depends on. Column-major fill is what makes "true WR1, true WR2,
true WR3" a coherent, orderable statement at all.

**Grid overflow:** if the ranked pool (real data + the unranked tail) is
larger than the published grid's total cell capacity for that position, add
however many extra column(s) are needed rather than dropping a player — a
true depth chart must never omit someone who has recorded real usage. Note
this as a shape deviation from the published chart when it happens; it
should be rare, since published charts are typically already deep enough to
cover the active roster.

## Step 5 — Apply injury demotion (unchanged from V1)

Once the true ordering is built, apply `lineup-picker-depth-chart.md`'s
**Injury Marks** section exactly as written, with no modification:

- `Q` / `D` → mark only (red, see Step 6), player stays in their true-ranked
  slot.
- `P` → never marked, never affects position.
- `O` (and, once available, anything more severe — IR/PUP/NFI, see V1's open
  item on that source) → demoted to the absolute bottom of that position
  group, with everyone originally below them — in the **true** order this
  time, not the published order — shifting up one slot in the same relative
  order they already had.

Injuries override pecking order **on top of** the opportunity-share ranking,
the same way they override the published ranking in V1. The mechanism is
identical; only the base ordering it's applied to has changed.

## Step 6 — Movement indicators (true vs. published)

For every WR/TE/RB on a team, compute one comparable number from each chart:

- **`published_flat_rank`** — flatten the published grid for that position
  column-major (all `pos_rank == 1` players across the position's rows, in
  `pos_slot` order, are ranks 1..N; all `pos_rank == 2` players are ranks
  N+1..2N; and so on). This is "if you named the team's WR1, WR2, WR3... in
  order, where does this player fall," read straight off the published
  chart.
- **`true_flat_rank`** — the same flattening applied to the true chart built
  in Steps 2–5 (which, by construction, already fills column-major, so this
  is just each player's position in that fill order).

Compare them per player, **within their own position group only** (WR
compared to WR, never to RB):

- `true_flat_rank < published_flat_rank` (a numerically better/lower rank) →
  **moved up.**
- `true_flat_rank > published_flat_rank` → **moved down.**
- Equal → no change, no indicator.

**Front-end rendering, if a front end is ever built on this document** (none
is built here — this is the specification for one):

| Direction | Cell background | Marker next to player name |
|---|---|---|
| Moved up (true rank better than published) | Pale green | Solid green up arrow (▲) |
| Moved down (true rank worse than published) | Pale red | Solid red down arrow (▼) |
| No change | Default/unstyled | None |

This is deliberately the same visual language as a leaderboard-movement
indicator (sports standings, stock tickers): a muted background tone signals
*direction* at a glance across the whole chart, and a solid, saturated arrow
of the same color gives the same signal explicitly next to the name for
anyone scanning individual rows rather than the whole table. The background
and the arrow always agree in color/direction — never a green cell with a
red arrow or vice versa.

**Interaction with injury marks (Step 5):** the movement indicator and the
injury mark are independent and both render together when both apply — e.g.
a player who moved up two true-WR slots on usage but is now questionable
shows the pale-green cell / green up-arrow *and* the red `Q` mark next to
their name. They answer different questions (has this player's role changed
vs. is this player healthy) and neither should suppress the other.

**Edge cases for the comparison itself:**

- A player who is unranked in the true pool (Step 3's no-data tail) but was
  ranked in the published chart will, in almost all cases, show as moved
  down — there is no real usage to justify their published slot.
- A player with real share data who does not appear on the published
  chart's WR/TE/RB rows for that team at all (a genuine roster/data mismatch
  — e.g. a very recent trade or elevation the published chart hasn't caught
  up to) is out of scope for this comparison; treating that case is a data-
  quality problem, not a movement-indicator problem, and isn't handled here.

---

## Notes / Known Limitations

- This entire document inherits `opportunity_share.md`'s own limitations on
  the underlying shares (single-season sample size, the mean-of-weekly-%
  averaging convention, the games-played denominator rule) — nothing here
  resolves those, it just consumes the "All" view as-is.
- RZ Target Share / RZ Rush Share are excluded from pecking order for now
  (see Context). A player who is the true WR1 by overall target share but a
  non-factor in the red zone will still rank WR1 here — that's a known,
  accepted simplification of this version, not an oversight.
- FB and every non-WR/TE/RB row is untouched by this document and simply
  mirrors the published chart — there is no opportunity-share analog for
  those positions in `opportunity_share.md` to re-rank them by.
- The "All" view choice (season-to-date average, vs. a single week) is a
  judgment call made in this document, not dictated verbatim anywhere else —
  worth revisiting if a use case ever wants a true depth chart that reacts
  to one hot/cold week rather than a season-long role.
- Grid overflow (Step 4) and the no-data tail (Step 3) both need to be
  handled explicitly by any implementation — silently truncating either one
  would misrepresent a player's actual standing.

---

## Appendix — Calibration Reference: WR / TE / RB Share Thresholds (2020–2025)

Supporting context for *interpreting* a true depth chart once built — e.g.
"this player is technically this team's true WR1 by share, but at 18% it's a
weak one." Not part of the construction steps above.

Computed from `nflreadpy` weekly player stats, 2020–2025 regular seasons.
Each player's season target/carry share is calculated against their own
team's totals in the weeks they actually played (min. 8 games to qualify),
then ranked within their team-season. This gives 192 team-seasons per
position (32 teams x 6 years) to build real distributions.

### WR1 — target share (n=192 team-leading WRs)

| Percentile | Target share |
|---|---|
| 10th | 19.4% |
| 25th | 21.9% |
| 50th (median) | 24.7% |
| 75th | 27.9% |
| 90th | 30.1% |
| 95th | 31.7% |
| Max | 35.8% |

**A "true WR1"** — the guy the offense is built around, not just whoever
happens to lead a muddled room — clears roughly **24–25%+ target share**,
and that's the median outcome for a team's actual leading receiver. Below
~20% usually means the passing game is spread out or RB/TE-centric and
there isn't a real alpha.

**Elite/alpha WR1** (focal point of the whole passing offense):
**~29–30%+**. Calibration: Ja'Marr Chase 2025 (32.2%), Tyreek Hill 2023
(32.7%), Davante Adams' Raiders prime (32–33%), A.J. Brown 2024 (34.3%).
Most "good WR1" seasons (Puka Nacua, CeeDee Lamb, Amon-Ra St. Brown) live
in the 27–30% band.

### TE1 — target share (n=192)

| Percentile | Target share |
|---|---|
| 10th | 9.9% |
| 25th | 12.6% |
| 50th (median) | 15.6% |
| 75th | 19.3% |
| 90th | 22.7% |
| 95th | 24.7% |
| Max | 29.3% |

**A "strong TE1"** (weekly fantasy relevance, real receiving role) sits at
**~19–20%+ share** — that's George Kittle's strong years (20–24%), Mark
Andrews' peak (25–28%), typical Travis Kelce (22–25%).

**"Main target" tier — Bowers/McBride territory**: **~23–25%+**, with the
real ceiling around **28–29%**. Trey McBride's 2024 season (29.3%) is
literally the single highest full-season TE target share in this entire
6-year dataset — genuinely the WR1-of-the-team-in-everything-but-name
usage level. Brock Bowers 2024 (25.8%) is right behind it. Below ~13%
(25th percentile), a TE is a checkdown/blocking option, not a real target
hog.

### RB1 — carry share (n=192)

| Percentile | Carry share |
|---|---|
| 10th | 40.3% |
| 25th | 45.6% |
| 50th (median) | 52.9% |
| 75th | 59.0% |
| 90th | 66.5% |
| 95th | 73.6% |
| Max | 84.2% |

**A "true lead RB"** clears **~55–60%+ carry share** — that's the
median-to-75th-percentile zone and matches names like Saquon Barkley,
Jonathan Taylor, Josh Jacobs in their typical seasons (57–65%).

**True workhorse/bellcow** (minimal committee): **~65–70%+**. The extreme
ceiling examples — Josh Jacobs 2022 (79.4%), Jonathan Taylor 2025
(73.1%), Derrick Henry 2021/2022 (75–84%) — also come with a **40+
percentage-point gap** to the RB2, i.e., the backup is a token
change-of-pace/injury-fill player, not a real co-starter.

### RB committee (1a/1b) split

The gap between each team's RB1 and RB2 share was computed across all
team-seasons; median gap is 24.6 points, 25th percentile is 12.5 points.

**A genuine 1a/1b committee** is roughly a **≤10–15 point gap**, with
*both* backs carrying meaningful volume (each in the 35–50% range) rather
than one guy dominating and a scraps-eater behind him. Real examples from
the data, essentially even splits:

| Season | Team | RB1 | Share | RB2 | Share |
|---|---|---|---|---|---|
| 2020 | LAC | Austin Ekeler | 41.7% | Kalen Ballage | 41.7% |
| 2021 | LAR | Sony Michel | 49.5% | Darrell Henderson | 49.5% |
| 2021 | DET | Jamaal Williams | 48.6% | D'Andre Swift | 48.4% |
| 2023 | CHI | D'Onta Foreman | 36.3% | Khalil Herbert | 36.1% |
| 2024 | JAX | Travis Etienne | 42.6% | Tank Bigsby | 42.3% |
| 2025 | KC | Kareem Hunt | 37.9% | Isiah Pacheco | 35.5% |

Contrast that with a true bellcow situation like Josh Jacobs 2022 (79.4%
vs. 5.5%, a 74-point gap) — same "RB1" label, completely different
reality for roster construction and start/sit decisions.
