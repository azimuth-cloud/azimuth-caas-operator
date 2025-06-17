import datetime
import logging
import os

import easykube
import kopf

from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd

SCHEDULE_API_VERSION = "scheduling.azimuth.stackhpc.com/v1alpha1"
FINALIZER = "caas.azimuth.stackhpc.com"
LOG = logging.getLogger(__name__)


class LeaseInError(Exception):
    pass


async def adopt_lease(client, cluster: cluster_crd.Cluster):
    """
    Ensures that the lease for the cluster is adopted by the cluster.
    """
    ekleases = await client.api(SCHEDULE_API_VERSION).resource("leases")
    lease = await ekleases.fetch(
        cluster.spec.leaseName, namespace=cluster.metadata.namespace
    )
    lease_patch = []
    if "finalizers" not in lease.metadata:
        lease_patch.append(
            {
                "op": "add",
                "path": "/metadata/finalizers",
                "value": [],
            }
        )
    if FINALIZER not in lease.metadata.get("finalizers", []):
        lease_patch.append(
            {
                "op": "add",
                "path": "/metadata/finalizers/-",
                "value": FINALIZER,
            }
        )
    if "ownerReferences" not in lease.metadata:
        lease_patch.append(
            {
                "op": "add",
                "path": "/metadata/ownerReferences",
                "value": [],
            }
        )
    if not any(
        ref["uid"] == cluster.metadata.uid
        for ref in lease.metadata.get("ownerReferences", [])
    ):
        lease_patch.append(
            {
                "op": "add",
                "path": "/metadata/ownerReferences/-",
                "value": {
                    "apiVersion": cluster.api_version,
                    "kind": cluster.kind,
                    "name": cluster.metadata.name,
                    "uid": cluster.metadata.uid,
                    "blockOwnerDeletion": True,
                },
            }
        )
    if lease_patch:
        lease = await ekleases.json_patch(
            lease.metadata.name, lease_patch, namespace=lease.metadata.namespace
        )
    return lease


async def release_lease(client, cluster: cluster_crd.Cluster):
    ekleases = await client.api(SCHEDULE_API_VERSION).resource("leases")
    try:
        lease = await ekleases.fetch(
            cluster.spec.leaseName, namespace=cluster.metadata.namespace
        )
    except easykube.ApiError as exc:
        if exc.status_code == 404:
            return
        else:
            raise
    # Remove our finalizer from the lease to indicate that we are done with it
    existing_finalizers = lease.metadata.get("finalizers", [])
    if FINALIZER in existing_finalizers:
        await ekleases.patch(
            lease.metadata.name,
            {
                "metadata": {
                    "finalizers": [f for f in existing_finalizers if f != FINALIZER],
                },
            },
            namespace=lease.metadata.namespace,
        )


async def ensure_lease_active(client, cluster: cluster_crd.Cluster):
    """
    Ensures that the given cluster has it's ID set.
    """
    if not cluster.spec.leaseName:
        LOG.info("No leaseName set, skipping lease check.")
        return {}

    # Get and adopt the lease
    lease = await adopt_lease(client, cluster)

    lease_status = lease.get("status", {})

    if lease_status.get("phase", "Unknown") == "Active":
        LOG.info("Lease is active!")
        # return mapping of requested flavor to reservation flavor
        return lease["status"]["sizeMap"]

    if lease_status.get("phase", "Unknown") == "Error":
        raise LeaseInError(lease_status.get("errorMessage", "Error creating lease"))

    LOG.info(f"Lease {cluster.spec.leaseName} is not active, wait till active.")
    delay = int(os.environ.get("LEASE_CHECK_INTERVAL_SECONDS", "10"))
    if lease:
        lease_start_str = lease["spec"].get("startTime")
        if lease_start_str:
            lease_start = datetime.datetime.fromisoformat(lease_start_str).astimezone(
                tz=datetime.timezone.utc
            )
            time_until_expiry = lease_start - datetime.datetime.now(
                tz=datetime.timezone.utc
            )
            if time_until_expiry.total_seconds() > delay:
                delay = time_until_expiry.total_seconds()

    # Wait until the lease is active
    raise kopf.TemporaryError(
        f"Lease {cluster.spec.leaseName} is not active.", delay=delay
    )
