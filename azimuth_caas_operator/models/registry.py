import kube_custom_resource as crd

from azimuth_caas_operator.models.v1alpha1 import cluster_type

API_GROUP = "azimuth.stackhpc.com"
CATEGORIES = "azimuth"


def get_registry():
    registry = crd.CustomResourceRegistry(API_GROUP, CATEGORIES)
    registry.discover_models(cluster_type)
    return registry
