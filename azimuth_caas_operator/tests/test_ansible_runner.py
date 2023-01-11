import yaml

from azimuth_caas_operator import ansible_runner
from azimuth_caas_operator.models import registry
from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd
from azimuth_caas_operator.tests import base


class TestAnsibleRunner(base.TestCase):
    def test_get_job(self):
        cluster = cluster_crd.Cluster(
            apiVersion=registry.API_VERSION,
            kind="Cluster",
            metadata=dict(name="test1", uid="fakeuid1"),
            spec=dict(
                clusterTypeName="type1",
                cloudCredentialsSecretName="cloudsyaml",
                extraVars=dict(foo="bar"),
            ),
        )
        cluster_type = cluster_type_crd.ClusterType(
            apiVersion=registry.API_VERSION,
            kind="ClusterType",
            metadata=dict(name="test1"),
            spec=dict(
                uiMetaUrl="https://url1",
                gitUrl="https://github.com/test.git",
                gitVersion="12345ab",
                playbook="sample.yaml",
                extraVars=dict(
                    cluster_image="testimage1",
                ),
            ),
        )

        job = ansible_runner.get_job(cluster, cluster_type)

        expected = """\
apiVersion: batch/v1
kind: Job
metadata:
  generateName: test1
  labels:
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
      - command:
        - /bin/ash
        - -c
        - 'echo ''---'' >/env/extravars; echo ''cluster_id: fakeuid1'' >>/env/extravars;
          echo ''cluster_name: test1'' >>/env/extravars; echo ''cluster_image: testimage1''
          >>/env/extravars;'
        env:
        - name: PWD
          value: /repo
        image: alpine/git
        name: env
        volumeMounts:
        - mountPath: /env
          name: env
        workingDir: /env
      restartPolicy: Never
      volumes:
      - emptyDir: {}
        name: playbooks
      - emptyDir: {}
        name: inventory
      - emptyDir: {}
        name: env
"""  # noqa
        self.assertEqual(expected, yaml.dump(job))
