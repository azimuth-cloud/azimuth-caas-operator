import json
import logging

import kopf

from azimuth_caas_operator.models import registry
from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd
from azimuth_caas_operator.utils import ansible_runner
from azimuth_caas_operator.utils import cluster as cluster_utils
from azimuth_caas_operator.utils import k8s

LOG = logging.getLogger(__name__)
CLUSTER_LABEL = "azimuth-caas-cluster"
K8S_CLIENT = None


@kopf.on.startup()
async def startup(**kwargs):
    global K8S_CLIENT
    K8S_CLIENT = k8s.get_k8s_client()
    for resource in registry.get_crd_resources():
        await K8S_CLIENT.apply_object(resource, force=True)
    LOG.info("All CRDs updated.")


@kopf.on.cleanup()
async def cleanup(**kwargs):
    if K8S_CLIENT:
        await K8S_CLIENT.aclose()
    LOG.info("Cleanup complete.")


# TODO(johngarbutt): fetch ui meta from git repo and update crd
@kopf.on.create(registry.API_GROUP, "clustertypes")
async def cluster_type_create(body, name, namespace, labels, **kwargs):
    cluster_type = cluster_type_crd.ClusterType(**body)
    LOG.debug(f"seen cluster_type event {cluster_type.spec.gitUrl}")


@kopf.on.create(registry.API_GROUP, "cluster", backoff=20)
async def cluster_create(body, name, namespace, labels, **kwargs):
    LOG.info(f"Attempt cluster create for {name} in {namespace}")
    cluster = cluster_crd.Cluster(**body)

    # TODO(johngarbutt): share more code with delete!
    create_jobs = await ansible_runner.get_jobs_for_cluster(K8S_CLIENT, name, namespace)
    if ansible_runner.is_any_successful_jobs(create_jobs):
        await cluster_utils.update_cluster(
            K8S_CLIENT, name, namespace, cluster_crd.ClusterPhase.READY
        )
        LOG.info(f"Successful creation of cluster: {name} in: {namespace}")
        return
    if len(create_jobs) != 0:
        if not ansible_runner.are_all_jobs_in_error_state(create_jobs):
            raise RuntimeError(
                f"wait for create job to complete for {name} in {namespace}"
            )
        else:
            if len(create_jobs) >= 3:
                msg = f"Too many failed creates for {name} in {namespace}"
                LOG.error(msg)
                await cluster_utils.update_cluster(
                    K8S_CLIENT, name, namespace, cluster_crd.ClusterPhase.FAILED
                )
                raise RuntimeError(msg)
            LOG.warning(
                f"Some failed jobs for {name} in {namespace}, tiggering a retry."
            )

    await ansible_runner.start_job(K8S_CLIENT, cluster, namespace, remove=False)
    # TODO(johngarbutt): not always needed on a retry
    await cluster_utils.update_cluster(
        K8S_CLIENT, name, namespace, cluster_crd.ClusterPhase.CREATING
    )
    LOG.info(f"Create cluster started for cluster: {name} in: {namespace}")
    raise RuntimeError(f"wait for create job to complete for {name} in {namespace}")


@kopf.on.delete(registry.API_GROUP, "cluster", backoff=20)
async def cluster_delete(body, name, namespace, labels, **kwargs):
    LOG.info(f"Attempt cluster delete for {name} in {namespace}")
    cluster = cluster_crd.Cluster(**body)

    # Check for any pending jobs
    # and fail if we are still running a create job
    ansible_runner.ensure_create_jobs_finished(K8S_CLIENT, name, namespace)
    delete_jobs_status = await ansible_runner.get_delete_jobs_status(
        K8S_CLIENT, name, namespace
    )

    # If we find a completed delete job, we are done.
    # If we find a running job, trigger a retry in the hope its complete soon
    for completed_state in delete_jobs_status:
        if completed_state is True:
            LOG.info(f"Delete job complete for {name} in {namespace}")
            return
        if completed_state is None:
            # TODO(johngarbutt): check for multiple pending delete jobs?
            # TODO(johngarbutt): update cluster with current tasks from job log?
            raise RuntimeError(
                f"wait for delete job to complete for {name} in {namespace}"
            )
        LOG.debug("This job failed, keep looking at other jobs.")

    # Don't create a new delete job if we hit max retries
    if len(delete_jobs_status) >= 3:
        await cluster_utils.update_cluster(
            K8S_CLIENT, name, namespace, cluster_crd.ClusterPhase.FAILED
        )
        LOG.error(
            f"Tried to delete {name} in {namespace} three times, but they all failed. "
            "Please fix the problem, "
            "then delete all failed jobs to trigger a new delete job."
        )
        raise RuntimeError(f"failed to delete {name}")

    # OK, so there are no running delete job,
    # and if there are any completed jobs they failed,
    # but equally we have not yet hit the max retry count.
    # As such we should create a new delete job
    if len(delete_jobs_status) == 0:
        LOG.info(f"No delete jobs so lets create one for {name} in {namespace}")
    else:
        LOG.warning(
            f"Previous delete jobs have failed, "
            "create a new one for {name} in {namespace}"
        )

    await ansible_runner.start_job(K8S_CLIENT, cluster, namespace, remove=True)
    await cluster_utils.update_cluster(
        K8S_CLIENT, name, namespace, cluster_crd.ClusterPhase.DELETING
    )
    LOG.info(f"Success creating a delete job for {name} in {namespace}")
    raise Exception(f"wait for delete job to complete for {name} in {namespace}")


# TODO(johngarbutt): work this into the above loops
@kopf.on.event(
    "job",
    labels={"azimuth-caas-cluster": kopf.PRESENT, "azimuth-caas-action-todo": "create"},
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
    job_log = await get_ansible_runner_event(name, namespace)
    LOG.info(f"Job for {cluster_name} had log {job_log}")

    # TODO(johngarbutt) this is horrible!
    if success:
        cluster_resource = await K8S_CLIENT.api(registry.API_VERSION).resource(
            "cluster"
        )
        await cluster_resource.patch(
            cluster_name,
            dict(status=dict(phase=cluster_crd.ClusterPhase.READY)),
            namespace=namespace,
        )
    if failed:
        cluster_resource = await K8S_CLIENT.api(registry.API_VERSION).resource(
            "cluster"
        )
        await cluster_resource.patch(
            cluster_name,
            dict(status=dict(phase=cluster_crd.ClusterPhase.FAILED)),
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


async def _get_pod_names_for_job(job_name, namespace):
    pod_resource = await k8s.get_pod_resource(K8S_CLIENT)
    return [
        pod["metadata"]["name"]
        async for pod in pod_resource.list(
            labels={"job-name": job_name}, namespace=namespace
        )
    ]


async def _get_pod_log_lines(pod_name, namespace):
    log_resource = await K8S_CLIENT.api("v1").resource("pods/log")
    # TODO(johngarbutt): we should pass tail param here?
    log_string = await log_resource.fetch(pod_name, namespace=namespace)
    # remove trailing space
    log_string = log_string.strip()
    # return a list of log lines
    return log_string.split("\n")


async def get_ansible_runner_event(job_name, namespace):
    pod_names = await _get_pod_names_for_job(job_name, namespace)
    if len(pod_names) == 0 or len(pod_names) > 1:
        # TODO(johngarbutt) only works because our jobs don't retry,
        # and we don't yet check the pod is running or finished
        LOG.debug(f"Found pods:{pod_names} for job {job_name} in {namespace}")
        return
    pod_name = pod_names[0]

    log_lines = await _get_pod_log_lines(pod_name, namespace)
    last_log_line = log_lines[-1]

    try:
        last_log_event = json.loads(last_log_line)
        event_data = last_log_event.get("event_data", {})
        task = event_data.get("task")
        if task:
            LOG.info(f"For job: {job_name} in: {namespace} seen task: {task}")
        return event_data
    except json.decoder.JSONDecodeError:
        LOG.debug("failed to decode log, most likely not ansible json output.")
