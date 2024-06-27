import base64
import json
import logging
import os
import yaml

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from easykube import ApiError

from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd
from azimuth_caas_operator.utils import cluster_type as cluster_type_utils
from azimuth_caas_operator.utils import image as image_utils
from azimuth_caas_operator.utils import k8s

LOG = logging.getLogger(__name__)


async def create_deploy_key_secret(client, name: str, cluster: cluster_crd.Cluster):
    """
    Creates a new deploy key secret for the specified cluster.
    """
    # Generate an SSH keypair
    keypair = ed25519.Ed25519PrivateKey.generate()
    public_key = keypair.public_key()
    public_key_bytes = public_key.public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    )
    public_key_text = public_key_bytes.decode()
    private_key_bytes = keypair.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    )
    private_key_text = private_key_bytes.decode()
    return await client.create_object(
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": name,
                "namespace": cluster.metadata.namespace,
                "ownerReferences": [
                    {
                        "apiVersion": cluster.api_version,
                        "kind": cluster.kind,
                        "name": cluster.metadata.name,
                        "uid": cluster.metadata.uid,
                    },
                ],
            },
            "stringData": {
                "id_ed25519.pub": public_key_text,
                "id_ed25519": private_key_text,
            },
        }
    )


async def ensure_deploy_key_secret(client, cluster: cluster_crd.Cluster):
    """
    Ensures that a deploy key secret exists for the given cluster.
    """
    deploy_key_secret_name = f"{cluster.metadata.name}-deploy-key"

    secret_resource = await client.api("v1").resource("secrets")
    try:
        secret = await secret_resource.fetch(
            deploy_key_secret_name, namespace=cluster.metadata.namespace
        )
    except ApiError as exc:
        if exc.status_code == 404:
            secret = await create_deploy_key_secret(
                client, deploy_key_secret_name, cluster
            )
        else:
            raise
    return base64.b64decode(secret.data["id_ed25519.pub"]).decode()


def get_env_configmap(
    cluster: cluster_crd.Cluster,
    cluster_type_spec: cluster_type_crd.ClusterTypeSpec,
    cluster_deploy_ssh_public_key: str,
    remove=False,
    update=False,
):
    extraVars = dict(cluster_type_spec.extraVars, **cluster.spec.extraVars)
    extraVars["cluster_name"] = cluster.metadata.name
    extraVars["cluster_id"] = cluster.status.clusterID
    extraVars["cluster_type"] = cluster.spec.clusterTypeName
    extraVars["cluster_deploy_ssh_public_key"] = cluster_deploy_ssh_public_key
    # This is the file containing the private key for the deploy key
    extraVars["cluster_ssh_private_key_file"] = "/var/lib/caas/ssh/id_ed25519"
    if remove:
        extraVars["cluster_state"] = "absent"

    envvars = dict(cluster_type_spec.envVars)
    try:
        envvars["CONSUL_HTTP_ADDR"] = os.environ["CONSUL_HTTP_ADDR"]
    except KeyError:
        raise RuntimeError("CONSUL_HTTP_ADDR is not set")
    if "ARA_API_SERVER" in os.environ:
        envvars["ARA_API_CLIENT"] = "http"
        envvars["ARA_API_SERVER"] = os.environ["ARA_API_SERVER"]

    # TODO(johngarbutt) this logic is scattered in a few places!
    action = "create"
    if remove:
        action = "remove"
    elif update:
        action = "update"

    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": f"{cluster.metadata.name}-{action}",
            "namespace": cluster.metadata.namespace,
            "ownerReferences": [
                {
                    "apiVersion": cluster.api_version,
                    "kind": cluster.kind,
                    "name": cluster.metadata.name,
                    "uid": cluster.metadata.uid,
                },
            ],
        },
        "data": {
            "envvars": yaml.safe_dump(envvars),
            "extravars": yaml.safe_dump(extraVars),
        },
    }


def get_job(
    cluster: cluster_crd.Cluster,
    cluster_type_spec: cluster_type_crd.ClusterTypeSpec,
    remove=False,
    update=False,
):
    action = "create"
    if remove:
        action = "remove"
    elif update:
        action = "update"

    image = image_utils.get_ansible_runner_image()

    defines_inventory = "ANSIBLE_INVENTORY" in dict(cluster_type_spec.envVars)
    # for ANSIBLE_INVENTORY in envvars to work, there must be no inventory/ directory

    # TODO(johngarbutt): need get secret keyname from somewhere
    job_yaml = f"""apiVersion: batch/v1
kind: Job
metadata:
  generateName: "{cluster.metadata.name}-{action}-"
  namespace: {cluster.metadata.namespace}
  labels:
      azimuth-caas-cluster: "{cluster.metadata.name}"
      azimuth-caas-action: "{action}"
  ownerReferences:
    - apiVersion: {cluster.api_version}
      kind: {cluster.kind}
      name: {cluster.metadata.name}
      uid: "{cluster.metadata.uid}"
spec:
  template:
    spec:
{f'''
      # auto-remove delete jobs after one hour
      ttlSecondsAfterFinished: 3600
 ''' if remove else ''}
      securityContext:
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
      restartPolicy: Never
      initContainers:
{f'''
      - image: "{image}"
        name: inventory
        workingDir: /inventory
        command:
        - /bin/bash
        - -c
        - |
            echo '[openstack]' >/runner/inventory/hosts
            echo 'localhost ansible_connection=local ansible_python_interpreter=/usr/bin/python3' >>/runner/inventory/hosts
        volumeMounts:
        - name: runner-data
          mountPath: /runner/inventory
          subPath: inventory
''' if not defines_inventory else ''}
      - image: "{image}"
        name: clone
        workingDir: /runner
        command:
        - /bin/bash
        - -c
        - |
            set -ex
            git clone {cluster_type_spec.gitUrl} /runner/project
            git config --global --add safe.directory /runner/project
            cd /runner/project
            git checkout {cluster_type_spec.gitVersion}
            git submodule update --init --recursive
            ls -al /runner/project
        volumeMounts:
        - name: runner-data
          mountPath: /runner/project
          subPath: project
      containers:
      - name: run
        image: "{image}"
        command:
        - /bin/bash
        - -c
        - |
            set -ex
            export ANSIBLE_CALLBACK_PLUGINS="$(python3 -m ara.setup.callback_plugins)"
            if [ -f /runner/project/requirements.yml ]; then
              ansible-galaxy install -r /runner/project/requirements.yml
            elif [ -f /runner/project/roles/requirements.yml ]; then
              ansible-galaxy install -r /runner/project/roles/requirements.yml
            fi
            ansible-runner run /runner -j
            {f"openstack application credential delete az-caas-{cluster.metadata.name} || true" if remove else ""}
        env:
        - name: RUNNER_PLAYBOOK
          value: "{cluster_type_spec.playbook}"
        # OpenStack environment variables are set here rather than envvars
        # so that they are available for use with the OpenStack CLI if required
        - name: OS_CLOUD
          value: "openstack"
        - name: OS_CLIENT_CONFIG_FILE
          value: "/var/lib/caas/cloudcreds/clouds.yaml"
        # Tell Ansible that we definitely want to use ansible.cfg from the runner directory
        # This is required because emptyDir does not allow the defaultMode
        # to be set, and resists any attempts to chmod the mount
        # Note that we are not subject to any of the security concerns referred
        # to in the Ansible docs that justify this behaviour
        # See https://docs.ansible.com/ansible/devel/reference_appendices/config.html#avoiding-security-risks-with-ansible-cfg-in-the-current-directory
        # We set this here rather than envvars because it needs to be available
        # to the ansible-galaxy command as well
        - name: ANSIBLE_CONFIG
          value: /runner/project/ansible.cfg
        # Use the writable directory for ansible-home
        - name: ANSIBLE_HOME
          value: /var/lib/ansible
        volumeMounts:
        - name: runner-data
          mountPath: /runner/project
          subPath: project
{f'''
        - name: runner-data
          mountPath: /runner/inventory
          subPath: inventory
''' if not defines_inventory else ''}
        - name: runner-data
          mountPath: /runner/artifacts
          subPath: artifacts
        - name: ansible-home
          mountPath: /var/lib/ansible
        - name: env
          mountPath: /runner/env
          readOnly: true
        - name: cloudcreds
          mountPath: /var/lib/caas/cloudcreds
          readOnly: true
        - name: deploy-key
          mountPath: /var/lib/caas/ssh
          readOnly: true
        - name: ssh
          mountPath: /home/runner/.ssh
          readOnly: true
      volumes:
      - name: runner-data
        emptyDir: {{}}
      - name: ansible-home
        emptyDir: {{}}
      - name: env
        configMap:
          name: {cluster.metadata.name}-{action}
      - name: cloudcreds
        secret:
          secretName: "{cluster.spec.cloudCredentialsSecretName}"
      - name: deploy-key
        secret:
          secretName: "{cluster.metadata.name}-deploy-key"
          defaultMode: 256
      - name: ssh
        secret:
          secretName: "ssh-{cluster.spec.clusterTypeName}"
          defaultMode: 256
          optional: true
  backoffLimit: {1 if remove else 0}
  # Set timeout so that jobs don't get stuck in configuring state if something goes wrong
  activeDeadlineSeconds: {cluster_type_spec.jobTimeout}"""  # noqa
    return yaml.safe_load(job_yaml)


async def get_job_resource(client):
    # TODO(johngarbutt): how to test this?
    return await client.api("batch/v1").resource("jobs")


async def is_create_job_running(client, cluster_name, namespace):
    create_job = await get_create_job_for_cluster(client, cluster_name, namespace)
    if not create_job:
        return False
    return create_job.status.get("active", 0) == 1


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


async def _get_jobs_for_cluster(
    client, cluster_name, namespace, remove=False, update=False
):
    job_resource = await get_job_resource(client)
    action = "remove" if remove else ("update" if update else "create")
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
    # with a retry this might be greater than 1
    failed = job.status.get("failed", 0) >= 1

    if active:
        return None
    if success:
        return True
    if failed:
        return False
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


async def get_outputs_from_job(client, job):
    state = get_job_completed_state(job)
    if state is not None:
        return await _get_job_outputs(client, job)
    else:
        LOG.warning(f"No outputs as job not completed: {job}")


async def _get_job_outputs(client, job):
    # first get the tail of the logs
    events = await _get_ansible_runner_events(
        client, job.metadata.name, job.metadata.namespace
    )
    events.reverse()
    for event_details in events:
        # look for the last debug action
        # that has an outputs key in its result object
        if event_details["event"] == "runner_on_ok":
            event_data = event_details["event_data"]
            task_action = event_data["task_action"]
            if task_action in {"debug", "ansible.builtin.debug"}:
                debug_result = event_data.get("res", {})
                outputs = debug_result.get("outputs", {})
                if isinstance(outputs, dict):
                    LOG.info(f"Outputs found for job: {job} {outputs.keys()}")
                    return outputs
                else:
                    LOG.warning(f"Invalid outputs found for job: {job}")
    LOG.info(f"No outputs found for job: {job}")


async def get_job_error_message(client, job):
    events = await _get_ansible_runner_events(
        client, job.metadata.name, job.metadata.namespace
    )
    events.reverse()
    for event_details in events:
        # look for the last debug action
        # that has an outputs key in its result object
        if event_details["event"] == "runner_on_failed":
            event_data = event_details.get("event_data", {})
            task = event_data.get("task", "Unknown Task")

            msg = "<message hidden for security reasons>"
            result = event_data.get("res", {})
            no_log = result.get("_ansible_no_log") == "true"
            if result and not no_log and "msg" in result:
                msg = result["msg"]

            return f"Task:'{task}' Error:\n{msg}"


async def _get_most_recent_pod_for_job(client, job_name, namespace):
    pod_resource = await k8s.get_pod_resource(client)
    job_pods = [
        pod
        async for pod in pod_resource.list(
            labels={"job-name": job_name}, namespace=namespace
        )
    ]
    sorted_pods = sorted(
        job_pods, key=lambda p: p["metadata"]["creationTimestamp"], reverse=True
    )
    if len(sorted_pods) > 0:
        return sorted_pods[0]["metadata"]["name"]
    else:
        return None


async def _get_pod_log_lines(client, pod_name, namespace):
    log_resource = await client.api("v1").resource("pods/log")
    # last 5 is a bit random, but does the trick?
    log_string = await log_resource.fetch(
        pod_name, namespace=namespace, params=dict(tail=-10)
    )
    # remove trailing space
    log_string = log_string.strip()
    # return a list of log lines
    return log_string.split("\n")


async def _get_ansible_runner_events(client, job_name, namespace):
    pod_name = await _get_most_recent_pod_for_job(client, job_name, namespace)
    if pod_name:
        LOG.debug(f"found pod {pod_name} for job {job_name} in {namespace}")
    else:
        LOG.debug(f"no pods found for job {job_name} in {namespace}")
        return []

    log_lines = await _get_pod_log_lines(client, pod_name, namespace)
    json_events = []
    for line in log_lines:
        try:
            json_log = json.loads(line)
        except json.decoder.JSONDecodeError:
            LOG.warning("failed to decode log, most likely not ansible json output.")
        else:
            if "event" in json_log:
                json_events.append(json_log)
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
    create_jobs = await _get_jobs_for_cluster(client, cluster_name, namespace)
    if not create_jobs:
        LOG.warning(f"can't find any create jobs for {cluster_name} in {namespace}")
        return
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
    delete_jobs = await _get_jobs_for_cluster(
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

    # ensure that we have generated an SSH key for the cluster
    cluster_deploy_ssh_public_key = await ensure_deploy_key_secret(client, cluster)

    # generate config for the job
    await client.apply_object(
        get_env_configmap(
            cluster,
            cluster_type_spec,
            cluster_deploy_ssh_public_key,
            remove=remove,
            update=update,
        ),
        force=True,
    )

    # create the job
    await client.create_object(
        get_job(cluster, cluster_type_spec, remove=remove, update=update)
    )


async def delete_secret(client, secret_name, namespace):
    secrets_resource = await client.api("v1").resource("secrets")
    await secrets_resource.delete(secret_name, namespace=namespace)
