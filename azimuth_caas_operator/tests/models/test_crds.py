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
            "description": "Base class for defining custom resources.",
            "type": "object",
            "properties": {
              "spec": {
                "description": "Base model for use within CRD definitions.",
                "type": "object",
                "properties": {
                  "uiMetaUrl": {
                    "minLength": 1,
                    "maxLength": 65536,
                    "format": "uri",
                    "type": "string"
                  },
                  "gitUrl": {
                    "minLength": 1,
                    "maxLength": 65536,
                    "format": "uri",
                    "type": "string"
                  },
                  "gitVersion": {
                    "type": "string"
                  },
                  "playbook": {
                    "type": "string"
                  },
                  "extraVars": {
                    "type": "object",
                    "additionalProperties": {
                      "type": "string"
                    }
                  }
                },
                "required": [
                  "uiMetaUrl",
                  "gitUrl",
                  "gitVersion",
                  "playbook"
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
                  },
                  "uiMeta": {
                    "type": "object",
                    "properties": {
                      "name": {
                        "type": "string"
                      },
                      "label": {
                        "type": "string"
                      },
                      "description": {
                        "type": "string"
                      },
                      "logo": {
                        "type": "string"
                      },
                      "requiresSshKey": {
                        "type": "boolean"
                      },
                      "parameters": {
                        "type": "array",
                        "items": {
                          "type": "object",
                          "properties": {
                            "name": {
                              "type": "string"
                            },
                            "label": {
                              "type": "string"
                            },
                            "description": {
                              "type": "string"
                            },
                            "kind": {
                              "type": "string"
                            },
                            "options": {
                              "type": "object",
                              "additionalProperties": {
                                "type": "string"
                              }
                            },
                            "immutable": {
                              "type": "boolean"
                            },
                            "required": {
                              "type": "boolean"
                            },
                            "default": {
                              "type": "string"
                            }
                          },
                          "required": [
                            "name",
                            "label",
                            "description",
                            "kind",
                            "options",
                            "immutable",
                            "required",
                            "default"
                          ]
                        }
                      },
                      "services": {
                        "type": "array",
                        "items": {
                          "type": "object",
                          "properties": {
                            "name": {
                              "type": "string"
                            },
                            "label": {
                              "type": "string"
                            },
                            "iconUrl": {
                              "type": "string"
                            },
                            "when": {
                              "type": "string"
                            }
                          },
                          "required": [
                            "name",
                            "label",
                            "iconUrl",
                            "when"
                          ]
                        }
                      },
                      "usageTemplate": {
                        "type": "string"
                      }
                    },
                    "required": [
                      "name",
                      "label",
                      "description",
                      "logo",
                      "requiresSshKey",
                      "parameters",
                      "services",
                      "usageTemplate"
                    ]
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
            "description": "Base class for defining custom resources.",
            "type": "object",
            "properties": {
              "spec": {
                "description": "Base model for use within CRD definitions.",
                "type": "object",
                "properties": {
                  "clusterTypeName": {
                    "type": "string"
                  },
                  "clusterTypeVersion": {
                    "type": "string"
                  },
                  "cloudCredentialsSecretName": {
                    "type": "string"
                  },
                  "extraVars": {
                    "type": "object",
                    "additionalProperties": {
                      "type": "string"
                    }
                  }
                },
                "required": [
                  "clusterTypeName",
                  "cloudCredentialsSecretName"
                ]
              },
              "status": {
                "description": "Base model for use within CRD definitions.",
                "type": "object",
                "properties": {
                  "phase": {
                    "description": "An enumeration.",
                    "enum": [
                      "Creating",
                      "Configuring",
                      "Ready",
                      "Failed",
                      "Deleting"
                    ],
                    "type": "string"
                  },
                  "clusterTypeSpec": {
                    "description": "Base model for use within CRD definitions.",
                    "type": "object",
                    "properties": {
                      "uiMetaUrl": {
                        "minLength": 1,
                        "maxLength": 65536,
                        "format": "uri",
                        "type": "string"
                      },
                      "gitUrl": {
                        "minLength": 1,
                        "maxLength": 65536,
                        "format": "uri",
                        "type": "string"
                      },
                      "gitVersion": {
                        "type": "string"
                      },
                      "playbook": {
                        "type": "string"
                      },
                      "extraVars": {
                        "type": "object",
                        "additionalProperties": {
                          "type": "string"
                        }
                      }
                    },
                    "required": [
                      "uiMetaUrl",
                      "gitUrl",
                      "gitVersion",
                      "playbook"
                    ]
                  },
                  "clusterTypeVersion": {
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
