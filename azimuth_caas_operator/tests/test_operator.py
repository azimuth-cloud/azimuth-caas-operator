import json
import unittest
from unittest import mock

from azimuth_caas_operator import operator


class AsyncIter:
    def __init__(self, items):
        self.items = items
        self.kwargs = None

    async def list(self, **kwargs):
        self.kwargs = kwargs
        for item in self.items:
            yield item


class TesOperator(unittest.IsolatedAsyncioTestCase):
    @mock.patch("azimuth_caas_operator.models.registry.get_crd_resources")
    @mock.patch.object(operator, "K8S_CLIENT", new_callable=mock.AsyncMock)
    async def test_startup_register_crds(self, mock_client, mock_crds):
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
        "azimuth_caas_operator.k8s.get_pod_resource", new_callable=mock.AsyncMock
    )
    async def test_get_pod_names_for_job(self, mock_pod):
        mock_iter = AsyncIter(
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
