from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

import polars as pl

from brady_bot.paths import CACHE_DIR, ensure_dirs


class CacheStore:
    def __init__(self, root: Path | None = None):
        ensure_dirs()
        self.root = root or CACHE_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def _meta_path(self, key: str) -> Path:
        return self.root / f"{key}.meta.json"

    def _data_path(self, key: str, fmt: str) -> Path:
        return self.root / f"{key}.{fmt}"

    def get_parquet(self, key: str, ttl_seconds: int) -> Optional[pl.DataFrame]:
        meta_p = self._meta_path(key)
        data_p = self._data_path(key, "parquet")
        if not meta_p.exists() or not data_p.exists():
            return None
        meta = json.loads(meta_p.read_text())
        age = time.time() - float(meta.get("fetched_at", 0))
        if age > ttl_seconds:
            return None
        return pl.read_parquet(data_p)

    def get_parquet_stale(self, key: str) -> Optional[pl.DataFrame]:
        data_p = self._data_path(key, "parquet")
        if data_p.exists():
            return pl.read_parquet(data_p)
        return None

    def set_parquet(self, key: str, df: pl.DataFrame) -> None:
        data_p = self._data_path(key, "parquet")
        meta_p = self._meta_path(key)
        df.write_parquet(data_p)
        meta_p.write_text(json.dumps({"fetched_at": time.time()}))

    def get_json(self, key: str, ttl_seconds: int) -> Optional[Any]:
        meta_p = self._meta_path(key)
        data_p = self._data_path(key, "json")
        if not meta_p.exists() or not data_p.exists():
            return None
        meta = json.loads(meta_p.read_text())
        if time.time() - float(meta.get("fetched_at", 0)) > ttl_seconds:
            return None
        return json.loads(data_p.read_text())

    def get_json_stale(self, key: str) -> Optional[Any]:
        data_p = self._data_path(key, "json")
        if data_p.exists():
            return json.loads(data_p.read_text())
        return None

    def set_json(self, key: str, payload: Any) -> None:
        data_p = self._data_path(key, "json")
        meta_p = self._meta_path(key)
        data_p.write_text(json.dumps(payload))
        meta_p.write_text(json.dumps({"fetched_at": time.time()}))

    def fetch_parquet(
        self,
        key: str,
        ttl_seconds: int,
        loader: Callable[[], pl.DataFrame],
        no_cache: bool = False,
    ) -> tuple[pl.DataFrame, bool]:
        """Returns (df, used_stale)."""
        if not no_cache:
            cached = self.get_parquet(key, ttl_seconds)
            if cached is not None:
                return cached, False
        try:
            df = self._retry(loader)
            self.set_parquet(key, df)
            return df, False
        except Exception:
            stale = self.get_parquet_stale(key)
            if stale is not None:
                return stale, True
            raise

    def fetch_json(
        self,
        key: str,
        ttl_seconds: int,
        loader: Callable[[], Any],
        no_cache: bool = False,
    ) -> tuple[Any, bool]:
        if not no_cache:
            cached = self.get_json(key, ttl_seconds)
            if cached is not None:
                return cached, False
        try:
            payload = self._retry(loader)
            self.set_json(key, payload)
            return payload, False
        except Exception:
            stale = self.get_json_stale(key)
            if stale is not None:
                return stale, True
            raise

    @staticmethod
    def _retry(fn: Callable[[], Any], attempts: int = 3) -> Any:
        delay = 0.5
        last = None
        for _ in range(attempts):
            try:
                return fn()
            except Exception as e:
                last = e
                time.sleep(delay)
                delay *= 2
        raise last  # type: ignore[misc]
