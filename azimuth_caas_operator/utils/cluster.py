import datetime

import yaml

from azimuth_caas_operator.models import registry

# TODO(johngarbutt) move to config!
POD_IMAGE = "ghcr.io/stackhpc/azimuth-caas-operator-ar:f12550b"


async def update_cluster(client, name, namespace, phase, extra_vars=None):
    now = datetime.datetime.utcnow()
    now_string = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    status_updates = dict(phase=phase, updatedTimestamp=now_string)
    if extra_vars:
        status_updates["appliedExtraVars"] = extra_vars

    cluster_resource = await client.api(registry.API_VERSION).resource("cluster")
    await cluster_resource.patch(
        name,
        dict(status=status_updates),
        namespace=namespace,
    )


async def create_scheduled_delete_job(client, name, namespace, uid):
    now = datetime.datetime.now(datetime.timezone.utc)
    delete_time = now + datetime.timedelta(minutes=1)
    cron_schedule = (
        f"{delete_time.minute} {delete_time.hour} "
        f"{delete_time.day} {delete_time.month} *"
    )
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
            image: "{POD_IMAGE}"
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
