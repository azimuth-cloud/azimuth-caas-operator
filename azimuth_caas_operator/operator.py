import json
import logging

import easykube
import kopf
from pydantic.json import pydantic_encoder
import yaml

from azimuth_caas_operator.models import registry

LOG = logging.getLogger(__name__)

easykube_field_manager = "azimuth-caas-operator"
CLUSTER_LABEL = "azimuth-caas-cluster"


async def register_crds(client):
    for resource in registry.get_crd_resources():
        await client.apply_object(resource, force=True)
    LOG.info("CRDs imported")


def get_k8s_client():
    return easykube.Configuration.from_environment(
        json_encoder=pydantic_encoder
    ).async_client(default_field_manager=easykube_field_manager)


async def get_job_log(client, job_name, namespace):
    # find the pod fomr the job label
    pod_resource = await client.api("v1").resource("pods")
    pods = [
        pod
        async for pod in pod_resource.list(
            labels={"job-name": job_name}, namespace=namespace
        )
    ]
    if len(pods) == 0 or len(pods) > 1:
        LOG.warning(f"Can't find pod for job {job_name} in {namespace}")
        return
    pod_name = pods[0]["metadata"]["name"]
    log_resource = await client.api("v1").resource("pods/log")
    # TODO(johngarbutt): we should pass tail here
    logs = await log_resource.fetch(pod_name, namespace=namespace)
    # TODO(johngarbutt): easykube.kubernetes.client.errors.ApiError:
    # container "run" in pod "test2rfc6z-5zw84" is waiting to start:
    # PodInitializing

    # split into lines
    logs = logs.strip()
    logs = logs.split("\n")

    # check we can parse everything
    for log in logs:
        last_log_event = json.loads(log)
        task = last_log_event["event_data"].get("task")
        LOG.debug(f"task: {task}")
        failures = last_log_event["event_data"].get("failures", 0)
        LOG.debug(f"failures: {failures}")

    return last_log_event["event_data"]


@kopf.on.startup()
async def startup(**kwargs):
    LOG.info("Starting")
    client = get_k8s_client()
    await register_crds(client)


@kopf.on.cleanup()
def cleanup(**kwargs):
    LOG.info("cleaned up!")


@kopf.on.create(registry.API_GROUP, "clustertypes")
async def cluster_type_event(body, name, namespace, labels, **kwargs):
    if type == "DELETED":
        LOG.info(f"cluster_type {name} in {namespace} is deleted")
        return

    LOG.debug(f"cluster_type event for {name} in {namespace}")
    cluster_type = registry.parse_model(body)
    LOG.info(f"seen cluster_type event {cluster_type.spec.gitUrl}")
    # TODO(johngarbutt): fetch ui meta from git repo and update crd


@kopf.on.create(registry.API_GROUP, "cluster")
async def cluster_event(body, name, namespace, labels, **kwargs):
    LOG.info(f"cluster event for {name} in {namespace}")
    cluster = registry.parse_model(body)
    cluster_type_name = cluster.spec.clusterTypeName
    LOG.info(f"seen cluster of type {cluster_type_name} with status {cluster.status}")

    # Fetch the cluster type, if available, get the git ref
    client = get_k8s_client()
    cluster_type = await client.api(registry.API_VERSION).resource("clustertype")
    # TODO(johngarbutt) how to catch not found errors?
    cluster_type_raw = await cluster_type.fetch(cluster_type_name)
    LOG.info(f"Git URL: {cluster_type_raw.spec.gitUrl}")

    # job_resource =
    job_resource = await client.api("batch/v1").resource("jobs")
    # TOOD(johngarbutt): template out and include ownership, etc.
    cluster_uid = body["metadata"]["uid"]
    job_yaml = f"""apiVersion: batch/v1
kind: Job
metadata:
  generateName: "{name}"
  labels:
      azimuth-caas-cluster: "{name}"
  ownerReferences:
    - apiVersion: "{registry.API_VERSION}"
      kind: Cluster
      name: "{name}"
      uid: "{cluster_uid}"
spec:
  template:
    spec:
      restartPolicy: Never
      initContainers:
      - image: alpine/git
        name: clone
        command:
        - git
        - clone
        - "{cluster_type_raw.spec.gitUrl}"
        - /repo
        volumeMounts:
        - name: playbooks
          mountPath: /repo
      - image: alpine/git
        name: checkout
        workingDir: /repo
        command:
        - git
        - checkout
        - "{cluster_type_raw.spec.gitVersion}"
        volumeMounts:
        - name: playbooks
          mountPath: /repo
        env:
        - name: PWD
          value: /repo
      - image: alpine/git
        name: permissions
        workingDir: /repo
        command:
        - /bin/ash
        - -c
        - "chmod 755 /repo/"
        volumeMounts:
        - name: playbooks
          mountPath: /repo
        env:
        - name: PWD
          value: /repo
      - image: alpine/git
        name: inventory
        workingDir: /inventory
        command:
        - /bin/ash
        - -c
        - "echo '[openstack]' >/inventory/hosts; echo 'localhost ansible_connection=local ansible_python_interpreter=/usr/bin/python3' >>/inventory/hosts"
        volumeMounts:
        - name: inventory
          mountPath: /inventory
        env:
        - name: PWD
          value: /repo
      containers:
      - name: run
        image: ghcr.io/stackhpc/caas-ee:5289aa7
        command:
        - /bin/bash
        - -c
        - "ansible-galaxy install -r /runner/project/roles/requirements.yml; ansible-runner run /runner -j"
        env:
        - name: RUNNER_PLAYBOOK
          value: "sample-appliance.yml"
        volumeMounts:
        - name: playbooks
          mountPath: /runner/project
        - name: inventory
          mountPath: /runner/inventory
      volumes:
      - name: playbooks
        emptyDir: {{}}
      - name: inventory
        emptyDir: {{}}
  backoffLimit: 0"""  # noqa
    job_data = yaml.safe_load(job_yaml)
    job = await job_resource.create(job_data)
    LOG.info(f"{job}")


@kopf.on.event("job", labels={"azimuth-caas-cluster": kopf.PRESENT})
async def job_event(type, body, name, namespace, labels, **kwargs):
    cluster_name = labels.get("azimuth-caas-cluster")
    if type == "DELETED":
        LOG.info(f"job deleted cluster {cluster_name} in {namespace}")
        return

    LOG.debug(f"seen job update for cluster {cluster_name} in {namespace}")

    job_status = body.get("status", {})
    ready = job_status.get("ready", 0) == 1
    success = job_status.get("succeeded", 0) == 1
    failed = job_status.get("failed", 0) == 1
    active = job_status.get("active", 0) == 1

    completion_time = job_status.get("completionTime")
    LOG.debug(
        f"job {cluster_name} status - ready:{ready} "
        f"success:{success} completed at:{completion_time}"
    )

    if not success and not failed and not active:
        LOG.error("what happened here?")
        LOG.info(f"{body}")
        return

    if active and not ready:
        LOG.info(f"job is running, pod not ready.")
        # skip checking logs until pod init container finished
        return

    if active:
        LOG.info(f"job is running, pod ready:{ready}")
    if failed:
        LOG.error("job failed!!")
    if success:
        LOG.info(f"job completed on {completion_time}")

    # TODO(johngarbutt) update the CRD with logs
    client = get_k8s_client()
    job_log = await get_job_log(client, name, namespace)
    LOG.info(f"{job_log}")

    if success:
        job_resource = await client.api("batch/v1").resource("jobs")
        # TODO(johngarbutt): send propagationPolicy="Background" like kubectl
        await job_resource.delete(name, namespace=namespace)
        LOG.info(f"deleted job {name} in {namespace}")

        # delete pods so they are not orphaned
        pod_resource = await client.api("v1").resource("pods")
        pods = [
            pod
            async for pod in pod_resource.list(
                labels={"job-name": name}, namespace=namespace
            )
        ]
        for pod in pods:
            await pod_resource.delete(pod["metadata"]["name"], namespace=namespace)
