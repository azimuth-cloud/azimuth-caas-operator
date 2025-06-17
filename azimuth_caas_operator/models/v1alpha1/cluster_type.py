import datetime

import kube_custom_resource as crd
import pydantic
from kube_custom_resource import schema


class ClusterTypePhase(str, schema.Enum):
    PENDING = "Pending"
    AVAILABLE = "Available"
    FAILED = "Failed"


class ClusterTypeStatus(schema.BaseModel):
    phase: ClusterTypePhase = pydantic.Field(ClusterTypePhase.PENDING)
    uiMeta: schema.Dict[str, schema.Any] = pydantic.Field(default_factory=dict)
    uiMetaUrl: schema.Optional[schema.AnyHttpUrl] = None
    updatedTimestamp: schema.Optional[datetime.datetime] = pydantic.Field(
        None, description="The timestamp at which the resource was updated."
    )


class ClusterTypeSpec(schema.BaseModel):
    uiMetaUrl: schema.AnyHttpUrl
    gitUrl: schema.AnyUrl
    gitVersion: str
    # Playbook is contained in the above git repo
    playbook: str
    # The timeout (in seconds) to apply to the kubernetes job resource
    # which creates, updates and deletes the cluster instances
    jobTimeout: int = pydantic.Field(default=1200)
    # Option to add cloud specific details, like the image
    extraVars: schema.Dict[str, schema.Any] = pydantic.Field(default_factory=dict)
    # Option to define cluster-type specific details, like inventory
    envVars: schema.Dict[str, schema.Any] = pydantic.Field(default_factory=dict)
    # optionally copy in a secret to mount as ~/.ssh
    sshSharedSecretName: schema.Optional[str] = None
    sshSharedSecretNamespace: schema.Optional[str] = None


class ClusterType(
    crd.CustomResource,
    scope=crd.Scope.CLUSTER,
    subresources={"status": {}},
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
    ],
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
