import datetime
import logging

import kopf

from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd

SCHEDULE_API_VERSION = "scheduling.azimuth.stackhpc.com/v1alpha1"
LOG = logging.getLogger(__name__)


async def ensure_lease_active(client, cluster: cluster_crd.Cluster):
    """
    Ensures that the given cluster has it's ID set.
    """
    if not cluster.spec.leaseName:
        LOG.info("No leaseName set, skipping lease check.")
        return

    lease_resource = await client.api(SCHEDULE_API_VERSION).resource("leases")
    lease = await lease_resource.fetch(
        cluster.spec.leaseName,
        namespace=cluster.metadata.namespace,
    )
    if lease and "status" in lease and lease["status"]["phase"] == "Active":
        LOG.info("Lease is active!")
        # return mapping of requested flavor to reservation flavor
        return lease["status"]["flavorMap"]

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
