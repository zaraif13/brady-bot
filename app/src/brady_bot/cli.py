from __future__ import annotations

import json
import textwrap
from typing import Optional

import typer
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from brady_bot.config import load_config
from brady_bot.derive.context import build_week_context
from brady_bot.derive.depth import NO_DEPTH_ENTRY
from brady_bot.explain import _top_signal_phrases, build_explanation
from brady_bot.models import Player, Position
from brady_bot.normalizer import load_overrides, resolve_player
from brady_bot.optimizer import optimize_lineup
from brady_bot.paths import DATA_DIR, MODULE_ROOT
from brady_bot.predictions import append_predictions, backfill_actuals
from brady_bot.sources.cache import CacheStore
from brady_bot.sources import nflverse

load_dotenv(MODULE_ROOT / ".env")

app = typer.Typer(help="Brady Bot")
lineup_app = typer.Typer()
app.add_typer(lineup_app, name="lineup")
console = Console()


def _load_roster_yaml() -> list[Player]:
    cfg = load_config()
    cache = CacheStore()
    players_df = nflverse.load_players_cached(cache)
    overrides = load_overrides()
    raw = yaml.safe_load((DATA_DIR / "roster.yaml").read_text())
    out = []
    for row in raw.get("roster") or []:
        out.append(
            resolve_player(
                row["name"],
                row.get("team"),
                row.get("position"),
                players_df,
                cfg.team_aliases,
                overrides,
            )
        )
    return out


def _format_score(scored) -> str:
    if scored.gate_result == "auto_start":
        return "AUTO"
    if scored.bonus > 0:
        return f"{scored.start_score:.3f} ({scored.weighted_sum:.3f}+{scored.bonus:.3f})"
    return f"{scored.start_score:.3f}"


def _drivers(scored) -> str:
    if scored.gate_result == "auto_start":
        reason = scored.gate_reason or "auto_start"
        return reason.replace("_", " ")
    phrases = _top_signal_phrases(scored.factors, 2)
    return ", ".join(phrases) if phrases else "—"


def _parse_no_cache(value: Optional[str]) -> tuple[bool, bool]:
    """Return (no_cache, refresh_odds). --no-cache=odds refreshes odds only."""
    if not value:
        return False, False
    if value == "odds":
        return False, True
    return True, False


@lineup_app.command("validate")
def validate():
    cfg = load_config()
    console.print(f"[green]Config OK[/green] — {cfg.league.name} {cfg.league.season}")
    for key, block in cfg.weights.positions.items():
        console.print(f"  weights.{key} = {sum(block.values()):.2f}")
    roster_path = DATA_DIR / "roster.yaml"
    if not roster_path.exists():
        console.print("[yellow]WARN[/yellow] roster.yaml not found")
        return
    cache = CacheStore()
    players_df = nflverse.load_players_cached(cache)
    overrides = load_overrides()
    raw = yaml.safe_load(roster_path.read_text())
    for row in raw.get("roster") or []:
        p = resolve_player(
            row["name"],
            row.get("team"),
            row.get("position"),
            players_df,
            cfg.team_aliases,
            overrides,
        )
        console.print(f"  roster: {p.name} → {p.player_id} ({p.team}/{p.position.value})")
    console.print("[green]Roster OK[/green]")


@lineup_app.command("pick")
def pick(
    week: int = typer.Option(..., "--week"),
    no_cache: Optional[str] = typer.Option(None, "--no-cache"),
    verbose: bool = typer.Option(False, "--verbose"),
):
    cfg = load_config()
    cache = CacheStore()
    roster = _load_roster_yaml()
    refresh_all, refresh_odds = _parse_no_cache(no_cache)
    ctx = build_week_context(
        roster, cfg, week, cache, no_cache=refresh_all, refresh_odds=refresh_odds
    )
    lineup = optimize_lineup(ctx, cfg)
    append_predictions(lineup)

    console.print(f"Brady Bot — Week {week} Lineup")
    console.print(f"Data as of {lineup.fetched_at}  |  run_id: {lineup.run_id}")
    if lineup.blended:
        console.print(
            "[yellow]WARN[/yellow] Ranks are blended with prior season through Week 4"
        )
    if ctx.odds_unavailable:
        console.print("[yellow]WARN[/yellow] Odds unavailable — baseline factors neutral (0.50)")

    table = Table()
    table.add_column("SLOT")
    table.add_column("PLAYER")
    table.add_column("POS")
    table.add_column("TEAM")
    table.add_column("OPP")
    table.add_column("SCORE")
    table.add_column("DRIVERS")
    for slot, scored in lineup.starters.items():
        if not scored:
            table.add_row(slot, "EMPTY", "", "", "", "", "")
            continue
        table.add_row(
            slot,
            scored.player.name,
            scored.player.position.value,
            scored.player.team,
            scored.opponent or "",
            _format_score(scored),
            _drivers(scored),
        )
    console.print(table)

    if lineup.bench:
        bench_bits = [
            f"{s.player.name} ({s.start_score:.3f})" for s in lineup.bench[:12]
        ]
        console.print(f"\nBENCH  {' · '.join(bench_bits)}")

    # Weeks 1–4 lean on pos_rank, so a starter the chart omits is scoring 0.00 on a
    # 20–40% factor. Name him — absence can be a data gap (§5.9a, D20).
    unlisted = [s for s in lineup.starters.values() if s and NO_DEPTH_ENTRY in s.flags]
    if unlisted:
        console.print(
            f"\nNO DEPTH ENTRY — pos_rank scores 0.00 (wk {ctx.week}); "
            "override in config/committee_overrides.yaml if the chart is stale"
        )
        for s in unlisted:
            console.print(f"  · {s.player.name} ({s.player.team}) — {s.player.position.value}")

    if lineup.warnings:
        console.print("\nWARNINGS")
        for w in lineup.warnings:
            console.print(f"  · {w}")

    if verbose:
        all_scored = [
            (slot, s)
            for slot, s in lineup.starters.items()
            if s
        ] + [("BN", s) for s in lineup.bench]
        for slot, scored in all_scored:
            if not scored.factors:
                continue
            console.print(f"\n[bold]{scored.player.name}[/bold] ({slot}) — {scored.start_score:.3f}")
            console.print(
                f"  {'FACTOR':<18} {'INPUT':<34} {'SCORE':>6} {'WEIGHT':>7} {'CONTRIB':>8}"
            )
            total = 0.0
            for f in scored.factors:
                # The depth blend shows both components and their weights, so the input
                # column has to wrap rather than show a bare number.
                lines = textwrap.wrap(f.raw_value or "—", 34) or ["—"]
                console.print(
                    f"  {f.name:<18} {lines[0]:<34} {f.score:>6.2f} {f.weight:>7.2f} {f.contribution:>8.3f}"
                )
                for cont in lines[1:]:
                    console.print(f"  {'':<18} {cont:<34}")
                total += f.contribution
            if scored.bonus:
                console.print(f"  {'Tier 2 bonus':<18} {'':<34} {'':>6} {'':>7} {scored.bonus:>8.3f}")
            console.print(
                f"  {'':<18} {'':<34} {'':>6} {'TOTAL':>7} {scored.start_score:>8.3f}"
            )


@lineup_app.command("explain")
def explain(
    week: int = typer.Option(..., "--week"),
    player: str = typer.Option(..., "--player"),
    no_cache: Optional[str] = typer.Option(None, "--no-cache"),
):
    cfg = load_config()
    cache = CacheStore()
    roster = _load_roster_yaml()
    refresh_all, refresh_odds = _parse_no_cache(no_cache)
    ctx = build_week_context(
        roster, cfg, week, cache, no_cache=refresh_all, refresh_odds=refresh_odds
    )
    lineup = optimize_lineup(ctx, cfg)
    target = player.strip().lower()
    found = None
    slot = None
    for s, scored in lineup.starters.items():
        if scored and scored.player.name.lower() == target:
            found = scored
            slot = s
            break
    if not found:
        for scored in lineup.bench:
            if scored.player.name.lower() == target:
                found = scored
                slot = "BN"
                break
    if not found:
        console.print(f"[red]Player not found in lineup:[/red] {player!r}")
        raise typer.Exit(1)
    outcome = "starter" if slot and slot != "BN" else "bench"
    text = build_explanation(found, slot=slot, outcome=outcome)
    console.print(text)
    if found.factors:
        console.print(f"\nStart Score {found.start_score:.3f} (weighted {found.weighted_sum:.3f})")
        for f in found.factors:
            console.print(f"  {f.name}: {f.score:.2f} × {f.weight:.2f} = {f.contribution:.3f}")
        if found.bonus:
            console.print(f"  Tier 2 bonus: +{found.bonus:.3f}")


@lineup_app.command("backfill")
def backfill(week: int = typer.Option(..., "--week")):
    # Placeholder: without live points, no-op message
    n = backfill_actuals(week, {})
    console.print(f"Updated {n} rows (provide actuals map in future)")


if __name__ == "__main__":
    app()
