from __future__ import annotations

import polars as pl

try:
    import nflreadpy
except ImportError:  # pragma: no cover
    nflreadpy = None  # type: ignore

from brady_bot.sources.cache import CacheStore

TTL = {
    "schedules": 24 * 3600,
    "player_stats": 6 * 3600,
    "team_stats": 6 * 3600,
    "snap_counts": 6 * 3600,
    "injuries": 2 * 3600,
    "depth_charts": 6 * 3600,
    "players": 7 * 24 * 3600,
    "teams": 7 * 24 * 3600,
    "pbp": 6 * 3600,
}


def _ensure() -> None:
    if nflreadpy is None:
        raise RuntimeError("nflreadpy is required")


def _to_polars(obj) -> pl.DataFrame:
    if isinstance(obj, pl.DataFrame):
        return obj
    # pandas fallback
    return pl.from_pandas(obj)


def load_schedules(cache: CacheStore, seasons: list[int], no_cache: bool = False) -> pl.DataFrame:
    key = f"schedules_{'_'.join(map(str, seasons))}"

    def loader():
        _ensure()
        return _to_polars(nflreadpy.load_schedules(seasons=seasons))

    df, _ = cache.fetch_parquet(key, TTL["schedules"], loader, no_cache=no_cache)
    return df


def load_player_stats(cache: CacheStore, seasons: list[int], no_cache: bool = False) -> pl.DataFrame:
    key = f"player_stats_{'_'.join(map(str, seasons))}"

    def loader():
        _ensure()
        return _to_polars(nflreadpy.load_player_stats(seasons=seasons))

    df, _ = cache.fetch_parquet(key, TTL["player_stats"], loader, no_cache=no_cache)
    return df


def load_team_stats(cache: CacheStore, seasons: list[int], no_cache: bool = False) -> pl.DataFrame:
    key = f"team_stats_{'_'.join(map(str, seasons))}"

    def loader():
        _ensure()
        return _to_polars(nflreadpy.load_team_stats(seasons=seasons))

    df, _ = cache.fetch_parquet(key, TTL["team_stats"], loader, no_cache=no_cache)
    return df


def load_snap_counts(cache: CacheStore, seasons: list[int], no_cache: bool = False) -> pl.DataFrame:
    key = f"snap_counts_{'_'.join(map(str, seasons))}"

    def loader():
        _ensure()
        return _to_polars(nflreadpy.load_snap_counts(seasons=seasons))

    df, _ = cache.fetch_parquet(key, TTL["snap_counts"], loader, no_cache=no_cache)
    return df


def load_injuries(cache: CacheStore, seasons: list[int], no_cache: bool = False) -> pl.DataFrame:
    key = f"injuries_{'_'.join(map(str, seasons))}"

    def loader():
        _ensure()
        return _to_polars(nflreadpy.load_injuries(seasons=seasons))

    df, _ = cache.fetch_parquet(key, TTL["injuries"], loader, no_cache=no_cache)
    return df


def load_depth_charts(cache: CacheStore, seasons: list[int], no_cache: bool = False) -> pl.DataFrame:
    key = f"depth_charts_{'_'.join(map(str, seasons))}"

    def loader():
        _ensure()
        return _to_polars(nflreadpy.load_depth_charts(seasons=seasons))

    df, _ = cache.fetch_parquet(key, TTL["depth_charts"], loader, no_cache=no_cache)
    return df


def load_pbp(cache: CacheStore, seasons: list[int], no_cache: bool = False) -> pl.DataFrame:
    key = f"pbp_{'_'.join(map(str, seasons))}"

    def loader():
        _ensure()
        return _to_polars(nflreadpy.load_pbp(seasons=seasons))

    df, _ = cache.fetch_parquet(key, TTL["pbp"], loader, no_cache=no_cache)
    return df


def load_players_cached(cache: CacheStore, no_cache: bool = False) -> pl.DataFrame:
    key = "players"

    def loader():
        _ensure()
        return _to_polars(nflreadpy.load_players())

    df, _ = cache.fetch_parquet(key, TTL["players"], loader, no_cache=no_cache)
    return df


def load_teams_cached(cache: CacheStore, no_cache: bool = False) -> pl.DataFrame:
    key = "teams_logos"

    def loader():
        _ensure()
        return _to_polars(nflreadpy.load_teams())

    df, _ = cache.fetch_parquet(key, TTL["teams"], loader, no_cache=no_cache)
    return df


def team_logo_map(teams_df: pl.DataFrame, aliases: dict[str, str] | None = None) -> dict[str, str]:
    """team abbr -> logo URL."""
    from brady_bot.normalizer import normalize_team

    aliases = aliases or {}
    if teams_df.is_empty():
        return {}
    abbr_col = next(
        (c for c in ("team_abbr", "abbr", "team", "club_code") if c in teams_df.columns),
        None,
    )
    logo_col = next(
        (
            c
            for c in (
                "team_logo_espn",
                "team_logo_wikipedia",
                "logo",
                "team_logo",
            )
            if c in teams_df.columns
        ),
        None,
    )
    if not abbr_col or not logo_col:
        return {}
    out: dict[str, str] = {}
    for r in teams_df.to_dicts():
        abbr = normalize_team(str(r.get(abbr_col) or ""), aliases)
        url = r.get(logo_col)
        if abbr and url:
            out[abbr] = str(url)
    return out
