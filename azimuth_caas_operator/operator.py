import json
import logging

import easykube
import kopf
from pydantic.json import pydantic_encoder

from azimuth_caas_operator import ansible_runner
from azimuth_caas_operator.models import registry
from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd

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
    # TODO(johngarbutt): easykube.kubernetes.client.errors.ApiError:
    # container "run" in pod "test2rfc6z-5zw84" is waiting to start:
    # PodInitializing

    # split into lines
    logs = logs.strip()
    logs = logs.split("\n")

    # check we can parse everything
    last_log_event = {}
    for log in logs:
        try:
            last_log_event = json.loads(log)
        except json.decoder.JSONDecodeError:
            continue
        last_log_event = json.loads(log)
        task = last_log_event["event_data"].get("task")
        LOG.debug(f"task: {task}")
        failures = last_log_event["event_data"].get("failures", 0)
        LOG.debug(f"failures: {failures}")

    return last_log_event.get("event_data")


@kopf.on.startup()
async def startup(**kwargs):
    LOG.info("Starting")
    client = get_k8s_client()
    await register_crds(client)


@kopf.on.cleanup()
def cleanup(**kwargs):
    LOG.info("cleaned up!")


@kopf.on.create(registry.API_GROUP, "clustertypes")
async def cluster_type_event(body, name, namespace, labels, **kwargs):
    if type == "DELETED":
        LOG.info(f"cluster_type {name} in {namespace} is deleted")
        return

    LOG.debug(f"cluster_type event for {name} in {namespace}")
    cluster_type = registry.parse_model(body)
    LOG.info(f"seen cluster_type event {cluster_type.spec.gitUrl}")
    # TODO(johngarbutt): fetch ui meta from git repo and update crd


@kopf.on.create(registry.API_GROUP, "cluster")
async def cluster_event(body, name, namespace, labels, **kwargs):
    cluster = cluster_crd.Cluster(**body)
    cluster_type_name = cluster.spec.clusterTypeName

    # Fetch cluster type
    client = get_k8s_client()
    cluster_type = await client.api(registry.API_VERSION).resource("clustertype")
    # TODO(johngarbutt) how to catch not found errors?
    cluster_type_raw = await cluster_type.fetch(cluster_type_name)
    cluster_type = cluster_type_crd.ClusterType(**cluster_type_raw)
    # TODO(johngarbutt) cache cluster_type in a config map for doing delete?

    # Create the config map for extra vars
    configmap_data = ansible_runner.get_env_configmap(cluster, cluster_type)
    configmap_resource = await client.api("v1").resource("ConfigMap")
    await configmap_resource.create(configmap_data, namespace=namespace)

    # Create the ansible runner job to create this cluster
    job_data = ansible_runner.get_job(cluster, cluster_type)
    job_resource = await client.api("batch/v1").resource("jobs")
    job = await job_resource.create(job_data, namespace=namespace)

    # update the cluster phase to creating
    cluster_resource = await client.api(registry.API_VERSION).resource("cluster")
    await cluster_resource.patch(
        name,
        dict(status=dict(phase=cluster_crd.ClusterPhase.CREATING)),
        namespace=namespace,
    )

    LOG.info(
        f"Created job {job.metadata.name} for cluster {name} "
        f"of type {cluster_type_name} in {namespace}"
    )


def get_job_completed_state(job):
    if not job:
        return

    active = job.status.get("active", 0) == 1
    success = job.status.get("succeeded", 0) == 1
    failed = job.status.get("failed", 0) == 1

    if success:
        return True
    if failed:
        return False
    if active:
        return None
    if not active:
        LOG.warning(f"job has not started yet {job}")
    else:
        LOG.warning(f"job in a strange state {job}")


@kopf.on.delete(registry.API_GROUP, "cluster")
async def cluster_delete(body, name, namespace, labels, **kwargs):
    LOG.info(f"Attempt cluster delete for {name} in {namespace}")
    cluster = cluster_crd.Cluster(**body)
    client = get_k8s_client()

    # Check for any running create jobs, wait till they error out
    job_resource = await client.api("batch/v1").resource("jobs")
    create_jobs = [
        job
        async for job in job_resource.list(
            labels={"azimuth-caas-cluster": name, "azimuth-caas-action": "create"},
            namespace=namespace,
        )
    ]
    if not create_jobs:
        LOG.error(f"can't find any create jobs for {name} in {namespace}")
        raise Exception("waiting for create to start")
    for job in create_jobs:
        if get_job_completed_state(job) is None:
            raise Exception(f"waiting for create job to finish {job.metadata.name}")

    # Check for any running delete jobs, success if its completed
    job_resource = await client.api("batch/v1").resource("jobs")
    delete_jobs = [
        job
        async for job in job_resource.list(
            labels={"azimuth-caas-cluster": name, "azimuth-caas-action": "remove"},
            namespace=namespace,
        )
    ]
    if len(delete_jobs) == 0:
        LOG.info("found no delete jobs")
    if len(delete_jobs) > 1:
        LOG.warning("found more than one delete job, need to limit retries!")
    for job in delete_jobs:
        completed_state = get_job_completed_state(job)
        if completed_state is None:
            # TODO(johngarbutt): check for any other pending delete jobs?
            raise Exception(f"waiting for delete job {job.metadata.name}")
        if completed_state is True:
            LOG.info(f"delete job has completed {job.metadata.name}")
            # we are done, so just return and let the cluster delete
            return
        else:
            # delete job is an error, allow a retry
            LOG.info(f"delete job has an error, need to retry {job.metadata.name}")
            continue

    LOG.info("must be no delete jobs in progress, and none that worked")

    # TODO(johngarbutt): cache this in a config map?
    cluster_type_name = cluster.spec.clusterTypeName
    cluster_type_resource = await client.api(registry.API_VERSION).resource(
        "clustertype"
    )
    cluster_type_raw = await cluster_type_resource.fetch(cluster_type_name)
    cluster_type = cluster_type_crd.ClusterType(**cluster_type_raw)

    # update the configmap for the delete job
    # TODO(johngarbutt) create a new one!
    configmap_data = ansible_runner.get_env_configmap(
        cluster, cluster_type, remove=True
    )
    configmap_resource = await client.api("v1").resource("ConfigMap")
    await configmap_resource.create_or_patch(
        configmap_data["metadata"]["name"], configmap_data, namespace=namespace
    )

    # Create a job to delete the cluster
    job_data = ansible_runner.get_job(cluster, cluster_type, remove=True)
    job_resource = await client.api("batch/v1").resource("jobs")
    job = await job_resource.create(job_data, namespace=namespace)

    # update the cluster phase to deleting
    cluster_resource = await client.api(registry.API_VERSION).resource("cluster")
    await cluster_resource.patch(
        name,
        dict(status=dict(phase=cluster_crd.ClusterPhase.DELETING)),
        namespace=namespace,
    )

    # trigger a retry to check on the job
    raise Exception(f"wait for job {job.metadata.name} to finish!")


@kopf.on.event(
    "job",
    labels={"azimuth-caas-cluster": kopf.PRESENT, "azimuth-caas-action": "create"},
)
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

    if active and not ready:
        LOG.info(f"job is running, pod not ready.")
        # skip checking logs until pod init container finished
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

    if success:
        cluster_resource = await client.api(registry.API_VERSION).resource("cluster")
        await cluster_resource.patch(
            name,
            dict(status=dict(phase=cluster_crd.ClusterPhase.READY)),
            namespace=namespace,
        )
    #     job_resource = await client.api("batch/v1").resource("jobs")
    #     # TODO(johngarbutt): send propagationPolicy="Background" like kubectl
    #     await job_resource.delete(name, namespace=namespace)
    #     LOG.info(f"deleted job {name} in {namespace}")

    #     # delete pods so they are not orphaned
    #     pod_resource = await client.api("v1").resource("pods")
    #     pods = [
    #         pod
    #         async for pod in pod_resource.list(
    #             labels={"job-name": name}, namespace=namespace
    #         )
    #     ]
    #     for pod in pods:
    #         await pod_resource.delete(pod["metadata"]["name"], namespace=namespace)
