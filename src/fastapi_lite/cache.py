"""SQLite-backed cache with TTL support and an optional FastAPI router."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body
from fastapi.concurrency import run_in_threadpool


# ---------------------------------------------------------------------------
# Core cache classes
# ---------------------------------------------------------------------------


class CacheStore:
    """A single-namespace SQLite-backed key/value store with optional TTL."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._init_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return

        with self._init_lock:
            if self._initialized:
                return

            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = self._connect()
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA temp_store=MEMORY")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cache (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at INTEGER,
                        expires_at INTEGER
                    )
                    """
                )
                conn.commit()
                self._initialized = True
            finally:
                conn.close()

    def set_item(self, key: str, value: Any, ttl_ms: Optional[int] = None) -> None:
        self._ensure_initialized()
        now = int(time.time() * 1000)
        expires_at = now + ttl_ms if ttl_ms else None
        payload = json.dumps(value, ensure_ascii=False)

        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO cache (key, value, updated_at, expires_at) VALUES (?, ?, ?, ?)",
                    (key, payload, now, expires_at),
                )
                conn.commit()
            finally:
                conn.close()

    def get_item(self, key: str) -> Optional[Dict[str, Any]]:
        self._ensure_initialized()
        now = int(time.time() * 1000)

        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT value, updated_at, expires_at FROM cache WHERE key = ?",
                (key,),
            ).fetchone()
            if not row:
                return None

            expires_at = row["expires_at"]
            if expires_at is not None and expires_at <= now:
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                conn.commit()
                return None

            return {
                "value": json.loads(row["value"]),
                "updatedAt": row["updated_at"],
                "expiresAt": row["expires_at"],
            }
        finally:
            conn.close()

    def remove_item(self, key: str) -> None:
        self._ensure_initialized()
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                conn.commit()
            finally:
                conn.close()

    def clear_all(self) -> None:
        self._ensure_initialized()
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM cache")
                conn.commit()
            finally:
                conn.close()

    def clear_by_prefix(self, prefix: str) -> None:
        self._ensure_initialized()
        pattern = f"{prefix}:%"
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM cache WHERE key LIKE ?", (pattern,))
                conn.commit()
            finally:
                conn.close()

    def get_latest_timestamp(self, prefix: str) -> Optional[int]:
        self._ensure_initialized()
        pattern = f"{prefix}:%"
        now = int(time.time() * 1000)

        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT MAX(updated_at) AS latest
                FROM cache
                WHERE key LIKE ?
                  AND (expires_at IS NULL OR expires_at > ?)
                """,
                (pattern, now),
            ).fetchone()
            return row["latest"] if row and row["latest"] is not None else None
        finally:
            conn.close()

    def get_items_by_prefix(
        self,
        prefix: str,
        key_pattern: Optional[str] = None,
        key_pattern_flags: str = "",
    ) -> List[Dict[str, Any]]:
        self._ensure_initialized()
        pattern = f"{prefix}:%"
        now = int(time.time() * 1000)
        flags = 0
        if "i" in key_pattern_flags:
            flags |= re.IGNORECASE
        if "m" in key_pattern_flags:
            flags |= re.MULTILINE
        if "s" in key_pattern_flags:
            flags |= re.DOTALL
        compiled = re.compile(key_pattern, flags) if key_pattern else None

        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT key, value, updated_at, expires_at FROM cache WHERE key LIKE ?",
                (pattern,),
            ).fetchall()

            results: List[Dict[str, Any]] = []
            expired_keys: List[str] = []

            for row in rows:
                expires_at = row["expires_at"]
                if expires_at is not None and expires_at <= now:
                    expired_keys.append(row["key"])
                    continue
                if compiled and not compiled.search(row["key"]):
                    continue

                results.append(
                    {
                        "key": row["key"],
                        "value": json.loads(row["value"]),
                        "updatedAt": row["updated_at"],
                        "expiresAt": row["expires_at"],
                    }
                )

            if expired_keys:
                with self._write_lock:
                    conn.executemany(
                        "DELETE FROM cache WHERE key = ?",
                        [(key,) for key in expired_keys],
                    )
                    conn.commit()

            return results
        finally:
            conn.close()

    def list_items(
        self,
        limit: int = 100,
        offset: int = 0,
        key_contains: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._ensure_initialized()
        now = int(time.time() * 1000)
        like_value = f"%{key_contains}%" if key_contains else "%"

        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM cache WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now,),
            )
            conn.commit()

            total_row = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM cache
                WHERE (expires_at IS NULL OR expires_at > ?)
                  AND key LIKE ?
                """,
                (now, like_value),
            ).fetchone()

            rows = conn.execute(
                """
                SELECT key, value, updated_at, expires_at
                FROM cache
                WHERE (expires_at IS NULL OR expires_at > ?)
                  AND key LIKE ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (now, like_value, limit, offset),
            ).fetchall()

            items = [
                {
                    "key": row["key"],
                    "value": json.loads(row["value"]),
                    "updatedAt": row["updated_at"],
                    "expiresAt": row["expires_at"],
                }
                for row in rows
            ]

            return {"items": items, "total": total_row["total"] if total_row else 0}
        finally:
            conn.close()


class CacheManager:
    """Manages multiple :class:`CacheStore` instances keyed by namespace."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._lock = threading.Lock()
        self._stores: Dict[str, CacheStore] = {}

    @staticmethod
    def _sanitize_namespace(namespace: str) -> str:
        if not namespace:
            return "default"
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in namespace.strip())
        return safe or "default"

    def get_store(self, namespace: str) -> CacheStore:
        safe_namespace = self._sanitize_namespace(namespace)
        with self._lock:
            store = self._stores.get(safe_namespace)
            if store:
                return store

            db_path = self._base_dir / f"{safe_namespace}.sqlite3"
            store = CacheStore(db_path)
            self._stores[safe_namespace] = store
            return store

    def list_namespaces(self) -> List[str]:
        self._base_dir.mkdir(parents=True, exist_ok=True)
        namespaces = []
        for path in self._base_dir.glob("*.sqlite3"):
            namespaces.append(path.stem)
        if not namespaces:
            namespaces.append("default")
        return sorted(set(namespaces))


# ---------------------------------------------------------------------------
# FastAPI router – /api/cache
# ---------------------------------------------------------------------------

_cache_manager: Optional[CacheManager] = None


def set_cache_manager(manager: CacheManager) -> None:
    """Set the global cache manager used by the router."""
    global _cache_manager
    _cache_manager = manager


def get_cache_manager() -> CacheManager:
    """Return the current cache manager, creating a default one if needed."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager(Path.home() / ".fastapi_lite" / "cache")
    return _cache_manager


def _get_store(namespace: str) -> CacheStore:
    return get_cache_manager().get_store(namespace)


DEFAULT_PREFIX = "/api/cache"


def create_router(prefix: str = DEFAULT_PREFIX) -> APIRouter:
    """Create a cache router with a custom prefix."""
    r = APIRouter(prefix=prefix)

    @r.get("/namespaces")
    async def list_namespaces():
        namespaces = await run_in_threadpool(get_cache_manager().list_namespaces)
        return {"namespaces": namespaces}

    @r.post("/{namespace}/set")
    async def set_item(namespace: str, data=Body(...)):
        key = data.get("key")
        value = data.get("value")
        ttl_ms = data.get("ttlMs")
        store = _get_store(namespace)
        await run_in_threadpool(store.set_item, key, value, ttl_ms)
        return {"ok": True}

    @r.post("/{namespace}/get")
    async def get_item(namespace: str, data=Body(...)):
        key = data.get("key")
        store = _get_store(namespace)
        result = await run_in_threadpool(store.get_item, key)
        return result or {"value": None}

    @r.post("/{namespace}/get-with-meta")
    async def get_item_with_meta(namespace: str, data=Body(...)):
        key = data.get("key")
        store = _get_store(namespace)
        result = await run_in_threadpool(store.get_item, key)
        return result or {"value": None}

    @r.post("/{namespace}/remove")
    async def remove_item(namespace: str, data=Body(...)):
        key = data.get("key")
        store = _get_store(namespace)
        await run_in_threadpool(store.remove_item, key)
        return {"ok": True}

    @r.post("/{namespace}/clear")
    async def clear_all(namespace: str):
        store = _get_store(namespace)
        await run_in_threadpool(store.clear_all)
        return {"ok": True}

    @r.post("/{namespace}/clear-by-prefix")
    async def clear_by_prefix(namespace: str, data=Body(...)):
        prefix = data.get("prefix")
        store = _get_store(namespace)
        await run_in_threadpool(store.clear_by_prefix, prefix)
        return {"ok": True}

    @r.post("/{namespace}/latest-timestamp")
    async def latest_timestamp(namespace: str, data=Body(...)):
        prefix = data.get("prefix")
        store = _get_store(namespace)
        timestamp = await run_in_threadpool(store.get_latest_timestamp, prefix)
        return {"timestamp": timestamp}

    @r.post("/{namespace}/items-by-prefix")
    async def items_by_prefix(namespace: str, data=Body(...)):
        prefix = data.get("prefix")
        key_pattern = data.get("keyPattern")
        key_pattern_flags = data.get("keyPatternFlags", "")
        store = _get_store(namespace)
        items = await run_in_threadpool(
            store.get_items_by_prefix,
            prefix,
            key_pattern,
            key_pattern_flags,
        )
        return {"items": items}

    @r.post("/{namespace}/items")
    async def list_items(namespace: str, data=Body(...)):
        limit = data.get("limit", 100)
        offset = data.get("offset", 0)
        key_contains = data.get("keyContains")
        store = _get_store(namespace)
        result = await run_in_threadpool(store.list_items, limit, offset, key_contains)
        return result

    return r


router = create_router()
