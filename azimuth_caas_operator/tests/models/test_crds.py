import json

from azimuth_caas_operator.models import registry
from azimuth_caas_operator.tests import base


class TestModels(base.TestCase):
    def test_cluster_type_crd_json(self):
        cluster_type_crd = None
        for resource in registry.get_crd_resources():
            meta = resource.get("metadata", {})
            name = meta.get("name")
            if name == "clustertypes.caas.azimuth.stackhpc.com":
                cluster_type_crd = resource

        actual = json.dumps(cluster_type_crd, indent=2)
        expected = """{
  "apiVersion": "apiextensions.k8s.io/v1",
  "kind": "CustomResourceDefinition",
  "metadata": {
    "name": "clustertypes.caas.azimuth.stackhpc.com"
  },
  "spec": {
    "group": "caas.azimuth.stackhpc.com",
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
            "properties": {
              "spec": {
                "properties": {
                  "uiMetaUrl": {
                    "format": "uri",
                    "minLength": 1,
                    "type": "string"
                  },
                  "gitUrl": {
                    "format": "uri",
                    "minLength": 1,
                    "type": "string"
                  },
                  "gitVersion": {
                    "type": "string"
                  },
                  "playbook": {
                    "type": "string"
                  },
                  "jobTimeout": {
                    "type": "integer"
                  },
                  "extraVars": {
                    "additionalProperties": {
                      "x-kubernetes-preserve-unknown-fields": true
                    },
                    "type": "object",
                    "x-kubernetes-preserve-unknown-fields": true
                  },
                  "envVars": {
                    "additionalProperties": {
                      "x-kubernetes-preserve-unknown-fields": true
                    },
                    "type": "object",
                    "x-kubernetes-preserve-unknown-fields": true
                  },
                  "sshSharedSecretName": {
                    "nullable": true,
                    "type": "string"
                  },
                  "sshSharedSecretNamespace": {
                    "nullable": true,
                    "type": "string"
                  }
                },
                "required": [
                  "uiMetaUrl",
                  "gitUrl",
                  "gitVersion",
                  "playbook"
                ],
                "type": "object"
              },
              "status": {
                "properties": {
                  "phase": {
                    "enum": [
                      "Pending",
                      "Available",
                      "Failed"
                    ],
                    "type": "string"
                  },
                  "uiMeta": {
                    "additionalProperties": {
                      "x-kubernetes-preserve-unknown-fields": true
                    },
                    "type": "object",
                    "x-kubernetes-preserve-unknown-fields": true
                  },
                  "uiMetaUrl": {
                    "format": "uri",
                    "minLength": 1,
                    "nullable": true,
                    "type": "string"
                  },
                  "updatedTimestamp": {
                    "description": "The timestamp at which the resource was updated.",
                    "format": "date-time",
                    "nullable": true,
                    "type": "string"
                  }
                },
                "type": "object"
              }
            },
            "required": [
              "spec"
            ],
            "type": "object"
          }
        },
        "subresources": {
          "status": {}
        },
        "additionalPrinterColumns": [
          {
            "name": "Git URL",
            "type": "string",
            "jsonPath": ".spec.gitUrl"
          },
          {
            "name": "Git Version",
            "type": "string",
            "jsonPath": ".spec.gitVersion"
          },
          {
            "name": "Playbook",
            "type": "string",
            "jsonPath": ".spec.playbook"
          },
          {
            "name": "Phase",
            "type": "string",
            "jsonPath": ".status.phase"
          },
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
        cluster_crd = None
        for resource in registry.get_crd_resources():
            meta = resource.get("metadata", {})
            name = meta.get("name")
            if name == "clusters.caas.azimuth.stackhpc.com":
                cluster_crd = resource

        actual = json.dumps(cluster_crd, indent=2)
        expected = """{
  "apiVersion": "apiextensions.k8s.io/v1",
  "kind": "CustomResourceDefinition",
  "metadata": {
    "name": "clusters.caas.azimuth.stackhpc.com"
  },
  "spec": {
    "group": "caas.azimuth.stackhpc.com",
    "scope": "Namespaced",
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
            "properties": {
              "spec": {
                "properties": {
                  "clusterTypeName": {
                    "minLength": 1,
                    "type": "string"
                  },
                  "clusterTypeVersion": {
                    "minLength": 1,
                    "type": "string"
                  },
                  "cloudCredentialsSecretName": {
                    "minLength": 1,
                    "type": "string"
                  },
                  "leaseName": {
                    "nullable": true,
                    "type": "string"
                  },
                  "extraVars": {
                    "additionalProperties": {
                      "x-kubernetes-preserve-unknown-fields": true
                    },
                    "type": "object",
                    "x-kubernetes-preserve-unknown-fields": true
                  },
                  "extraVarOverrides": {
                    "additionalProperties": {
                      "x-kubernetes-preserve-unknown-fields": true
                    },
                    "nullable": true,
                    "type": "object",
                    "x-kubernetes-preserve-unknown-fields": true
                  },
                  "createdByUsername": {
                    "nullable": true,
                    "type": "string"
                  },
                  "createdByUserId": {
                    "nullable": true,
                    "type": "string"
                  },
                  "updatedByUsername": {
                    "nullable": true,
                    "type": "string"
                  },
                  "updatedByUserId": {
                    "nullable": true,
                    "type": "string"
                  },
                  "paused": {
                    "type": "boolean"
                  }
                },
                "required": [
                  "clusterTypeName",
                  "clusterTypeVersion",
                  "cloudCredentialsSecretName"
                ],
                "type": "object"
              },
              "status": {
                "properties": {
                  "phase": {
                    "enum": [
                      "Creating",
                      "Configuring",
                      "Upgrading",
                      "Ready",
                      "Failed",
                      "Deleting"
                    ],
                    "type": "string"
                  },
                  "clusterID": {
                    "nullable": true,
                    "type": "string"
                  },
                  "clusterTypeSpec": {
                    "nullable": true,
                    "properties": {
                      "uiMetaUrl": {
                        "format": "uri",
                        "minLength": 1,
                        "type": "string"
                      },
                      "gitUrl": {
                        "format": "uri",
                        "minLength": 1,
                        "type": "string"
                      },
                      "gitVersion": {
                        "type": "string"
                      },
                      "playbook": {
                        "type": "string"
                      },
                      "jobTimeout": {
                        "type": "integer"
                      },
                      "extraVars": {
                        "additionalProperties": {
                          "x-kubernetes-preserve-unknown-fields": true
                        },
                        "type": "object",
                        "x-kubernetes-preserve-unknown-fields": true
                      },
                      "envVars": {
                        "additionalProperties": {
                          "x-kubernetes-preserve-unknown-fields": true
                        },
                        "type": "object",
                        "x-kubernetes-preserve-unknown-fields": true
                      },
                      "sshSharedSecretName": {
                        "nullable": true,
                        "type": "string"
                      },
                      "sshSharedSecretNamespace": {
                        "nullable": true,
                        "type": "string"
                      }
                    },
                    "required": [
                      "uiMetaUrl",
                      "gitUrl",
                      "gitVersion",
                      "playbook"
                    ],
                    "type": "object"
                  },
                  "clusterTypeVersion": {
                    "nullable": true,
                    "type": "string"
                  },
                  "appliedExtraVars": {
                    "additionalProperties": {
                      "x-kubernetes-preserve-unknown-fields": true
                    },
                    "type": "object",
                    "x-kubernetes-preserve-unknown-fields": true
                  },
                  "updatedTimestamp": {
                    "description": "The timestamp at which the resource was updated.",
                    "format": "date-time",
                    "nullable": true,
                    "type": "string"
                  },
                  "patchedTimestamp": {
                    "description": "The timestamp at which version was last changed.",
                    "format": "date-time",
                    "nullable": true,
                    "type": "string"
                  },
                  "outputs": {
                    "additionalProperties": {
                      "x-kubernetes-preserve-unknown-fields": true
                    },
                    "nullable": true,
                    "type": "object",
                    "x-kubernetes-preserve-unknown-fields": true
                  },
                  "error": {
                    "nullable": true,
                    "type": "string"
                  }
                },
                "type": "object"
              }
            },
            "required": [
              "spec"
            ],
            "type": "object"
          }
        },
        "subresources": {
          "status": {}
        },
        "additionalPrinterColumns": [
          {
            "name": "Cluster Type",
            "type": "string",
            "jsonPath": ".spec.clusterTypeName"
          },
          {
            "name": "Cluster Type Version",
            "type": "string",
            "jsonPath": ".spec.clusterTypeVersion"
          },
          {
            "name": "Phase",
            "type": "string",
            "jsonPath": ".status.phase"
          },
          {
            "name": "Cluster ID",
            "type": "string",
            "jsonPath": ".status.clusterID"
          },
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
