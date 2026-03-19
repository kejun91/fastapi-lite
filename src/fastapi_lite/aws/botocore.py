from __future__ import annotations

import botocore
import botocore.loaders
import botocore.session
from botocore import xform_name
from botocore.exceptions import DataNotFoundError
from fastapi import APIRouter

bcs = botocore.session.get_session()
loader = botocore.loaders.Loader()

DEFAULT_PREFIX = "/api/botocore"


def create_router(prefix: str = DEFAULT_PREFIX) -> APIRouter:
    """Create a botocore router with a custom prefix."""
    r = APIRouter(prefix=prefix)

    @r.get("/version")
    async def get_botocore_version():
        return {"botocore_version": botocore.__version__}

    @r.get("/available-services")
    async def get_available_services():
        services = []
        for s in bcs.get_available_services():
            service_model = bcs.get_service_model(s)
            services.append({"service_name": s, "service_id": service_model.service_id})
        return services

    @r.get("/available-regions/{service_name}/{aws_partition}")
    async def get_available_regions(service_name: str, aws_partition: str):
        return bcs.get_available_regions(service_name, partition_name=aws_partition)

    @r.get("/service-model/{service_name}")
    async def get_service_model(service_name: str):
        types = ["waiters-2", "paginators-1", "service-2", "examples-1"]
        service_model = {}
        pythonic_operation_names = []
        for t in types:
            try:
                service_model[t] = loader.load_service_model(service_name, t)
                if t == "service-2":
                    for on in service_model[t].get("operations", {}).keys():
                        pythonic_operation_names.append({"pythonic": xform_name(on), "operation": on})
            except DataNotFoundError:
                pass
        return {
            "serviceModel": service_model,
            "pythonicOperationNames": pythonic_operation_names,
        }

    @r.get("/endpoints")
    async def get_endpoints():
        endpoint_data = loader.load_data("endpoints")
        return endpoint_data

    return r


router = create_router()
