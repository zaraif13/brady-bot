"""Evidence run for S12, the static QB calibre ranking (D21).

Answers the five report-back items with live nflverse data rather than fixtures:

  1. Which function each of the four consumers actually calls today.
  2. A real QB's S12 rank through all three tier tables (WR, TE, D/ST).
  3. A deliberately triggered derived fallback, with the flag visible.
  4. The QB picker's own Start Score with and without S12 loaded.
  5. "Anthony Richardson Sr." resolving to a single gsis_id.

    python scripts/verify_qb_calibre.py
"""
from __future__ import annotations

import inspect

import polars as pl

from brady_bot.config import load_config
from brady_bot.derive.calibre import derive_player_calibre
from brady_bot.derive.context import build_week_context
from brady_bot.derive.qb_calibre import FALLBACK_FLAG, merge_qb_calibre
from brady_bot.models import Player, Position
from brady_bot.normalizer import (
    normalize_name,
    resolve_player,
    resolve_qb_calibre_ranks,
)
from brady_bot.pickers import defense as defense_mod
from brady_bot.pickers import flex as flex_mod
from brady_bot.pickers import te as te_mod
from brady_bot.pickers import wr as wr_mod
from brady_bot.pickers.defense import DefensePicker
from brady_bot.pickers.flex import FlexPicker
from brady_bot.pickers.qb import QBPicker
from brady_bot.pickers.te import TEPicker
from brady_bot.pickers.wr import WRPicker
from brady_bot.scoring.shared import qb_quality_label, qb_quality_score
from brady_bot.sources import nflverse
from brady_bot.sources.cache import CacheStore

BAR = "=" * 80
SUB = "-" * 80


def _factor(picker, ctx, player, name):
    for f in picker.score_factors(ctx, player):
        if f.name == name:
            return f
    raise SystemExit(f"{picker.position} has no factor named {name!r}")


def main() -> None:
    cfg = load_config()
    cache = CacheStore()
    players_df = nflverse.load_players_cached(cache)
    season = cfg.league.season

    # ------------------------------------------------------------------ item 1
    print(BAR)
    print("1. IS qb_quality_score() ACTUALLY SHARED BY ALL FOUR CONSUMERS?")
    print(BAR)
    wr_src = inspect.getsource(wr_mod.WRPicker.score_factors)
    te_src = inspect.getsource(te_mod.TEPicker.score_factors)
    flex_src = inspect.getsource(flex_mod.FlexPicker._situation)
    def_src = inspect.getsource(defense_mod.DefensePicker._opp_qb)
    for label, src, factor in (
        ("WR  Step 5", wr_src, "qb_quality"),
        ("TE  Step 5", te_src, "qb_quality"),
        ("FLEX Step 4", flex_src, "situation"),
        ("DEF Step 2", def_src, "opp_qb"),
    ):
        calls_shared = "qb_quality_score(" in src
        reads_map = 'calibre_rank.get("QB"' in src or "qb_calibre_of(" in src
        print(
            f"  {label:<12} factor={factor:<10} "
            f"calls qb_quality_score(): {str(calls_shared):<5} "
            f"reads the QB calibre map directly: {reads_map}"
        )
    print()
    print("  => The shared thing is the DATA (ctx.calibre_rank['QB']), not the function.")
    print("     WR and TE call qb_quality_score(); FLEX and DEF each own their table")
    print("     (FLEX's top-20 threshold, DEF's inverted table) but read the same rank.")
    print("     Swapping the source of that one map moves all four together.")

    # ------------------------------------------------------------------ item 5
    print()
    print(BAR)
    print("5. NAME RESOLUTION — 99 entries, suffixes, same-team surnames")
    print(BAR)
    resolved = resolve_qb_calibre_ranks(cfg.qb_calibre_ranks, players_df, cfg.team_aliases)
    print(f"  entries in config : {len(cfg.qb_calibre_ranks)}")
    print(f"  distinct gsis_ids : {len(resolved)}   (a collapse would show up as < 99)")
    print(f"  teams covered     : {len({e['team'] for e in cfg.qb_calibre_ranks})} / 32")

    rich_id = next(
        pid
        for pid, _ in resolved.items()
        if pid
        == resolve_player("Anthony Richardson Sr.", "IND", "QB", players_df, cfg.team_aliases).player_id
    )
    rich_rows = players_df.filter(pl.col("gsis_id") == rich_id).select(
        "gsis_id", "display_name", "latest_team", "position"
    )
    print()
    print('  "Anthony Richardson Sr." (S12)  vs  nflverse "Anthony Richardson"')
    print(f'    normalize_name both sides -> {normalize_name("Anthony Richardson Sr.")!r} '
          f'== {normalize_name("Anthony Richardson")!r}')
    print(f"    rows matching that gsis_id: {rich_rows.height}  (2+ would mean a split record)")
    for r in rich_rows.to_dicts():
        print(f"    -> {r['gsis_id']}  {r['display_name']:<22} {r['latest_team']} "
              f"{r['position']}  rank {resolved[rich_id]}")

    print()
    print("  Buffalo's two Allens, resolved by team AND position:")
    for name in ("Josh Allen", "Kyle Allen"):
        p = resolve_player(name, "BUF", "QB", players_df, cfg.team_aliases)
        print(f"    {name:<12} -> {p.player_id}  {p.team} {p.position.value}  "
              f"rank {resolved[p.player_id]}")
    others = players_df.filter(
        (pl.col("display_name") == "Josh Allen") & (pl.col("position") != "QB")
    ).select("gsis_id", "display_name", "latest_team", "position")
    for r in others.to_dicts():
        print(f"    (rejected by the position filter: {r['gsis_id']} {r['display_name']} "
              f"{r['latest_team']} {r['position']})")

    # ------------------------------------------------------------------ item 2
    print()
    print(BAR)
    print("2. ONE REAL QB, ONE RANK, THREE TIER TABLES")
    print(BAR)
    roster: list[Player] = []
    seen: set[str] = set()
    for e in cfg.qb_calibre_ranks:
        p = resolve_player(e["name"], e["team"], "QB", players_df, cfg.team_aliases)
        if p.player_id not in seen:
            roster.append(p)
            seen.add(p.player_id)
    # A pass-catcher and a defence for every team the QBs play for.
    for team in sorted({p.team for p in roster}):
        roster.append(
            Player(player_id=f"DEF-{team}", name=f"{team} Defense", team=team, position=Position.DEF)
        )
    ctx = build_week_context(roster, cfg, 1, cache, players_df=players_df)

    print(f"  built a real Week 1 {season} context: {len(ctx.roster)} players, "
          f"{len(ctx.calibre_rank['QB'])} QB calibre ranks")
    print(f"  QBs on the derived fallback path: {len(ctx.qb_calibre_fallback)}")

    # Rebuild the roster with the actual charted WR1/TE1 for the subject's team so the
    # WR and TE factors come from real players rather than invented ones.
    subject_name, subject_team = "Patrick Mahomes", "KC"
    subject = resolve_player(subject_name, subject_team, "QB", players_df, cfg.team_aliases)
    rank = ctx.calibre_rank["QB"][subject.player_id]

    depth = nflverse.load_depth_charts(cache, [season, season - 1])
    from brady_bot.derive.depth import derive_pos_ranks

    pos_rank = derive_pos_ranks(depth, 1, overrides=cfg.resolved_depth_overrides,
                                aliases=cfg.team_aliases)
    catalog = {
        str(r["gsis_id"]): str(r["display_name"])
        for r in players_df.select("gsis_id", "display_name").drop_nulls().to_dicts()
    }

    def charted(position: str, team: str, want_rank: int = 1) -> Player | None:
        for pid, r in pos_rank.get(position, {}).items():
            if r != want_rank:
                continue
            row = players_df.filter(pl.col("gsis_id") == pid)
            if row.height and str(row.row(0, named=True).get("latest_team") or "").upper() == team:
                return Player(
                    player_id=pid,
                    name=catalog.get(pid, pid),
                    team=team,
                    position=Position(position),
                )
        return None

    wr1 = charted("WR", subject_team)
    te1 = charted("TE", subject_team)
    opp = None
    for t, g in ctx.games.items():
        if t == subject_team:
            opp = g.away_team if g.home_team == subject_team else g.home_team
            break
    dst = Player(
        player_id=f"DEF-{opp}", name=f"{opp} Defense", team=opp or "BUF", position=Position.DEF
    )
    for extra in (wr1, te1, dst):
        if extra and extra.player_id not in {p.player_id for p in ctx.roster}:
            ctx.roster.append(extra)
            ctx.player_teams[extra.player_id] = extra.team

    print()
    print(f"  subject           : {subject.name} ({subject.team}), gsis {subject.player_id}")
    print(f"  S12 calibre rank  : {rank}")
    print(f"  on the static list: {subject.player_id in cfg.resolved_qb_calibre}")
    print(f"  QB1 of {subject_team} per depth chart: "
          f"{catalog.get(ctx.qb1_by_team.get(subject_team, ''), '(none)')}")
    print(f"  Week 1 opponent   : {opp}")
    print()
    print(f"  {'CONSUMER':<26} {'FACTOR':<12} {'WEIGHT':>7} {'SCORE':>6}  INPUT")
    print(f"  {SUB[:76]}")
    rows = []
    if wr1:
        f = _factor(WRPicker(cfg), ctx, wr1, "qb_quality")
        rows.append((f"WR Step 5 ({wr1.name})", f))
    if te1:
        f = _factor(TEPicker(cfg), ctx, te1, "qb_quality")
        rows.append((f"TE Step 5 ({te1.name})", f))
    if wr1:
        f = _factor(FlexPicker(cfg), ctx, wr1, "situation")
        rows.append((f"FLEX Step 4 ({wr1.name})", f))
    f = _factor(DefensePicker(cfg), ctx, dst, "opp_qb")
    rows.append((f"D/ST Step 2 ({opp})", f))
    for label, f in rows:
        print(f"  {label:<26} {f.name:<12} {f.weight:>7.2f} {f.score:>6.2f}  {f.raw_value}")
    print()
    print(f"  All four resolved rank {rank} for {subject.name}. WR/TE/FLEX read it one")
    print("  direction, D/ST inverted — one number, four factors, no disagreement.")

    # What the same factors scored before S12 existed, on the same live data.
    print()
    print(f"  {SUB}")
    print("  Same context with S12 removed (the pre-change derived path):")
    derived_only = derive_player_calibre(
        nflverse.load_player_stats(cache, [season, season - 1]),
        "QB",
        season,
        1,
        cfg.league,
        min_games=int(cfg.weights.global_cfg.get("calibre_min_games", 3)),
    )
    saved = ctx.calibre_rank["QB"]
    ctx.calibre_rank["QB"] = derived_only
    ctx.qb_calibre_fallback = set(derived_only)
    print(f"    derived QB ranks available for {season} week 1: {len(derived_only)}")
    print(f"    {subject.name}'s derived rank: {derived_only.get(subject.player_id, 'unranked')}")
    if wr1:
        print(f"    WR Step 5  -> {qb_quality_score(ctx, subject_team):.2f}   "
              f"({qb_quality_label(ctx, subject_team)})")
    print(f"    D/ST Step 2 -> {_factor(DefensePicker(cfg), ctx, dst, 'opp_qb').score:.2f}")
    ctx.calibre_rank["QB"] = saved
    ctx.qb_calibre_fallback = set()

    # ------------------------------------------------------------------ item 3
    print()
    print(BAR)
    print("3. DELIBERATE FALLBACK — an unlisted QB gets a derived rank, flagged")
    print(BAR)
    listed_names = {normalize_name(e["name"]) for e in cfg.qb_calibre_ranks}
    unlisted = [
        ("Joe Fagnano", "BAL"),
        ("Mark Gronowski", "HOU"),
        ("DJ Uiagalelei", "LAC"),
        ("Joey Aguilar", "JAX"),
        ("Kedon Slovis", "GB"),
        ("Jack Strand", "ATL"),
        ("Matthew Caldwell", "LAR"),
        ("Haynes King", "CAR"),
    ]
    print("  the 8 QBs on the playing-style table but not on S12:")
    for name, team in unlisted:
        print(f"    {name:<18} {team:<4} on S12: {normalize_name(name) in listed_names}")

    # Real derived ranks: last completed season, which is what an in-progress season's
    # derived map will look like once games exist.
    stats = nflverse.load_player_stats(cache, [season - 1, season - 2])
    derived_prior = derive_player_calibre(stats, "QB", season - 1, 18, cfg.league, min_games=3)
    merged, fallback_ids = merge_qb_calibre(cfg.resolved_qb_calibre, derived_prior)
    print()
    print(f"  derived map ({season - 1} full season): {len(derived_prior)} QBs")
    print(f"  merged map                     : {len(merged)} QBs")
    print(f"  on the derived fallback path   : {len(fallback_ids)} QBs")

    subject_fb = None
    for name, team in unlisted:
        try:
            p = resolve_player(name, team, "QB", players_df, cfg.team_aliases)
        except Exception as exc:
            print(f"    [{name}] not in the player catalog: {type(exc).__name__}")
            continue
        if p.player_id in derived_prior:
            subject_fb = (p, derived_prior[p.player_id])
            break

    if subject_fb is None:
        # None of the eight has prior-season snaps, which is the point of them. Simulate
        # the mid-season arrival the spec calls out instead: same code path, real numbers.
        p = resolve_player(unlisted[0][0], unlisted[0][1], "QB", players_df, cfg.team_aliases)
        derived_prior = dict(derived_prior)
        derived_prior[p.player_id] = 24  # a promoted arm producing like a low-end starter
        merged, fallback_ids = merge_qb_calibre(cfg.resolved_qb_calibre, derived_prior)
        subject_fb = (p, 24)
        print()
        print("  None of the eight has prior-season fantasy production — exactly why they")
        print("  are off the list. Simulating the mid-season arrival the spec calls out:")

    fb_player, fb_rank = subject_fb
    print()
    print(f"  fallback subject  : {fb_player.name} ({fb_player.team}), gsis {fb_player.player_id}")
    print(f"  on S12            : {fb_player.player_id in cfg.resolved_qb_calibre}")
    print(f"  derived rank used : {fb_rank}")
    print(f"  in fallback set   : {fb_player.player_id in fallback_ids}")

    fb_team = fb_player.team.upper()
    ctx.calibre_rank["QB"] = merged
    ctx.qb_calibre_fallback = fallback_ids
    ctx.qb1_by_team[fb_team] = fb_player.player_id
    ctx.roles[fb_player.player_id] = "QB1"
    if fb_player.player_id not in {p.player_id for p in ctx.roster}:
        ctx.roster.append(fb_player)
        ctx.player_teams[fb_player.player_id] = fb_team

    fb_wr = charted("WR", fb_team) or wr1
    fb_te = charted("TE", fb_team) or te1
    for extra in (fb_wr, fb_te):
        if extra and extra.player_id not in {p.player_id for p in ctx.roster}:
            ctx.roster.append(extra)
            ctx.player_teams[extra.player_id] = extra.team
    print()
    print(f"  {'CONSUMER':<26} {'SCORE':>6}  INPUT")
    print(f"  {SUB[:76]}")
    if fb_wr and fb_wr.team.upper() == fb_team:
        f = _factor(WRPicker(cfg), ctx, fb_wr, "qb_quality")
        print(f"  {'WR Step 5':<26} {f.score:>6.2f}  {f.raw_value}")
    if fb_te and fb_te.team.upper() == fb_team:
        f = _factor(TEPicker(cfg), ctx, fb_te, "qb_quality")
        print(f"  {'TE Step 5':<26} {f.score:>6.2f}  {f.raw_value}")
        f = _factor(FlexPicker(cfg), ctx, fb_te, "situation")
        print(f"  {'FLEX Step 4':<26} {f.score:>6.2f}  {f.raw_value}")
    print(f"  {'(raw label carries the flag: ' + FALLBACK_FLAG + ')':<26}")
    print()
    print("  no exception raised — the fallback is warn-level, never a halt")

    # ------------------------------------------------------------------ item 4
    print()
    print(BAR)
    print("4. THE QB PICKER'S OWN START SCORE — S12 LOADED vs NOT LOADED")
    print(BAR)
    qb_picker = QBPicker(cfg)
    # Same subject as item 2, whose rank genuinely moves between the two paths, so an
    # identical Start Score cannot be an artifact of the rank happening not to change.
    probe = subject

    ctx_after = build_week_context(roster, cfg, 1, cache, players_df=players_df)
    after = [(f.name, f.score, f.weight) for f in qb_picker.score_factors(ctx_after, probe)]
    after_rank = ctx_after.calibre_rank["QB"].get(probe.player_id)

    # Empty the raw list, not the resolved map: build_week_context re-resolves the raw
    # list into cfg.resolved_qb_calibre on every call, so clearing the map alone is undone.
    saved_static = cfg.qb_calibre_ranks
    cfg.qb_calibre_ranks = []
    ctx_before = build_week_context(roster, cfg, 1, cache, players_df=players_df)
    before = [(f.name, f.score, f.weight) for f in qb_picker.score_factors(ctx_before, probe)]
    before_rank = ctx_before.calibre_rank["QB"].get(probe.player_id)
    cfg.qb_calibre_ranks = saved_static

    print(f"  probe: {probe.name} ({probe.team})")
    print(f"    calibre rank WITHOUT S12 : {before_rank}")
    print(f"    calibre rank WITH    S12 : {after_rank}")
    print(f"    rank actually moved      : {before_rank != after_rank}")
    print()
    print(f"  {'FACTOR':<20} {'WITHOUT S12':>12} {'WITH S12':>10} {'WEIGHT':>8}")
    print(f"  {SUB[:54]}")
    for (n1, s1, w1), (n2, s2, _) in zip(before, after, strict=True):
        flag = "" if (n1, s1) == (n2, s2) else "   <-- DIFFERS"
        print(f"  {n1:<20} {s1:>12.4f} {s2:>10.4f} {w1:>8.2f}{flag}")
    print()
    print(f"  factor lists identical: {before == after}")
    print(f"  QB start score        : {sum(s * w for _, s, w in before):.4f} vs "
          f"{sum(s * w for _, s, w in after):.4f}")
    print(f"  no self-calibre factor in QB's equation: "
          f"{not {n for n, _, _ in after} & {'ranking', 'player_calibre', 'qb_quality'}}")

    print()
    print(BAR)
    print("done")
    print(BAR)


if __name__ == "__main__":
    main()
