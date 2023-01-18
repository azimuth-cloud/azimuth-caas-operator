import unittest
from unittest import mock

from azimuth_caas_operator import operator


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
