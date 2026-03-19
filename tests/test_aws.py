from __future__ import annotations

import json
import sys
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


# --- BotoJSONEncoder ---
# Import session directly (it requires httplite at import time).
# If httplite is not installed / wrong version, mock it so we can still test
# the encoder and helpers.

_httplite_stub = MagicMock()
if "httplite" not in sys.modules:
    sys.modules["httplite"] = _httplite_stub

from fastapi_lite.aws.session import BotoJSONEncoder, remove_none_values  # noqa: E402
from fastapi_lite.aws.botocore import create_router as create_botocore_router  # noqa: E402


# --- BotoJSONEncoder ---


def test_encoder_datetime():
    dt = datetime(2025, 1, 15, 12, 30, 0)
    result = json.loads(json.dumps({"ts": dt}, cls=BotoJSONEncoder))
    assert result["ts"] == "2025-01-15T12:30:00"


def test_encoder_bytes():
    result = json.loads(json.dumps({"data": b"hello"}, cls=BotoJSONEncoder))
    assert result["data"] == "aGVsbG8="  # base64("hello")


def test_encoder_decimal_int():
    result = json.loads(json.dumps({"n": Decimal("42")}, cls=BotoJSONEncoder))
    assert result["n"] == 42


def test_encoder_decimal_float():
    result = json.loads(json.dumps({"n": Decimal("3.14")}, cls=BotoJSONEncoder))
    assert result["n"] == pytest.approx(3.14)


def test_encoder_regular_types():
    data = {"s": "hello", "i": 1, "f": 2.5, "b": True, "n": None}
    result = json.loads(json.dumps(data, cls=BotoJSONEncoder))
    assert result == data


# --- Botocore router ---


@pytest.fixture
def botocore_app():
    app = FastAPI()
    app.include_router(create_botocore_router())
    return app


async def test_botocore_version(botocore_app):
    transport = ASGITransport(app=botocore_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/botocore/version")
    assert resp.status_code == 200
    assert "botocore_version" in resp.json()


async def test_botocore_available_services(botocore_app):
    transport = ASGITransport(app=botocore_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/botocore/available-services")
    assert resp.status_code == 200
    services = resp.json()
    assert isinstance(services, list)
    assert len(services) > 0
    assert "service_name" in services[0]


async def test_botocore_available_regions(botocore_app):
    transport = ASGITransport(app=botocore_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/botocore/available-regions/s3/aws")
    assert resp.status_code == 200
    regions = resp.json()
    assert isinstance(regions, list)
    assert "us-east-1" in regions


async def test_botocore_service_model(botocore_app):
    transport = ASGITransport(app=botocore_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/botocore/service-model/s3")
    assert resp.status_code == 200
    data = resp.json()
    assert "serviceModel" in data
    assert "pythonicOperationNames" in data


async def test_botocore_endpoints(botocore_app):
    transport = ASGITransport(app=botocore_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/botocore/endpoints")
    assert resp.status_code == 200


async def test_botocore_custom_prefix():
    app = FastAPI()
    app.include_router(create_botocore_router(prefix="/v2/botocore"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v2/botocore/version")
    assert resp.status_code == 200


# --- Auth config helpers ---


def test_set_and_get_aws_config():
    from fastapi_lite.aws.auth import get_aws_config, set_aws_sso_config

    set_aws_sso_config([
        {"instance": "test-aws", "ssoRegion": "us-east-1", "ssoStartUrl": "https://example.com", "domain": "aws.amazon.com"},
    ])
    cfg = get_aws_config("test-aws")
    assert cfg["ssoRegion"] == "us-east-1"


def test_get_aws_config_not_found():
    from fastapi_lite.aws.auth import get_aws_config, set_aws_sso_config

    set_aws_sso_config([])
    with pytest.raises(ValueError, match="Could not find"):
        get_aws_config("nonexistent")


# --- session helpers ---


def test_remove_none_values():
    assert remove_none_values({"a": 1, "b": None, "c": 3}) == {"a": 1, "c": 3}
    assert remove_none_values({}) == {}
    assert remove_none_values({"x": None}) == {}
