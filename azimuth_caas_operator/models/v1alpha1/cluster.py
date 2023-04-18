import datetime
import typing

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
    clusterTypeSpec: typing.Optional[ClusterTypeSpec]
    # used to detect upgrade requests
    clusterTypeVersion: typing.Optional[str]
    # used to detect extra var changes
    appliedExtraVars: schema.Dict[str, schema.Any] = pydantic.Field(
        default_factory=dict
    )
    updatedTimestamp: typing.Optional[datetime.datetime] = pydantic.Field(
        None, description="The timestamp at which the resource was updated."
    )
    outputs: typing.Optional[schema.Dict[str, schema.Any]] = pydantic.Field(
        default_factory=dict
    )
    error: typing.Optional[str]


class ClusterSpec(schema.BaseModel):
    clusterTypeName: str = pydantic.Field(min_length=1)
    clusterTypeVersion: str = pydantic.Field(min_length=1)
    cloudCredentialsSecretName: str = pydantic.Field(min_length=1)
    # partially described by the cluster type ui-meta
    extraVars: schema.Dict[str, schema.Any] = pydantic.Field(default_factory=dict)


class Cluster(crd.CustomResource, scope=crd.Scope.NAMESPACED):
    spec: ClusterSpec
    status: ClusterStatus = pydantic.Field(default_factory=ClusterStatus)


def get_fake():
    return Cluster(**get_fake_dict())


def get_fake_dict():
    return dict(
        apiVersion="fake",
        kind="Cluster",
        metadata=dict(name="test1", uid="fakeuid1"),
        spec=dict(
            clusterTypeName="type1",
            clusterTypeVersion="1234",
            cloudCredentialsSecretName="cloudsyaml",
            extraVars=dict(foo="bar", very_random_int=42, nested=dict(baz="bob")),
        ),
    )
