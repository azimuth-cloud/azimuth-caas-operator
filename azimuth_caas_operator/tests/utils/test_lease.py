import unittest
from unittest import mock

import kopf

from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.utils import lease


class TestLease(unittest.IsolatedAsyncioTestCase):
    @mock.patch.object(lease, "_patch_finalizers")
    @mock.patch.object(lease, "_get_lease")
    async def test_ensure_lease_active_returns_dict(
        self, mock_get_lease, mock_patch_finalizers
    ):
        client = mock.Mock()
        cluster = cluster_crd.get_fake()
        mock_get_lease.return_value = {
            "status": {"phase": "Active", "sizeMap": {"m1.small": "reservation1"}}
        }

        result = await lease.ensure_lease_active(client, cluster)

        self.assertEqual(result, {"m1.small": "reservation1"})
        mock_get_lease.assert_awaited_once_with(client, cluster)
        mock_patch_finalizers.assert_awaited_once_with(
            client,
            cluster.spec.leaseName,
            cluster.metadata.namespace,
            ["caas.azimuth.stackhpc.com"],
        )

    @mock.patch.object(lease, "_patch_finalizers")
    @mock.patch.object(lease, "_get_lease")
    async def test_ensure_lease_not_active_raises(
        self, mock_get_lease, mock_patch_finalizers
    ):
        client = mock.Mock()
        cluster = cluster_crd.get_fake()
        mock_get_lease.return_value = {
            "status": {"phase": "asdf"},
            "spec": {"startTime": "2021-01-01T00:00:00"},
            "metadata": {"finalizers": ["caas.azimuth.stackhpc.com"]},
        }

        with self.assertRaises(kopf.TemporaryError) as ctx:
            await lease.ensure_lease_active(client, cluster)

        self.assertEqual(
            "Lease test1 is not active.",
            str(ctx.exception),
        )
        self.assertEqual(60, ctx.exception.delay)

        mock_get_lease.assert_awaited_once_with(client, cluster)
        mock_patch_finalizers.assert_not_called()

    @mock.patch.object(lease, "_patch_finalizers")
    @mock.patch.object(lease, "_get_lease")
    async def test_drop_lease_finalizer(self, mock_get_lease, mock_patch_finalizers):
        client = mock.Mock()
        cluster = cluster_crd.get_fake()
        mock_get_lease.return_value = {
            "status": {"phase": "asdf"},
            "spec": {"startTime": "2021-01-01T00:00:00"},
            "metadata": {"finalizers": ["caas.azimuth.stackhpc.com", "abc"]},
        }

        await lease.drop_lease_finalizer(client, cluster)

        mock_get_lease.assert_awaited_once_with(client, cluster)
        mock_patch_finalizers.assert_awaited_once_with(
            client,
            cluster.spec.leaseName,
            cluster.metadata.namespace,
            ["abc"],
        )
