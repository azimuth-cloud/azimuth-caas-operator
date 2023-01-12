import yaml

from azimuth_caas_operator.models import registry
from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd


def get_env_configmap(
    cluster: cluster_crd.Cluster,
    cluster_type: cluster_type_crd.ClusterType,
    remove=False,
):
    extraVars = dict(cluster_type.spec.extraVars, **cluster.spec.extraVars)
    extraVars["cluster_name"] = cluster.metadata.name
    extraVars["cluster_id"] = cluster.metadata.uid
    # TODO(johngarbutt) need to lookup deployment ssh key pair!
    extraVars[
        "cluster_deploy_ssh_public_key"
    ] = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQDE8MwOaScxQTIYpXXHawwhiZ4+9HbsUT354BTh+eaNE4cw7xmqMfUsz3yxJ1IIgmNKwHHdKz/kLjqWeynio6gxMHWEG05pGRyTpziGI/jBFSpRwfEQ5ISavrzJacMuDy3qtgsdaUXQ6Bj9HZvNzdOD/YcnrN+RhqgJ/oMP0lwC/XzF+YZWnkjmFZ7IaOTVlQW3pnTZNi8D7Sr7Acxwejw7NSHh7gKWhcs4bSMZocyIUYVyhXykZhKHrfGNN0dzbrACyFQY3W27QbhYMGFM4+rUyTe1h9DG9LzgNSyqAe6zpibUlZQZVxLxOJJNCKFHX8zXXuiNC6+KLEHjJCj5zvW8XCFlLbUy7mh/FEX2X5U5Ghw4irbX5XKUg6tgJN4cKnYhqN62jsK7YaxQ2OAcyfpBlEu/zq/7+t6AJiY93DEr7H7Og8mjsXNrchNMwrV+BLbuymcwtpDolZfdLGonj6bjSYUoJLKKsFfF2sAhc64qKDjVbbpvb52Ble1YNHcOPZ8="  # noqa
    extraVars["cluster_ssh_private_key_file"] = "/runner/ssh/id_rsa"

    if remove:
        extraVars["cluster_state"] = "absent"
    extraVars = "---\n" + yaml.dump(extraVars)

    envvars = dict(
        CONSUL_HTTP_ADDR="172.17.0.8:8500",
        OS_CLOUD="openstack",
        OS_CLIENT_CONFIG_FILE="/openstack/clouds.yaml",
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
      restartPolicy: Never
      initContainers:
      - image: alpine/git
        name: clone
        command:
        - git
        - clone
        - "{cluster_type.spec.gitUrl}"
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
        - "{cluster_type.spec.gitVersion}"
        volumeMounts:
        - name: playbooks
          mountPath: /repo
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
      containers:
      - name: run
        image: ghcr.io/stackhpc/azimuth-caas-operator-ar:49bd308
        command:
        - /bin/bash
        - -c
        - "yum update -y; yum install unzip; ansible-galaxy install -r /runner/project/roles/requirements.yml; ansible-runner run /runner -j"
        env:
        - name: RUNNER_PLAYBOOK
          value: "sample-appliance.yml"
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
          mountPath: /runner/ssh
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
  backoffLimit: 0"""  # noqa
    return yaml.safe_load(job_yaml)
