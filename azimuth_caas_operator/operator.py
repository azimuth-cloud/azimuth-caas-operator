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


@kopf.on.event("azimuth.stackhpc.com", "clustertypes")
async def clustertype_event(type, body, name, namespace, labels, **kwargs):
    LOG.info(f"cluster type event for {name} in {namespace}")


@kopf.on.event("azimuth.stackhpc.com", "cluster")
async def cluster_event(type, body, name, namespace, labels, **kwargs):
    LOG.info(f"cluster event for {name} in {namespace}")


@kopf.on.event("job", labels={"azimuth-caas-cluster": kopf.PRESENT})
async def job_event(type, body, name, namespace, labels, **kwargs):
    cluster_name = labels.get("azimuth-caas-cluster")
    if type == "DELETED":
        LOG.info(f"job deleted cluster {cluster_name} in {namespace}")
        return

    LOG.debug(f"seen job update for cluster {cluster_name} in {namespace}")

    job_status = body.get("status", {})
    ready = job_status.get("ready", 0) == 1
    success = job_status.get("succeeded", 0) == 1
    failed = job_status.get("failed", 0) == 1
    active = job_status.get("active", 0) == 1

    completion_time = job_status.get("completionTime")
    LOG.debug(
        f"job {cluster_name} status - ready:{ready} "
        f"success:{success} completed at:{completion_time}"
    )

    if active:
        LOG.info(f"job is running, pod ready:{ready}")
    if failed:
        LOG.error("job failed!!")
    if success:
        LOG.info(f"job completed on {completion_time}")

    if not success and not failed and not active:
        LOG.error("what happened here?")
        LOG.info(f"{body}")


@kopf.on.startup()
async def startup(**kwargs):
    LOG.info("Starting")
    client = get_k8s_client()
    await register_crds(client)
    # TODO(johngarbutt): check for any pending clusters without a job?


@kopf.on.cleanup()
def cleanup(**kwargs):
    LOG.info("cleaned up!")
