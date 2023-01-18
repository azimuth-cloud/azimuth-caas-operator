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
