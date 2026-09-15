# Opportunity & Red Zone Share — Tech Spec

## Context

This document specifies how to compute a per-team, per-player "opportunity share" view from `nflreadpy` player-level stats and play-by-play, covering four usage metrics:

1. **Target Share** — nflreadpy-native. % of a team's passing-game targets a player earned in a given week.
2. **Rush Share** — *derived in this spec*. % of a team's rushing attempts an RB carried in a given week.
3. **RZ Target Share** — *derived in this spec*. % of a team's red-zone passing-game targets a player earned.
4. **RZ Rush Share** — *derived in this spec*. % of a team's red-zone rushing attempts an RB carried.

A fifth, team-level (not per-player) number — **RZ play mix** — is also computed: of a team's red-zone plays, what % were passes vs. runs. It is not its own column; it is surfaced as a note directly under the RZ Target Share and RZ Rush Share column headers for that team's card (see Step 8), since it's the same pair of numbers (they sum to 100%) contextualizing both RZ columns at once.

Two more presentation-layer additions ride alongside the four metrics, not as new metrics of their own:

- **Qty** — every one of the four % metrics is shown with its underlying raw count next to it (e.g. `35.1% (13)`). A percentage alone hides volume (5/5 and 50/50 both read as a big number, but the RZ Target Share of one game's random bounce is not the RZ Target Share of a full season of designed looks) — Qty keeps the raw count visible right next to the share it produced, with no separate lookup needed. See Step 6.
- **Bellcow flag (🔔)** — any RB whose Rush Share is `>= 60%` gets a bell emoji next to their name. It's a threshold-based label, not a metric, applied only to RBs. See Step 8.

These metrics exist to support waiver-wire / opportunity-based fantasy football analysis in the `brady-bot` project: raw box-score stats (yards, TDs) are noisy and volume-dependent, but target/rush share isolate *usage* — the leading indicator of sustained fantasy value — independent of efficiency or game script. The red-zone versions narrow that same lens to the highest-leverage part of the field, where touches convert to touchdowns at a much higher rate, and where usage patterns (e.g. a receiving back who disappears near the goal line) often diverge sharply from a player's overall share.

**Two ways to view the data, selectable in one page:**

- **A single gameweek** (e.g. "Week 3") — every metric reflects that one week only, exactly as described above.
- **"All" (season to date)** — every metric becomes the *average of that player's per-week values, across only the weeks they actually qualified in*. A week a player missed — bye, injury, healthy scratch, or simply zero qualifying touches — is dropped from their denominator entirely; it is never averaged in as a 0%. This is the one rule in this whole spec that most needs to be stated plainly, because it's easy to get wrong silently: **the denominator for a player's "All" average is their own games played, not the number of weeks the season has completed.** Two players in Week 5 of the season can have "All" averages built on a different number of games (5 vs. 3, say, if one missed two weeks to injury) and that must be visible, not just true — see the `GP` badge in Step 8. Full derivation in Step 7.

This spec is written to be re-run at **any point in the season**. It does not hard-code a season or week. Instead, it defines `SEASON` and the set of completed weeks as variables derived from the current date (via `nflreadpy`'s own published data, not calendar math), so that anyone (or any LLM) following this spec on a given day computes every week's numbers — and the "All" average — correctly and automatically, no manual lookup required.

**Output shape:** one page, one dropdown selecting the view (each completed week, plus "All"). For the selected view: one "team card" per team, each containing every relevant player's four metrics (with Qty) in one row per player, a bellcow flag where earned, and (in "All" only) a `GP` games-played badge per player. See Step 8 for the full layout spec.

## Prerequisites

- Python 3.10+
- `nflreadpy` installed (`pip install nflreadpy`) — confirmed working at v0.1.5, uses `polars` DataFrames.

```python
import nflreadpy as nfl
import polars as pl
```

## Step 1 — Resolve `SEASON` and the set of completed weeks

Do not hard-code these. Compute them fresh every time this spec is run, so the doc self-corrects across bye weeks and season boundaries — and so it naturally picks up new weeks (and any team's data that lags behind the rest, e.g. a Monday nighter that hasn't finished) with no code changes.

```python
SEASON = nfl.get_current_season()  # e.g. 2026 — flips over after Labor Day Thursday each year

stats_all = nfl.load_player_stats(seasons=[SEASON]).filter(pl.col("season_type") == "REG")

if stats_all.height == 0:
    raise RuntimeError(f"No player stats published yet for {SEASON} — season hasn't started.")

CURRENT_WEEK = stats_all["week"].max()
COMPLETED_WEEKS = sorted(stats_all["week"].unique().to_list())  # e.g. [1, 2, 3] — every week with any published data
```

**`CURRENT_WEEK` = the highest regular-season week number for which `load_player_stats` has any rows at all** — i.e. the most recent week nflreadpy has started publishing stats for, complete or not. It's the default-selected view in the UI (Step 8).

**`COMPLETED_WEEKS` = every regular-season week number with any published data**, in order — this becomes the list of selectable weeks (Step 8's dropdown) and the set that "All" (Step 7) averages over. In ordinary operation this is `[1, 2, ..., CURRENT_WEEK]` with no gaps, but the spec derives it directly from the data rather than assuming contiguity.

**Why not require the whole week to have finished:** an earlier draft of this spec computed the latest week from `load_schedules` and required every game in the week to have a final score. That over-constrains it — mid-week (e.g. after Sunday/Monday games but before a Thursday nightcap, or vice versa), most of a week's stats are already published and usable, and `load_player_stats` will already reflect them. Requiring full completion made the spec return nothing during exactly the window it's meant to be run in. Partial-week completeness is instead surfaced explicitly per-view (`missing_teams`, Step 3), not hidden by delaying the week.

**Why not `nfl.get_current_week()`:** with default args it returns the week of the *next scheduled* game, which is often a week *ahead* of the last one with usable stats (e.g. it can flip to Week 3 before Week 3 has been played at all). `CURRENT_WEEK` here is always a week with real stats behind it.

## Step 2 — Load season-wide stats and play-by-play once

Load the full season once for each source, rather than re-querying per week — everything downstream filters these in memory. Two sources are needed: `load_player_stats` for season-week totals (Target Share, Rush Share), and `load_pbp` for red-zone play detail (RZ Target Share, RZ Rush Share, RZ play mix) — red-zone splits aren't available in `load_player_stats` and must be built from individual plays.

```python
pbp_all = nfl.load_pbp(seasons=[SEASON]).filter(pl.col("week").is_in(COMPLETED_WEEKS))

sched = nfl.load_schedules(seasons=[SEASON])
all_teams_this_season = sorted(set(sched["home_team"].to_list()) | set(sched["away_team"].to_list()))
```

Note: derive the active team list from `load_schedules(seasons=[SEASON])`, **not** from `load_teams()` — the latter returns all 36 franchise abbreviations across history, including relocated/retired ones (`OAK`, `SD`, `STL`, `LAR`), which would falsely show up as "missing" every single week.

## Step 3 — Per-week computation: `compute_week(week)`

Everything in Steps 3–6 runs **once per week**, for every `week in COMPLETED_WEEKS`, inside one function (`compute_week`). It produces that week's team-card data, which is stored as `views[str(week)]`. Nothing here is hard-coded to a single week — the loop in Step 8 is what makes every completed week (and the running "All" view) available from one page.

**3a — Which teams have data this week.** Not all 32 teams will necessarily have rows for a given week (bye weeks, or a game simply not finished yet). Only include teams actually present — never assume all 32, and never hard-code a team list or an exclusion list. This is what makes teams appear automatically the moment `load_player_stats`/`load_pbp` has rows for them — no code change needed as the week fills in.

```python
def compute_week(week):
    df = stats_all.filter(pl.col("week") == week)
    pbp = pbp_all.filter(pl.col("week") == week)

    teams_with_data = sorted(df["team"].unique().to_list())
    missing_teams = sorted(set(all_teams_this_season) - set(teams_with_data))
```

Report `missing_teams` visibly in that week's output so absent teams read as "no data yet," not an omission error.

**3b — Target Share (nflreadpy-native).** `target_share` is provided natively as a per-player-per-week column: `targets / team_total_targets` for that game. Use it directly. Population: any player with `targets > 0` that week.

```python
    tgt = (
        df.filter(pl.col("targets") > 0)
        .select(["team", "player_id", "player_display_name", "position", "targets", "target_share"])
        .with_columns((pl.col("target_share") * 100).round(1).alias("target_share_pct"))
    )
```

**3c — Rush Share (derived).**

```
rush_share = player_carries / team_rushing_attempts
```

`team_rushing_attempts` is the sum of **all** carries by the team that week (every rusher, not just RBs). Population: `position == "RB"` and `carries > 0`.

```python
    team_carries = df.group_by("team").agg(pl.col("carries").sum().alias("team_rushing_attempts"))
    rb = (
        df.filter((pl.col("position") == "RB") & (pl.col("carries") > 0))
        .select(["team", "player_id", "player_display_name", "carries"])
        .join(team_carries, on="team")
        .with_columns((pl.col("carries") / pl.col("team_rushing_attempts") * 100).round(1).alias("rush_share_pct"))
    )
```

## Step 4 — Red zone play set and RZ play mix (per team, per week, derived)

**Red zone definition:** any offensive play with `yardline_100 <= 20`, restricted to real offensive snaps — `play_type in ("pass", "run")`. This excludes `qb_kneel`, `qb_spike`, `no_play` (penalties/aborted snaps), `punt`, `field_goal`, `extra_point`, `kickoff`. A sack is classified as `play_type == "pass"` in nflreadpy's pbp (it was a dropback), so sacks are correctly counted as pass plays, not dropped.

```python
    plays = pbp.filter(pl.col("play_type").is_in(["pass", "run"]) & ~pl.col("posteam").is_in(missing_teams))
    rz = plays.filter(pl.col("yardline_100") <= 20)

    team_rz_mix = (
        rz.group_by("posteam")
        .agg(
            pl.len().alias("rz_plays"),
            (pl.col("play_type") == "pass").sum().alias("rz_pass_plays"),
            (pl.col("play_type") == "run").sum().alias("rz_rush_plays"),
        )
        .with_columns(
            (pl.col("rz_pass_plays") / pl.col("rz_plays") * 100).round(1).alias("rz_pass_pct"),
            (pl.col("rz_rush_plays") / pl.col("rz_plays") * 100).round(1).alias("rz_rush_pct"),
        )
    )
```

**`rz_pass_pct`** = % of the team's red-zone plays that week that were pass plays. **`rz_rush_pct`** = % that were run plays. By construction they sum to 100% for any team with `rz_plays > 0`. This is the **RZ play mix**. If `rz_plays == 0` (team hasn't reached the red zone yet that week), both are `null` — display as "no RZ plays yet."

## Step 5 — RZ Target Share and RZ Rush Share (per player, per week, derived)

**RZ Target Share:**

```
rz_target_share = player_rz_targets / team_rz_targets
```

Numerator: player's targets on red-zone pass plays. Denominator: team's total red-zone targets. A target requires a non-null `receiver_player_id` (excludes sacks and throwaways with no recorded receiver).

```python
    rz_pass = rz.filter((pl.col("play_type") == "pass") & pl.col("receiver_player_id").is_not_null())
    team_rz_targets = rz_pass.group_by("posteam").agg(pl.len().alias("team_rz_targets"))
    player_rz_targets = (
        rz_pass.group_by(["posteam", "receiver_player_id"])
        .agg(pl.len().alias("rz_targets"))
        .join(team_rz_targets, on="posteam")
        .with_columns((pl.col("rz_targets") / pl.col("team_rz_targets") * 100).round(1).alias("rz_target_share_pct"))
        .rename({"posteam": "team", "receiver_player_id": "player_id"})
    )
```

Applies to the same population as Target Share (3b) — a player can't have an RZ target without an overall target. Zero RZ targets that week → `rz_target_share_pct = 0.0` (not `null`), handled in the merge (Step 6).

**RZ Rush Share:**

```
rz_rush_share = player_rz_carries / team_rz_rush_attempts
```

Numerator: player's carries on red-zone run plays. Denominator: team's total red-zone rush attempts (all rushers, same team-wide convention as 3c).

```python
    rz_run = rz.filter((pl.col("play_type") == "run") & pl.col("rusher_player_id").is_not_null())
    team_rz_rush = rz_run.group_by("posteam").agg(pl.len().alias("team_rz_rush_attempts"))
    player_rz_rush = (
        rz_run.group_by(["posteam", "rusher_player_id"])
        .agg(pl.len().alias("rz_carries"))
        .join(team_rz_rush, on="posteam")
        .with_columns((pl.col("rz_carries") / pl.col("team_rz_rush_attempts") * 100).round(1).alias("rz_rush_share_pct"))
        .rename({"posteam": "team", "rusher_player_id": "player_id"})
    )
```

Applies to the same population as Rush Share (3c). Zero RZ carries that week → `rz_rush_share_pct = 0.0`, handled in the merge (Step 6).

## Step 6 — Merge into one row per player per team (per week)

Join key `(team, player_id)`. **Row population** = union of the Target Share population (3b) and the Rush Share population (3c) — every pass catcher and every carrying RB that week, deduplicated.

**Per-metric fill rule:** if a player is in that metric's own population, use its value (defaulting the RZ pair to `0.0` when the player qualified but had no RZ look/carry that week); if not, the value is `null` → renders as "—". "—" always means *this metric doesn't apply to this player* (e.g. Rush Share for a WR); a real zero renders as `0.0%`, never "—".

**Qty (raw counts):** carry each metric's underlying raw count through too — `targets`, `carries`, `rz_targets`, `rz_carries` — the numerators already computed in Steps 3b/3c/5, just not dropped before display. `null` Qty pairs with "—"; `0` Qty pairs with a real `0.0%`.

```python
    tgt_map = {(r["team"], r["player_id"]): r for r in tgt.to_dicts()}
    rb_map = {(r["team"], r["player_id"]): r for r in rb.to_dicts()}
    rz_tgt_map = {(r["team"], r["player_id"]): r for r in player_rz_targets.to_dicts()}
    rz_rb_map = {(r["team"], r["player_id"]): r for r in player_rz_rush.to_dicts()}

    all_keys = set(tgt_map) | set(rb_map)
    rows = []
    for team, pid in all_keys:
        t, r = tgt_map.get((team, pid)), rb_map.get((team, pid))
        rzt, rzr = rz_tgt_map.get((team, pid)), rz_rb_map.get((team, pid))
        base = t or r
        rows.append({
            "team": team, "player_id": pid,
            "player": base["player_display_name"],
            "position": t["position"] if t else "RB",
            "targets": t["targets"] if t else None,
            "target_share_pct": t["target_share_pct"] if t else None,
            "carries": r["carries"] if r else None,
            "rush_share_pct": r["rush_share_pct"] if r else None,
            "rz_targets": rzt["rz_targets"] if rzt else (0 if t else None),
            "rz_target_share_pct": rzt["rz_target_share_pct"] if rzt else (0.0 if t else None),
            "rz_carries": rzr["rz_carries"] if rzr else (0 if r else None),
            "rz_rush_share_pct": rzr["rz_rush_share_pct"] if rzr else (0.0 if r else None),
            "touches": (t["targets"] if t else 0) + (r["carries"] if r else 0),
        })
    return {"missing_teams": missing_teams, "teams": ...}, rows, {m["posteam"]: m for m in team_rz_mix.to_dicts()}
```

**Sort:** within each team, sort rows by `touches` (`targets + carries`) descending — one combined "workload" ranking mixing pass catchers and rushers sensibly.

Call `compute_week(w)` for every `w in COMPLETED_WEEKS`, storing each week's `rows` (and its `team_rz_mix`) — these feed both `views[str(w)]` directly and the "All" aggregation in Step 7.

## Step 7 — "All" (season-to-date) view: averaging with a per-player denominator

This is the view selected as `"all"` in the dropdown (Step 8). It is **not** a fresh query — it's a second pass over the `rows` already produced by every call to `compute_week` in Step 6.

**Per-player averaging.** Group every week's rows by `(team, player_id)`. For each player:

- `tgt_weeks` = the subset of their weekly rows where `target_share_pct is not None` — i.e. the weeks they were actually in the Target Share population (3b). A week with no row for this player at all (bye, inactive, didn't play) is simply absent from this list — it is not a week with value `0`.
- `rsh_weeks` = same idea for `rush_share_pct` (3c population).
- `target_share_pct` (All) = **mean** of `target_share_pct` over `tgt_weeks` only.
- `rush_share_pct` (All) = **mean** of `rush_share_pct` over `rsh_weeks` only.
- `rz_target_share_pct` (All) = **mean** of that week's `rz_target_share_pct` over `tgt_weeks` (the same week set as Target Share — a week only has a meaningful RZ-target number if the player qualified for Target Share that week at all; the 0.0-fill from Step 6 already handles "qualified but no RZ look" correctly inside that mean).
- `rz_rush_share_pct` (All) = **mean** over `rsh_weeks`, same logic.
- **This is the rule the user of this spec must never lose sight of: the denominator of each average is `len(tgt_weeks)` or `len(rsh_weeks)` — the count of weeks that player actually qualified in — never `len(COMPLETED_WEEKS)`.** A week missed for any reason (bye, injury, healthy scratch, simply zero qualifying touches) is excluded from the average outright, not folded in as a 0%.
- `GP` (games played) badges, carried alongside the averages for transparency: `gp_tgt = len(tgt_weeks)`, `gp_rsh = len(rsh_weeks)`, and `gp = len(weekly)` (the union — total distinct weeks this player has *any* qualifying row at all, used as the single visible badge; the two more specific counts are available on hover since a player's role can shift mid-season, e.g. a committee back who stops seeing carries but keeps catching passes).
- **Qty** (All) = **sum**, not mean, of the raw counts over the same qualifying weeks (`targets`, `carries`, `rz_targets`, `rz_carries`) — the season-to-date total behind the averaged share.

```python
from collections import defaultdict

player_weekly = defaultdict(list)  # (team, player_id) -> list of that player's weekly row dicts
for week, rows in all_rows_by_week.items():
    for r in rows:
        player_weekly[(r["team"], r["player_id"])].append(r)

def mean(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None

all_rows = []
for (team, pid), weekly in player_weekly.items():
    latest = weekly[-1]
    tgt_weeks = [w for w in weekly if w["target_share_pct"] is not None]
    rsh_weeks = [w for w in weekly if w["rush_share_pct"] is not None]

    all_rows.append({
        "team": team, "player_id": pid,
        "player": latest["player"], "position": latest["position"],
        "gp": len(weekly), "gp_tgt": len(tgt_weeks), "gp_rsh": len(rsh_weeks),
        "targets": sum(w["targets"] for w in tgt_weeks) if tgt_weeks else None,
        "target_share_pct": mean([w["target_share_pct"] for w in tgt_weeks]),
        "carries": sum(w["carries"] for w in rsh_weeks) if rsh_weeks else None,
        "rush_share_pct": mean([w["rush_share_pct"] for w in rsh_weeks]),
        "rz_targets": sum(w["rz_targets"] or 0 for w in tgt_weeks) if tgt_weeks else None,
        "rz_target_share_pct": mean([w["rz_target_share_pct"] for w in tgt_weeks]),
        "rz_carries": sum(w["rz_carries"] or 0 for w in rsh_weeks) if rsh_weeks else None,
        "rz_rush_share_pct": mean([w["rz_rush_share_pct"] for w in rsh_weeks]),
        "touches": (targets_sum := (sum(w["targets"] for w in tgt_weeks) if tgt_weeks else 0)) + (sum(w["carries"] for w in rsh_weeks) if rsh_weeks else 0),
    })
```

**Team-level RZ play mix (All) is cumulative, not averaged** — deliberately different from the per-player convention above:

```
rz_pass_pct (All) = sum(rz_pass_plays across weeks the team played) / sum(rz_plays across weeks the team played)
```

```python
team_rz_cum = defaultdict(lambda: {"rz_plays": 0, "rz_pass_plays": 0, "rz_rush_plays": 0})
for week, mix_map in all_mix_by_week.items():
    for team, m in mix_map.items():
        acc = team_rz_cum[team]
        acc["rz_plays"] += m["rz_plays"]
        acc["rz_pass_plays"] += m["rz_pass_plays"]
        acc["rz_rush_plays"] += m["rz_rush_plays"]
# rz_pass_pct = round(acc["rz_pass_plays"] / acc["rz_plays"] * 100, 1) if acc["rz_plays"] else None, and symmetrically for rz_rush_pct
```

Why cumulative here and averaged for players: a team's red-zone play count each week has no "did they participate" ambiguity the way an individual player's touches do (a team that played has *some* `rz_plays`, possibly zero), so summing across the weeks it actually played (byes naturally contribute nothing, since a team on bye produces no pbp rows that week) yields the correct season-long play-calling tendency without any player-style exclusion logic being needed.

`missing_teams` for "All" = `all_teams_this_season` minus the set of teams that appear in *any* completed week's rows — i.e. a team is only "missing" from All if it has never had a single game's worth of data yet this season.

## Step 8 — Page layout: week selector, team cards, "All" view

- **Week selector** (dropdown): one option per `w in COMPLETED_WEEKS` labeled `"Week {w}"`, plus a final option `"All (season to date)"` with value `"all"`. Default selection = `CURRENT_WEEK`.
- **Header/caption, per selected view:**
  - Single week: states `SEASON` and the selected week number; the two-tier table header's season-group label reads **"Season"**; each team card's red-zone-play count reads as that week's count; `missing_teams` shown is that week's list (Step 3a).
  - "All": states `SEASON` and the completed-weeks range (`weeks 1–{max(COMPLETED_WEEKS)}`); the season-group label reads **"Season to Date"**; each team card's red-zone-play count is labeled "(season to date)" and uses the Step 7 cumulative total; `missing_teams` shown is the Step 7 all-time list.
  - **A visible banner (not just a tooltip) appears only in the "All" view**, stating in plain language: each player's average is computed only over the games they actually played; a missed week (bye, injury, inactive) is excluded from their denominator, not counted as a 0%; the `GP n` badge next to a name shows exactly how many qualifying games that average is built from. This is a deliberate, explicit call-out — the denominator rule is easy to misread from the numbers alone, so it's stated on the page itself, not left to a hover or a footnote.
- **Team card, table, two-tier header:** unchanged in structure from the single-week spec — an empty cell over Player/Pos, then a season-group header spanning Target Share / Rush Share (label per above), then a red-zone-group header spanning RZ Target Share / RZ Rush Share, with that team's RZ play mix note (Step 4) rendered under the RZ column labels, not as its own column.
- **Body rows:** one per player (Step 6 order for a single week; Step 7 order — sorted by `touches` — for All), each metric cell as a percentage with a small proportional bar, followed by **Qty** in parentheses (raw count for a single week; season-to-date sum for All). "—" for inapplicable metrics; a "—" cell shows no Qty.
- **`GP` badge** (All view only): rendered in the Player cell right after the name, before the bellcow flag — visible text is `GP {gp}` (the union count); hovering reveals the split `gp_tgt` vs. `gp_rsh` counts, since they can differ for a player whose role changed mid-season (e.g. lost carries but kept receiving work).
- **Bellcow flag:** append 🔔 immediately after the name (after the GP badge, if present) when `position == "RB" and rush_share_pct is not None and rush_share_pct >= 60` — evaluated against whichever `rush_share_pct` is active for the selected view (the single week's value, or the All-view average). Applies to Rush Share only (not RZ Rush Share), RBs only. Hard cutoff: 59.9% gets no flag, 60.0% does.
- Each team's table is its own scroll container (`overflow-x: auto`) rather than letting the whole page scroll horizontally.
- A team-name/abbreviation filter above the cards narrows to specific teams, and re-applies instantly when the week selector changes (it filters whichever view is currently active).

## Notes / Known Limitations

- `target_share`'s denominator is team pass-attempts-that-generated-a-target for that single week only — small-sample noise is expected in Week 1 and after injuries change target distribution mid-week. Red-zone samples are smaller still (a team may run only 10-20 total RZ plays in a week), so RZ Target/Rush Share are noisier per-week than their season-wide counterparts.
- `rush_share` and `rz_rush_share` are carries-based, not touches-based (they exclude targets/receptions), so pass-catching backs will look under-utilized on these metrics alone — pair with Target Share / RZ Target Share for a fuller usage picture.
- `rz_pass_pct` + `rz_rush_pct` always sum to 100% for a team with any RZ plays (single week or cumulative in All), since both share the same `rz_plays` denominator — they describe *play-calling mix*, not conversion rate or efficiency.
- Red zone is defined purely by field position (`yardline_100 <= 20`), not down/distance or score context — a garbage-time kneel-adjacent snap inside the 20 wouldn't occur (kneels are excluded via `play_type`), but a meaningless 4th-and-25 heave from the 18 with the game decided would still count.
- **"All" uses a simple mean of weekly percentages, not a re-aggregated ratio of summed counts.** For a player with a stable role these are close, but they can diverge when a player's team context swings week to week (e.g. a blowout that inflates one week's team pass volume) — mean-of-shares weights every qualifying week equally, regardless of how many total team plays happened that week. This was a deliberate choice (see Step 7) to keep "All" literally an *average of the per-week metric*, matching the metric's own name, rather than a different, re-derived ratio.
- Team-level RZ play mix in "All" is cumulative (summed), not averaged — deliberately different from the per-player convention, and documented as such in Step 7.
- Re-running this spec on the same date after nflreadpy's underlying data source (nflverse) issues a correction will change historical week values, and therefore the "All" averages built on them — treat every output (single-week or All) as reflecting nflreadpy's data as of the moment of the run, not an immutable snapshot.
- The 60% bellcow threshold is a fixed, somewhat arbitrary cutoff. On a single week it will flag (or fail to flag) backs based on one game's game script (e.g. a blowout that shelves the passing game inflates rush share for a backup). On the All view it's evaluated against a multi-game average, which smooths that noise out somewhat — but a player who was a bellcow for 2 games and buried on the depth chart for 1 will still show an average that may or may not cross 60%, and the `GP` badge is what lets a reader judge how much to trust that.
- Dynamic team inclusion: `missing_teams` (and therefore which teams' cards appear) is recomputed per view directly from whichever data `load_player_stats`/`load_pbp` currently has — there is no hardcoded team list or exclusion list anywhere in this pipeline. Any team appears automatically, in that week's view and in "All", the moment nflreadpy has rows for them; nothing in this spec or its implementation needs to change as the season fills in.
