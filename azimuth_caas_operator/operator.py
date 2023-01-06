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


@kopf.on.startup()
async def startup(**kwargs):
    LOG.info("Starting")
    reg = registry.get_registry()
    client = get_k8s_client()
    for crd in reg:
        resource = crd.kubernetes_resource()
        await client.apply_object(resource, force=True)
    LOG.info("CRDs imported")


@kopf.on.cleanup()
def cleanup(**kwargs):
    LOG.info("cleaned up!")
