# Lineup Picker — QB Calibre Ranking (Cross-Position)

## Context

This file is the **authoritative QB calibre ranking used to score every
position other than QB himself.** It is a companion reference to
`lineup-picker-QB.md` (playing style), `lineup-picker-OLINE.md`, and
`lineup-picker-DEPTH-CHART.md` — same role, same pattern: one hard-coded,
human-verified list, consumed by multiple pickers, no second copy to drift.

**This ranking never feeds the QB picker's own scoring.** The QB model has no
self-calibre factor — its equation is Style, PassCatcher, OLine, Matchup,
SecondaryInjury, Baseline. Calibre only matters when *someone else's* score
depends on how good a QB is: a receiver whose ceiling is capped by his own
quarterback, or a defense sizing up how much damage the opponent's quarterback
can do.

**This replaces the V1 derived calibre for QB specifically.** The original
design computed QB calibre the same way as every other position — realized
fantasy points per game, ranked descending (tech spec §5.6). That derivation
is retired for QB and replaced by this static list. It remains unchanged for
every other position (RB, WR, TE, K).

---

## Consumers

| Module | Factor | Weight | How it reads the ranking |
|---|---|---|---|
| **WR** | Step 5, QB_Quality_Score | 15% | Own team's QB1 (or backup, capped) → tier score |
| **TE** | Step 5, QB_Quality_Score | 15% | Own team's QB1 (or backup, capped) → tier score |
| **FLEX** | Step 4, Situation (WR/TE candidates) | 15% of Situation | Same as WR/TE, via the shared `qb_quality_score()` function |
| **D/ST** | Step 2, Opposing QB Quality | **30%** | **Opponent's** QB1 (or backup) → inverted tier score |

All four consumers call the same shared function,
`qb_quality_score()` (tech spec §7.3), and read the same rank for a given
player. There is no second QB ranking anywhere in the system.

**Assumption made explicit:** the source instruction named "WR and TE" as
examples. D/ST is included here because it consumes the identical shared
function and the identical rank — having D/ST read a *different*, derived
ranking for the same real-world quantity would mean the system disagreeing with
itself about how good a given QB is. If D/ST was meant to keep the derived
ranking instead, that is a one-line change to `qb_quality_score()`'s call site
in the DEF picker — flag it and it comes out cleanly.

---

## The Ranking

Rank 1 = best. Hard-coded for the 2026 season; does not change during the year.

| Rank | Player | Team | Rank | Player | Team | Rank | Player | Team |
|---|---|---|---|---|---|---|---|---|
| 1 | Josh Allen | BUF | 34 | Michael Penix Jr. | ATL | 67 | Kyle Allen | BUF |
| 2 | Drake Maye | NE | 35 | Kirk Cousins | LV | 68 | Tanner McKee | PHI |
| 3 | Joe Burrow | CIN | 36 | Carson Beck | ARI | 69 | Jalon Daniels | TB |
| 4 | Lamar Jackson | BAL | 37 | Spencer Rattler | NO | 70 | Cole Payton | PHI |
| 5 | Dak Prescott | DAL | 38 | J.J. McCarthy | MIN | 71 | Jalen Milroe | SEA |
| 6 | Brock Purdy | SF | 39 | Mason Rudolph | PIT | 72 | Stetson Bennett IV | LAR |
| 7 | Jalen Hurts | PHI | 40 | Marcus Mariota | WAS | 73 | Kyle McCord | MIA |
| 8 | Matthew Stafford | LAR | 41 | Jameis Winston | NYG | 74 | Brady Cook | MIA |
| 9 | Jayden Daniels | WAS | 42 | Mac Jones | SF | 75 | Taylen Green | CLE |
| 10 | Caleb Williams | CHI | 43 | Davis Mills | HOU | 76 | Cooper Rush | ATL |
| 11 | Trevor Lawrence | JAX | 44 | Riley Leonard | IND | 77 | Zach Wilson | NO |
| 12 | Jared Goff | DET | 45 | Joe Flacco | CIN | 78 | Joe Milton III | DAL |
| 13 | Patrick Mahomes | KC | 46 | Justin Fields | KC | 79 | Skylar Thompson | BAL |
| 14 | Justin Herbert | LAC | 47 | Tyrod Taylor | GB | 80 | Hendon Hooker | TEN |
| 15 | Bo Nix | DEN | 48 | Gardner Minshew II | ARI | 81 | Nick Mullens | JAX |
| 16 | Jaxson Dart | NYG | 49 | Cade Klubnik | NYJ | 82 | Luke Altmyer | DET |
| 17 | Kyler Murray | MIN | 50 | Kenny Pickett | CAR | 83 | Easton Stick | TB |
| 18 | Baker Mayfield | TB | 51 | Ty Simpson | LAR | 84 | Garrett Nussmeier | KC |
| 19 | Jordan Love | GB | 52 | Andy Dalton | PHI | 85 | Behren Morton | NE |
| 20 | Tyler Shough | NO | 53 | Quinn Ewers | JAX | 86 | Shane Buechele | BUF |
| 21 | Sam Darnold | SEA | 54 | Tyler Huntley | BAL | 87 | Sam Ehlinger | DEN |
| 22 | C.J. Stroud | HOU | 55 | Carson Wentz | MIN | 88 | Sean Clifford | CIN |
| 23 | Daniel Jones | IND | 56 | Trey Lance | LAC | 89 | Graham Mertz | HOU |
| 24 | Malik Willis | MIA | 57 | Tyson Bagent | CHI | 90 | Josh Johnson | CIN |
| 25 | Bryce Young | CAR | 58 | Drew Allar | PIT | 91 | Case Keenum | CHI |
| 26 | Jacoby Brissett | ARI | 59 | Anthony Richardson Sr. | IND | 92 | Kurtis Rourke | SF |
| 27 | Cam Ward | TEN | 60 | Will Howard | PIT | 93 | Athan Kaliakmanis | WAS |
| 28 | Geno Smith | NYJ | 61 | Tommy DeVito | NE | 94 | Aidan O'Connell | LV |
| 29 | Aaron Rodgers | PIT | 62 | Joshua Dobbs | DET | 95 | Bailey Zappe | NYJ |
| 30 | Fernando Mendoza | LV | 63 | Mitchell Trubisky | TEN | 96 | Max Brosmer | MIN |
| 31 | Tua Tagovailoa | ATL | 64 | Jarrett Stidham | DEN | 97 | Dillon Gabriel | CLE |
| 32 | Deshaun Watson | CLE | 65 | Sam Howell | DAL | 98 | Sam Hartman | WAS |
| 33 | Shedeur Sanders | CLE | 66 | Drew Lock | SEA | 99 | Jake Haener | NYG |

### Coverage

| Check | Result |
|---|---|
| Quarterbacks ranked | 99 |
| Teams covered | 32 of 32 |
| Ranks | 1–99, contiguous, no duplicates |
| Update cadence | Static for V1 — see Maintenance |

---

## How the rank becomes a score

**Nothing changes downstream of the rank itself.** The existing tier table and
the existing backup cap (tech spec §7.3) are unchanged — only the source of the
rank number changes, from a derived per-game average to this list.

**For WR, TE, and FLEX** (`qb_quality_score()`):

```
if QB1 is unavailable (per the injury availability rules):
    score = min(0.50, tier_score(backup_rank))    # hard cap regardless of backup's rank
else:
    score = tier_score(qb1_rank)
```

| Calibre rank | Score |
|---|---|
| 1–5 | 1.00 |
| 6–12 | 0.75 |
| 13–20 | 0.50 |
| 21–28 | 0.25 |
| 29+ | 0.00 |

**For D/ST** (Step 2, inverted — a bad or unavailable opposing QB is good news
for your defense):

| Situation | Score |
|---|---|
| Opposing QB1 unavailable, backup rank 29+ or unranked | 1.00 |
| Opposing QB1 unavailable, backup rank 15–28 | 0.85 |
| QB1 playing, team in top-10 turnover rate | 0.80 |
| QB1 playing, rank 21–28 | 0.65 |
| QB1 playing, rank 13–20 | 0.50 |
| QB1 playing, rank 6–12 | 0.35 |
| QB1 playing, rank 1–5 | 0.15 |
| QB1 playing, rank 1–5 **and** mobile (per `lineup-picker-QB.md`'s style table) | 0.00 |

The elite-and-mobile row reads a **different** static list (QB playing style)
for the mobility check. Same rank, two lookups, unrelated to each other.

---

## Fallback for unlisted quarterbacks

**Eight quarterbacks present in the 107-entry QB Playing Style Reference table
are absent from this 99-entry calibre ranking:**

| Player | Team |
|---|---|
| Joe Fagnano | BAL |
| Mark Gronowski | HOU |
| DJ Uiagalelei | LAC |
| Joey Aguilar | JAX |
| Kedon Slovis | GB |
| Jack Strand | ATL |
| Matthew Caldwell | LAR |
| Haynes King | CAR |

All eight are fourth- or fifth-string quarterbacks, unlikely to ever take a
regular-season snap. But the system must not break if one does — a promoted
practice-squad arm following multiple injuries is exactly the kind of edge case
a fantasy season produces.

**Fallback:** any QB not in this list is scored using the original derived
method (tech spec §5.6) — realized fantasy points per game this season, ranked
against the field, with the standard `calibre_prior_season` /
`calibre_unknown` handling for insufficient data. Flag the output
`qb_calibre_derived_fallback` so it's visible that this player came from the
fallback path rather than the authoritative list.

**Same treatment for any quarterback who enters the league mid-season** — a
practice-squad promotion, a post-cuts waiver claim, an injury replacement not
on either roster at publication. The list is not updated in-season; the
fallback exists precisely for this.

---

## Name resolution

Names resolve to `gsis_id` at startup via `nflreadpy.load_players()`, same
pattern as every other static list.

**Suffix note:** this list uses "Anthony Richardson Sr." where the QB Playing
Style Reference table and nflverse both use "Anthony Richardson." The standard
suffix-stripping normalization (Jr./Sr./II/III/IV removed before matching)
resolves this automatically — no special-case needed, but worth knowing it's
there so a future name addition with a suffix doesn't quietly fail to match.

**Team-level duplicate surnames exist in this list** — Buffalo has both Josh
Allen (rank 1) and Kyle Allen (rank 67); several teams carry 3–4 entries deep
into their QB rooms. Resolution must filter on team **and** position, never
name alone, matching the same rule already established for the QB Playing
Style Reference table.

**Ambiguity or failure to resolve halts the run**, naming the entry. Silent
resolution failure here is worse than in most static lists, because it would
mean a WR or TE's Step 5 factor — or 30% of a D/ST score — silently falls back
to a different ranking without anyone noticing.

---

## Configuration

Stored as `config/qb_calibre_ranks.yaml`, its own file — same reasoning as
`oline_ranks.yaml`: this is a flat, independently-updatable list that doesn't
belong nested inside `static_lists.yaml`.

```yaml
# Authoritative QB calibre ranking, 2026 season. Rank 1 = best.
# Consumed by qb_quality_score() — WR Step 5, TE Step 5, FLEX Step 4,
# and DEF Step 2 (inverted). NEVER consumed by the QB picker's own scoring.
# Unlisted QBs fall back to derived per-game fantasy points (tech spec §5.6),
# flagged qb_calibre_derived_fallback.
qb_calibre_ranks:
  - {rank: 1,  name: "Josh Allen",       team: BUF}
  - {rank: 2,  name: "Drake Maye",       team: NE}
  - {rank: 3,  name: "Joe Burrow",       team: CIN}
  # ... 99 entries total, see the full table above
  - {rank: 99, name: "Jake Haener",      team: NYG}
```

### Required validation at load

| Check | On failure |
|---|---|
| Ranks are 1–99, contiguous, no duplicates | **Halt**, naming the duplicate or gap |
| No duplicate names | **Halt** |
| Every name resolves to a `gsis_id`, filtered by team and position | **Halt**, naming the entry |
| A QB not in the list falls back cleanly, never errors | Warn-level flag `qb_calibre_derived_fallback`, not a halt |

---

## Maintenance

Static for V1. Review before Week 1 and, optionally, after the trade deadline —
a mid-season trade changes a QB's team but not, in the model's view, his
calibre, so only the `team` field needs updating if resolution starts failing
because of it.

If a rank becomes indefensible mid-season (a backup takes over and clearly
outperforms his listed tier), edit `config/qb_calibre_ranks.yaml` directly and
note the change and date here. Do not add a second ranking source, and do not
let WR/TE/FLEX/D-ST drift onto different rankings from each other.

---

## Deviation recorded

| ID | Was | Now |
|---|---|---|
| **D21** | QB calibre derived identically to every other position — realized fantasy points per game, ranked (tech spec §5.6) | Replaced by this static, human-sourced ranking for QB specifically. Retained as an automatic fallback for the 8 quarterbacks (plus any mid-season arrival) not on the list. |

---

## Key Principle

Every other position's calibre answers "how good has this player actually
been," measured from what already happened. QB calibre, when used to score
someone *else*, answers a related but distinct question: "how much should a
receiver's or a defense's score be shaped by the quality of a specific
quarterback." A human-sourced ranking, checked once and reused everywhere, is
a defensible substitute for a derived one precisely because every consumer of
it — WR, TE, FLEX, and D/ST — needs to agree on the same answer to that
question. A single list guarantees they do.
