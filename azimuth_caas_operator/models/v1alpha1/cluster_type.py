import datetime
import typing

import kube_custom_resource as crd
from kube_custom_resource import schema
import pydantic


class ClusterTypePhase(str, schema.Enum):
    PENDING = "Pending"
    AVAILABLE = "Available"
    FAILED = "Failed"


class ClusterParameter(schema.BaseModel):
    #: The name of the parameter
    name: str
    #: A human-readable label for the parameter
    label: str
    #: A description of the parameter
    description: typing.Optional[str]
    #: The kind of the parameter
    kind: str
    #: A dictionary of kind-specific options for the parameter
    options: schema.Dict[str, schema.Any] = pydantic.Field(default_factory=dict)
    #: Indicates if the option is immutable, i.e. cannot be updated
    immutable: typing.Optional[bool]
    #: Indicates if the parameter is required
    required: typing.Optional[bool]
    #: A default value for the parameter
    default: typing.Optional[
        schema.Any
    ]  # TODO(johngarbutt): k8s said no if this was any before?!


class ClusterServiceSpec(schema.BaseModel):
    #: The name of the service
    name: str
    #: A human-readable label for the service
    label: str
    #: The URL of an icon for the service
    iconUrl: typing.Optional[str]
    #: An expression indicating when the service is available
    when: typing.Optional[str]


class ClusterUiMeta(schema.BaseModel):
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
    parameters: typing.Optional[typing.Sequence[ClusterParameter]]
    #: The services for the cluster type
    services: typing.Optional[typing.Sequence[ClusterServiceSpec]]
    #: Template for the usage of the clusters deployed using this type
    #: Can use Jinja2 syntax and should produce valid Markdown
    #: Receives the cluster parameters, as defined in `parameters`, as template args
    usageTemplate: typing.Optional[str]


class ClusterTypeStatus(schema.BaseModel):
    phase: ClusterTypePhase = pydantic.Field(ClusterTypePhase.PENDING)
    uiMeta: typing.Optional[ClusterUiMeta]
    uiMetaUrl: typing.Optional[pydantic.AnyHttpUrl]
    updatedTimestamp: typing.Optional[datetime.datetime] = pydantic.Field(
        None, description="The timestamp at which the resource was updated."
    )


class ClusterTypeSpec(schema.BaseModel):
    uiMetaUrl: pydantic.AnyHttpUrl
    gitUrl: pydantic.AnyUrl
    gitVersion: str
    # Playbook is contained in the above git repo
    playbook: str
    # Option to add cloud specific details, like the image
    extraVars: schema.Dict[str, schema.Any] = pydantic.Field(default_factory=dict)
    # optionally copy in a secret to mount as ~/.ssh
    sshSharedSecretName: typing.Optional[str]
    sshSharedSecretNamespace: typing.Optional[str]


class ClusterType(
    crd.CustomResource,
    scope=crd.Scope.CLUSTER,
    printer_columns=[
        {
            "name": "Git URL",
            "type": "string",
            "jsonPath": ".spec.gitUrl",
        },
        {
            "name": "Git Version",
            "type": "string",
            "jsonPath": ".spec.gitVersion",
        },
        {
            "name": "Playbook",
            "type": "string",
            "jsonPath": ".spec.playbook",
        },
        {
            "name": "Phase",
            "type": "string",
            "jsonPath": ".status.phase",
        },
    ]
):
    spec: ClusterTypeSpec
    status: ClusterTypeStatus = pydantic.Field(default_factory=ClusterTypeStatus)


def get_fake():
    return ClusterType(**get_fake_dict())


def get_fake_dict():
    return dict(
        apiVersion="fake",
        kind="ClusterType",
        metadata=dict(name="type1"),
        spec=dict(
            uiMetaUrl="https://url1",
            gitUrl="https://github.com/test.git",
            gitVersion="12345ab",
            playbook="sample.yaml",
            extraVars=dict(
                cluster_image="testimage1",
                random_bool=True,
                random_int=8,
                random_dict=dict(random_str="foo"),
            ),
        ),
    )
