import json
import logging

import easykube
import kopf
from pydantic.json import pydantic_encoder

from azimuth_caas_operator.models import registry

LOG = logging.getLogger(__name__)

easykube_field_manager = "azimuth-caas-operator"
CLUSTER_LABEL = "azimuth-caas-cluster"


async def register_crds(client):
    for resource in registry.get_crd_resources():
        await client.apply_object(resource, force=True)
    LOG.info("CRDs imported")


def get_k8s_client():
    return easykube.Configuration.from_environment(
        json_encoder=pydantic_encoder
    ).async_client(default_field_manager=easykube_field_manager)


async def get_job_log(client, job_name, namespace):
    # find the pod fomr the job label
    pod_resource = await client.api("v1").resource("pods")
    pods = [
        pod
        async for pod in pod_resource.list(
            labels={"job-name": job_name}, namespace=namespace
        )
    ]
    if len(pods) == 0 or len(pods) > 1:
        LOG.warning(f"Can't find pod for job {job_name} in {namespace}")
        return
    pod_name = pods[0]["metadata"]["name"]
    log_resource = await client.api("v1").resource("pods/log")
    # TODO(johngarbutt): we should pass tail here
    logs = await log_resource.fetch(pod_name, namespace=namespace)

    # split into lines
    logs = logs.strip()
    logs = logs.split("\n")

    # check we can parse everything
    for log in logs:
        last_log_event = json.loads(log)
        task = last_log_event["event_data"].get("task")
        LOG.debug(f"task: {task}")
        failures = last_log_event["event_data"].get("failures", 0)
        LOG.debug(f"failures: {failures}")

    return last_log_event["event_data"]


@kopf.on.startup()
async def startup(**kwargs):
    LOG.info("Starting")
    client = get_k8s_client()
    await register_crds(client)


@kopf.on.cleanup()
def cleanup(**kwargs):
    LOG.info("cleaned up!")


@kopf.on.create("azimuth.stackhpc.com", "clustertypes")
async def cluster_type_event(body, name, namespace, labels, **kwargs):
    if type == "DELETED":
        LOG.info(f"cluster_type {name} in {namespace} is deleted")
        return

    LOG.debug(f"cluster_type event for {name} in {namespace}")
    cluster_type = registry.parse_model(body)
    LOG.info(f"seen cluster_type event {cluster_type.spec.gitUrl}")
    # TODO(johngarbutt): fetch ui meta from git repo and update crd


@kopf.on.create("azimuth.stackhpc.com", "cluster")
async def cluster_event(body, name, namespace, labels, **kwargs):
    LOG.info(f"cluster event for {name} in {namespace}")
    cluster = registry.parse_model(body)
    cluster_type_name = cluster.spec.clusterTypeName
    LOG.info(f"seen cluster of type {cluster_type_name} with status {cluster.status}")
    # TODO(johngarbutt): fetch the cluster type, if available, get the git ref

    # TODO(johngarbutt): create a job to create the cluster!


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

    if not success and not failed and not active:
        LOG.error("what happened here?")
        LOG.info(f"{body}")
        return

    if active:
        LOG.info(f"job is running, pod ready:{ready}")
    if failed:
        LOG.error("job failed!!")
    if success:
        LOG.info(f"job completed on {completion_time}")

    # TODO(johngarbutt) update the CRD with logs
    client = get_k8s_client()
    job_log = await get_job_log(client, name, namespace)
    LOG.info(f"{job_log}")
