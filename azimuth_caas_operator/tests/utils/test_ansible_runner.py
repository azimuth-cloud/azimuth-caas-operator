import base64
import json
import os
import unittest
from unittest import mock

import yaml
from easykube.rest.util import PropertyDict

from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd
from azimuth_caas_operator.tests import async_utils
from azimuth_caas_operator.utils import ansible_runner


class TestAnsibleRunner(unittest.TestCase):
    @mock.patch.dict(
        os.environ,
        {
            "ANSIBLE_RUNNER_IMAGE_TAG": "12345ab",
        },
        clear=True,
    )
    def test_get_job_remove(self):
        cluster = cluster_crd.get_fake()
        cluster.spec.leaseName = None
        cluster_type = cluster_type_crd.get_fake()

        job = ansible_runner.get_job(
            cluster, cluster_type.spec, "test1-tfstate", None, remove=True
        )

        expected = """\
apiVersion: batch/v1
kind: Job
metadata:
  generateName: test1-remove-
  labels:
    azimuth-caas-action: remove
    azimuth-caas-cluster: test1
  namespace: ns1
spec:
  activeDeadlineSeconds: 1200
  backoffLimit: 1
  template:
    spec:
      containers:
      - command:
        - /bin/bash
        - -c
        - "set -ex\\nif [ -f /var/lib/caas/cloudcreds/cacert ]; then\\n  export OS_CACERT=/var/lib/caas/cloudcreds/cacert\\n\\
          fi\\nexport ANSIBLE_CALLBACK_PLUGINS=\\"$(python3 -m ara.setup.callback_plugins)\\"\\
          \\nif [ -f /runner/project/requirements.yml ]; then\\n  ansible-galaxy install\\
          \\ -r /runner/project/requirements.yml\\nelif [ -f /runner/project/roles/requirements.yml\\
          \\ ]; then\\n  ansible-galaxy install -r /runner/project/roles/requirements.yml\\n\\
          fi\\nansible-runner run /runner -j\\nopenstack application credential delete\\
          \\ az-caas-test1 || true\\n"
        env:
        - name: RUNNER_PLAYBOOK
          value: sample.yaml
        - name: OS_CLOUD
          value: openstack
        - name: OS_CLIENT_CONFIG_FILE
          value: /var/lib/caas/cloudcreds/clouds.yaml
        - name: ANSIBLE_CONFIG
          value: /runner/project/ansible.cfg
        - name: ANSIBLE_HOME
          value: /var/lib/ansible
        - name: ANSIBLE_SSH_RETRIES
          value: '10'
        image: ghcr.io/azimuth-cloud/azimuth-caas-operator-ee:12345ab
        name: run
        volumeMounts:
        - mountPath: /runner/project
          name: runner-data
          subPath: project
        - mountPath: /runner/inventory
          name: runner-data
          subPath: inventory
        - mountPath: /runner/artifacts
          name: runner-data
          subPath: artifacts
        - mountPath: /var/lib/ansible
          name: ansible-home
        - mountPath: /runner/env
          name: env
          readOnly: true
        - mountPath: /var/lib/caas/cloudcreds
          name: cloudcreds
          readOnly: true
        - mountPath: /var/lib/caas/ssh
          name: deploy-key
          readOnly: true
        - mountPath: /home/runner/.ssh
          name: ssh
          readOnly: true
      initContainers:
      - command:
        - /bin/bash
        - -c
        - 'echo ''[openstack]'' >/runner/inventory/hosts

          echo ''localhost ansible_connection=local ansible_python_interpreter=/usr/bin/python3''
          >>/runner/inventory/hosts

          '
        image: ghcr.io/azimuth-cloud/azimuth-caas-operator-ee:12345ab
        name: inventory
        volumeMounts:
        - mountPath: /runner/inventory
          name: runner-data
          subPath: inventory
        workingDir: /inventory
      - command:
        - /bin/bash
        - -c
        - 'set -ex

          git clone https://github.com/test.git /runner/project

          git config --global --add safe.directory /runner/project

          cd /runner/project

          git checkout 12345ab

          git submodule update --init --recursive

          ls -al /runner/project

          '
        image: ghcr.io/azimuth-cloud/azimuth-caas-operator-ee:12345ab
        name: clone
        volumeMounts:
        - mountPath: /runner/project
          name: runner-data
          subPath: project
        workingDir: /runner
      restartPolicy: Never
      securityContext:
        fsGroup: 1000
        runAsGroup: 1000
        runAsUser: 1000
      serviceAccountName: test1-tfstate
      volumes:
      - emptyDir: {}
        name: runner-data
      - emptyDir: {}
        name: ansible-home
      - configMap:
          name: test1-remove
        name: env
      - name: cloudcreds
        secret:
          secretName: cloudsyaml
      - name: deploy-key
        secret:
          defaultMode: 256
          secretName: test1-deploy-key
      - name: ssh
        secret:
          defaultMode: 256
          optional: true
          secretName: ssh-type1
  ttlSecondsAfterFinished: 36000
"""  # noqa

        self.assertEqual(expected, yaml.safe_dump(job))

    @mock.patch.dict(
        os.environ,
        {
            "ANSIBLE_RUNNER_IMAGE_TAG": "12345ab",
        },
        clear=True,
    )
    def test_get_job_create_with_trust_bundle(self):
        cluster = cluster_crd.get_fake()
        cluster.spec.leaseName = None
        cluster_type = cluster_type_crd.get_fake()
        cluster_type.spec.jobCreateRetries = 3

        job = ansible_runner.get_job(
            cluster,
            cluster_type.spec,
            "test1-tfstate",
            "trust-bundle",
        )

        expected = """\
apiVersion: batch/v1
kind: Job
metadata:
  generateName: test1-create-
  labels:
    azimuth-caas-action: create
    azimuth-caas-cluster: test1
  namespace: ns1
spec:
  activeDeadlineSeconds: 1200
  backoffLimit: 3
  template:
    spec:
      containers:
      - command:
        - /bin/bash
        - -c
        - "set -ex\\nif [ -f /var/lib/caas/cloudcreds/cacert ]; then\\n  export OS_CACERT=/var/lib/caas/cloudcreds/cacert\\n\\
          fi\\nexport ANSIBLE_CALLBACK_PLUGINS=\\"$(python3 -m ara.setup.callback_plugins)\\"\\
          \\nif [ -f /runner/project/requirements.yml ]; then\\n  ansible-galaxy install\\
          \\ -r /runner/project/requirements.yml\\nelif [ -f /runner/project/roles/requirements.yml\\
          \\ ]; then\\n  ansible-galaxy install -r /runner/project/roles/requirements.yml\\n\\
          fi\\nansible-runner run /runner -j\\n"
        env:
        - name: RUNNER_PLAYBOOK
          value: sample.yaml
        - name: OS_CLOUD
          value: openstack
        - name: OS_CLIENT_CONFIG_FILE
          value: /var/lib/caas/cloudcreds/clouds.yaml
        - name: ANSIBLE_CONFIG
          value: /runner/project/ansible.cfg
        - name: ANSIBLE_HOME
          value: /var/lib/ansible
        - name: ANSIBLE_SSH_RETRIES
          value: '10'
        - name: CURL_CA_BUNDLE
          value: /etc/ssl/certs/ca-certificates.crt
        - name: GIT_SSL_CAINFO
          value: /etc/ssl/certs/ca-certificates.crt
        - name: REQUESTS_CA_BUNDLE
          value: /etc/ssl/certs/ca-certificates.crt
        - name: SSL_CERT_FILE
          value: /etc/ssl/certs/ca-certificates.crt
        image: ghcr.io/azimuth-cloud/azimuth-caas-operator-ee:12345ab
        name: run
        volumeMounts:
        - mountPath: /runner/project
          name: runner-data
          subPath: project
        - mountPath: /runner/inventory
          name: runner-data
          subPath: inventory
        - mountPath: /runner/artifacts
          name: runner-data
          subPath: artifacts
        - mountPath: /var/lib/ansible
          name: ansible-home
        - mountPath: /runner/env
          name: env
          readOnly: true
        - mountPath: /var/lib/caas/cloudcreds
          name: cloudcreds
          readOnly: true
        - mountPath: /var/lib/caas/ssh
          name: deploy-key
          readOnly: true
        - mountPath: /home/runner/.ssh
          name: ssh
          readOnly: true
        - mountPath: /etc/ssl/certs
          name: trust-bundle
          readOnly: true
      initContainers:
      - command:
        - /bin/bash
        - -c
        - 'echo ''[openstack]'' >/runner/inventory/hosts

          echo ''localhost ansible_connection=local ansible_python_interpreter=/usr/bin/python3''
          >>/runner/inventory/hosts

          '
        image: ghcr.io/azimuth-cloud/azimuth-caas-operator-ee:12345ab
        name: inventory
        volumeMounts:
        - mountPath: /runner/inventory
          name: runner-data
          subPath: inventory
        workingDir: /inventory
      - command:
        - /bin/bash
        - -c
        - 'set -ex

          git clone https://github.com/test.git /runner/project

          git config --global --add safe.directory /runner/project

          cd /runner/project

          git checkout 12345ab

          git submodule update --init --recursive

          ls -al /runner/project

          '
        env:
        - name: CURL_CA_BUNDLE
          value: /etc/ssl/certs/ca-certificates.crt
        - name: GIT_SSL_CAINFO
          value: /etc/ssl/certs/ca-certificates.crt
        - name: SSL_CERT_FILE
          value: /etc/ssl/certs/ca-certificates.crt
        image: ghcr.io/azimuth-cloud/azimuth-caas-operator-ee:12345ab
        name: clone
        volumeMounts:
        - mountPath: /runner/project
          name: runner-data
          subPath: project
        - mountPath: /etc/ssl/certs
          name: trust-bundle
          readOnly: true
        workingDir: /runner
      restartPolicy: Never
      securityContext:
        fsGroup: 1000
        runAsGroup: 1000
        runAsUser: 1000
      serviceAccountName: test1-tfstate
      volumes:
      - emptyDir: {}
        name: runner-data
      - emptyDir: {}
        name: ansible-home
      - configMap:
          name: test1-create
        name: env
      - name: cloudcreds
        secret:
          secretName: cloudsyaml
      - name: deploy-key
        secret:
          defaultMode: 256
          secretName: test1-deploy-key
      - name: ssh
        secret:
          defaultMode: 256
          optional: true
          secretName: ssh-type1
      - configMap:
          name: trust-bundle
        name: trust-bundle
"""  # noqa
        self.assertEqual(expected, yaml.safe_dump(job))

    @mock.patch.dict(
        os.environ,
        {
            "ARA_API_SERVER": "fakearaurl",
        },
        clear=True,
    )
    def test_get_job_env_configmap(self):
        cluster = cluster_crd.get_fake()
        cluster_type = cluster_type_crd.get_fake()
        global_extravars = {
            "global_extravar1": "value1",
            "global_extravar2": "value2",
        }

        config = ansible_runner.get_env_configmap(
            cluster, cluster_type.spec, "fakekey", global_extravars
        )
        expected = """\
apiVersion: v1
data:
  envvars: 'ARA_API_CLIENT: http

    ARA_API_SERVER: fakearaurl

    '
  extravars: "cluster_deploy_ssh_public_key: fakekey\\ncluster_id: fakeclusterID1\\n\\
    cluster_image: testimage1\\ncluster_name: test1\\ncluster_ssh_private_key_file:\\
    \\ /var/lib/caas/ssh/id_ed25519\\ncluster_type: type1\\nfoo: boo\\nglobal_extravar1:\\
    \\ value1\\nglobal_extravar2: value2\\nnested:\\n  baz: bob\\nrandom_bool: true\\nrandom_dict:\\n\\
    \\  random_str: foo\\nrandom_int: 8\\nvery_random_int: 42\\n"
kind: ConfigMap
metadata:
  labels:
    azimuth-caas-cluster: test1
  name: test1-create
  namespace: ns1
"""  # noqa
        self.assertEqual(expected, yaml.safe_dump(config))
        # check cluster_image comes from cluster template
        self.assertEqual(
            "testimage1",
            yaml.load(config["data"]["extravars"], Loader=yaml.BaseLoader)[
                "cluster_image"
            ],
        )
        # check very_random_int comes from extravars
        self.assertEqual(
            "42",
            yaml.load(config["data"]["extravars"], Loader=yaml.BaseLoader)[
                "very_random_int"
            ],
        )
        # check foo is correctly overridden by extra vars overrides
        self.assertEqual(
            "boo", yaml.load(config["data"]["extravars"], Loader=yaml.BaseLoader)["foo"]
        )


class TestAsyncUtils(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_trust_bundle_configmap_no_configmap(self):
        mock_client = mock.Mock()

        trust_bundle_configmap = await ansible_runner.ensure_trust_bundle_configmap(
            mock_client, "ns-2"
        )

        self.assertIsNone(trust_bundle_configmap)
        mock_client.api.assert_not_called()

    @mock.patch.dict(
        os.environ,
        {
            "TRUST_BUNDLE_CONFIGMAP": "trust-bundle",
            "SELF_NAMESPACE": "ns-1",
        },
        clear=True,
    )
    async def test_ensure_trust_bundle_configmap(self):
        trust_bundle_data = {"ca-certificates.crt": "certificatedata"}
        trust_bundle_source = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": "trust-bundle",
                "namespace": "ns-1",
                "creationTimestamp": "timestamp",
                "uid": "trust-bundle-uid",
            },
            "data": trust_bundle_data,
        }
        trust_bundle_mirror = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": "trust-bundle",
                "namespace": "ns-2",
                "labels": {
                    "app.kubernetes.io/created-by": "azimuth-caas-operator",
                },
                "annotations": {
                    "caas.azimuth.stackhpc.com/mirrors": "ns-1/trust-bundle",
                },
            },
            "data": trust_bundle_data,
        }

        mock_client = mock.Mock()
        mock_client.apply_object = mock.AsyncMock()
        mock_api = mock.AsyncMock()
        mock_client.api.return_value = mock_api
        mock_resource = mock.AsyncMock()
        mock_api.resource.return_value = mock_resource
        mock_resource.fetch.return_value = trust_bundle_source

        trust_bundle_configmap = await ansible_runner.ensure_trust_bundle_configmap(
            mock_client, "ns-2"
        )

        self.assertEqual("trust-bundle", trust_bundle_configmap)
        mock_client.api.assert_called_once_with("v1")
        mock_api.resource.assert_called_once_with("configmaps")
        mock_resource.fetch.assert_called_once_with("trust-bundle", namespace="ns-1")
        mock_client.apply_object.assert_called_once_with(
            trust_bundle_mirror, force=True
        )

    @mock.patch.dict(
        os.environ, {"GLOBAL_EXTRAVARS_SECRET": "ns-1/extravars"}, clear=True
    )
    async def test_get_global_extravars(self):
        mock_client = mock.Mock()
        mock_api = mock.AsyncMock()
        mock_client.api.return_value = mock_api
        mock_resource = mock.AsyncMock()
        mock_api.resource.return_value = mock_resource
        secret_data = {
            "extravars": {
                "extravar_1": "value1",
                "extravar_2": "value2",
            },
            "moreextravars": {
                "extravar_3": "value3",
            },
        }
        mock_resource.fetch.return_value = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": "extravars",
                "namespace": "ns-1",
            },
            "data": {
                k: base64.b64encode(yaml.safe_dump(v).encode()).decode()
                for k, v in secret_data.items()
            },
        }

        global_extravars = await ansible_runner.get_global_extravars(mock_client)

        self.assertEqual(
            {
                "extravar_1": "value1",
                "extravar_2": "value2",
                "extravar_3": "value3",
            },
            global_extravars,
        )

    async def test_get_global_extravars_no_secret(self):
        mock_client = mock.AsyncMock()
        global_extravars = await ansible_runner.get_global_extravars(mock_client)
        self.assertEqual({}, global_extravars)

    @mock.patch.dict(
        os.environ,
        {"ANSIBLE_RUNNER_CLUSTER_ROLE": "azimuth-caas-operator:tfstate"},
        clear=True,
    )
    async def test_ensure_service_account(self):
        mock_client = mock.AsyncMock()

        def fake_apply_object(obj, force=False):
            return PropertyDict(obj)

        mock_client.apply_object.side_effect = fake_apply_object
        cluster = cluster_crd.get_fake()

        service_account_name = await ansible_runner.ensure_service_account(
            mock_client, cluster
        )

        class KindMatcher:
            def __init__(self, kind):
                self._kind = kind

            def __eq__(self, actual):
                return actual["kind"] == self._kind

        self.assertEqual("test1-tfstate", service_account_name)
        self.assertEqual(2, mock_client.apply_object.call_count)
        mock_client.apply_object.assert_any_call(
            KindMatcher("ServiceAccount"), force=True
        )
        mock_client.apply_object.assert_any_call(KindMatcher("RoleBinding"), force=True)

    @mock.patch.object(ansible_runner, "get_job_resource")
    async def test_get_jobs_for_cluster_create(self, mock_job_resource):
        fake_job_list = ["fakejob1", "fakejob2"]
        list_iter = async_utils.AsyncIterList(fake_job_list)
        mock_job_resource.return_value = list_iter

        jobs = await ansible_runner._get_jobs_for_cluster("client", "cluster1", "ns")

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

        jobs = await ansible_runner._get_jobs_for_cluster(
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

    @mock.patch(
        "azimuth_caas_operator.utils.k8s.get_pod_resource", new_callable=mock.AsyncMock
    )
    async def test_get_most_recent_pod_for_job(self, mock_pod):
        mock_iter = async_utils.AsyncIterList(
            [
                dict(
                    metadata=dict(name="pod1", creationTimestamp="2023-10-31T12:48:28Z")
                ),
                dict(
                    metadata=dict(name="pod2", creationTimestamp="2023-10-31T13:48:28Z")
                ),
            ]
        )
        mock_pod.return_value = mock_iter

        name = await ansible_runner._get_most_recent_pod_for_job(
            "client", "job1", "default"
        )

        self.assertEqual("pod2", name)
        self.assertEqual(
            {"labels": {"job-name": "job1"}, "namespace": "default"}, mock_iter.kwargs
        )

    @mock.patch(
        "azimuth_caas_operator.utils.k8s.get_pod_resource", new_callable=mock.AsyncMock
    )
    async def test_get_most_recent_pod_for_job_no_pods(self, mock_pod):
        mock_iter = async_utils.AsyncIterList([])
        mock_pod.return_value = mock_iter

        name = await ansible_runner._get_most_recent_pod_for_job(
            "client", "job1", "default"
        )

        self.assertIsNone(name)
        self.assertEqual(
            {"labels": {"job-name": "job1"}, "namespace": "default"}, mock_iter.kwargs
        )

    @mock.patch.object(ansible_runner, "LOG")
    @mock.patch.object(ansible_runner, "_get_pod_log_lines")
    @mock.patch.object(ansible_runner, "_get_most_recent_pod_for_job")
    async def test_get_ansible_runner_event_returns_event(
        self, mock_pod_names, mock_get_lines, mock_log
    ):
        mock_pod_names.return_value = "pod1"
        fake_event = dict(event="event_name", event_data=dict(task="stuff"))
        not_event = dict(data=dict(one="two"))
        mock_get_lines.return_value = [
            "foo",
            "bar",
            json.dumps(not_event),
            json.dumps(fake_event),
        ]

        event = await ansible_runner._get_ansible_runner_events("client", "job", "ns")

        self.assertEqual([fake_event], event)
        mock_pod_names.assert_awaited_once_with("client", "job", "ns")
        mock_get_lines.assert_awaited_once_with("client", "pod1", "ns")

    @mock.patch.object(ansible_runner, "LOG")
    @mock.patch.object(ansible_runner, "_get_pod_log_lines")
    @mock.patch.object(ansible_runner, "_get_most_recent_pod_for_job")
    async def test_get_ansible_runner_event_returns_no_event_on_bad_json(
        self, mock_pod_name, mock_get_lines, mock_log
    ):
        mock_pod_name.return_value = "pod1"
        mock_get_lines.return_value = ["foo", "bar"]

        event = await ansible_runner._get_ansible_runner_events("client", "job", "ns")

        self.assertEqual([], event)
        mock_pod_name.assert_awaited_once_with("client", "job", "ns")
        mock_get_lines.assert_awaited_once_with("client", "pod1", "ns")

    @mock.patch.object(ansible_runner, "LOG")
    @mock.patch.object(ansible_runner, "_get_pod_log_lines")
    @mock.patch.object(ansible_runner, "_get_most_recent_pod_for_job")
    async def test_get_ansible_runner_event_returns_no_event_on_no_pod(
        self, mock_pod_name, mock_get_lines, mock_log
    ):
        mock_pod_name.return_value = None

        event = await ansible_runner._get_ansible_runner_events("client", "job", "ns")

        self.assertEqual([], event)
        mock_pod_name.assert_awaited_once_with("client", "job", "ns")
        mock_get_lines.assert_not_awaited()

    @mock.patch.object(ansible_runner, "get_create_job_for_cluster")
    async def test_is_create_job_running_returns_true(self, mock_get_create_job):
        mock_job = mock.MagicMock()
        mock_job.status = {"active": 1}
        mock_get_create_job.return_value = mock_job

        result = await ansible_runner.is_create_job_running("client", "cluster", "ns")

        self.assertTrue(result)
        mock_get_create_job.assert_awaited_once_with("client", "cluster", "ns")

    @mock.patch.object(ansible_runner, "get_create_job_for_cluster")
    async def test_is_create_job_running_returns_false_no_job(
        self, mock_get_create_job
    ):
        mock_get_create_job.return_value = None

        result = await ansible_runner.is_create_job_running("client", "cluster", "ns")

        self.assertFalse(result)

    @mock.patch.object(ansible_runner, "get_create_job_for_cluster")
    async def test_is_create_job_running_returns_false_not_active(
        self, mock_get_create_job
    ):
        mock_job = mock.MagicMock()
        mock_job.status = {}
        mock_get_create_job.return_value = mock_job

        result = await ansible_runner.is_create_job_running("client", "cluster", "ns")

        self.assertFalse(result)
        mock_get_create_job.assert_awaited_once_with("client", "cluster", "ns")

    def _configure_mock_api(self, resources):
        mock_resources = {resource: mock.AsyncMock() for resource in resources}
        mock_api = mock.AsyncMock()
        mock_api.resource.side_effect = lambda resource: mock_resources[resource]
        return mock_api, mock_resources

    def _configure_mock_client(self, apis):
        mock_apis = {}
        mock_resources = {}
        for api, resources in apis.items():
            mock_api, mock_api_resources = self._configure_mock_api(resources)
            mock_apis[api] = mock_api
            mock_resources[api] = mock_api_resources
        mock_client = mock.Mock()
        mock_client.api.side_effect = lambda api: mock_apis[api]
        return mock_client, mock_apis, mock_resources

    async def test_purge_job_resources(self):
        mock_client, mock_apis, mock_resources = self._configure_mock_client(
            {
                "v1": ["configmaps", "secrets", "serviceaccounts"],
                "rbac.authorization.k8s.io/v1": ["rolebindings"],
                "batch/v1": ["jobs"],
            }
        )
        cluster = cluster_crd.get_fake()

        await ansible_runner.purge_job_resources(mock_client, cluster)

        mock_client.api.assert_any_call("v1")
        mock_apis["v1"].resource.assert_any_await("secrets")
        mock_resources["v1"]["secrets"].delete.assert_awaited_once_with(
            "test1-deploy-key", namespace="ns1"
        )
        mock_apis["v1"].resource.assert_any_await("serviceaccounts")
        mock_resources["v1"]["serviceaccounts"].delete.assert_awaited_once_with(
            "test1-tfstate", namespace="ns1"
        )
        mock_apis["v1"].resource.assert_any_await("configmaps")
        mock_resources["v1"]["configmaps"].delete.assert_has_awaits(
            [
                mock.call("test1-create", namespace="ns1"),
                mock.call("test1-update", namespace="ns1"),
                mock.call("test1-remove", namespace="ns1"),
            ],
            any_order=True,
        )

        mock_client.api.assert_any_call("rbac.authorization.k8s.io/v1")
        mock_apis["rbac.authorization.k8s.io/v1"].resource.assert_any_await(
            "rolebindings"
        )
        mock_resources["rbac.authorization.k8s.io/v1"][
            "rolebindings"
        ].delete.assert_awaited_once_with("test1-tfstate", namespace="ns1")

        mock_client.api.assert_any_call("batch/v1")
        mock_apis["batch/v1"].resource.assert_any_await("jobs")
        mock_resources["batch/v1"]["jobs"].delete_all.assert_awaited_once_with(
            labels={"azimuth-caas-cluster": "test1"}, namespace="ns1"
        )
