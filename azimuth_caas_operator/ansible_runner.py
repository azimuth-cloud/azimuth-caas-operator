import yaml

from azimuth_caas_operator.models import registry
from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd


def get_job(cluster: cluster_crd.Cluster, cluster_type: cluster_type_crd.ClusterType):
    # TOOD(johngarbutt): template out and include ownership, etc.
    cluster_uid = cluster.metadata.uid
    name = cluster.metadata.name
    # TODO(johngarbutt): terrible hard code here, need all extra vars, and merge
    cluster_image = cluster_type.spec.extraVars.get("cluster_image")
    # TODO(johngarbutt): need to get the vars from the cluster crd and merge them!
    # and extra vars should probably be a config map
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
      - image: alpine/git
        name: env
        workingDir: /env
        command:
        - /bin/ash
        - -c
        - >-
          echo '---' >/env/extravars;
          echo 'cluster_id: {cluster_uid}' >>/env/extravars;
          echo 'cluster_name: {name}' >>/env/extravars;
          echo 'cluster_image: {cluster_image}' >>/env/extravars;
        volumeMounts:
        - name: env
          mountPath: /env
        env:
        - name: PWD
          value: /repo
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
      volumes:
      - name: playbooks
        emptyDir: {{}}
      - name: inventory
        emptyDir: {{}}
      - name: env
        emptyDir: {{}}

  backoffLimit: 0"""  # noqa
    return yaml.safe_load(job_yaml)
