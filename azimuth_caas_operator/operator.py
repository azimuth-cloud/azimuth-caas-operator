import datetime
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


async def _update_cluster_type(client, name, namespace, status):
    now = datetime.datetime.utcnow()
    now_string = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    status.updatedTimestamp = now_string

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


async def _fetch_ui_meta_from_url(url):
    raw_yaml_str = await _fetch_text_from_url(url)
    ui_meta = yaml.safe_load(raw_yaml_str)
    # check its a dict at the top level?
    ui_meta.setdefault("requiresSshKey", False)
    ui_meta.setdefault("description", "")
    ui_meta.setdefault("logo", "")
    ui_meta["usageTemplate"] = ui_meta.get("usage_template", "")

    raw_parameters = ui_meta.get("parameters", [])
    params = []
    for raw in raw_parameters:
        raw.setdefault("immutable", True)  # is this correct?
        raw.setdefault("required", True)
        cluster_param = cluster_type_crd.ClusterParameter(**raw)
        params.append(cluster_param)
    ui_meta["parameters"] = params

    raw_services = ui_meta.get("services", [])
    services = []
    for raw in raw_services:
        raw["iconUrl"] = raw.get("icon_url", "")
        services.append(cluster_type_crd.ClusterServiceSpec(**raw))
    ui_meta["services"] = services

    return cluster_type_crd.ClusterUiMeta(**ui_meta)


@kopf.on.create(registry.API_GROUP, "clustertypes")
async def cluster_type_create(body, name, namespace, labels, **kwargs):
    cluster_type = cluster_type_crd.ClusterType(**body)
    LOG.debug(f"seen cluster_type event {cluster_type.spec.gitUrl}")
    ui_meta_obj = await _fetch_ui_meta_from_url(cluster_type.spec.uiMetaUrl)
    cluster_type.status = cluster_type_crd.ClusterTypeStatus(
        phase=cluster_type_crd.ClusterTypePhase.AVAILABLE, uiMeta=ui_meta_obj
    )
    await _update_cluster_type(K8S_CLIENT, name, namespace, cluster_type.status)


@kopf.on.update(registry.API_GROUP, "clustertypes")
@kopf.on.resume(registry.API_GROUP, "clustertypes")
async def cluster_type_updated(body, name, namespace, labels, **kwargs):
    cluster_type = cluster_type_crd.ClusterType(**body)
    if cluster_type.spec.uiMetaUrl == cluster_type.status.uiMetaUrl:
        LOG.info("No update of uimeta needed.")
    else:
        LOG.info("Updating UI Meta.")
        ui_meta_obj = await _fetch_ui_meta_from_url(cluster_type.spec.uiMetaUrl)
        cluster_type.status = cluster_type_crd.ClusterTypeStatus(
            phase=cluster_type_crd.ClusterTypePhase.AVAILABLE,
            uiMeta=ui_meta_obj,
            uiMetaUrl=cluster_type.spec.uiMetaUrl,
        )
        await _update_cluster_type(K8S_CLIENT, name, namespace, cluster_type.status)


@kopf.on.create(registry.API_GROUP, "cluster")
async def cluster_create(body, name, namespace, labels, **kwargs):
    LOG.info(f"Attempt cluster create for {name} in {namespace}")
    cluster = cluster_crd.Cluster(**body)

    # TODO(johngarbutt): share more code with delete!
    create_jobs = await ansible_runner.get_jobs_for_cluster(K8S_CLIENT, name, namespace)
    if ansible_runner.is_any_successful_jobs(create_jobs):
        lifetime_hours = cluster.spec.extraVars.get("appliance_lifetime_hrs")
        if lifetime_hours:
            # TODO(johngarbutt) hack to autodelete
            await cluster_utils.create_scheduled_delete_job(
                K8S_CLIENT, name, namespace, cluster.metadata.uid, lifetime_hours
            )

        outputs = await ansible_runner.get_outputs_from_create_job(
            K8S_CLIENT, name, namespace
        )
        await cluster_utils.update_cluster(
            K8S_CLIENT, name, namespace, cluster_crd.ClusterPhase.READY, outputs=outputs
        )

        LOG.info(f"Successful creation of cluster: {name} in: {namespace}")
        return
    if len(create_jobs) != 0:
        if not ansible_runner.are_all_jobs_in_error_state(create_jobs):
            # TODO(johngarbutt): update cluster with the last event name from job log
            raise kopf.TemporaryError(
                f"wait for create job to complete for {name} in {namespace}", delay=20
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
        K8S_CLIENT,
        name,
        namespace,
        cluster_crd.ClusterPhase.CREATING,
        extra_vars=cluster.spec.extraVars,
    )
    LOG.info(f"Create cluster started for cluster: {name} in: {namespace}")
    raise kopf.TemporaryError(
        f"wait for create job to complete for {name} in {namespace}"
    )


@kopf.on.update(registry.API_GROUP, "cluster")
@kopf.on.resume(registry.API_GROUP, "cluster")
async def cluster_changed(body, name, namespace, labels, **kwargs):
    LOG.debug(f"Attempt cluster update for {name} in {namespace}")
    cluster = cluster_crd.Cluster(**body)

    is_upgrade = cluster.spec.clusterTypeVersion != cluster.status.clusterTypeVersion
    if is_upgrade:
        LOG.info(f"Upgrade requested for: {name} in {namespace}!")
        await cluster_utils.update_cluster(
            K8S_CLIENT,
            name,
            namespace,
            # cluster_crd.ClusterPhase.UPGRADE,
            cluster_crd.ClusterPhase.FAILED,
            error="Not implemented upgrade yet!",
        )
        LOG.error("Not implemented upgrade yet!")

    is_extra_var_update = cluster.spec.extraVars != cluster.status.appliedExtraVars
    if is_extra_var_update:
        # TODO(johngarbutt) this will always trigger for the moment, needs fixing
        LOG.info(f"Detected extra vars have changed for: {name} in {namespace}")
        await cluster_utils.update_cluster(
            K8S_CLIENT,
            name,
            namespace,
            # cluster_crd.ClusterPhase.CONFIG,
            cluster_crd.ClusterPhase.FAILED,
            error="Not implemented re-configure yet!",
        )
        LOG.error("Not implemented re-configure yet!")

    elif not is_upgrade:
        LOG.info(f"No changes for: {name} in {namespace}")

    # TODO(johngarbutt): we need to do something!


@kopf.on.delete(registry.API_GROUP, "cluster")
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
            raise kopf.TemporaryError(
                f"wait for delete job to complete for {name} in {namespace}", delay=20
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
    raise kopf.TemporaryError(
        f"wait for delete job to complete for {name} in {namespace}"
    )
