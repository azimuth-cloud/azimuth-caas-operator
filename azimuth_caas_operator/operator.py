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


# TODO(johngarbutt): move to utils.cluster_type
async def _fetch_text_from_url(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.text()


# TODO(johngarbutt): move to utils.cluster_type
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
    LOG.debug(f"Attempt cluster create for {name} in {namespace}")
    cluster = cluster_crd.Cluster(**body)

    # Check for an existing create job
    create_job = await ansible_runner.get_create_job_for_cluster(
        K8S_CLIENT, name, namespace
    )
    if create_job:
        is_job_success = ansible_runner.get_job_completed_state(create_job)

        # raise exception to retry if the job is still running
        if is_job_success is None:
            # TODO(johngarbutt): update cluster with the last event name from job log
            # but for now we just bump the updated_at time by calling update again
            await cluster_utils.update_cluster(
                K8S_CLIENT,
                name,
                namespace,
                cluster_crd.ClusterPhase.CREATING,
            )
            msg = f"Waiting for create job to complete for {name} in {namespace}"
            LOG.info(msg)
            raise kopf.TemporaryError(msg, delay=20)

        # if the job finished, update the cluster
        if is_job_success:
            outputs = await ansible_runner.get_outputs_from_create_job(
                K8S_CLIENT, name, namespace
            )
            await cluster_utils.update_cluster(
                K8S_CLIENT,
                name,
                namespace,
                cluster_crd.ClusterPhase.READY,
                outputs=outputs,
            )
            LOG.info(f"Successful creation of cluster: {name} in: {namespace}")
            return

        else:
            await cluster_utils.update_cluster(
                K8S_CLIENT,
                name,
                namespace,
                cluster_crd.ClusterPhase.FAILED,
                # TODO(johngarbutt): we to better information on the reason!
                error=(
                    "Failed to create platform. "
                    "Please check your cloud has enough free space. "
                    "To retry please click patch."
                ),
            )
            LOG.error(f"Create job failed for {name} in {namespace}")
            return

    # There is no running create job, so lets create one
    await ansible_runner.start_job(K8S_CLIENT, cluster, namespace, remove=False)
    await cluster_utils.update_cluster(
        K8S_CLIENT,
        name,
        namespace,
        cluster_crd.ClusterPhase.CREATING,
        extra_vars=cluster.spec.extraVars,
    )

    # If requested, schedule auto delete of this cluster
    # TODO(johngarbutt): its a bit odd this is just a random extra var!
    lifetime_hours = cluster.spec.extraVars.get("appliance_lifetime_hrs")
    if lifetime_hours:
        await cluster_utils.create_scheduled_delete_job(
            K8S_CLIENT, name, namespace, cluster.metadata.uid, lifetime_hours
        )

    LOG.info(f"Create cluster started for cluster: {name} in: {namespace}")

    # Trigger a retry in 60 seconds to check on the job we just created
    raise kopf.TemporaryError(
        f"wait for create job to complete for {name} in {namespace}"
    )


@kopf.on.update(registry.API_GROUP, "cluster", field="spec")
async def cluster_update(body, name, namespace, labels, **kwargs):
    LOG.debug(f"Attempt cluster update for {name} in {namespace}")
    cluster = cluster_crd.Cluster(**body)

    # Fail if create is still in progress
    # Note that we don't care if create worked.
    # If create failed, we allow update and patch to trigger a retry
    if not await ansible_runner.is_create_job_finished(K8S_CLIENT, name, namespace):
        raise kopf.TemporaryError(
            f"Can't process update until create completed for {name} in {namespace}"
        )

    # check for any update jobs
    update_job = await ansible_runner.get_update_job_for_cluster(
        K8S_CLIENT, name, namespace
    )
    if update_job:
        is_job_success = ansible_runner.get_job_completed_state(update_job)

        # raise exception to retry if the job is still running
        if is_job_success is None:
            await cluster_utils.update_cluster(
                K8S_CLIENT,
                name,
                namespace,
                cluster_crd.ClusterPhase.CONFIG,
            )
            msg = f"Waiting for update job to complete for {name} in {namespace}"
            LOG.info(msg)
            raise kopf.TemporaryError(msg, delay=20)

        # if the job finished, update the cluster
        if is_job_success:
            outputs = await ansible_runner.get_outputs_from_create_job(
                K8S_CLIENT, name, namespace
            )
            await ansible_runner.unlabel_job(K8S_CLIENT, update_job)
            await cluster_utils.update_cluster(
                K8S_CLIENT,
                name,
                namespace,
                cluster_crd.ClusterPhase.READY,
                outputs=outputs,
            )
            LOG.info(f"Successful update of cluster: {name} in: {namespace}")
            return

        else:
            await cluster_utils.update_cluster(
                K8S_CLIENT,
                name,
                namespace,
                cluster_crd.ClusterPhase.FAILED,
                # TODO(johngarbutt): we to better information on the reason!
                error=("Failed to update the platform. To retry please click patch."),
            )
            LOG.error(f"Update job failed for {name} in {namespace}")
            return

    is_upgrade = cluster.spec.clusterTypeVersion != cluster.status.clusterTypeVersion
    is_extra_var_update = cluster.spec.extraVars != cluster.status.appliedExtraVars

    # Skip starting an update job, if no real changes made?
    if not is_upgrade and not is_extra_var_update:
        LOG.info(f"Skip update, no meaningful changes for: {name} in {namespace}")
        return

    # TODO(johngarbutt): should we check if we are about to be auto-deleted?

    # There is no running create job, so lets create one
    await ansible_runner.start_job(K8S_CLIENT, cluster, namespace, update=True)
    await cluster_utils.update_cluster(
        K8S_CLIENT,
        name,
        namespace,
        cluster_crd.ClusterPhase.CONFIG,
        extra_vars=cluster.spec.extraVars,
    )

    LOG.info(f"Cluster update started for cluster: {name} in: {namespace}")

    # Trigger a retry in 60 seconds to check on the job we just created
    raise kopf.TemporaryError(
        f"Need to wait for update job to complete for {name} in {namespace}", delay=30
    )


@kopf.on.delete(registry.API_GROUP, "cluster")
async def cluster_delete(body, name, namespace, labels, **kwargs):
    LOG.info(f"Attempt cluster delete for {name} in {namespace}")
    cluster = cluster_crd.Cluster(**body)

    # Check for any pending jobs
    # and fail if we are still running a create job
    await ansible_runner.ensure_create_jobs_finished(K8S_CLIENT, name, namespace)
    delete_job = await ansible_runner.get_delete_job_for_cluster(
        K8S_CLIENT, name, namespace
    )
    if delete_job:
        is_job_success = ansible_runner.get_job_completed_state(delete_job)

        # raise exception to retry if the job is still running
        if is_job_success is None:
            await cluster_utils.update_cluster(
                K8S_CLIENT,
                name,
                namespace,
                cluster_crd.ClusterPhase.DELETING,
            )
            msg = f"Waiting for delete job to complete for {name} in {namespace}"
            LOG.info(msg)
            raise kopf.TemporaryError(msg, delay=20)

        # if the delete job finished
        if is_job_success:
            await ansible_runner.delete_secret(
                K8S_CLIENT, cluster.spec.cloudCredentialsSecretName, namespace
            )
            LOG.info(f"Delete job complete for {name} in {namespace}")
            # let kopf remove finalizer and complete the cluster delete
            return

        else:
            await cluster_utils.update_cluster(
                K8S_CLIENT,
                name,
                namespace,
                cluster_crd.ClusterPhase.FAILED,
                # TODO(johngarbutt): how does a user retry the delete, eek!
                error=(
                    "Failed to delete the platform. Please contact Azimuth operators."
                ),
            )
            LOG.error(f"Delete job failed for {name} in {namespace}")
            LOG.error(
                f"Delete job failed for {name} in {namespace}. "
                "Please fix the problem, "
                "then delete all failed jobs to trigger a new delete job."
            )
            raise RuntimeError(f"Failed to delete {name}")

    # delete job not yet created, lets create one
    await ansible_runner.start_job(K8S_CLIENT, cluster, namespace, remove=True)
    await cluster_utils.update_cluster(
        K8S_CLIENT, name, namespace, cluster_crd.ClusterPhase.DELETING
    )
    LOG.info(f"Success creating a delete job for {name} in {namespace}")
    raise kopf.TemporaryError(
        f"wait for delete job to complete for {name} in {namespace}"
    )
