from pydantic import Field

import kube_custom_resource as crd
from kube_custom_resource import schema


class ClusterTypePhase(str, schema.Enum):
    PENDING = "Pending"
    AVAILABLE = "Available"
    FAILED = "Failed"


class ClusterTypeStatus(schema.BaseModel):
    phase: ClusterTypePhase = Field(ClusterTypePhase.PENDING)


class ClusterTypeSpec(schema.BaseModel):
    gitUrl: str


class ClusterType(crd.CustomResource, scope=crd.Scope.CLUSTER):
    spec: ClusterTypeSpec
    status: ClusterTypeStatus = Field(default_factory=ClusterTypeStatus)
