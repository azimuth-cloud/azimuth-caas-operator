import json
import unittest
from unittest import mock
import yaml

from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd
from azimuth_caas_operator.tests import async_utils
from azimuth_caas_operator.tests import base
from azimuth_caas_operator.utils import ansible_runner


class TestAnsibleRunner(base.TestCase):
    def test_get_job(self):
        cluster = cluster_crd.get_fake()
        cluster_type = cluster_type_crd.get_fake()

        job = ansible_runner.get_job(cluster, cluster_type.spec)

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
  activeDeadlineSeconds: 1200
  backoffLimit: 0
  template:
    spec:
      containers:
      - command:
        - /bin/bash
        - -c
        - chmod 755 /runner/project; ansible-galaxy install -r /runner/project/roles/requirements.yml;
          ansible-runner run /runner -j
        env:
        - name: RUNNER_PLAYBOOK
          value: sample.yaml
        image: ghcr.io/stackhpc/azimuth-caas-operator-ar:v0.1.0
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
        - mountPath: /home/runner/.ssh
          name: ssh
      initContainers:
      - command:
        - /bin/bash
        - -c
        - echo '[openstack]' >/runner/inventory/hosts; echo 'localhost ansible_connection=local
          ansible_python_interpreter=/usr/bin/python3' >>/runner/inventory/hosts
        image: ghcr.io/stackhpc/azimuth-caas-operator-ar:v0.1.0
        name: inventory
        volumeMounts:
        - mountPath: /runner/inventory
          name: inventory
        workingDir: /inventory
      - command:
        - /bin/bash
        - -c
        - chmod 755 /runner/project; git clone https://github.com/test.git /runner/project;
          git config --global --add safe.directory /runner/project; cd /runner/project;
          git checkout 12345ab; ls -al
        image: ghcr.io/stackhpc/azimuth-caas-operator-ar:v0.1.0
        name: clone
        volumeMounts:
        - mountPath: /runner/project
          name: playbooks
        workingDir: /runner
      restartPolicy: Never
      securityContext:
        fsGroup: 1000
        runAsGroup: 1000
        runAsUser: 1000
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
          defaultMode: 256
          secretName: azimuth-sshkey
"""  # noqa
        self.assertEqual(expected, yaml.dump(job))

    def test_get_job_env_configmap(self):
        cluster = cluster_crd.get_fake()
        cluster_type = cluster_type_crd.get_fake()

        config = ansible_runner.get_env_configmap(cluster, cluster_type.spec, "fakekey")
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
    "envvars": "---\\nANSIBLE_CALLBACK_PLUGINS: /home/runner/.local/lib/python3.10/site-packages/ara/plugins/callback\\nARA_API_CLIENT: http\\nARA_API_SERVER: http://azimuth-ara.azimuth-caas-operator:8000\\nCONSUL_HTTP_ADDR: zenith-consul-server.zenith:8500\\nOS_CLIENT_CONFIG_FILE: /openstack/clouds.yaml\\nOS_CLOUD: openstack\\n",
    "extravars": "---\\ncluster_deploy_ssh_public_key: fakekey\\ncluster_id: fakeuid1\\ncluster_image: testimage1\\ncluster_name: test1\\ncluster_ssh_private_key_file: /home/runner/.ssh/id_rsa\\ncluster_type: type1\\nfoo: bar\\nrandom_bool: true\\nrandom_dict:\\n  random_str: foo\\nrandom_int: 8\\n"
  }
}"""  # noqa
        self.assertEqual(expected, json.dumps(config, indent=2))


class TestAsyncUtils(unittest.IsolatedAsyncioTestCase):
    @mock.patch.object(ansible_runner, "get_job_resource")
    async def test_get_jobs_for_cluster_create(self, mock_job_resource):
        fake_job_list = ["fakejob1", "fakejob2"]
        list_iter = async_utils.AsyncIterList(fake_job_list)
        mock_job_resource.return_value = list_iter

        jobs = await ansible_runner.get_jobs_for_cluster("client", "cluster1", "ns")

        self.assertEqual(fake_job_list, jobs)
        mock_job_resource.assert_awaited_once_with("client")
        self.assertEqual(
            dict(
                labels={
                    "azimuth-caas-action": "create",
                    "azimuth-caas-cluster": "cluster1",
                },
                namespace="ns",
            ),
            list_iter.kwargs,
        )

    @mock.patch.object(ansible_runner, "get_job_resource")
    async def test_get_jobs_for_cluster_remove(self, mock_job_resource):
        fake_job_list = ["fakejob1", "fakejob2"]
        list_iter = async_utils.AsyncIterList(fake_job_list)
        mock_job_resource.return_value = list_iter

        jobs = await ansible_runner.get_jobs_for_cluster(
            "client", "cluster1", "ns", remove=True
        )

        self.assertEqual(fake_job_list, jobs)
        mock_job_resource.assert_awaited_once_with("client")
        self.assertEqual(
            dict(
                labels={
                    "azimuth-caas-action": "remove",
                    "azimuth-caas-cluster": "cluster1",
                },
                namespace="ns",
            ),
            list_iter.kwargs,
        )
