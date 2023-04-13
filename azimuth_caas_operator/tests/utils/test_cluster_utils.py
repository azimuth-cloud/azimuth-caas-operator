import unittest
from unittest import mock

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
