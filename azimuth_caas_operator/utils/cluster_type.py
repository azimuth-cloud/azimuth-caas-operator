import datetime
import logging

from azimuth_caas_operator.models import registry
from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd

LOG = logging.getLogger(__name__)


async def get_cluster_type_info(
    client, cluster: cluster_crd.Cluster
) -> cluster_type_crd.ClusterTypeSpec:
    if cluster.status and (
        cluster.spec.clusterTypeVersion == cluster.status.clusterTypeVersion
    ):
        # We have the correct version cached, so lets return the cache
        return cluster.status.clusterTypeSpec

    # NOTE(johngarbutt): this is required, so it shouldn't ever happen
    if not cluster.spec.clusterTypeVersion:
        LOG.error("User has not specified a cluster version!")
        raise RuntimeError("User must specify a cluster type version!")

    cluster_type_name = cluster.spec.clusterTypeName
    cluster_type_resource = await client.api(registry.API_VERSION).resource(
        "clustertype"
    )
    cluster_type_raw = await cluster_type_resource.fetch(cluster_type_name)
    cluster_type = cluster_type_crd.ClusterType(**cluster_type_raw)

    cluster_version = cluster_type_raw.metadata.resourceVersion
    if cluster_version != cluster.spec.clusterTypeVersion:
        # has been seen with a race in updating clusters
        # and users creating a cluster
        LOG.warning(
            f"Requested {cluster.spec.clusterTypeVersion} "
            f"but we found {cluster_version}"
        )

    await _cache_client_type(client, cluster, cluster_type_raw.spec, cluster_version)
    return cluster_type.spec


async def _cache_client_type(client, cluster, cluster_type_spec, cluster_version):
    patchedTimestamp = None
    # if we have an existing version, add a patched timestamp
    if cluster.status.clusterTypeVersion:
        now = datetime.datetime.now(datetime.timezone.utc)
        patchedTimestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # if we didn't use the requested version,
    # update that to match
    if cluster_version != cluster.spec.clusterTypeVersion:
        cluster_resource = await client.api(registry.API_VERSION).resource("clusters")
        await cluster_resource.patch(
            cluster.metadata.name,
            dict(spec=dict(clusterTypeVersion=cluster_version)),
            namespace=cluster.metadata.namespace,
        )

    cluster_status_resource = await client.api(registry.API_VERSION).resource(
        "clusters/status"
    )
    await cluster_status_resource.patch(
        cluster.metadata.name,
        dict(
            status=dict(
                clusterTypeVersion=cluster_version,
                clusterTypeSpec=cluster_type_spec,
                patchedTimestamp=patchedTimestamp,
            ),
        ),
        namespace=cluster.metadata.namespace,
    )
