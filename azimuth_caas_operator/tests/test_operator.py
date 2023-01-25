import json
import unittest
from unittest import mock

from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd
from azimuth_caas_operator import operator
from azimuth_caas_operator.tests import async_utils
from azimuth_caas_operator.utils import ansible_runner
from azimuth_caas_operator.utils import cluster as cluster_utils


class TestOperator(unittest.IsolatedAsyncioTestCase):
    @mock.patch("azimuth_caas_operator.models.registry.get_crd_resources")
    @mock.patch("azimuth_caas_operator.utils.k8s.get_k8s_client")
    async def test_startup_register_crds(self, mock_get, mock_crds):
        mock_client = mock.AsyncMock()
        mock_get.return_value = mock_client
        mock_crds.return_value = ["fakecrd1", "fakecrd2"]

        await operator.startup()

        mock_client.apply_object.assert_has_awaits(
            [mock.call("fakecrd1", force=True), mock.call("fakecrd2", force=True)]
        )

    @mock.patch.object(operator, "K8S_CLIENT", new_callable=mock.AsyncMock)
    async def test_cleanup_calls_aclose(self, mock_client):
        await operator.cleanup()
        mock_client.aclose.assert_awaited_once_with()

    @mock.patch(
        "azimuth_caas_operator.utils.k8s.get_pod_resource", new_callable=mock.AsyncMock
    )
    async def test_get_pod_names_for_job(self, mock_pod):
        mock_iter = async_utils.AsyncIterList(
            [
                dict(metadata=dict(name="pod1")),
                dict(metadata=dict(name="pod2")),
            ]
        )
        mock_pod.return_value = mock_iter

        names = await operator._get_pod_names_for_job("job1", "default")

        self.assertEqual(["pod1", "pod2"], names)
        self.assertEqual(
            {"labels": {"job-name": "job1"}, "namespace": "default"}, mock_iter.kwargs
        )

    @mock.patch.object(operator, "LOG")
    @mock.patch.object(operator, "_get_pod_log_lines")
    @mock.patch.object(operator, "_get_pod_names_for_job")
    async def test_get_ansible_runner_event_returns_event(
        self, mock_pod_names, mock_get_lines, mock_log
    ):
        mock_pod_names.return_value = ["pod1"]
        fake_event = dict(event_data=dict(task="stuff"))
        mock_get_lines.return_value = ["foo", "bar", json.dumps(fake_event)]

        event = await operator.get_ansible_runner_event("job", "ns")

        self.assertEqual(fake_event["event_data"], event)
        mock_pod_names.assert_awaited_once_with("job", "ns")
        mock_get_lines.assert_awaited_once_with("pod1", "ns")
        mock_log.info.assert_called_once_with("For job: job in: ns seen task: stuff")

    @mock.patch.object(operator, "LOG")
    @mock.patch.object(operator, "_get_pod_log_lines")
    @mock.patch.object(operator, "_get_pod_names_for_job")
    async def test_get_ansible_runner_event_returns_no_event_on_bad_json(
        self, mock_pod_names, mock_get_lines, mock_log
    ):
        mock_pod_names.return_value = ["pod1"]
        mock_get_lines.return_value = ["foo", "bar"]

        event = await operator.get_ansible_runner_event("job", "ns")

        self.assertIsNone(event)
        mock_pod_names.assert_awaited_once_with("job", "ns")
        mock_get_lines.assert_awaited_once_with("pod1", "ns")

    @mock.patch.object(operator, "LOG")
    @mock.patch.object(operator, "_get_pod_log_lines")
    @mock.patch.object(operator, "_get_pod_names_for_job")
    async def test_get_ansible_runner_event_returns_no_event_multi_pod(
        self, mock_pod_names, mock_get_lines, mock_log
    ):
        mock_pod_names.return_value = ["pod1", "pod2"]
        mock_get_lines.return_value = ["foo", "bar"]

        event = await operator.get_ansible_runner_event("job", "ns")

        self.assertIsNone(event)
        mock_pod_names.assert_awaited_once_with("job", "ns")
        mock_get_lines.assert_not_awaited()

    async def test_cluster_type_create(self):
        # TODO(johngarbutt): probably need to actually fetch the ui meta!
        await operator.cluster_type_create(
            cluster_type_crd.get_fake_dict(), "type1", "ns", {}
        )

    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "start_job")
    @mock.patch.object(ansible_runner, "get_jobs_for_cluster")
    async def test_cluster_create_creates_job_and_raise(
        self, mock_get_jobs, mock_start, mock_update
    ):
        # testing the zero jobs case
        mock_get_jobs.return_value = []
        fake_body = cluster_crd.get_fake_dict()

        with self.assertRaises(RuntimeError) as ctx:
            await operator.cluster_create(fake_body, "cluster1", "ns", {})

        self.assertEqual(
            "wait for create job to complete for cluster1 in ns", str(ctx.exception)
        )
        mock_get_jobs.assert_awaited_once_with(operator.K8S_CLIENT, "cluster1", "ns")
        cluster = cluster_crd.Cluster(**fake_body)
        mock_start.assert_awaited_once_with(
            operator.K8S_CLIENT, cluster, "ns", remove=False
        )
        mock_update.assert_awaited_once_with(
            operator.K8S_CLIENT, "cluster1", "ns", cluster_crd.ClusterPhase.CREATING
        )

    @mock.patch.object(cluster_utils, "create_scheduled_delete_job")
    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "is_any_successful_jobs")
    @mock.patch.object(ansible_runner, "get_jobs_for_cluster")
    async def test_cluster_create_spots_successful_job(
        self,
        mock_get_jobs,
        mock_success,
        mock_update,
        mock_auto,
    ):
        mock_get_jobs.return_value = ["fakejob"]
        mock_success.return_value = True
        fake_body = cluster_crd.get_fake_dict()

        await operator.cluster_create(fake_body, "cluster1", "ns", {})

        mock_update.assert_awaited_once_with(
            operator.K8S_CLIENT, "cluster1", "ns", cluster_crd.ClusterPhase.READY
        )
        mock_auto.assert_awaited_once_with(operator.K8S_CLIENT, "cluster1", "ns")

    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "are_all_jobs_in_error_state")
    @mock.patch.object(ansible_runner, "is_any_successful_jobs")
    @mock.patch.object(ansible_runner, "get_jobs_for_cluster")
    async def test_cluster_create_waits_for_job_to_complete(
        self, mock_get_jobs, mock_success, mock_all_error, mock_update
    ):
        mock_get_jobs.return_value = ["fakejob"]
        mock_success.return_value = False
        mock_all_error.return_value = False
        fake_body = cluster_crd.get_fake_dict()

        with self.assertRaises(RuntimeError) as ctx:
            await operator.cluster_create(fake_body, "cluster1", "ns", {})

        mock_update.assert_not_awaited()
        self.assertEqual(
            "wait for create job to complete for cluster1 in ns", str(ctx.exception)
        )

    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "are_all_jobs_in_error_state")
    @mock.patch.object(ansible_runner, "is_any_successful_jobs")
    @mock.patch.object(ansible_runner, "get_jobs_for_cluster")
    async def test_cluster_create_raise_on_too_many_jobs(
        self, mock_get_jobs, mock_success, mock_all_error, mock_update
    ):
        # TODO(johngarbutt): should generate a working fake job list!
        mock_get_jobs.return_value = ["fakejob", "fakejob2", "fakejob3"]
        mock_success.return_value = False
        mock_all_error.return_value = True
        fake_body = cluster_crd.get_fake_dict()

        with self.assertRaises(RuntimeError) as ctx:
            await operator.cluster_create(fake_body, "cluster1", "ns", {})

        self.assertEqual(
            "Too many failed creates for cluster1 in ns", str(ctx.exception)
        )
        mock_update.assert_awaited_once_with(
            operator.K8S_CLIENT, "cluster1", "ns", cluster_crd.ClusterPhase.FAILED
        )

    @mock.patch.object(ansible_runner, "start_job")
    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "are_all_jobs_in_error_state")
    @mock.patch.object(ansible_runner, "is_any_successful_jobs")
    @mock.patch.object(ansible_runner, "get_jobs_for_cluster")
    async def test_cluster_create_raise_on_retry(
        self, mock_get_jobs, mock_success, mock_all_error, mock_update, mock_start
    ):
        # TODO(johngarbutt): should generate a working fake job list!
        mock_get_jobs.return_value = ["fakejob", "fakejob2"]
        mock_success.return_value = False
        mock_all_error.return_value = True
        fake_body = cluster_crd.get_fake_dict()

        with self.assertRaises(RuntimeError) as ctx:
            await operator.cluster_create(fake_body, "cluster1", "ns", {})

        self.assertEqual(
            "wait for create job to complete for cluster1 in ns", str(ctx.exception)
        )
        cluster = cluster_crd.Cluster(**fake_body)
        mock_start.assert_awaited_once_with(
            operator.K8S_CLIENT, cluster, "ns", remove=False
        )
        mock_update.assert_awaited_once_with(
            operator.K8S_CLIENT, "cluster1", "ns", cluster_crd.ClusterPhase.CREATING
        )

    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "start_job")
    @mock.patch.object(ansible_runner, "get_delete_jobs_status")
    @mock.patch.object(ansible_runner, "ensure_create_jobs_finished")
    async def test_cluster_delete_creates_job_and_raises(
        self, mock_create_finsish, mock_get_jobs, mock_start, mock_update
    ):
        # testing the zero jobs case
        mock_get_jobs.return_value = []
        fake_body = cluster_crd.get_fake_dict()

        with self.assertRaises(RuntimeError) as ctx:
            await operator.cluster_delete(fake_body, "cluster1", "ns", {})

        self.assertEqual(
            "wait for delete job to complete for cluster1 in ns", str(ctx.exception)
        )
        mock_create_finsish.assert_awaited_once_with(
            operator.K8S_CLIENT, "cluster1", "ns"
        )
        mock_get_jobs.assert_awaited_once_with(operator.K8S_CLIENT, "cluster1", "ns")
        cluster = cluster_crd.Cluster(**fake_body)
        mock_start.assert_awaited_once_with(
            operator.K8S_CLIENT, cluster, "ns", remove=True
        )
        mock_update.assert_awaited_once_with(
            operator.K8S_CLIENT, "cluster1", "ns", cluster_crd.ClusterPhase.DELETING
        )
