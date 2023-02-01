import dataclasses
import typing

import kube_custom_resource as crd
from kube_custom_resource import schema
import pydantic


class ClusterTypePhase(str, schema.Enum):
    PENDING = "Pending"
    AVAILABLE = "Available"
    FAILED = "Failed"


@dataclasses.dataclass
class ClusterParameter:
    #: The name of the parameter
    name: str
    #: A human-readable label for the parameter
    label: str
    #: A description of the parameter
    description: typing.Optional[str]
    #: The kind of the parameter
    kind: str
    #: A dictionary of kind-specific options for the parameter
    options: typing.Mapping[str, typing.Any]
    #: Indicates if the option is immutable, i.e. cannot be updated
    immutable: bool
    #: Indicates if the parameter is required
    required: bool
    #: A default value for the parameter
    default: typing.Optional[str]  # TODO(johngarbutt): k8s said no if this was any!


@dataclasses.dataclass
class ClusterServiceSpec:
    #: The name of the service
    name: str
    #: A human-readable label for the service
    label: str
    #: The URL of an icon for the service
    iconUrl: typing.Optional[str]
    #: An expression indicating when the service is available
    when: typing.Optional[str]


@dataclasses.dataclass
class ClusterUiMeta:
    #: The name of the cluster type
    name: str
    #: A human-readable label for the cluster type
    label: str
    #: A description of the cluster type
    description: typing.Optional[str]
    #: The URL or data URI of the logo for the cluster type
    logo: typing.Optional[str]
    #: Indicates whether the cluster requires a user SSH key
    requiresSshKey: typing.Optional[bool]
    #: The parameters for the cluster type
    parameters: typing.Sequence[ClusterParameter]
    #: The services for the cluster type
    services: typing.Sequence[ClusterServiceSpec]
    #: Template for the usage of the clusters deployed using this type
    #: Can use Jinja2 syntax and should produce valid Markdown
    #: Receives the cluster parameters, as defined in `parameters`, as template args
    usageTemplate: typing.Optional[str]


class ClusterTypeStatus(schema.BaseModel):
    phase: ClusterTypePhase = pydantic.Field(ClusterTypePhase.PENDING)
    uiMeta: typing.Optional[ClusterUiMeta]


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


def get_fake():
    return ClusterType(**get_fake_dict())


def get_fake_dict():
    return dict(
        apiVersion="fake",
        kind="ClusterType",
        metadata=dict(name="test1"),
        spec=dict(
            uiMetaUrl="https://url1",
            gitUrl="https://github.com/test.git",
            gitVersion="12345ab",
            playbook="sample.yaml",
            extraVars=dict(
                cluster_image="testimage1",
            ),
        ),
    )
