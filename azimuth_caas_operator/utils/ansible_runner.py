import logging
import yaml

from azimuth_caas_operator.models import registry
from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd
from azimuth_caas_operator.utils import cluster_type as cluster_type_utils

LOG = logging.getLogger(__name__)

# TODO(johngarbutt) move to config!
POD_TAG = "227c806"
POD_IMAGE = f"ghcr.io/stackhpc/azimuth-caas-operator-ar:{POD_TAG}"


def get_env_configmap(
    cluster: cluster_crd.Cluster,
    cluster_type: cluster_type_crd.ClusterType,
    remove=False,
):
    extraVars = dict(cluster_type.spec.extraVars, **cluster.spec.extraVars)
    extraVars["cluster_name"] = cluster.metadata.name
    extraVars["cluster_id"] = cluster.metadata.uid
    extraVars["cluster_type"] = cluster_type.metadata.name
    # TODO(johngarbutt) need to lookup deployment ssh public key!
    extraVars[
        "cluster_deploy_ssh_public_key"
    ] = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQDE8MwOaScxQTIYpXXHawwhiZ4+9HbsUT354BTh+eaNE4cw7xmqMfUsz3yxJ1IIgmNKwHHdKz/kLjqWeynio6gxMHWEG05pGRyTpziGI/jBFSpRwfEQ5ISavrzJacMuDy3qtgsdaUXQ6Bj9HZvNzdOD/YcnrN+RhqgJ/oMP0lwC/XzF+YZWnkjmFZ7IaOTVlQW3pnTZNi8D7Sr7Acxwejw7NSHh7gKWhcs4bSMZocyIUYVyhXykZhKHrfGNN0dzbrACyFQY3W27QbhYMGFM4+rUyTe1h9DG9LzgNSyqAe6zpibUlZQZVxLxOJJNCKFHX8zXXuiNC6+KLEHjJCj5zvW8XCFlLbUy7mh/FEX2X5U5Ghw4irbX5XKUg6tgJN4cKnYhqN62jsK7YaxQ2OAcyfpBlEu/zq/7+t6AJiY93DEr7H7Og8mjsXNrchNMwrV+BLbuymcwtpDolZfdLGonj6bjSYUoJLKKsFfF2sAhc64qKDjVbbpvb52Ble1YNHcOPZ8="  # noqa
    extraVars["cluster_ssh_private_key_file"] = "/home/runner/.ssh/id_rsa"

    if remove:
        extraVars["cluster_state"] = "absent"
    extraVars = "---\n" + yaml.dump(extraVars)

    # TODO(johngarbutt): consul address must come from config!
    envvars = dict(
        CONSUL_HTTP_ADDR="zenith-consul-server.zenith:8500",
        OS_CLOUD="openstack",
        OS_CLIENT_CONFIG_FILE="/openstack/clouds.yaml",
        # TODO(johngarbutt) make this optional via config?
        ANSIBLE_CALLBACK_PLUGINS=(
            "/home/runner/.local/lib/python3.10/site-packages/ara/plugins/callback"
        ),
        ARA_API_CLIENT="http",
        ARA_API_SERVER="http://azimuth-ara.azimuth-caas-operator:8000",
    )
    envvars = "---\n" + yaml.dump(envvars)

    action = "remove" if remove else "create"
    template = f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: {cluster.metadata.name}-{action}
  ownerReferences:
    - apiVersion: "{registry.API_VERSION}"
      kind: Cluster
      name: "{cluster.metadata.name}"
      uid: "{cluster.metadata.uid}"
data:
  envvars: ""
  extravars: ""
"""
    config_map = yaml.safe_load(template)
    config_map["data"]["extravars"] = extraVars
    config_map["data"]["envvars"] = envvars
    return config_map


def get_job(
    cluster: cluster_crd.Cluster,
    cluster_type: cluster_type_crd.ClusterType,
    remove=False,
):
    cluster_uid = cluster.metadata.uid
    name = cluster.metadata.name
    action = "remove" if remove else "create"
    # TODO(johngarbutt): need get secret keyname from somewhere
    job_yaml = f"""apiVersion: batch/v1
kind: Job
metadata:
  generateName: "{name}-{action}-"
  labels:
      azimuth-caas-cluster: "{name}"
      azimuth-caas-action: "{action}"
  ownerReferences:
    - apiVersion: "{registry.API_VERSION}"
      kind: Cluster
      name: "{name}"
      uid: "{cluster_uid}"
spec:
  template:
    spec:
      securityContext:
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
      restartPolicy: Never
      initContainers:
      - image: "{POD_IMAGE}"
        name: inventory
        workingDir: /inventory
        command:
        - /bin/bash
        - -c
        - "echo '[openstack]' >/runner/inventory/hosts; echo 'localhost ansible_connection=local ansible_python_interpreter=/usr/bin/python3' >>/runner/inventory/hosts"
        volumeMounts:
        - name: inventory
          mountPath: /runner/inventory
      - image: "{POD_IMAGE}"
        name: clone
        workingDir: /runner
        command:
        - /bin/bash
        - -c
        - "chmod 755 /runner/project; git clone {cluster_type.spec.gitUrl} /runner/project; git config --global --add safe.directory /runner/project; cd /runner/project; git checkout {cluster_type.spec.gitVersion}; ls -al"
        volumeMounts:
        - name: playbooks
          mountPath: /runner/project
      containers:
      - name: run
        image: "{POD_IMAGE}"
        command:
        - /bin/bash
        - -c
        - "chmod 755 /runner/project; ansible-galaxy install -r /runner/project/roles/requirements.yml; ansible-runner run /runner -vvv"
        env:
        - name: RUNNER_PLAYBOOK
          value: "{cluster_type.spec.playbook}"
        volumeMounts:
        - name: playbooks
          mountPath: /runner/project
        - name: inventory
          mountPath: /runner/inventory
        - name: env
          mountPath: /runner/env
        - name: cloudcreds
          mountPath: /openstack
        - name: ssh
          mountPath: /home/runner/.ssh
      volumes:
      - name: playbooks
        emptyDir: {{}}
      - name: inventory
        emptyDir: {{}}
      - name: env
        configMap:
          name: {name}-{action}
      - name: cloudcreds
        secret:
          secretName: "{cluster.spec.cloudCredentialsSecretName}"
      - name: ssh
        secret:
          secretName: "azimuth-sshkey"
          defaultMode: 256
  backoffLimit: 0
  # timeout after 20 mins
  activeDeadlineSeconds: 1200"""  # noqa
    return yaml.safe_load(job_yaml)


async def get_job_resource(client):
    # TODO(johngarbutt): how to test this?
    return await client.api("batch/v1").resource("jobs")


async def get_jobs_for_cluster(client, cluster_name, namespace, remove=False):
    job_resource = await get_job_resource(client)
    action = "remove" if remove else "create"
    return [
        job
        async for job in job_resource.list(
            labels={
                "azimuth-caas-cluster": cluster_name,
                "azimuth-caas-action": action,
            },
            namespace=namespace,
        )
    ]


def get_job_completed_state(job):
    if not job:
        return

    active = job.status.get("active", 0) == 1
    success = job.status.get("succeeded", 0) == 1
    failed = job.status.get("failed", 0) == 1

    if success:
        return True
    if failed:
        return False
    if active:
        return None
    if not active:
        LOG.debug(f"job has not started yet {job.metadata.name}")
    else:
        LOG.warning(f"job in a strange state {job.metadata.name}")


def is_any_successful_jobs(job_list):
    for job in job_list:
        state = get_job_completed_state(job)
        if state:
            return True
    return False


def are_all_jobs_in_error_state(job_list):
    if not job_list:
        return False
    for job in job_list:
        state = get_job_completed_state(job)
        if state is not False:
            return False
    return True


async def ensure_create_jobs_finished(client, cluster_name, namespace):
    create_jobs = await get_jobs_for_cluster(client, cluster_name, namespace)
    if not create_jobs:
        LOG.error(f"can't find any create jobs for {cluster_name} in {namespace}")
        raise RuntimeError("waiting for create job to start")
    for job in create_jobs:
        if get_job_completed_state(job) is None:
            raise RuntimeError(f"waiting for create job to finish {job.metadata.name}")


async def get_delete_jobs_status(client, cluster_name, namespace):
    """List of jobs and thier states.

    Status returned for all created jobs.
    None means the job has not completed.
    True means the job was a success.
    False means the job hit an error."""
    # TODO(johngarbutt): add current task if running
    delete_jobs = await get_jobs_for_cluster(
        client, cluster_name, namespace, remove=True
    )
    return [get_job_completed_state(job) for job in delete_jobs]


async def start_job(client, cluster, namespace, remove=False):
    cluster_type = await cluster_type_utils.get_cluster_type_info(client, cluster)

    # generate config
    configmap_data = get_env_configmap(
        cluster,
        cluster_type,
        remove=remove,
    )
    configmap_resource = await client.api("v1").resource("ConfigMap")
    await configmap_resource.create_or_patch(
        configmap_data["metadata"]["name"], configmap_data, namespace=namespace
    )

    # ensure deploy secret, copy across for now
    # TODO(johngarbutt): generate?
    sshkey_secret_name = "azimuth-sshkey"
    copy_from_namespace = "azimuth-caas-operator"
    secrets_resource = await client.api("v1").resource("secrets")
    ssh_secret = await secrets_resource.fetch(
        sshkey_secret_name, namespace=copy_from_namespace
    )
    await secrets_resource.create_or_patch(
        sshkey_secret_name,
        {"metadata": {"name": sshkey_secret_name}, "data": ssh_secret.data},
        namespace=namespace,
    )

    # create the job
    job_data = get_job(cluster, cluster_type, remove=remove)
    job_resource = await client.api("batch/v1").resource("jobs")
    await job_resource.create(job_data, namespace=namespace)


async def delete_secret(client, secret_name, namespace):
    secrets_resource = await client.api("v1").resource("secrets")
    await secrets_resource.delete(secret_name, namespace=namespace)
