from azimuth_caas_operator.models import registry
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd


async def get_cluster_type_info(client, cluster):
    # TODO(johngarbutt): the first time we hit this for each cluster we should
    # cache the current version
    cluster_type_name = cluster.spec.clusterTypeName
    cluster_type_resource = await client.api(registry.API_VERSION).resource(
        "clustertype"
    )
    cluster_type_raw = await cluster_type_resource.fetch(cluster_type_name)
    return cluster_type_crd.ClusterType(**cluster_type_raw)
