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
  labels:
    azimuth-caas-cluster: test1
    azimuth-cass-action: create
  name: test1-create
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
          name: test1
        name: env
      - name: cloudcreds
        secret:
          secretName: cloudsyaml
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
    "name": "test1",
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
    "envvars": "---\\nCONSUL_HTTP_ADDR: 172.17.0.7:8500\\nOS_CLIENT_CONFIG_FILE: /openstack/clouds.yaml\\nOS_CLOUD: openstack\\n",
    "extravars": "---\\ncluster_id: fakeuid1\\ncluster_image: testimage1\\ncluster_name: test1\\nfoo: bar\\n"
  }
}"""  # noqa
        self.assertEqual(expected, json.dumps(config, indent=2))
