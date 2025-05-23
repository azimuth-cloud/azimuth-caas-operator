import unittest
from unittest import mock

import kopf
from easykube.rest.util import PropertyDict

from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.utils import lease


class TestLease(unittest.IsolatedAsyncioTestCase):
    @mock.patch.object(lease, "adopt_lease")
    async def test_ensure_lease_active_returns_dict(self, mock_adopt_lease):
        client = mock.Mock()
        cluster = cluster_crd.get_fake()
        mock_adopt_lease.return_value = {
            "status": {"phase": "Active", "sizeMap": {"m1.small": "reservation1"}}
        }

        result = await lease.ensure_lease_active(client, cluster)

        self.assertEqual(result, {"m1.small": "reservation1"})
        mock_adopt_lease.assert_awaited_once_with(client, cluster)

    @mock.patch.object(lease, "adopt_lease")
    async def test_ensure_lease_not_active_raises(self, mock_adopt_lease):
        client = mock.Mock()
        cluster = cluster_crd.get_fake()
        mock_adopt_lease.return_value = {
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
        self.assertEqual(10, ctx.exception.delay)

        mock_adopt_lease.assert_awaited_once_with(client, cluster)

    async def test_adopt_lease_no_patch_when_present(self):
        mock_client = mock.Mock()
        mock_client.api.return_value = mock_api = mock.AsyncMock()
        mock_api.resource.return_value = mock_resource = mock.AsyncMock()
        mock_resource.fetch.return_value = PropertyDict(
            {
                "metadata": {
                    "name": "test1",
                    "namespace": "ns1",
                    "finalizers": ["caas.azimuth.stackhpc.com"],
                    "ownerReferences": [
                        {
                            "apiVersion": "caas.azimuth.stackhpc.com/v1alpha1",
                            "kind": "Cluster",
                            "name": "test1",
                            "uid": "fakeuid1",
                            "blockOwnerDeletion": True,
                        }
                    ],
                }
            }
        )
        cluster = cluster_crd.get_fake()

        await lease.adopt_lease(mock_client, cluster)

        mock_resource.fetch.assert_awaited_once_with("test1", namespace="ns1")
        mock_resource.json_patch.assert_not_awaited()

    async def test_adopt_lease_patches_when_not_present(self):
        mock_client = mock.Mock()
        mock_client.api.return_value = mock_api = mock.AsyncMock()
        mock_api.resource.return_value = mock_resource = mock.AsyncMock()
        mock_resource.fetch.return_value = PropertyDict(
            {
                "metadata": {
                    "name": "test1",
                    "namespace": "ns1",
                },
            }
        )
        cluster = cluster_crd.get_fake()

        await lease.adopt_lease(mock_client, cluster)

        mock_resource.fetch.assert_awaited_once_with("test1", namespace="ns1")
        mock_resource.json_patch.assert_awaited_once_with(
            "test1",
            [
                {"op": "add", "path": "/metadata/finalizers", "value": []},
                {
                    "op": "add",
                    "path": "/metadata/finalizers/-",
                    "value": "caas.azimuth.stackhpc.com",
                },
                {"op": "add", "path": "/metadata/ownerReferences", "value": []},
                {
                    "op": "add",
                    "path": "/metadata/ownerReferences/-",
                    "value": {
                        "apiVersion": "caas.azimuth.stackhpc.com/v1alpha1",
                        "kind": "Cluster",
                        "name": "test1",
                        "uid": "fakeuid1",
                        "blockOwnerDeletion": True,
                    },
                },
            ],
            namespace="ns1",
        )

    async def test_release_lease_no_patch_when_not_present(self):
        mock_client = mock.Mock()
        mock_client.api.return_value = mock_api = mock.AsyncMock()
        mock_api.resource.return_value = mock_resource = mock.AsyncMock()
        mock_resource.fetch.return_value = PropertyDict(
            {
                "metadata": {
                    "name": "test1",
                    "namespace": "ns1",
                },
            }
        )
        cluster = cluster_crd.get_fake()

        await lease.release_lease(mock_client, cluster)

        mock_resource.patch.assert_not_awaited()

    async def test_release_lease_removes_finalizer_when_present(self):
        mock_client = mock.Mock()
        mock_client.api.return_value = mock_api = mock.AsyncMock()
        mock_api.resource.return_value = mock_resource = mock.AsyncMock()
        mock_resource.fetch.return_value = PropertyDict(
            {
                "metadata": {
                    "name": "test1",
                    "namespace": "ns1",
                    "finalizers": ["caas.azimuth.stackhpc.com"],
                },
            }
        )
        cluster = cluster_crd.get_fake()

        await lease.release_lease(mock_client, cluster)

        mock_resource.patch.assert_awaited_once_with(
            "test1", {"metadata": {"finalizers": []}}, namespace="ns1"
        )

    async def test_release_lease_preserves_other_finalizers(self):
        mock_client = mock.Mock()
        mock_client.api.return_value = mock_api = mock.AsyncMock()
        mock_api.resource.return_value = mock_resource = mock.AsyncMock()
        mock_resource.fetch.return_value = PropertyDict(
            {
                "metadata": {
                    "name": "test1",
                    "namespace": "ns1",
                    "finalizers": ["another-finalizer", "caas.azimuth.stackhpc.com"],
                },
            }
        )
        cluster = cluster_crd.get_fake()

        await lease.release_lease(mock_client, cluster)

        mock_resource.patch.assert_awaited_once_with(
            "test1",
            {"metadata": {"finalizers": ["another-finalizer"]}},
            namespace="ns1",
        )
