import datetime
import logging

import easykube
import kopf

from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd

SCHEDULE_API_VERSION = "scheduling.azimuth.stackhpc.com/v1alpha1"
FINALIZER = "caas.azimuth.stackhpc.com"
LOG = logging.getLogger(__name__)


class LeaseInError(Exception):
    pass


async def _patch_finalizers(resource, name, namespace, finalizers):
    """
    Patches the finalizers of a resource. If the resource does not exist any
    more, that is classed as a success.
    """
    try:
        await resource.patch(
            name, {"metadata": {"finalizers": finalizers}}, namespace=namespace
        )
    except easykube.ApiError as exc:
        if exc.status_code != 404:
            raise


async def ensure_lease_active(client, cluster: cluster_crd.Cluster):
    """
    Ensures that the given cluster has it's ID set.
    """
    if not cluster.spec.leaseName:
        LOG.info("No leaseName set, skipping lease check.")
        return {}

    lease_resource = await client.api(SCHEDULE_API_VERSION).resource("leases")
    lease = await lease_resource.fetch(
        cluster.spec.leaseName,
        namespace=cluster.metadata.namespace,
    )

    # we want to use this lease, so lets add a finalizer
    # we can remove once we are happy to delete the lease
    finalizers = lease.get("metadata", {}).get("finalizers", [])
    if FINALIZER not in finalizers:
        finalizers.append(FINALIZER)
        await _patch_finalizers(
            lease_resource,
            cluster.spec.leaseName,
            cluster.metadata.namespace,
            finalizers,
        )
        LOG.info("Added finalizer to the lease.")

    lease_status = lease.get("status", {})

    if lease_status.get("phase", "Unknown") == "Active":
        LOG.info("Lease is active!")
        # return mapping of requested flavor to reservation flavor
        return lease["status"]["sizeMap"]

    if lease_status.get("phase", "Unknown") == "Error":
        raise LeaseInError(lease_status.get("errorMessage", "Error creating lease"))

    LOG.info(f"Lease {cluster.spec.leaseName} is not active, wait till active.")
    delay = 60
    if lease:
        lease_start = lease["spec"].get("startTime")
        if lease_start:
            time_until_expiry = lease_start - datetime.datetime.now(
                tz=datetime.timezone.utc
            )
            if time_until_expiry.total_seconds() > 60:
                delay = time_until_expiry.total_seconds()

    # Wait until the lease is active
    raise kopf.TemporaryError(
        f"Lease {cluster.spec.leaseName} is not active.", delay=delay
    )


async def drop_lease_finalizer(client, cluster: cluster_crd.Cluster):
    lease_resource = await client.api(SCHEDULE_API_VERSION).resource("leases")
    try:
        lease = await lease_resource.fetch(
            cluster.spec.leaseName,
            namespace=cluster.metadata.namespace,
        )
    except easykube.ApiError as exc:
        if exc.status_code == 404:
            return
        else:
            raise
    finalizers = lease.get("metadata", {}).get("finalizers", [])
    await _patch_finalizers(
        lease_resource,
        cluster.spec.leaseName,
        cluster.metadata.namespace,
        [f for f in finalizers if f != FINALIZER],
    )
