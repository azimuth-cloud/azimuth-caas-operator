import logging

import easykube
import kopf
from pydantic.json import pydantic_encoder

from azimuth_caas_operator.models import registry

LOG = logging.getLogger(__name__)

easykube_field_manager = "azimuth-caas-operator"


def get_k8s_client():
    return easykube.Configuration.from_environment(
        json_encoder=pydantic_encoder
    ).async_client(default_field_manager=easykube_field_manager)


async def register_crds(client):
    reg = registry.get_registry()
    for crd in reg:
        resource = crd.kubernetes_resource()
        await client.apply_object(resource, force=True)
    LOG.info("CRDs imported")


@kopf.on.startup()
async def startup(**kwargs):
    LOG.info("Starting")
    client = get_k8s_client()
    await register_crds(client)


@kopf.on.cleanup()
def cleanup(**kwargs):
    LOG.info("cleaned up!")
