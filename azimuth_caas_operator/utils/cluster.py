from azimuth_caas_operator.models import registry


async def update_cluster(client, name, namespace, phase):
    cluster_resource = await client.api(registry.API_VERSION).resource("cluster")
    await cluster_resource.patch(
        name,
        dict(status=dict(phase=phase)),
        namespace=namespace,
    )
