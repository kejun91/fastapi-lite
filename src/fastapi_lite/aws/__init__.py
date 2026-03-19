"""AWS utilities: session management, authentication, botocore models, and FastAPI routers."""

from fastapi_lite.aws.session import (
    BotoJSONEncoder,
    execute_aws_action,
    fetch_signin_token,
    get_boto3_session,
)
from fastapi_lite.aws.auth import get_awssso, set_aws_sso_config
from fastapi_lite.aws.botocore import create_router as create_botocore_router
from fastapi_lite.aws.botocore import router as botocore_router
from fastapi_lite.aws.router import create_router as create_aws_router
from fastapi_lite.aws.router import router as aws_router
from fastapi_lite.aws.auth import create_router as create_auth_router
from fastapi_lite.aws.auth import router as auth_router

__all__ = [
    "BotoJSONEncoder",
    "execute_aws_action",
    "fetch_signin_token",
    "get_boto3_session",
    "get_awssso",
    "set_aws_sso_config",
    "create_botocore_router",
    "create_aws_router",
    "create_auth_router",
    "botocore_router",
    "aws_router",
    "auth_router",
]
