import json
import logging

import aiohttp
import kopf
import yaml

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


async def update_cluster_type(client, name, namespace, status):
    cluster_type_resource = await client.api(registry.API_VERSION).resource(
        "clustertype"
    )
    await cluster_type_resource.patch(
        name,
        dict(status=status),
        namespace=namespace,
    )


async def _fetch_text_from_url(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.text()


# TODO(johngarbutt): fetch ui meta from git repo and update crd
@kopf.on.create(registry.API_GROUP, "clustertypes")
async def cluster_type_create(body, name, namespace, labels, **kwargs):
    cluster_type = cluster_type_crd.ClusterType(**body)
    LOG.debug(f"seen cluster_type event {cluster_type.spec.gitUrl}")
    print(cluster_type.spec.uiMetaUrl)
    raw_yaml_str = await _fetch_text_from_url(cluster_type.spec.uiMetaUrl)
    ui_meta = yaml.safe_load(raw_yaml_str)
    # check its a dict at the top level?
    print(ui_meta)
    ui_meta.setdefault("requiresSshKey", False)
    ui_meta.setdefault("description", "")
    ui_meta.setdefault("logo", "")
    ui_meta["usageTemplate"] = ui_meta.get("usage_template", "")

    raw_parameters = ui_meta.get("parameters", [])
    params = []
    for raw in raw_parameters:
        raw.setdefault("immutable", True)  # is this correct?
        raw.setdefault("required", True)
        raw.setdefault("default", "")
        if raw.get("default") is None:
            raw["default"] = ""
        raw_options = raw.get("options", {})
        options = {}
        for key, value in raw_options.items():
            options[key] = str(value)
        raw["options"] = options
        cluster_param = cluster_type_crd.ClusterParameter(**raw)
        params.append(cluster_param)
    ui_meta["parameters"] = params

    raw_services = ui_meta.get("services", [])
    services = []
    for raw in raw_services:
        raw.setdefault("when", "")
        raw["iconUrl"] = raw.get("icon_url", "")
        services.append(cluster_type_crd.ClusterServiceSpec(**raw))
    ui_meta["services"] = services

    ui_meta_obj = cluster_type_crd.ClusterUiMeta(**ui_meta)
    cluster_type.status.uiMeta = ui_meta_obj
    cluster_type.status = cluster_type_crd.ClusterTypeStatus(
        phase=cluster_type_crd.ClusterTypePhase.AVAILABLE, uiMeta=ui_meta_obj
    )
    print(cluster_type.status)
    await update_cluster_type(K8S_CLIENT, name, namespace, cluster_type.status)


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

        # TODO(johngarbutt) hack to autodelete
        # await cluster_utils.create_scheduled_delete_job(
        #    K8S_CLIENT, name, namespace, cluster.metadata.uid
        # )

        LOG.info(f"Successful creation of cluster: {name} in: {namespace}")
        return
    if len(create_jobs) != 0:
        if not ansible_runner.are_all_jobs_in_error_state(create_jobs):
            # TODO(johngarbutt): update cluster with the last event name from job log
            raise RuntimeError(
                f"wait for create job to complete for {name} in {namespace}"
            )
        else:
            if len(create_jobs) >= 2:
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
    await ansible_runner.ensure_create_jobs_finished(K8S_CLIENT, name, namespace)
    delete_jobs_status = await ansible_runner.get_delete_jobs_status(
        K8S_CLIENT, name, namespace
    )

    # If we find a completed delete job, we are done.
    # If we find a running job, trigger a retry in the hope its complete soon
    for completed_state in delete_jobs_status:
        if completed_state is True:
            # TODO(johngarbutt): how to delete app cred in openstack?
            await ansible_runner.delete_secret(
                K8S_CLIENT, cluster.spec.cloudCredentialsSecretName, namespace
            )
            LOG.info(f"Delete job complete for {name} in {namespace}")
            return
        if completed_state is None:
            # TODO(johngarbutt): update cluster with current tasks from job log?
            raise RuntimeError(
                f"wait for delete job to complete for {name} in {namespace}"
            )
            # TODO(johngarbutt): check for multiple pending delete jobs?
        LOG.debug("This job failed, keep looking at other jobs.")

    # Don't create a new delete job if we hit max retries
    if len(delete_jobs_status) >= 2:
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
    raise RuntimeError(f"wait for delete job to complete for {name} in {namespace}")


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
