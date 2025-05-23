import asyncio
import functools

import easykube
from aiohttp import web

from .models import registry


class Metric:
    """Represents a metric."""

    # The name of the metric
    name = None
    # The type of the metric - info or gauge
    type = "info"
    # The description of the metric
    description = None
    # The API version of the resource
    api_version = registry.API_VERSION
    # The resource that the metric is for
    resource = None

    def __init__(self):
        self._objs = []

    def add_obj(self, obj):
        self._objs.append(obj)

    def labels(self, obj):
        """The labels for the given object."""
        raise NotImplementedError

    def value(self, obj):
        """The value for the given object."""
        return 1

    def records(self):
        """Returns the records for the metric, i.e. a list of (labels, value) tuples."""
        for obj in self._objs:
            yield self.labels(obj), self.value(obj)


class ClusterTypePhase(Metric):
    """Metric for the phase of a cluster type."""

    name = "azimuth_caas_clustertypes_phase"
    description = "Cluster type phase"
    resource = "clustertypes"

    def labels(self, obj):
        return {
            "cluster_type_name": obj.metadata.name,
            "cluster_type_version": obj.metadata["resourceVersion"],
            "phase": obj.get("status", {}).get("phase", "Unknown"),
        }


class ClusterPhase(Metric):
    """Metric for the phase of a cluster."""

    name = "azimuth_caas_clusters_phase"
    description = "Cluster phase"
    resource = "clusters"

    def labels(self, obj):
        return {
            "cluster_namespace": obj.metadata.namespace,
            "cluster_name": obj.metadata.name,
            "cluster_type_name": obj.spec["clusterTypeName"],
            "cluster_type_version": obj.spec["clusterTypeVersion"],
            "phase": obj.get("status", {}).get("phase", "Unknown"),
        }


def escape(content):
    """Escape the given content for use in metric output."""
    return content.replace("\\", r"\\").replace("\n", r"\n").replace('"', r"\"")


def render_openmetrics(*metrics):
    """Renders the metrics using OpenMetrics text format."""
    output = []
    for metric in metrics:
        output.append(f"# TYPE {metric.name} {metric.type}\n")
        if metric.description:
            output.append(f"# HELP {metric.name} {escape(metric.description)}\n")

        for labels, value in metric.records():
            if labels:
                labelstr = "{{{0}}}".format(  # noqa
                    ",".join([f'{k}="{escape(v)}"' for k, v in sorted(labels.items())])
                )
            else:
                labelstr = ""
            output.append(f"{metric.name}{labelstr} {value}\n")
    output.append("# EOF\n")

    return (
        "application/openmetrics-text; version=1.0.0; charset=utf-8",
        "".join(output).encode("utf-8"),
    )


async def metrics_handler(ekclient, request):
    """Produce metrics for the operator."""
    ekapi = ekclient.api(registry.API_VERSION)

    cluster_type_phase_metric = ClusterTypePhase()
    cluster_phase_metric = ClusterPhase()

    clustertypes = await ekapi.resource("clustertypes")
    async for cluster_type in clustertypes.list():
        cluster_type_phase_metric.add_obj(cluster_type)

    clusters = await ekapi.resource("clusters")
    async for cluster in clusters.list(all_namespaces=True):
        cluster_phase_metric.add_obj(cluster)

    content_type, content = render_openmetrics(
        cluster_type_phase_metric, cluster_phase_metric
    )
    return web.Response(headers={"Content-Type": content_type}, body=content)


async def metrics_server():
    """Launch a lightweight HTTP server to serve the metrics endpoint."""
    ekclient = easykube.Configuration.from_environment().async_client()

    app = web.Application()
    app.add_routes([web.get("/metrics", functools.partial(metrics_handler, ekclient))])

    runner = web.AppRunner(app, handle_signals=False)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", "8080", shutdown_timeout=1.0)
    await site.start()

    # Sleep until we need to clean up
    try:
        await asyncio.Event().wait()
    finally:
        await asyncio.shield(runner.cleanup())
