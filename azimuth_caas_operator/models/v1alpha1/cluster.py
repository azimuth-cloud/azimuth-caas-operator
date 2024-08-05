import datetime

import kube_custom_resource as crd
from kube_custom_resource import schema
import pydantic

from azimuth_caas_operator.models.v1alpha1.cluster_type import ClusterTypeSpec


class ClusterPhase(str, schema.Enum):
    CREATING = "Creating"
    CONFIG = "Configuring"
    UPGRADE = "Upgrading"
    READY = "Ready"
    FAILED = "Failed"
    DELETING = "Deleting"


class ClusterStatus(schema.BaseModel):
    phase: ClusterPhase = pydantic.Field(ClusterPhase.CREATING)
    # Persistent cluster ID (set to Kubernetes UID on create or if not set)
    clusterID: schema.Optional[str] = None
    clusterTypeSpec: schema.Optional[ClusterTypeSpec] = None
    # used to detect upgrade requests
    clusterTypeVersion: schema.Optional[str] = None
    # used to detect extra var changes
    appliedExtraVars: schema.Dict[str, schema.Any] = pydantic.Field(
        default_factory=dict
    )
    updatedTimestamp: schema.Optional[datetime.datetime] = pydantic.Field(
        None, description="The timestamp at which the resource was updated."
    )
    patchedTimestamp: schema.Optional[datetime.datetime] = pydantic.Field(
        None, description="The timestamp at which version was last changed."
    )
    outputs: schema.Optional[schema.Dict[str, schema.Any]] = pydantic.Field(
        default_factory=dict
    )
    error: schema.Optional[str] = None


class ClusterSpec(schema.BaseModel):
    clusterTypeName: str = pydantic.Field(min_length=1)
    clusterTypeVersion: str = pydantic.Field(min_length=1)
    cloudCredentialsSecretName: str = pydantic.Field(min_length=1)
    leaseName: schema.Optional[str] = None
    # partially described by the cluster type ui-meta
    extraVars: schema.Dict[str, schema.Any] = pydantic.Field(default_factory=dict)
    createdByUsername: schema.Optional[str] = None
    createdByUserId: schema.Optional[str] = None
    updatedByUsername: schema.Optional[str] = None
    updatedByUserId: schema.Optional[str] = None
    paused: bool = False


class Cluster(
    crd.CustomResource,
    scope=crd.Scope.NAMESPACED,
    subresources={"status": {}},
    printer_columns=[
        {
            "name": "Cluster Type",
            "type": "string",
            "jsonPath": ".spec.clusterTypeName",
        },
        {
            "name": "Cluster Type Version",
            "type": "string",
            "jsonPath": ".spec.clusterTypeVersion",
        },
        {
            "name": "Phase",
            "type": "string",
            "jsonPath": ".status.phase",
        },
        {
            "name": "Cluster ID",
            "type": "string",
            "jsonPath": ".status.clusterID",
        },
    ],
):
    spec: ClusterSpec
    status: ClusterStatus = pydantic.Field(default_factory=ClusterStatus)


def get_fake():
    return Cluster(**get_fake_dict())


def get_fake_dict():
    return dict(
        apiVersion="caas.azimuth.stackhpc.com/v1alpha1",
        kind="Cluster",
        metadata=dict(name="test1", uid="fakeuid1", namespace="ns1"),
        spec=dict(
            clusterTypeName="type1",
            clusterTypeVersion="1234",
            cloudCredentialsSecretName="cloudsyaml",
            leaseName="test1",
            extraVars=dict(foo="bar", very_random_int=42, nested=dict(baz="bob")),
        ),
        status=dict(clusterID="fakeclusterID1"),
    )
