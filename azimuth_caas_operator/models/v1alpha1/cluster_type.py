import kube_custom_resource as crd
from kube_custom_resource import schema
import pydantic


class ClusterTypePhase(str, schema.Enum):
    PENDING = "Pending"
    AVAILABLE = "Available"
    FAILED = "Failed"


class ClusterTypeStatus(schema.BaseModel):
    phase: ClusterTypePhase = pydantic.Field(ClusterTypePhase.PENDING)


class ClusterTypeSpec(schema.BaseModel):
    uiMetaUrl: pydantic.AnyHttpUrl
    gitUrl: pydantic.AnyUrl
    gitVersion: str
    # Playbook is contained in the above git repo
    playbook: str
    # Option to add cloud specific details, like the image
    extraVars: dict[str, str] = pydantic.Field(default_factory=dict[str, str])


class ClusterType(crd.CustomResource, scope=crd.Scope.CLUSTER):
    spec: ClusterTypeSpec
    status: ClusterTypeStatus = pydantic.Field(default_factory=ClusterTypeStatus)
