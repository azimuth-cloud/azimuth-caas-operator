import kube_custom_resource as crd

from azimuth_caas_operator.models.v1alpha1 import cluster_type
from azimuth_caas_operator.tests import base


API_GROUP = "azimuth.stackhpc.com"
CATEGORIES = "azimuth"

REGISTRY = crd.CustomResourceRegistry(API_GROUP, CATEGORIES)
REGISTRY.discover_models(cluster_type)

class TestClusterType(base.TestCase):
    def test_cluster_type_crd(self):
        crds = list(REGISTRY)
        self.assertEqual(1, len(crds))
        expected = "CRD"
        self.assertEqual(expected, crds[0].kubernetes_resource())
