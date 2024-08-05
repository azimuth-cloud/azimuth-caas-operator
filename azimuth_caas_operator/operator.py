import asyncio
import datetime
import logging
import os
import sys

import aiohttp
import kopf
import yaml

from azimuth_caas_operator.models import registry
from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd
from azimuth_caas_operator.utils import ansible_runner
from azimuth_caas_operator.utils import cluster as cluster_utils
from azimuth_caas_operator.utils import lease as lease_utils
from azimuth_caas_operator.utils import k8s

LOG = logging.getLogger(__name__)
CLUSTER_LABEL = "azimuth-caas-cluster"
K8S_CLIENT = None


@kopf.on.startup()
async def startup(settings, **kwargs):
    # Apply kopf setting to force watches to restart periodically
    settings.watching.client_timeout = int(os.environ.get("KOPF_WATCH_TIMEOUT", "600"))
    global K8S_CLIENT
    K8S_CLIENT = k8s.get_k8s_client()
    # Create or update the CRDs
    for crd in registry.get_crd_resources():
        try:
            await K8S_CLIENT.apply_object(crd, force=True)
        except Exception:
            LOG.exception("error applying CRD %s - exiting", crd["metadata"]["name"])
            sys.exit(1)
    LOG.info("All CRDs updated.")
    # Give Kubernetes a chance to create the APIs for the CRDs
    await asyncio.sleep(0.5)
    # Check to see if the APIs for the CRDs are up
    # If they are not, the kopf watches will not start properly
    for crd in registry.get_crd_resources():
        api_group = crd["spec"]["group"]
        preferred_version = next(
            v["name"] for v in crd["spec"]["versions"] if v["storage"]
        )
        api_version = f"{api_group}/{preferred_version}"
        plural_name = crd["spec"]["names"]["plural"]
        try:
            _ = await K8S_CLIENT.get(f"/apis/{api_version}/{plural_name}")
        except Exception:
            LOG.exception("api for %s not available - exiting", crd["metadata"]["name"])
            sys.exit(1)


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
        "clustertypes/status"
    )
    await cluster_type_resource.patch(
        name,
        dict(status=status),
        namespace=namespace,
    )


# TODO(johngarbutt): move to utils.cluster_type
async def _fetch_ui_meta_from_url(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            response.raise_for_status()
            return yaml.safe_load(await response.text())


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
        if cluster_type.status.phase != cluster_type_crd.ClusterTypePhase.PENDING:
            # make cluster type unavailable while we update it
            cluster_type.status.phase = cluster_type_crd.ClusterTypePhase.PENDING
            await _update_cluster_type(K8S_CLIENT, name, namespace, cluster_type.status)

        ui_meta_obj = await _fetch_ui_meta_from_url(cluster_type.spec.uiMetaUrl)
        cluster_type.status = cluster_type_crd.ClusterTypeStatus(
            phase=cluster_type_crd.ClusterTypePhase.AVAILABLE,
            uiMeta=ui_meta_obj,
            uiMetaUrl=cluster_type.spec.uiMetaUrl,
        )
        await _update_cluster_type(K8S_CLIENT, name, namespace, cluster_type.status)


@kopf.on.resume(registry.API_GROUP, "cluster")
async def cluster_resume(body, name, namespace, **kwargs):
    LOG.debug(f"Resuming cluster {name} in {namespace}")
    # Ensure that the clusterID is set for all clusters
    cluster = cluster_crd.Cluster(**body)
    await cluster_utils.ensure_cluster_id(K8S_CLIENT, cluster)


@kopf.on.create(registry.API_GROUP, "cluster")
async def cluster_create(body, name, namespace, labels, **kwargs):
    LOG.debug(f"Attempt cluster create for {name} in {namespace}")
    cluster = cluster_crd.Cluster(**body)

    # Before doing anything, ensure the clusterID is set
    await cluster_utils.ensure_cluster_id(K8S_CLIENT, cluster)

    # If cluster reconciliation is paused, don't do anything else
    if cluster.spec.paused:
        LOG.info(f"Cluster {name} in {namespace} is paused - no action taken")
        return

    # Wait for Blazar lease to be active
    flavor_map = await lease_utils.ensure_lease_active(K8S_CLIENT, cluster)
    await cluster_utils.update_cluster_flavors(K8S_CLIENT, cluster, flavor_map)

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
        outputs = await ansible_runner.get_outputs_from_job(K8S_CLIENT, create_job)
        if is_job_success:
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
            error = "Failed to create platform. To retry please click patch."
            reason = await ansible_runner.get_job_error_message(K8S_CLIENT, create_job)
            if reason:
                error += f" Possible reason for the failure was: {reason}"

            await cluster_utils.update_cluster(
                K8S_CLIENT,
                name,
                namespace,
                cluster_crd.ClusterPhase.FAILED,
                # TODO(johngarbutt): we to better information on the reason!
                error=error,
                outputs=outputs,
            )
            LOG.error(f"Create job failed for {name} in {namespace} because {reason}")
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

    # Before doing anything, ensure the clusterID is set
    await cluster_utils.ensure_cluster_id(K8S_CLIENT, cluster)

    # If cluster reconciliation is paused, don't do anything else
    if cluster.spec.paused:
        LOG.info(f"Cluster {name} in {namespace} is paused - no action taken")
        return

    # Wait for Blazar lease to be active
    await lease_utils.ensure_lease_active(K8S_CLIENT, cluster)

    # Fail if create is still in progress
    # Note that we don't care if create worked.
    # If create failed, we allow update and patch to trigger a retry
    if await ansible_runner.is_create_job_running(K8S_CLIENT, name, namespace):
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
        outputs = await ansible_runner.get_outputs_from_job(K8S_CLIENT, update_job)
        if is_job_success:
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
            error = "Failed to update the platform. To retry please click patch."
            reason = await ansible_runner.get_job_error_message(K8S_CLIENT, update_job)
            if reason:
                error += f" Possible reason for the failure was: {reason}"

            await ansible_runner.unlabel_job(K8S_CLIENT, update_job)
            await cluster_utils.update_cluster(
                K8S_CLIENT,
                name,
                namespace,
                cluster_crd.ClusterPhase.FAILED,
                # TODO(johngarbutt): we to better information on the reason!
                error=error,
                outputs=outputs,
            )
            LOG.error(f"Update job failed for {name} in {namespace} because {reason}")
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

    # Before doing anything, ensure the clusterID is set
    await cluster_utils.ensure_cluster_id(K8S_CLIENT, cluster)

    # If cluster reconciliation is paused, don't do anything else
    if cluster.spec.paused:
        LOG.info(f"Cluster {name} in {namespace} is paused - no action taken")
        return

    # Check for any pending jobs
    # and fail if we are still running a create job
    await ansible_runner.ensure_create_jobs_finished(K8S_CLIENT, name, namespace)
    delete_job = await ansible_runner.get_delete_job_for_cluster(
        K8S_CLIENT, name, namespace
    )

    # delete job not yet created, lets create one
    if not delete_job:
        await ansible_runner.start_job(K8S_CLIENT, cluster, namespace, remove=True)
        await cluster_utils.update_cluster(
            K8S_CLIENT, name, namespace, cluster_crd.ClusterPhase.DELETING
        )
        LOG.info(f"Success creating a delete job for {name} in {namespace}")
        raise kopf.TemporaryError(
            f"Wait for delete job to complete for {name} in {namespace}", delay=20
        )

    # delete job was created last time, check on progress
    is_job_success = ansible_runner.get_job_completed_state(delete_job)

    # raise exception to retry if the job is still running
    if is_job_success is None:
        await cluster_utils.update_cluster(
            K8S_CLIENT, name, namespace, cluster_crd.ClusterPhase.DELETING
        )
        msg = f"Wait for delete job to complete for {name} in {namespace}"
        LOG.info(msg)
        # Wait 20 seconds before checking if the delete has completed
        raise kopf.TemporaryError(msg, delay=20)

    if is_job_success:
        await ansible_runner.delete_secret(
            K8S_CLIENT, cluster, namespace
        )
        LOG.info(f"Delete job complete for {name} in {namespace}")
        # let kopf remove finalizer and complete the cluster delete
        return

    else:
        # job failed, update the cluster, and keep retrying
        error = "Failure when trying to delete platform."
        reason = await ansible_runner.get_job_error_message(K8S_CLIENT, delete_job)
        if reason:
            error += f" Possible reason for the failure was: {reason}"

        # don't go into an error state as we keep retrying,
        # but do set an error message to help debugging
        await cluster_utils.update_cluster(
            K8S_CLIENT,
            name,
            namespace,
            cluster_crd.ClusterPhase.DELETING,
            error=error,
        )
        # unlabel the job, so we trigger a retry next time
        await ansible_runner.unlabel_job(K8S_CLIENT, delete_job)

        # Wait 60 seconds before retrying the delete
        msg = f"Delete job failed for {name} in {namespace} because: {reason}"
        LOG.error(msg)
        raise kopf.TemporaryError(msg, delay=60)
