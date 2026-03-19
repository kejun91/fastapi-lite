from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from fastapi_lite.cache import CacheManager, CacheStore, create_router, set_cache_manager


# --- CacheStore ---


@pytest.fixture
def store(tmp_path):
    return CacheStore(tmp_path / "test.sqlite3")


def test_set_and_get(store):
    store.set_item("k1", {"hello": "world"})
    result = store.get_item("k1")
    assert result is not None
    assert result["value"] == {"hello": "world"}
    assert result["updatedAt"] is not None


def test_get_missing_key(store):
    assert store.get_item("nonexistent") is None


def test_set_overwrite(store):
    store.set_item("k1", "first")
    store.set_item("k1", "second")
    assert store.get_item("k1")["value"] == "second"


def test_remove_item(store):
    store.set_item("k1", "val")
    store.remove_item("k1")
    assert store.get_item("k1") is None


def test_clear_all(store):
    store.set_item("a", 1)
    store.set_item("b", 2)
    store.clear_all()
    assert store.get_item("a") is None
    assert store.get_item("b") is None


def test_ttl_expires(store):
    store.set_item("k1", "val", ttl_ms=1)
    time.sleep(0.01)
    assert store.get_item("k1") is None


def test_ttl_not_expired(store):
    store.set_item("k1", "val", ttl_ms=60000)
    assert store.get_item("k1")["value"] == "val"


def test_clear_by_prefix(store):
    store.set_item("ns:a", 1)
    store.set_item("ns:b", 2)
    store.set_item("other:c", 3)
    store.clear_by_prefix("ns")
    assert store.get_item("ns:a") is None
    assert store.get_item("ns:b") is None
    assert store.get_item("other:c") is not None


def test_get_latest_timestamp(store):
    store.set_item("ns:a", 1)
    time.sleep(0.01)
    store.set_item("ns:b", 2)
    ts = store.get_latest_timestamp("ns")
    assert ts is not None
    assert ts == store.get_item("ns:b")["updatedAt"]


def test_get_items_by_prefix(store):
    store.set_item("ns:x", 10)
    store.set_item("ns:y", 20)
    store.set_item("other:z", 30)
    items = store.get_items_by_prefix("ns")
    assert len(items) == 2
    keys = {i["key"] for i in items}
    assert keys == {"ns:x", "ns:y"}


def test_get_items_by_prefix_with_pattern(store):
    store.set_item("ns:alpha", 1)
    store.set_item("ns:beta", 2)
    items = store.get_items_by_prefix("ns", key_pattern="alpha")
    assert len(items) == 1
    assert items[0]["key"] == "ns:alpha"


def test_list_items(store):
    store.set_item("a", 1)
    store.set_item("b", 2)
    store.set_item("c", 3)
    result = store.list_items(limit=2, offset=0)
    assert result["total"] == 3
    assert len(result["items"]) == 2


def test_list_items_key_contains(store):
    store.set_item("foo-bar", 1)
    store.set_item("baz-qux", 2)
    result = store.list_items(key_contains="foo")
    assert result["total"] == 1
    assert result["items"][0]["key"] == "foo-bar"


# --- CacheManager ---


def test_manager_get_store(tmp_path):
    mgr = CacheManager(tmp_path)
    s1 = mgr.get_store("ns1")
    s2 = mgr.get_store("ns1")
    assert s1 is s2


def test_manager_different_namespaces(tmp_path):
    mgr = CacheManager(tmp_path)
    s1 = mgr.get_store("one")
    s2 = mgr.get_store("two")
    assert s1 is not s2


def test_manager_sanitize_namespace(tmp_path):
    mgr = CacheManager(tmp_path)
    s = mgr.get_store("my namespace!!")
    assert s is not None


def test_manager_list_namespaces(tmp_path):
    mgr = CacheManager(tmp_path)
    store = mgr.get_store("alpha")
    store.set_item("k", "v")
    namespaces = mgr.list_namespaces()
    assert "alpha" in namespaces


def test_manager_list_namespaces_default(tmp_path):
    mgr = CacheManager(tmp_path / "empty")
    namespaces = mgr.list_namespaces()
    assert namespaces == ["default"]


# --- Router (factory + endpoints) ---


@pytest.fixture
def cache_app(tmp_path):
    mgr = CacheManager(tmp_path)
    set_cache_manager(mgr)

    app = FastAPI()
    app.include_router(create_router())
    return app


async def test_router_namespaces(cache_app):
    transport = ASGITransport(app=cache_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/cache/namespaces")
    assert resp.status_code == 200
    assert "namespaces" in resp.json()


async def test_router_set_and_get(cache_app):
    transport = ASGITransport(app=cache_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/cache/test/set", json={"key": "k1", "value": "hello"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        resp = await client.post("/api/cache/test/get", json={"key": "k1"})
        assert resp.status_code == 200
        assert resp.json()["value"] == "hello"


async def test_router_remove(cache_app):
    transport = ASGITransport(app=cache_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/cache/test/set", json={"key": "k1", "value": "v"})
        resp = await client.post("/api/cache/test/remove", json={"key": "k1"})
        assert resp.json()["ok"] is True

        resp = await client.post("/api/cache/test/get", json={"key": "k1"})
        assert resp.json()["value"] is None


async def test_router_clear(cache_app):
    transport = ASGITransport(app=cache_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/cache/test/set", json={"key": "a", "value": 1})
        resp = await client.post("/api/cache/test/clear")
        assert resp.json()["ok"] is True

        resp = await client.post("/api/cache/test/get", json={"key": "a"})
        assert resp.json()["value"] is None


async def test_router_custom_prefix(tmp_path):
    mgr = CacheManager(tmp_path)
    set_cache_manager(mgr)

    app = FastAPI()
    app.include_router(create_router(prefix="/v2/cache"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v2/cache/namespaces")
    assert resp.status_code == 200


async def test_router_items(cache_app):
    transport = ASGITransport(app=cache_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/cache/ns/set", json={"key": "x", "value": 1})
        resp = await client.post("/api/cache/ns/items", json={"limit": 10, "offset": 0})
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1
