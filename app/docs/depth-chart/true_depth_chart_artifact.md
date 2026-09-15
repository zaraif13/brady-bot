# True Depth Chart Artifact — Build Instructions

## Context

This document specifies how to build a **single-page interactive artifact**
that displays one NFL team's depth chart at a time, selected via a team
filter, with a **toggle switch** on each team's page that flips the displayed
chart between:

- **"Depth Chart"** — the published/ESPN-sourced depth chart, exactly as
  specified in `lineup-picker-depth-chart.md` (V1, `lineup-picker/plan/V1/`).
- **"True Depth Chart"** — the same visual grid, but with WR/TE/RB pecking
  order re-derived from actual usage (target share / rush share), exactly as
  specified in `true_depth_chart.md` (V2, `lineup-picker/plan/V2/`).

Neither source document builds a front end — V1 defines how a published depth
chart table should be laid out and how injury marks affect it; V2 defines how
to compute the "true" reordering on top of that layout and how to render
movement indicators (who moved up/down vs. the published chart), but
explicitly says "this document specifies how to construct that object. It
does not build an artifact or a front end." **This document is that missing
piece**: it combines both specs into one concrete, buildable artifact —
team selector, toggle switch (green when set to "True Depth Chart"), table
layout, injury marks, and movement indicators — so an implementer (human or
Claude) can build the actual HTML/JS artifact from this file alone, without
re-deriving anything from the two source docs.

This file is **instructions for building the artifact**, not the artifact
itself. It does not contain the live data pipeline (that's `nflreadpy` +
`opportunity_share.md`'s computation, both out of scope here) — it assumes a
data payload already exists in the shape defined below (Section 2), however
that payload gets produced (real pipeline output today, or hand-authored
mock data for a first pass at the UI).

---

## 1. What the artifact must do

1. Show **one team at a time** — a team selector (dropdown or similar)
   filters the entire view to that team's depth chart. No side-by-side or
   all-teams view.
2. For the selected team, show a **toggle switch** with two states:
   `Depth Chart` ↔ `True Depth Chart`.
   - Default state on load: `Depth Chart`.
   - When toggled to `True Depth Chart`, **the switch itself turns green**
     (track and/or thumb — see Section 4 for the exact visual spec). When
     toggled back to `Depth Chart`, the switch returns to its default
     (unstyled/neutral) color.
   - The toggle state is per-artifact-session, not per-team-persisted —
     switching teams while in "True Depth Chart" mode may either reset to
     "Depth Chart" or preserve the mode across teams; preserving it (so a
     user comparing several teams' true charts doesn't have to re-toggle
     each time) is the recommended default. Either is acceptable; pick one
     and be consistent.
3. Render the selected team's chart according to whichever mode the toggle
   is in, using the table layout, section order, and injury-mark rules from
   V1 (Section 3 below) for **both** modes — the visual skeleton never
   changes between modes, only the occupants of the WR/TE/RB cells (and,
   in True mode only, movement styling on those same cells).

---

## 2. Data contract (current Brady Bot UI)

The live page no longer renders the full ESPN Offense / Defense / Special Teams
grid. It shows a **flat four-column skill table** (QB · RB · WR · TE) at ~80%
width, plus a right rail (**Other Starter Injuries**, ~20%) with O/D starter
counts for OL / DL / LBs / DBs. Toggle, injury marks, and True-mode movement
styling are unchanged. Ranking math is still from `true_depth_chart.md` +
`opportunity_share.md` (All view); only the payload shape and layout changed.

```jsonc
{
  "team": "BUF",
  "week": 2,                         // focus gameweek (injuries + right rail)
  "has_usage_data": true,
  "completed_weeks": [1, 2],
  "columns": {
    "QB": [                          // published only — no "true" object
      {
        "pos_rank": 1,
        "published": { "player_name": "Josh Allen", "injury_mark": null }
      }
    ],
    "RB": [
      {
        "pos_rank": 1,
        "published": { "player_name": "James Cook", "injury_mark": null },
        "true": {
          "player_name": "James Cook",
          "injury_mark": null,
          "movement": "none"           // "up" | "down" | "none"
        }
      }
    ],
    "WR": [ /* flat pos_rank 1…N */ ],
    "TE": [ /* … */ ]
  },
  "other_starter_injuries": {
    "OL": 0,                           // LT LG C RG RT, pos_rank==1, Out|Doubtful
    "DL": 1,                           // LDE LDT RDT RDE NT
    "LBs": 0,                          // WLB MLB SLB LILB RILB
    "DBs": 2                           // LCB RCB NB SS FS
  }
}
```

Notes on the contract:

- **Column order is fixed:** `QB`, `RB`, `WR`, `TE`. Each value is a flat list
  ordered by effective rank. Shorter columns imply blank cells when the
  renderer pads to `max(lengths)`.
- **`true` objects** exist only on RB / WR / TE. QB always mirrors published
  in both modes.
- **O demotion** still applies within each flat column (published and True).
- **Overflow:** a True list may be longer than published when usage includes a
  player the chart missed; published pads with `player_name: null`.
- **Other Starter Injuries** counts only `pos_rank == 1` starters with
  report_status Out or Doubtful (not Questionable), for the focus week
  (falling back to the latest injury week ≤ focus if needed).

The historical ESPN multi-section grid contract below is retained as
background for V1/V2 docs; the shipped Brady Bot page uses the shape above.

### Legacy ESPN-grid contract (reference only)

```jsonc
{
  "team": "BUF",
  "sections": [
    {
      "section": "Offense",           // "Offense" | "Defense" | "Special Teams"
      "group_label": "3WR 1TE",       // raw pos_grp value, display-only
      "rows": [
        {
          "pos_abb": "WR",            // row label, e.g. "WR", "LT", "WLB", "PK"
          "pos_slot": 3,              // row order within the section (sort key, not displayed)
          "true_depth_eligible": true, // true only for WR / TE / RB rows
          "columns": [
            {
              "pos_rank": 1,
              "published": {
                "player_name": "Stefon Diggs",
                "injury_mark": null    // "O" | "D" | "Q" | null  (never "P")
              },
              "true": {                // present only when true_depth_eligible; omit/null otherwise
                "player_name": "Khalil Shakir",
                "injury_mark": null,
                "movement": "up"       // "up" | "down" | "none" (vs. published_flat_rank)
              }
            }
            // ...one entry per pos_rank column, left to right, blank cell if unoccupied
          ]
        }
        // ...one row per pos_abb/pos_slot in this section
      ]
    }
    // Defense, Special Teams sections follow the same shape;
    // their rows will have true_depth_eligible: false and no "true" object.
  ]
}
```

Legacy notes:

- **Non-WR/TE/RB rows** (`true_depth_eligible: false` — QB, OL, all of
  Defense, all of Special Teams, and FB) carry only a `published` object per
  column; there is no `true` variant because V2 doesn't touch them. In
  `True Depth Chart` mode, render these rows identically to `Depth Chart`
  mode (same player, same injury mark, no movement styling).
- **Grid overflow** (V2 Step 4): if the true ranking needed extra columns
  beyond the published grid's width for a position, those extra columns
  simply appear in this payload's `columns` array for that row — the
  artifact doesn't need special-case logic, it just renders however many
  columns are present. In `Depth Chart` mode those extra columns will be
  blank (the published chart didn't have them); that's expected.
- **Blank cells**: a `columns` entry with `player_name: null` (or the entry
  absent for that `pos_rank`) renders as an empty cell — never collapse or
  reflow columns around a gap (V1's explicit rule).
- **`movement`** is only meaningful in `True Depth Chart` mode and only ever
  appears on `true_depth_eligible` rows. It's precomputed per V2 Step 6 (see
  Section 5 below) — the artifact just maps the string to a style, it does
  not compute flat ranks itself.

---

## 3. Shared table layout (both modes) — from V1

Reused verbatim from `lineup-picker-depth-chart.md`'s Depth Chart Table
Format section, since V2 states explicitly that the true depth chart "reuses
this exact grid shape... only the occupant of each cell changes":

- **Three sections per team, fixed order: Offense, Defense, Special Teams.**
  Render as three stacked tables (or three clearly-labeled table groups) on
  one page for the selected team.
- **One row per position slot** (`pos_abb`), ordered by `pos_slot` ascending
  within each section. The row label is `pos_abb`, displayed as-is (e.g.
  `QB`, `WR`, `LT`, `WLB`, `PK`).
- **One column per depth level** (`pos_rank`), populated left to right,
  column 1 = starter. Column count varies by team and by row — do not
  hard-code a fixed number of columns; render however many `columns` entries
  a row has.
- **Blank cell = real information**, not a layout error — render it as an
  empty cell, don't compress the table.

### Injury marks (both modes)

- Render `injury_mark` immediately after the player's name in that cell,
  e.g. `Josh Sweat (Q)`, styled **in red**.
- Applies to `O`, `D`, `Q` only. `P` (Probable) is never shown, and the data
  contract should never send it as a mark — if it does, treat it the same as
  `null` (no mark).
- This rendering rule is identical in `Depth Chart` and `True Depth Chart`
  mode — an injury mark on a player doesn't change based on which chart
  they're being viewed in, only their *position in the grid* might (via
  demotion, already baked into the payload — see Section 5).

---

## 4. Toggle switch — visual spec

- Two-state switch, labeled clearly on both sides or with an adjacent text
  label reflecting current state: **`Depth Chart`** / **`True Depth Chart`**.
- **Default / "Depth Chart" state:** neutral/unstyled track color (e.g. gray),
  matching the artifact's default UI palette.
- **"True Depth Chart" state: the switch turns green.** This is the one
  hard visual requirement from the request — track (and/or thumb) shifts to
  a green fill when toggled to True Depth Chart, with a smooth transition.
  Pick a green that passes contrast against both the track and the thumb in
  both light and dark theme (see the artifact theming rules your build
  process follows) — don't hardcode a green that only works on a light
  background.
- Toggling is immediate — no confirmation step, no page reload. The table(s)
  below re-render in place using the same section/row/column structure, just
  swapping `published` cell content for `true` cell content (plus movement
  styling) on the WR/TE/RB rows.
- Consider a small persistent legend near the toggle when in `True Depth
  Chart` mode (see Section 5's color/arrow key) so a first-time viewer
  understands the green/red cell shading without hunting for it.

---

## 5. True Depth Chart mode — movement indicators, from V2

These rules apply **only** to `true_depth_eligible` rows (WR/TE/RB) when the
toggle is set to `True Depth Chart`. Non-eligible rows render unchanged from
`Depth Chart` mode (Section 3).

For each WR/TE/RB player, the payload's `movement` field reflects a
comparison (done upstream, per V2 Step 6) of:

- `published_flat_rank` — the player's rank if you flattened the published
  grid for their position column-major (all column-1 players ranked 1..N,
  then all column-2 players N+1..2N, etc.).
- `true_flat_rank` — same flattening applied to the true-ranked grid.

Compared **within position group only** (a WR's movement is never compared
to a RB's):

| `movement` value | Cell background | Marker next to player name |
|---|---|---|
| `"up"` (true rank better/lower than published) | Pale green | Solid green up arrow (▲) |
| `"down"` (true rank worse/higher than published) | Pale red | Solid red down arrow (▼) |
| `"none"` (unchanged) | Default/unstyled | None |

Rules for applying this:

- The background tint and the arrow **always agree in color/direction** —
  never a green cell with a red arrow or vice versa.
- **Injury marks and movement indicators are independent and both render
  together** when both apply. E.g., a player who moved up two true-WR slots
  but is now questionable shows the pale-green cell **and** the red `(Q)`
  mark next to their name, simultaneously. Neither suppresses the other —
  they answer different questions (role change vs. health).
- A player who is unranked in the true pool (no qualifying usage data this
  season) but held a published slot will, in almost all cases, show
  `"down"` — expected, not a bug.
- Movement styling never appears in `Depth Chart` mode, even for the same
  player/cell — it's a `True Depth Chart`-only visual layer.

---

## 6. Team selector

- One control (dropdown, searchable select, or a row of team logos/abbrevs)
  listing all 32 NFL teams, keyed by team code (e.g. `BUF`, `KC`).
- Selecting a team re-renders the whole page for that team, respecting
  whatever toggle state is currently active (per Section 1, point 2).
- If a team's payload is missing or incomplete for a given mode (e.g. a
  team's true-depth data hasn't been computed yet), show that mode's toggle
  option but degrade gracefully — e.g. a "true depth chart not yet available
  for this team" message rather than a broken/empty table — instead of
  hiding the team from the selector entirely.

---

## 7. Notes / known limitations carried over from source docs

Worth keeping visible in the artifact (e.g. a small footnote) since they
affect how a viewer should interpret what they're seeing:

- **True Depth Chart** pecking order is driven only by season-wide Target
  Share (WR/TE) and Rush Share (RB) — red-zone-weighted share is explicitly
  out of scope for this version. A player can be the true WR1 by overall
  volume while being a non-factor in the red zone.
- The "All" (season-to-date average) view is what drives True Depth Chart
  ranking, not a single week's share — early in a season (only one
  completed week), True and Week-1 numbers are numerically identical; that's
  expected, not a bug.
- A player with real usage share who doesn't appear on the *published*
  chart's WR/TE/RB rows at all (e.g. a very recent trade) is a data-quality
  gap, not something the movement indicator is designed to handle — don't
  expect a movement arrow to appear for a player who isn't in the published
  grid to begin with.
- FB and every row outside WR/TE/RB is untouched by the True Depth Chart
  computation and always mirrors the published chart, in both toggle modes.

---

## 8. Suggested build approach

1. Start with the team selector wired to static/mock JSON payloads (Section
   2's shape) for a handful of teams — enough to validate layout, toggle
   behavior, and movement styling before any real data pipeline is wired in.
2. Build the three-section table renderer first, `Depth Chart` mode only
   (Section 3) — this alone should exactly reproduce a V1-style published
   depth chart.
3. Add the toggle switch (Section 4) and wire it to swap `published` →
   `true` cell content on `true_depth_eligible` rows only.
4. Layer in movement-indicator styling (Section 5) for `True Depth Chart`
   mode.
5. Layer in injury marks (Section 3, applies to both modes) last, since
   they're visually independent of everything else and easy to verify in
   isolation.
6. Once the UI is validated against mock data, swap the mock payload source
   for real output of the V1 table-construction logic + V2 Steps 1–6
   computation (out of scope for this artifact — that's pipeline work
   defined in the two source docs).
