from __future__ import annotations

import base64
from datetime import datetime, timezone
from decimal import Decimal
import json
import hashlib
import asyncio
import logging
from typing import Any, Dict, Optional

import boto3
from botocore.response import StreamingBody
from httplite import send_request
from urllib.parse import urlencode

from fastapi_lite.aws.auth import get_awssso

logger = logging.getLogger(__name__)


def remove_none_values(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


async def get_boto3_session(**authentication_info) -> boto3.session.Session:
    b3s = boto3.session.Session()

    if authentication_info is not None:
        t = authentication_info.get("authentication_type")
        if t == "sso":
            aws_sso_instance = authentication_info.get("aws_sso_instance")
            aws_account_id = authentication_info.get("aws_account_id")
            sso_role_name = authentication_info.get("sso_role_name")
            assumed_role_arn = authentication_info.get("assumed_role_arn")

            b3s = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: get_awssso(aws_sso_instance).get_boto3_session(
                    aws_account_id, sso_role_name, assumed_role_arn
                ),
            )

    return b3s


# In-flight request cache for deduplication
_in_flight_requests: Dict[str, asyncio.Future] = {}
_in_flight_lock = asyncio.Lock()


def _generate_request_hash(
    boto3_session: boto3.session.Session,
    aws_region: str,
    service: str,
    action: str,
    data: Any,
) -> str:
    creds = boto3_session.get_credentials()

    if creds is None:
        session_id = "anonymous"
    else:
        frozen_creds = creds.get_frozen_credentials()
        session_id = f"{frozen_creds.access_key}:{frozen_creds.secret_key}:{frozen_creds.token or ''}"

    request_key = f"{session_id}:{aws_region}:{service}:{action}:{json.dumps(data, sort_keys=True)}"
    return hashlib.sha256(request_key.encode()).hexdigest()


async def execute_aws_action(
    boto3_session: boto3.session.Session,
    aws_region: str,
    service: str,
    action: str,
    data: Any,
):
    """Execute an AWS API action with automatic request deduplication.

    If an identical request is already in-flight (same credentials, region,
    service, action, and parameters), this waits for and returns the result
    of the existing request instead of making a duplicate call.
    """
    request_hash = _generate_request_hash(boto3_session, aws_region, service, action, data)

    async with _in_flight_lock:
        if request_hash in _in_flight_requests:
            logger.debug("Deduplicating request: %s.%s (hash: %s...)", service, action, request_hash[:8])
            existing_future = _in_flight_requests[request_hash]
            return await existing_future

        future = asyncio.get_event_loop().create_future()
        _in_flight_requests[request_hash] = future

    try:
        def _execute():
            client = boto3_session.client(service, **remove_none_values({"region_name": aws_region}))
            return getattr(client, action)(**remove_none_values(data))

        logger.debug("Executing AWS request: %s.%s (hash: %s...)", service, action, request_hash[:8])
        result = await asyncio.get_event_loop().run_in_executor(None, _execute)

        future.set_result(result)
        return result

    except Exception as e:
        future.set_exception(e)
        raise

    finally:
        async with _in_flight_lock:
            _in_flight_requests.pop(request_hash, None)


class BotoJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles botocore/boto3 response types."""

    def default(self, obj):
        if isinstance(obj, StreamingBody):
            return obj.read().decode("utf-8", errors="replace")

        if isinstance(obj, datetime):
            return obj.isoformat()

        if isinstance(obj, bytes):
            return base64.b64encode(obj).decode()

        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)

        return super().default(obj)


_credentials: Dict[str, Any] = {}


async def fetch_signin_token(aws_domain: str, boto3_session: boto3.session.Session) -> Optional[str]:
    """Fetch a federation sign-in token for AWS Console access."""
    creds = boto3_session.get_credentials()
    key = f"signin-token-{aws_domain}-{hash(creds.access_key + creds.secret_key + creds.token)}"

    if key in _credentials:
        if _credentials[key].get("expiration") > int(datetime.now(tz=timezone.utc).timestamp() * 1000):
            return _credentials[key].get("SigninToken")

    encoded_session = urlencode(
        {
            "Session": json.dumps(
                {
                    "sessionId": creds.access_key,
                    "sessionKey": creds.secret_key,
                    "sessionToken": creds.token,
                }
            )
        }
    )

    get_signin_token_endpoint = f"https://signin.{aws_domain}/federation?Action=getSigninToken&{encoded_session}"

    res = await send_request("GET", get_signin_token_endpoint)

    _credentials[key] = {
        "expiration": int(datetime.now(tz=timezone.utc).timestamp() * 1000) + 600000,
        "SigninToken": res.json().get("SigninToken"),
    }

    return res.json().get("SigninToken")
