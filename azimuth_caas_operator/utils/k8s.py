import easykube
from pydantic.json import pydantic_encoder

FIELD_MANAGER_NAME = "azimuth-caas-operator"


def get_k8s_client():
    return easykube.Configuration.from_environment(
        json_encoder=pydantic_encoder
    ).async_client(default_field_manager=FIELD_MANAGER_NAME)


async def get_pod_resource(client):
    # TODO(johngarbutt): unclear how to mock this directly?
    return await client.api("v1").resource("pods")
