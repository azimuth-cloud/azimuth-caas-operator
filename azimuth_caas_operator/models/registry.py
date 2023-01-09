import kube_custom_resource as crd

from azimuth_caas_operator.models.v1alpha1 import cluster
from azimuth_caas_operator.models.v1alpha1 import cluster_type

API_GROUP = "azimuth.stackhpc.com"
CATEGORIES = ["azimuth"]


def get_registry():
    registry = crd.CustomResourceRegistry(API_GROUP, CATEGORIES)
    registry.discover_models(cluster)
    registry.discover_models(cluster_type)
    return registry


def get_crd_resources():
    reg = get_registry()
    for resource in reg:
        yield resource.kubernetes_resource()


def parse_model(raw: str):
    reg = get_registry()
    return reg.get_model_instance(raw)
