import datetime
import logging

import yaml

from azimuth_caas_operator.models import registry
from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.utils import image as image_utils


LOG = logging.getLogger(__name__)


async def ensure_cluster_id(client, cluster: cluster_crd.Cluster):
    """
    Ensures that the given cluster has it's ID set.
    """
    if cluster.status.clusterID:
        return
    # Only update the status of the cluster object we were given if the
    # patch is successful
    name = cluster.metadata.name
    namespace = cluster.metadata.namespace
    cluster_resource = await client.api(registry.API_VERSION).resource(
        "clusters/status"
    )
    await cluster_resource.patch(
        name,
        {"status": {"clusterID": cluster.metadata.uid}},
        namespace=namespace,
    )
    cluster.status.clusterID = cluster.metadata.uid
    LOG.debug(f"set clusterID for {name} in {namespace}")


async def update_cluster_flavors(client, cluster: cluster_crd.Cluster, flavors: dict):
    """
    Update the cluster with the flavors that were reserved.
    """
    flavor_overrides = {}
    for key, value in cluster.spec.extraVars.items():
        if value in flavors.keys():
            flavor_overrides[key] = flavors[value]
    name = cluster.metadata.name
    namespace = cluster.metadata.namespace
    cluster_resource = await client.api(registry.API_VERSION).resource("clusters")
    await cluster_resource.patch(
        name,
        {"spec": {"extraVarOverrides": flavor_overrides}},
        namespace=namespace,
    )
    LOG.debug(f"set flavors for {name} in {namespace}")


async def update_cluster(
    client, name, namespace, phase, extra_vars=None, outputs=None, error=None
):
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    now_string = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    status_updates = dict(phase=phase, updatedTimestamp=now_string)
    if extra_vars:
        status_updates["appliedExtraVars"] = extra_vars
    if outputs:
        # empty dict is a valid possible output we should record
        status_updates["outputs"] = outputs

    if error is not None:
        status_updates["error"] = error
    else:
        status_updates["error"] = None

    cluster_resource = await client.api(registry.API_VERSION).resource(
        "clusters/status"
    )
    LOG.debug(f"patching {name} in {namespace} with: {status_updates}")
    await cluster_resource.patch(
        name,
        dict(status=status_updates),
        namespace=namespace,
    )


async def create_scheduled_delete_job(client, name, namespace, uid, lifetime_hours):
    if "ever" in str(lifetime_hours).lower():
        # skip for never or forever
        LOG.info("Skipping scheduled delete.")
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    hours_int = 0
    try:
        hours_int = int(lifetime_hours)
    except ValueError:
        LOG.error(f"Invalid lifetime_hours requested: {lifetime_hours}")

    if hours_int <= 0 or hours_int > 24 * 30:
        hours_int = 24 * 30
        LOG.error(f"Invalid lifetime_hours of {hours_int} moved to 30 days.")

    delete_time = now + datetime.timedelta(hours=hours_int)
    cron_schedule = (
        f"{delete_time.minute} {delete_time.hour} "
        f"{delete_time.day} {delete_time.month} *"
    )
    image = image_utils.get_ansible_runner_image()
    configmap_yaml = f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: autodelete-{name}
  ownerReferences:
  - apiVersion: {registry.API_VERSION}
    kind: Cluster
    name: "{name}"
    uid: "{uid}"
data:
  delete.py: |
    import easykube
    config = easykube.Configuration.from_environment()
    client = config.sync_client(
        default_field_manager="autodelete", default_namespace="{namespace}")
    cluster_resource = client.api("{registry.API_VERSION}").resource("cluster")
    cluster_resource.delete("{name}")
"""
    job_yaml = f"""apiVersion: batch/v1
kind: CronJob
metadata:
  name: autodelete-{name}
  ownerReferences:
  - apiVersion: {registry.API_VERSION}
    kind: Cluster
    name: "{name}"
    uid: "{uid}"
spec:
  schedule: "{cron_schedule}"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: delete
            image: "{image}"
            command: ["/bin/sh"]
            args:
            - "-c"
            - "python3 /delete.py"
            volumeMounts:
            - name: python-delete
              mountPath: /delete.py
              subPath: delete.py
          restartPolicy: Never
          volumes:
            - name: python-delete
              configMap:
                name: autodelete-{name}
"""

    configmap_data = yaml.safe_load(configmap_yaml)
    configmap_resource = await client.api("v1").resource("ConfigMap")
    await configmap_resource.create(configmap_data, namespace=namespace)

    job_data = yaml.safe_load(job_yaml)
    job_resource = await client.api("batch/v1").resource("CronJob")
    await job_resource.create(job_data, namespace=namespace)

    # ensure above cron job can delete the cluster
    role_binding_yaml = f"""apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: azimuth-caas-operator-edit-{namespace}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: azimuth-caas-operator:edit
subjects:
- kind: ServiceAccount
  name: default
  namespace: {namespace}
"""
    role_binding_data = yaml.safe_load(role_binding_yaml)
    role_binding_resource = await client.api("rbac.authorization.k8s.io/v1").resource(
        "ClusterRoleBinding"
    )
    # TODO(johngarbutt): really just need to ensure its present
    await role_binding_resource.create_or_patch(
        f"azimuth-caas-operator-edit-{namespace}",
        role_binding_data,
        namespace=namespace,
    )
    LOG.info(f"Scheduled cluster auto delete for cluster: {name} in: {namespace}")
