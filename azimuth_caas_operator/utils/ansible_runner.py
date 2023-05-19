import base64
import json
import logging
import os
import yaml

from azimuth_caas_operator.models import registry
from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd
from azimuth_caas_operator.utils import cluster_type as cluster_type_utils
from azimuth_caas_operator.utils import image as image_utils
from azimuth_caas_operator.utils import k8s

LOG = logging.getLogger(__name__)


def get_env_configmap(
    cluster: cluster_crd.Cluster,
    cluster_type_spec: cluster_type_crd.ClusterTypeSpec,
    cluster_deploy_ssh_public_key: str,
    remove=False,
    update=False,
):
    extraVars = dict(cluster_type_spec.extraVars, **cluster.spec.extraVars)
    extraVars["cluster_name"] = cluster.metadata.name
    extraVars["cluster_id"] = cluster.metadata.uid
    extraVars["cluster_type"] = cluster.spec.clusterTypeName
    extraVars["cluster_deploy_ssh_public_key"] = cluster_deploy_ssh_public_key
    extraVars["cluster_ssh_private_key_file"] = "/home/runner/.ssh/id_rsa"

    if remove:
        extraVars["cluster_state"] = "absent"
    extraVars = "---\n" + yaml.dump(extraVars)

    # TODO(johngarbutt): probably should use more standard config
    envvars = dict(
        # Consul is used to store terraform state
        CONSUL_HTTP_ADDR=os.environ.get(
            "CONSUL_HTTP_ADDR", "zenith-consul-server.zenith:8500"
        ),
        # Configure ARA to help debug ansible executions
        ANSIBLE_CALLBACK_PLUGINS=(
            "/home/runner/.local/lib/python3.10/site-packages/ara/plugins/callback"
        ),
        ARA_API_CLIENT="http",
        ARA_API_SERVER=os.environ.get(
            "ARA_API_SERVER", "http://azimuth-ara.azimuth-caas-operator:8000"
        ),
        # This tells tools to use the app cred k8s secret we mount
        OS_CLOUD="openstack",
        OS_CLIENT_CONFIG_FILE="/openstack/clouds.yaml",
    )
    envvars = "---\n" + yaml.dump(envvars)

    # TODO(johngarbutt) this logic is scattered in a few places!
    action = "create"
    if remove:
        action = "remove"
    elif update:
        action = "update"

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
    cluster_type_spec: cluster_type_crd.ClusterTypeSpec,
    remove=False,
    update=False,
):
    cluster_uid = cluster.metadata.uid
    name = cluster.metadata.name

    action = "create"
    if remove:
        action = "remove"
    elif update:
        action = "update"

    image = image_utils.get_ansible_runner_image()

    ansible_runner_command = (
        "chmod 755 /runner/project; "
        "ansible-galaxy install -r /runner/project/roles/requirements.yml; "
        "ansible-runner run /runner -j"
    )
    if remove:
        # on success, delete the app cred
        ansible_runner_command += (
            "; rc=$?; if [ $rc == 0 ]; then openstack"
            # TODO(johngarbutt): very tight coupling with code in azimuth here :(
            f" application credential delete azimuth-caas-{name}; fi; exit $rc"
        )

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
      - image: "{image}"
        name: inventory
        workingDir: /inventory
        command:
        - /bin/bash
        - -c
        - "echo '[openstack]' >/runner/inventory/hosts; echo 'localhost ansible_connection=local ansible_python_interpreter=/usr/bin/python3' >>/runner/inventory/hosts"
        volumeMounts:
        - name: inventory
          mountPath: /runner/inventory
      - image: "{image}"
        name: clone
        workingDir: /runner
        command:
        - /bin/bash
        - -c
        - "chmod 755 /runner/project; git clone {cluster_type_spec.gitUrl} /runner/project; git config --global --add safe.directory /runner/project; cd /runner/project; git checkout {cluster_type_spec.gitVersion}; ls -al"
        volumeMounts:
        - name: playbooks
          mountPath: /runner/project
      containers:
      - name: run
        image: "{image}"
        command:
        - /bin/bash
        - -c
        - "{ansible_runner_command}"
        env:
        - name: RUNNER_PLAYBOOK
          value: "{cluster_type_spec.playbook}"
        - name: OS_CLOUD
          value: "openstack"
        - name: OS_CLIENT_CONFIG_FILE
          value: "/openstack/clouds.yaml"
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
          secretName: "ssh-{cluster.spec.clusterTypeName}"
          defaultMode: 256
          optional: true
  backoffLimit: 0
  # timeout after 20 mins
  activeDeadlineSeconds: 1200"""  # noqa
    return yaml.safe_load(job_yaml)


async def get_job_resource(client):
    # TODO(johngarbutt): how to test this?
    return await client.api("batch/v1").resource("jobs")


async def is_create_job_finished(client, cluster_name, namespace):
    is_create_job_success = None
    create_job = await get_create_job_for_cluster(client, cluster_name, namespace)
    if create_job:
        is_create_job_success = get_job_completed_state(create_job)
    return is_create_job_success is not None


async def get_create_job_for_cluster(client, cluster_name, namespace):
    return await get_job_for_cluster(client, cluster_name, namespace, remove=False)


async def get_update_job_for_cluster(client, cluster_name, namespace):
    return await get_job_for_cluster(client, cluster_name, namespace, update=True)


async def get_delete_job_for_cluster(client, cluster_name, namespace):
    return await get_job_for_cluster(client, cluster_name, namespace, remove=True)


async def get_job_for_cluster(
    client, cluster_name, namespace, remove=False, update=False
):
    job_resource = await get_job_resource(client)
    action = "create"
    if remove:
        action = "remove"
    elif update:
        action = "update"
    jobs = [
        job
        async for job in job_resource.list(
            labels={
                "azimuth-caas-cluster": cluster_name,
                "azimuth-caas-action": action,
            },
            namespace=namespace,
        )
    ]
    if len(jobs) == 1:
        return jobs[0]
    if len(jobs) > 1:
        raise Exception("too many jobs found!")


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


async def get_outputs_from_create_job(client, name, namespace):
    create_jobs = await get_jobs_for_cluster(client, name, namespace)
    completed_job = None
    for job in create_jobs:
        state = get_job_completed_state(job)
        if state:
            completed_job = job
            # TODO(johngarbutt): check for two jobs?
            break
    if completed_job:
        return await _get_job_outputs(client, completed_job)


async def _get_job_outputs(client, job):
    # first get the tail of the logs
    events = await _get_ansible_runner_events(
        client, job.metadata.name, job.metadata.namespace
    )
    events.reverse()
    debug_result = None
    for event_details in events:
        # look for the last debug action
        # that has an outputs key in its result object
        if event_details["event"] == "runner_on_ok":
            event_data = event_details["event_data"]
            task_action = event_data["task_action"]
            if task_action == "debug":
                debug_result = event_data.get("res", {})
                return debug_result.get("outputs", {})


async def _get_pod_names_for_job(client, job_name, namespace):
    pod_resource = await k8s.get_pod_resource(client)
    return [
        pod["metadata"]["name"]
        async for pod in pod_resource.list(
            labels={"job-name": job_name}, namespace=namespace
        )
    ]


async def _get_pod_log_lines(client, pod_name, namespace):
    log_resource = await client.api("v1").resource("pods/log")
    # last 5 is a bit random, but does the trick?
    log_string = await log_resource.fetch(
        pod_name, namespace=namespace, params=dict(tail=-5)
    )
    # remove trailing space
    log_string = log_string.strip()
    # return a list of log lines
    return log_string.split("\n")


async def _get_ansible_runner_events(client, job_name, namespace):
    pod_names = await _get_pod_names_for_job(client, job_name, namespace)
    if len(pod_names) == 0 or len(pod_names) > 1:
        # TODO(johngarbutt) only works because our jobs don't retry,
        # and we don't yet check the pod is running or finished
        LOG.debug(f"Found pods:{pod_names} for job {job_name} in {namespace}")
        return
    pod_name = pod_names[0]

    log_lines = await _get_pod_log_lines(client, pod_name, namespace)
    json_events = []
    for line in log_lines:
        try:
            json_log = json.loads(line)
            json_events.append(json_log)
        except json.decoder.JSONDecodeError:
            LOG.debug("failed to decode log, most likely not ansible json output.")
    return json_events


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


async def unlabel_job(client, job):
    job_resource = await client.api("batch/v1").resource("jobs")
    await job_resource.patch(
        job.metadata.name,
        dict(metadata=dict(labels={"azimuth-caas-action": "complete-update"})),
        namespace=job.metadata.namespace,
    )


async def start_job(
    client, cluster: cluster_crd.Cluster, namespace, remove=False, update=False
):
    cluster_type_spec = await cluster_type_utils.get_cluster_type_info(client, cluster)

    # TODO(johngarbutt): generate a deploy ssh key per cluster?
    cluster_deploy_ssh_public_key = ""

    # if required, copy in the specified secret
    if cluster_type_spec.sshSharedSecretName:
        copy_from_namespace = cluster_type_spec.sshSharedSecretNamespace
        if not copy_from_namespace:
            copy_from_namespace = "azimuth"
        secrets_resource = await client.api("v1").resource("secrets")
        ssh_secret = await secrets_resource.fetch(
            cluster_type_spec.sshSharedSecretName, namespace=copy_from_namespace
        )

        # make sure we have secret copied across
        secret_name = f"ssh-{cluster.spec.clusterTypeName}"
        await secrets_resource.create_or_patch(
            secret_name,
            {
                "metadata": {"name": secret_name},
                "data": ssh_secret.data,
            },
            namespace=namespace,
        )

        public_key_raw = ssh_secret.data.get("id_rsa.pub")
        if public_key_raw:
            cluster_deploy_ssh_public_key = (
                base64.b64decode(public_key_raw).decode("utf-8").strip()
            )

    # generate config
    configmap_data = get_env_configmap(
        cluster,
        cluster_type_spec,
        cluster_deploy_ssh_public_key,
        remove=remove,
        update=update,
    )
    configmap_resource = await client.api("v1").resource("ConfigMap")
    await configmap_resource.create_or_patch(
        configmap_data["metadata"]["name"], configmap_data, namespace=namespace
    )

    # create the job
    job_data = get_job(cluster, cluster_type_spec, remove=remove, update=update)
    job_resource = await client.api("batch/v1").resource("jobs")
    await job_resource.create(job_data, namespace=namespace)


async def delete_secret(client, secret_name, namespace):
    secrets_resource = await client.api("v1").resource("secrets")
    await secrets_resource.delete(secret_name, namespace=namespace)
