import datetime

import yaml

from azimuth_caas_operator.models import registry


async def update_cluster(client, name, namespace, phase):
    cluster_resource = await client.api(registry.API_VERSION).resource("cluster")
    await cluster_resource.patch(
        name,
        dict(status=dict(phase=phase)),
        namespace=namespace,
    )


async def create_scheduled_delete_job(client, name, namespace):
    now = datetime.datetime.now(datetime.timezone.utc)
    delete_time = now - datetime.timedelta(minutes=2)
    cron_schedule = (
        f"{delete_time.minute} {delete_time.hour} "
        f"{delete_time.day} {delete_time.month} *"
    )
    configmap_yaml = f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: delete-pod-{name}
data:
  delete.py: |
    import easykube
    config = easykube.Configuration.from_environment()
    client = config.sync_client(default_namespace="{namespace}")
    cluster_resource = client.api("{registry.API_VERSION}").resource("cluster")
    cluster.delete("{name}")
"""
    print(configmap_yaml)
    job_yaml = f"""apiVersion: batch/v1
kind: CronJob
metadata:
  name: delete-pod-{name}
spec:
  schedule: "{cron_schedule}"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: delete
            image: ghcr.io/stackhpc/azimuth-caas-operator-ar:69b9bdc
            command: ["/bin/sh"]
            args:
            - "-c"
            - "python3 delete.py"
            volumeMounts:
            - name: python-delete
              mountPath: /delete.py
              subPath: delete.py
          restartPolicy: Never
          volumes:
            - name: delete-pod-{name}
              configMap:
                name: python-delete"""
    print(job_yaml)

    configmap_data = yaml.safe_load(configmap_yaml)
    configmap_resource = await client.api("v1").resource("ConfigMap")
    await configmap_resource.create(configmap_data, namespace=namespace)

    job_data = yaml.safe_load(job_yaml)
    job_resource = await client.api("batch/v1").resource("CronJob")
    await job_resource.create(job_data, namespace=namespace)
