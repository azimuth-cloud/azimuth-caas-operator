import unittest
from unittest import mock

from azimuth_caas_operator.models import registry
from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.utils import cluster


class TestAsyncUtils(unittest.IsolatedAsyncioTestCase):
    @mock.patch.object(cluster.LOG, "info")
    async def test_create_scheduled_delete_job_skips(self, mock_log):
        await cluster.create_scheduled_delete_job(
            "client", "name", "ns", "uid", "never"
        )
        mock_log.assert_called_once_with("Skipping scheduled delete.")

    @mock.patch.object(cluster.LOG, "info")
    async def test_create_scheduled_delete_job_skips_forever(self, mock_log):
        await cluster.create_scheduled_delete_job(
            "client", "name", "ns", "uid", "forever"
        )
        mock_log.assert_called_once_with("Skipping scheduled delete.")

    async def test_ensure_cluster_id_is_noop_when_id_exists(self):
        mock_client = mock.Mock()
        fake_cluster = cluster_crd.get_fake()
        await cluster.ensure_cluster_id(mock_client, fake_cluster)
        mock_client.api.assert_not_called()

    async def test_ensure_cluster_id_updates_id_when_not_set(self):
        mock_client = mock.Mock()
        mock_api = mock.AsyncMock()
        mock_client.api.return_value = mock_api
        mock_resource = mock.AsyncMock()
        mock_api.resource.return_value = mock_resource

        fake_cluster = cluster_crd.get_fake()
        fake_cluster.status.clusterID = None

        await cluster.ensure_cluster_id(mock_client, fake_cluster)
        self.assertEqual(fake_cluster.status.clusterID, fake_cluster.metadata.uid)

        mock_client.api.assert_called_once_with(registry.API_VERSION)
        mock_api.resource.assert_awaited_once_with("cluster")
        mock_resource.patch.assert_awaited_once_with(
            fake_cluster.metadata.name,
            {"status": {"clusterID": fake_cluster.metadata.uid}},
            namespace=fake_cluster.metadata.namespace
        )
