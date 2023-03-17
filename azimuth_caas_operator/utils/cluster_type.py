import logging

from azimuth_caas_operator.models import registry
from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd

LOG = logging.getLogger(__name__)


async def get_cluster_type_info(client, cluster: cluster_crd.Cluster):
    if cluster.spec.clusterTypeVersion and (
        cluster.spec.clusterTypeVersion == cluster.status.clusterTypeVersion
    ):
        # We have the correct version cached, so lets return the cache
        return cluster.status.clusterTypeSpec, cluster.status.clusterTypeVersion

    cluster_type_name = cluster.spec.clusterTypeName
    cluster_type_resource = await client.api(registry.API_VERSION).resource(
        "clustertype"
    )
    cluster_type_raw = await cluster_type_resource.fetch(cluster_type_name)
    cluster_type = cluster_type_crd.ClusterType(**cluster_type_raw)

    # TODO(johng): should we fail if we can't find the requested version?
    cluster_version = cluster_type.metadata.resource_version
    if cluster.spec.clusterTypeVersion and (
        cluster_version != cluster.spec.clusterTypeVersion
    ):
        LOG.warning(
            "Requested f{cluster.spec.clusterTypeVersion} "
            "but we found f{cluster_version}"
        )

    await _cache_client_type(client, cluster, cluster_type_raw.spec, cluster_version)
    return cluster_type.spec, cluster_version


async def _cache_client_type(client, cluster, cluster_type_spec, cluster_version):
    cluster_resource = await client.api(registry.API_VERSION).resource("cluster")
    await cluster_resource.patch(
        cluster.metadata.name,
        dict(
            status=dict(
                clusterTypeVersion=cluster_version,
                clusterTypeSpec=cluster_type_spec,
            ),
            spec=dict(clusterTypeVersion=cluster_version),
        ),
        namespace=cluster.metadata.namespace,
    )
