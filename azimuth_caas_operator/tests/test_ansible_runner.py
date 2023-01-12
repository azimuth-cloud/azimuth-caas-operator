import json
import yaml

from azimuth_caas_operator import ansible_runner
from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd
from azimuth_caas_operator.tests import base


class TestAnsibleRunner(base.TestCase):
    def test_get_job(self):
        cluster = cluster_crd.get_fake()
        cluster_type = cluster_type_crd.get_fake()

        job = ansible_runner.get_job(cluster, cluster_type)

        expected = """\
apiVersion: batch/v1
kind: Job
metadata:
  generateName: test1-create-
  labels:
    azimuth-caas-action: create
    azimuth-caas-cluster: test1
  ownerReferences:
  - apiVersion: caas.azimuth.stackhpc.com/v1alpha1
    kind: Cluster
    name: test1
    uid: fakeuid1
spec:
  backoffLimit: 0
  template:
    spec:
      containers:
      - command:
        - /bin/bash
        - -c
        - yum update -y; yum install unzip; ansible-galaxy install -r /runner/project/roles/requirements.yml;
          ansible-runner run /runner -j
        env:
        - name: RUNNER_PLAYBOOK
          value: sample-appliance.yml
        image: ghcr.io/stackhpc/azimuth-caas-operator-ar:49bd308
        name: run
        volumeMounts:
        - mountPath: /runner/project
          name: playbooks
        - mountPath: /runner/inventory
          name: inventory
        - mountPath: /runner/env
          name: env
        - mountPath: /openstack
          name: cloudcreds
        - mountPath: /runner/ssh
          name: ssh
      initContainers:
      - command:
        - git
        - clone
        - https://github.com/test.git
        - /repo
        image: alpine/git
        name: clone
        volumeMounts:
        - mountPath: /repo
          name: playbooks
      - command:
        - git
        - checkout
        - 12345ab
        image: alpine/git
        name: checkout
        volumeMounts:
        - mountPath: /repo
          name: playbooks
        workingDir: /repo
      - command:
        - /bin/ash
        - -c
        - chmod 755 /repo/
        image: alpine/git
        name: permissions
        volumeMounts:
        - mountPath: /repo
          name: playbooks
        workingDir: /repo
      - command:
        - /bin/ash
        - -c
        - echo '[openstack]' >/inventory/hosts; echo 'localhost ansible_connection=local
          ansible_python_interpreter=/usr/bin/python3' >>/inventory/hosts
        image: alpine/git
        name: inventory
        volumeMounts:
        - mountPath: /inventory
          name: inventory
        workingDir: /inventory
      restartPolicy: Never
      volumes:
      - emptyDir: {}
        name: playbooks
      - emptyDir: {}
        name: inventory
      - configMap:
          name: test1-create
        name: env
      - name: cloudcreds
        secret:
          secretName: cloudsyaml
      - name: ssh
        secret:
          secretName: azimuth-sshkey
"""  # noqa
        self.assertEqual(expected, yaml.dump(job))

    def test_get_job_env_configmap(self):
        cluster = cluster_crd.get_fake()
        cluster_type = cluster_type_crd.get_fake()

        config = ansible_runner.get_env_configmap(cluster, cluster_type)
        expected = """\
{
  "apiVersion": "v1",
  "kind": "ConfigMap",
  "metadata": {
    "name": "test1-create",
    "ownerReferences": [
      {
        "apiVersion": "caas.azimuth.stackhpc.com/v1alpha1",
        "kind": "Cluster",
        "name": "test1",
        "uid": "fakeuid1"
      }
    ]
  },
  "data": {
    "envvars": "---\\nCONSUL_HTTP_ADDR: 172.17.0.8:8500\\nOS_CLIENT_CONFIG_FILE: /openstack/clouds.yaml\\nOS_CLOUD: openstack\\n",
    "extravars": "---\\ncluster_deploy_ssh_public_key: ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQDE8MwOaScxQTIYpXXHawwhiZ4+9HbsUT354BTh+eaNE4cw7xmqMfUsz3yxJ1IIgmNKwHHdKz/kLjqWeynio6gxMHWEG05pGRyTpziGI/jBFSpRwfEQ5ISavrzJacMuDy3qtgsdaUXQ6Bj9HZvNzdOD/YcnrN+RhqgJ/oMP0lwC/XzF+YZWnkjmFZ7IaOTVlQW3pnTZNi8D7Sr7Acxwejw7NSHh7gKWhcs4bSMZocyIUYVyhXykZhKHrfGNN0dzbrACyFQY3W27QbhYMGFM4+rUyTe1h9DG9LzgNSyqAe6zpibUlZQZVxLxOJJNCKFHX8zXXuiNC6+KLEHjJCj5zvW8XCFlLbUy7mh/FEX2X5U5Ghw4irbX5XKUg6tgJN4cKnYhqN62jsK7YaxQ2OAcyfpBlEu/zq/7+t6AJiY93DEr7H7Og8mjsXNrchNMwrV+BLbuymcwtpDolZfdLGonj6bjSYUoJLKKsFfF2sAhc64qKDjVbbpvb52Ble1YNHcOPZ8=\\ncluster_id: fakeuid1\\ncluster_image: testimage1\\ncluster_name: test1\\ncluster_ssh_private_key_file: /runner/ssh/id_rsa\\nfoo: bar\\n"
  }
}"""  # noqa
        self.assertEqual(expected, json.dumps(config, indent=2))
