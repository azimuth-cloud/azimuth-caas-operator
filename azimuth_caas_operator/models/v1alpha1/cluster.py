import kube_custom_resource as crd
from kube_custom_resource import schema
import pydantic


class ClusterPhase(str, schema.Enum):

    PENDING = "Pending"
    CONFIG = "Configuring"
    READY = "Ready"
    FAILED = "Failed"
    DELETING = "Deleting"


class ClusterStatus(schema.BaseModel):
    phase: ClusterPhase = pydantic.Field(ClusterPhase.PENDING)


class ClusterSpec(schema.BaseModel):
    clusterTypeName: str
    cloudCredentialsSecretName: str
    # as described by the cluster type ui-meta
    extraVars: dict[str, str] = pydantic.Field(default_factory=dict[str, str])


class Cluster(crd.CustomResource, scope=crd.Scope.CLUSTER):
    spec: ClusterSpec
    status: ClusterStatus = pydantic.Field(default_factory=ClusterStatus)
