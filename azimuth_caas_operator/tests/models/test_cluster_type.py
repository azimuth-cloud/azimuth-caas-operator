import json

from azimuth_caas_operator.models import registry
from azimuth_caas_operator.tests import base


class TestClusterType(base.TestCase):
    def test_registry_size(self):
        reg = registry.get_registry()
        self.assertEqual(2, len(list(reg)))

    def test_cluster_type_crd_json(self):
        crds = list(registry.get_registry())
        cluster_type_crd = None
        for crd in crds:
            resource = crd.kubernetes_resource()
            meta = resource.get("metadata", {})
            name = meta.get("name")
            if name == "clustertypes.azimuth.stackhpc.com":
                cluster_type_crd = resource

        actual = json.dumps(cluster_type_crd, indent=2)
        expected = """{
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
      "categories": [
        "azimuth"
      ]
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
        self.assertEqual(expected, actual)

    def test_cluster_crd_json(self):
        crds = list(registry.get_registry())
        cluster_crd = None
        for crd in crds:
            resource = crd.kubernetes_resource()
            meta = resource.get("metadata", {})
            name = meta.get("name")
            if name == "clusters.azimuth.stackhpc.com":
                cluster_crd = resource

        actual = json.dumps(cluster_crd, indent=2)
        expected = """{
  "apiVersion": "apiextensions.k8s.io/v1",
  "kind": "CustomResourceDefinition",
  "metadata": {
    "name": "clusters.azimuth.stackhpc.com"
  },
  "spec": {
    "group": "azimuth.stackhpc.com",
    "scope": "Cluster",
    "names": {
      "kind": "Cluster",
      "singular": "cluster",
      "plural": "clusters",
      "shortNames": [],
      "categories": [
        "azimuth"
      ]
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
                  "clusterTypeName": {
                    "type": "string"
                  }
                },
                "required": [
                  "clusterTypeName"
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
                      "Configuring",
                      "Ready",
                      "Failed",
                      "Deleting"
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
        self.assertEqual(expected, actual)
