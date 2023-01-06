import json

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
        expected = """\
{
  "apiVersion": "apiextensions.k8s.io/v1",
  "kind": "CustomResourceDefinition",
  "metadata": {
    "name": "clustertypes.azimuth.stackhpc.com"
  },
  "spec": {
    "group": "azimuth.stackhpc.com",
    "scope": "Cluster",
    "names": {
      "kind": "ClusterType",
      "singular": "clustertype",
      "plural": "clustertypes",
      "shortNames": [],
      "categories": "azimuth"
    },
    "versions": [
      {
        "name": "v1alpha1",
        "served": true,
        "storage": true,
        "schema": {
          "openAPIV3Schema": {
            "description": "Base class for defining custom resources.",
            "type": "object",
            "properties": {
              "spec": {
                "description": "Base model for use within CRD definitions.",
                "type": "object",
                "properties": {
                  "gitUrl": {
                    "type": "string"
                  }
                },
                "required": [
                  "gitUrl"
                ]
              },
              "status": {
                "description": "Base model for use within CRD definitions.",
                "type": "object",
                "properties": {
                  "phase": {
                    "description": "An enumeration.",
                    "enum": [
                      "Pending",
                      "Available",
                      "Failed"
                    ],
                    "type": "string"
                  }
                }
              }
            },
            "required": [
              "spec"
            ],
            "x-kubernetes-preserve-unknown-fields": true
          }
        },
        "subresources": {},
        "additionalPrinterColumns": [
          {
            "name": "Age",
            "type": "date",
            "jsonPath": ".metadata.creationTimestamp"
          }
        ]
      }
    ]
  }
}"""
        actual = json.dumps(crds[0].kubernetes_resource(), indent=2)
        self.assertEqual(expected, actual)
