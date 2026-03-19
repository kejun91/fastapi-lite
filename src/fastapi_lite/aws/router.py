from __future__ import annotations

import base64
import json
import logging
from typing import Optional
from urllib.parse import quote, unquote, urlparse

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from fastapi_lite.aws.auth import get_aws_config
from fastapi_lite.aws.session import (
    BotoJSONEncoder,
    execute_aws_action,
    fetch_signin_token,
    get_boto3_session,
    remove_none_values,
)

logger = logging.getLogger(__name__)

DEFAULT_PREFIX = "/aws"


def create_router(prefix: str = DEFAULT_PREFIX) -> APIRouter:
    """Create an AWS proxy router with a custom prefix."""
    r = APIRouter(prefix=prefix)

    @r.post("/{aws_account_alias}/b3/{service}/{action}")
    async def proxy_aws_action(aws_account_alias: str, service: str, action: str, request: Request):
        try:
            body = await request.json()
            authentication_info = body.get("authenticationInfo")
            aws_region = body.get("awsRegion")
            data = body.get("data")

            b3s = await get_boto3_session(**remove_none_values(authentication_info))
            res = await execute_aws_action(b3s, aws_region, service, action, data)

            return Response(content=json.dumps(res, cls=BotoJSONEncoder), media_type="application/json")
        except Exception as e:
            logger.exception("Error proxying AWS action", exc_info=e)
            return JSONResponse({"error": "view console logs for details"}, status_code=500)

    @r.get("/{aws_account_alias}/console/{base_path}")
    async def aws_console(
        aws_account_alias: str,
        base_path: str,
        auth_type: str = Query(..., alias="auth_type"),
        aws_sso_instance: str = Query(..., alias="aws_sso_instance"),
        aws_account_id: str = Query(..., alias="account_id"),
        sso_role_name: str = Query(..., alias="sso_role_name"),
        assumed_role_arn: str = Query(None, alias="assume_role_name"),
        aws_multi_session_enabled: bool = Query(False, alias="aws_multi_session_enabled"),
        destination_path: Optional[str] = Query(None, alias="destination_path"),
        aws_region: Optional[str] = Query(..., alias="aws_region"),
    ):
        if auth_type not in ["cognito", "sso"]:
            return RedirectResponse("/")

        b3s = await get_boto3_session(
            **remove_none_values(
                {
                    "authentication_type": auth_type,
                    "aws_sso_instance": aws_sso_instance,
                    "aws_account_id": aws_account_id,
                    "sso_role_name": sso_role_name,
                    "assumed_role_arn": assumed_role_arn,
                }
            )
        )

        sanitized_destination_path = "/console/home"

        if destination_path is not None:
            decoded_destination_path = base64.b64decode(unquote(destination_path)).decode("utf-8")
            if decoded_destination_path.startswith("/"):
                sanitized_destination_path = decoded_destination_path

        aws_config = get_aws_config(aws_sso_instance)
        aws_domain = aws_config.get("domain")
        sso_region = aws_config.get("ssoRegion")

        validated_aws_region = aws_region if aws_region is not None else None

        signin_token = await fetch_signin_token(aws_domain, b3s)
        destination_url = f"https://{(validated_aws_region + '.') if validated_aws_region is not None else ''}console.{aws_domain}{sanitized_destination_path}"
        signin_url = f"https://{sso_region}.signin.{aws_domain}/federation?Action=login&Destination={quote(destination_url, safe='')}&SigninToken={signin_token}"

        url = (
            signin_url
            if aws_multi_session_enabled
            else f"https://signin.{aws_domain}/oauth?Action=logout&redirect_uri={quote(signin_url, safe='')}"
        )

        parsed = urlparse(url)
        safe_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.query:
            safe_url += f"?{parsed.query}"
        if parsed.fragment:
            safe_url += f"#{parsed.fragment}"

        return RedirectResponse(safe_url)

    return r


router = create_router()
