from pydantic import Field

import kube_custom_resource as crd
from kube_custom_resource import schema


class ClusterPhase(str, schema.Enum):
    PENDING = "Pending"
    AVAILABLE = "Available"
    FAILED = "Failed"


class ClusterStatus(schema.BaseModel):
    phase: ClusterPhase = Field(ClusterPhase.PENDING)


class ClusterSpec(schema.BaseModel):
    gitUrl: str


class Cluster(crd.CustomResource, scope=crd.Scope.CLUSTER):
    spec: ClusterSpec
    status: ClusterStatus = Field(default_factory=ClusterStatus)
