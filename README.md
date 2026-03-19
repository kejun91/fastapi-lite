# fastapi-lite

Reusable FastAPI utilities extracted for shared use: AWS helpers (boto3 session, botocore models, SSO auth), SQLite-backed cache, and uvicorn-style access logging.

## Installation

```bash
pip install fastapi-lite
```

With AWS support (boto3, aws_sso_lite, httplite):

```bash
pip install fastapi-lite[aws]
```

## Modules

### `fastapi_lite.log` — Access logging

Drop-in uvicorn-style HTTP access-log middleware:

```python
from fastapi import FastAPI
from fastapi_lite.log import add_uvicorn_like_access_log

app = FastAPI()
add_uvicorn_like_access_log(app)
```

### `fastapi_lite.cache` — SQLite cache

Namespace-based SQLite cache with TTL, plus a ready-to-include FastAPI router:

```python
from pathlib import Path
from fastapi_lite.cache import CacheManager, CacheStore, router as cache_router, set_cache_manager

# Optionally configure cache directory (defaults to ~/.fastapi_lite/cache)
set_cache_manager(CacheManager(Path.home() / ".myapp" / "cache"))

app.include_router(cache_router)
```

Use the store directly:

```python
from fastapi_lite.cache import CacheManager
from pathlib import Path

manager = CacheManager(Path("/tmp/cache"))
store = manager.get_store("my-namespace")
store.set_item("key", {"hello": "world"}, ttl_ms=60000)
print(store.get_item("key"))
```

### `fastapi_lite.aws` — AWS helpers

Requires the `aws` extra: `pip install fastapi-lite[aws]`

```python
from fastapi_lite.aws import (
    get_boto3_session,
    execute_aws_action,
    BotoJSONEncoder,
    set_aws_sso_config,
    botocore_router,
    aws_router,
    auth_router,
)

# Configure SSO (call once at startup)
set_aws_sso_config([
    {
        "ssoRegion": "eu-west-1",
        "ssoStartUrl": "https://d-xxx.awsapps.com/start",
        "domain": "aws.amazon.com",
        "instance": "aws",
    }
])

# Include routers
app.include_router(botocore_router)
app.include_router(aws_router)
app.include_router(auth_router)
```

## License

MIT