from __future__ import annotations

import logging
from typing import Any, Dict, List

from aws_sso_lite.sso import AWSSSO
from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurable AWS SSO config store
# ---------------------------------------------------------------------------

_aws_sso_config: List[Dict[str, Any]] = []


def set_aws_sso_config(config: List[Dict[str, Any]]) -> None:
    """Set the AWS SSO configuration list.

    Each entry should contain at least ``instance``, ``ssoRegion``,
    ``ssoStartUrl``, and ``domain`` keys.  Call this once at application
    startup before any SSO operations are performed.
    """
    global _aws_sso_config
    _aws_sso_config = list(config)


def get_aws_config(aws_sso_instance: str) -> Dict[str, Any]:
    """Look up a single SSO configuration entry by instance name."""
    sc = next((item for item in _aws_sso_config if aws_sso_instance in item["instance"]), None)
    if sc is None:
        raise ValueError(f"Could not find AWS SSO configuration for instance: {aws_sso_instance}")
    return sc


def get_awssso(aws_sso_instance: str) -> AWSSSO:
    """Create an ``AWSSSO`` helper for the given instance name."""
    sc = get_aws_config(aws_sso_instance)
    sso_region = sc.get("ssoRegion")
    sso_start_url = sc.get("ssoStartUrl")
    return AWSSSO(sso_start_url, sso_region)


# ---------------------------------------------------------------------------
# FastAPI router factory – default prefix: /api/auth
# ---------------------------------------------------------------------------

DEFAULT_PREFIX = "/api/auth"


async def _get_aws_sso(request: Request):
    headers = request.headers
    aws_sso_instance = headers.get("X-Aws-Sso-Instance")
    return get_awssso(aws_sso_instance)


def create_router(prefix: str = DEFAULT_PREFIX) -> APIRouter:
    """Create an auth router with a custom prefix."""
    r = APIRouter(prefix=prefix)

    @r.get("/aws-sso/status")
    async def check_aws_sso_status(aws_sso=Depends(_get_aws_sso)):
        return {"aws": aws_sso.has_valid_access_token()}

    @r.get("/aws-sso/accounts")
    async def list_aws_accounts(aws_sso=Depends(_get_aws_sso)):
        account_infos = {}
        account_infos["accounts"] = await run_in_threadpool(aws_sso.get_aws_accounts)
        return account_infos

    @r.get("/aws-sso/account-roles")
    async def list_aws_account_roles(
        aws_sso=Depends(_get_aws_sso),
        account_id=Query(..., alias="accountId"),
    ):
        return await run_in_threadpool(aws_sso.get_aws_account_roles, account_id=account_id)

    @r.post("/aws-sso/start-device-authorization")
    async def start_device_authorization(aws_sso=Depends(_get_aws_sso)):
        return await run_in_threadpool(aws_sso.start_device_authorization)

    @r.post("/aws-sso/create-token")
    async def create_token(data=Body(...), aws_sso=Depends(_get_aws_sso)):
        device_code = data.get("deviceCode")
        if device_code:
            return await run_in_threadpool(aws_sso.create_token, device_code)
        else:
            return JSONResponse({"status": "error", "error": "deviceCode is required"}, status_code=400)

    return r


router = create_router()
