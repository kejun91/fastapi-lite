from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from fastapi_lite.log import add_uvicorn_like_access_log, format_status, get_logger


# --- format_status ---


def test_format_status_200():
    result = format_status(200)
    assert "200" in result
    assert "OK" in result


def test_format_status_404():
    result = format_status(404)
    assert "404" in result
    assert "Not Found" in result


def test_format_status_500():
    result = format_status(500)
    assert "500" in result
    assert "Internal Server Error" in result


def test_format_status_301():
    result = format_status(301)
    assert "301" in result


def test_format_status_unknown():
    result = format_status(999)
    assert "999" in result
    assert "UNKNOWN" in result


# --- get_logger ---


def test_get_logger_returns_logger():
    logger = get_logger("test_log_module")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test_log_module"
    assert logger.level == logging.DEBUG


def test_get_logger_default_name():
    logger = get_logger()
    assert logger.name == "fastapi_lite"


# --- access log middleware ---


@pytest.fixture
def app_with_log():
    app = FastAPI()
    add_uvicorn_like_access_log(app, logger_name="test_access")

    @app.get("/ping")
    async def ping():
        return {"pong": True}

    @app.get("/error")
    async def error():
        raise RuntimeError("boom")

    return app


async def test_access_log_200(app_with_log, caplog):
    transport = ASGITransport(app=app_with_log)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/ping")
    assert resp.status_code == 200
    assert resp.json() == {"pong": True}


async def test_access_log_404(app_with_log):
    transport = ASGITransport(app=app_with_log)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/nonexistent")
    assert resp.status_code == 404


async def test_access_log_with_query_string(app_with_log):
    transport = ASGITransport(app=app_with_log)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/ping?foo=bar")
    assert resp.status_code == 200
