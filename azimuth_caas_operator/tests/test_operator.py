import unittest
from unittest import mock

import kopf

from azimuth_caas_operator import operator
from azimuth_caas_operator.models.v1alpha1 import cluster as cluster_crd
from azimuth_caas_operator.models.v1alpha1 import cluster_type as cluster_type_crd
from azimuth_caas_operator.utils import ansible_runner
from azimuth_caas_operator.utils import cluster as cluster_utils
from azimuth_caas_operator.utils import lease as lease_utils


class TestOperator(unittest.IsolatedAsyncioTestCase):
    def _generate_fake_crd(self, name):
        plural_name, api_group = name.split(".", maxsplit=1)
        return {
            "metadata": {
                "name": name,
            },
            "spec": {
                "group": api_group,
                "names": {
                    "plural": plural_name,
                },
                "versions": [
                    {
                        "name": "v1alpha1",
                        "storage": True,
                    },
                ],
            },
        }

    @mock.patch("azimuth_caas_operator.models.registry.get_crd_resources")
    @mock.patch("azimuth_caas_operator.utils.k8s.get_k8s_client")
    async def test_startup_register_crds(self, mock_get, mock_crds):
        fake_crd1 = self._generate_fake_crd("crd1.fake.io")
        fake_crd2 = self._generate_fake_crd("crd2.fake.io")

        mock_client = mock.AsyncMock()
        mock_get.return_value = mock_client
        mock_crds.return_value = [fake_crd1, fake_crd2]

        mock_settings = mock.Mock()

        await operator.startup(mock_settings)

        # Test that the CRDs were applied
        mock_client.apply_object.assert_has_awaits(
            [mock.call(fake_crd1, force=True), mock.call(fake_crd2, force=True)]
        )
        # Test that the APIs were checked
        mock_client.get.assert_has_awaits(
            [
                mock.call("/apis/fake.io/v1alpha1/crd1"),
                mock.call("/apis/fake.io/v1alpha1/crd2"),
            ]
        )

    @mock.patch.object(operator, "K8S_CLIENT", new_callable=mock.AsyncMock)
    async def test_cleanup_calls_aclose(self, mock_client):
        await operator.cleanup()
        mock_client.aclose.assert_awaited_once_with()

    @mock.patch.object(operator, "_update_cluster_type")
    @mock.patch.object(operator, "_fetch_ui_meta_from_url")
    async def test_cluster_type_create_success(self, mock_fetch, mock_update):
        fake_meta = {}
        mock_fetch.return_value = fake_meta

        # TODO(johngarbutt): probably need to actually fetch the ui meta!
        await operator.cluster_type_create(
            cluster_type_crd.get_fake_dict(), "type1", "ns", {}
        )
        mock_fetch.assert_awaited_once_with("https://url1/")
        mock_update.assert_awaited_once_with(
            operator.K8S_CLIENT,
            "type1",
            "ns",
            cluster_type_crd.ClusterTypeStatus(
                phase=cluster_type_crd.ClusterTypePhase.AVAILABLE, uiMeta=fake_meta
            ),
        )

    @mock.patch.object(lease_utils, "adopt_lease")
    @mock.patch.object(cluster_utils, "adopt_identity_platform")
    @mock.patch.object(cluster_utils, "ensure_cluster_id")
    async def test_cluster_resume(
        self, mock_ensure_cluster_id, mock_adopt_identity_platform, mock_adopt_lease
    ):
        fake_body = cluster_crd.get_fake_dict()
        fake_cluster = cluster_crd.Cluster(**fake_body)
        await operator.cluster_resume(fake_body, "cluster1", "ns")
        mock_ensure_cluster_id.assert_awaited_once_with(
            operator.K8S_CLIENT, fake_cluster
        )
        mock_adopt_identity_platform.assert_awaited_once_with(
            operator.K8S_CLIENT, fake_cluster
        )
        mock_adopt_lease.assert_awaited_once_with(operator.K8S_CLIENT, fake_cluster)

    @mock.patch.object(cluster_utils, "update_cluster_flavors")
    @mock.patch.object(lease_utils, "ensure_lease_active")
    @mock.patch.object(cluster_utils, "adopt_identity_platform")
    @mock.patch.object(cluster_utils, "ensure_cluster_id")
    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "start_job")
    @mock.patch.object(ansible_runner, "get_create_job_for_cluster")
    async def test_cluster_create_creates_job_and_raise(
        self,
        mock_get_jobs,
        mock_start,
        mock_update,
        mock_ensure_cluster_id,
        mock_adopt_identity_platform,
        mock_ensure_lease,
        mock_update_flavors,
    ):
        # testing the zero jobs case
        mock_get_jobs.return_value = None
        fake_body = cluster_crd.get_fake_dict()
        mock_ensure_lease.return_value = {"flavor_a": "flavor_reserved"}

        with self.assertRaises(kopf.TemporaryError) as ctx:
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
            operator.K8S_CLIENT,
            "cluster1",
            "ns",
            cluster_crd.ClusterPhase.CREATING,
            extra_vars={"foo": "bar", "very_random_int": 42, "nested": {"baz": "bob"}},
        )
        mock_ensure_cluster_id.assert_awaited_once_with(operator.K8S_CLIENT, cluster)
        mock_adopt_identity_platform.assert_awaited_once_with(
            operator.K8S_CLIENT, cluster
        )
        mock_ensure_lease.assert_awaited_once_with(operator.K8S_CLIENT, cluster)
        mock_update_flavors.assert_awaited_once_with(
            operator.K8S_CLIENT, cluster, {"flavor_a": "flavor_reserved"}
        )

    @mock.patch.object(cluster_utils, "update_cluster_flavors")
    @mock.patch.object(lease_utils, "ensure_lease_active")
    @mock.patch.object(cluster_utils, "adopt_identity_platform")
    @mock.patch.object(cluster_utils, "ensure_cluster_id")
    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "get_job_completed_state")
    @mock.patch.object(ansible_runner, "get_outputs_from_job")
    @mock.patch.object(ansible_runner, "get_create_job_for_cluster")
    async def test_cluster_create_spots_successful_job(
        self,
        mock_get_jobs,
        mock_outputs,
        mock_success,
        mock_update,
        mock_ensure_cluster_id,
        mock_adopt_identity_platform,
        mock_ensure_lease,
        mock_update_flavors,
    ):
        mock_get_jobs.return_value = "fakejob"
        fake_body = cluster_crd.get_fake_dict()
        mock_outputs.return_value = {"asdf": 42}
        mock_success.return_value = True

        await operator.cluster_create(fake_body, "cluster1", "ns", {})

        cluster = cluster_crd.Cluster(**fake_body)
        mock_ensure_cluster_id.assert_awaited_once_with(operator.K8S_CLIENT, cluster)
        mock_adopt_identity_platform.assert_awaited_once_with(
            operator.K8S_CLIENT, cluster
        )
        mock_update.assert_awaited_once_with(
            operator.K8S_CLIENT,
            "cluster1",
            "ns",
            cluster_crd.ClusterPhase.READY,
            outputs={"asdf": 42},
        )
        mock_outputs.assert_awaited_once_with(operator.K8S_CLIENT, "fakejob")
        mock_get_jobs.assert_awaited_once_with(operator.K8S_CLIENT, "cluster1", "ns")
        mock_success.assert_called_once_with("fakejob")
        mock_ensure_lease.assert_awaited_once_with(operator.K8S_CLIENT, cluster)
        mock_update_flavors.assert_awaited_once_with(
            operator.K8S_CLIENT, cluster, mock.ANY
        )

    @mock.patch.object(lease_utils, "ensure_lease_active")
    @mock.patch.object(cluster_utils, "adopt_identity_platform")
    @mock.patch.object(cluster_utils, "ensure_cluster_id")
    @mock.patch.object(ansible_runner, "is_create_job_running")
    async def test_cluster_update_waits_for_create_job_to_complete(
        self,
        mock_create_job,
        mock_ensure_cluster_id,
        mock_adopt_identity_platform,
        mock_ensure_lease,
    ):
        mock_create_job.return_value = True
        fake_body = cluster_crd.get_fake_dict()

        with self.assertRaises(kopf.TemporaryError) as ctx:
            await operator.cluster_update(fake_body, "cluster1", "ns", {})

        self.assertEqual(
            "Can't process update until create completed for cluster1 in ns",
            str(ctx.exception),
        )
        cluster = cluster_crd.Cluster(**fake_body)
        mock_ensure_cluster_id.assert_awaited_once_with(operator.K8S_CLIENT, cluster)
        mock_create_job.assert_awaited_once_with(operator.K8S_CLIENT, "cluster1", "ns")
        mock_adopt_identity_platform.assert_awaited_once_with(
            operator.K8S_CLIENT, cluster
        )
        mock_ensure_lease.assert_awaited_once_with(operator.K8S_CLIENT, cluster)

    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(lease_utils, "ensure_lease_active")
    @mock.patch.object(cluster_utils, "adopt_identity_platform")
    @mock.patch.object(cluster_utils, "ensure_cluster_id")
    @mock.patch.object(ansible_runner, "is_create_job_running")
    async def test_cluster_create_error_on_lease_error(
        self,
        mock_create_job,
        mock_ensure_cluster_id,
        mock_adopt_identity_platform,
        mock_ensure_lease,
        mock_update,
    ):
        mock_create_job.return_value = True
        fake_body = cluster_crd.get_fake_dict()
        mock_ensure_lease.side_effect = lease_utils.LeaseInError(
            "external service enforcement filter denied the request"
        )

        with self.assertRaises(kopf.TemporaryError) as ctx:
            await operator.cluster_create(fake_body, "cluster1", "ns", {})

        self.assertEqual(
            "Lease is in Error state for cluster1 in ns",
            str(ctx.exception),
        )
        cluster = cluster_crd.Cluster(**fake_body)
        mock_ensure_cluster_id.assert_awaited_once_with(operator.K8S_CLIENT, cluster)
        mock_adopt_identity_platform.assert_awaited_once_with(
            operator.K8S_CLIENT, cluster
        )
        mock_create_job.assert_not_called()
        mock_ensure_lease.assert_awaited_once_with(operator.K8S_CLIENT, cluster)
        mock_update.assert_awaited_once_with(
            operator.K8S_CLIENT,
            "cluster1",
            "ns",
            cluster_crd.ClusterPhase.FAILED,
            error="Not enough credits to create platform",
        )

    @mock.patch.object(lease_utils, "ensure_lease_active")
    @mock.patch.object(cluster_utils, "adopt_identity_platform")
    @mock.patch.object(cluster_utils, "ensure_cluster_id")
    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "get_job_completed_state")
    @mock.patch.object(ansible_runner, "get_update_job_for_cluster")
    @mock.patch.object(ansible_runner, "is_create_job_running")
    async def test_cluster_update_waits_for_update_job_to_complete(
        self,
        mock_create_job,
        mock_update_job,
        mock_completed,
        mock_update,
        mock_ensure_cluster_id,
        mock_adopt_identity_platform,
        mock_ensure_lease,
    ):
        mock_create_job.return_value = False
        mock_update_job.return_value = "update-job"
        mock_completed.return_value = None

        fake_body = cluster_crd.get_fake_dict()

        with self.assertRaises(kopf.TemporaryError) as ctx:
            await operator.cluster_update(fake_body, "cluster1", "ns", {})

        self.assertEqual(
            "Waiting for update job to complete for cluster1 in ns",
            str(ctx.exception),
        )
        cluster = cluster_crd.Cluster(**fake_body)
        mock_ensure_cluster_id.assert_awaited_once_with(operator.K8S_CLIENT, cluster)
        mock_adopt_identity_platform.assert_awaited_once_with(
            operator.K8S_CLIENT, cluster
        )
        mock_update.assert_awaited_once_with(
            operator.K8S_CLIENT,
            "cluster1",
            "ns",
            cluster_crd.ClusterPhase.CONFIG,
        )
        mock_update_job.assert_awaited_once_with(operator.K8S_CLIENT, "cluster1", "ns")
        mock_completed.assert_called_once_with("update-job")
        mock_ensure_lease.assert_awaited_once_with(operator.K8S_CLIENT, cluster)

    @mock.patch.object(lease_utils, "ensure_lease_active")
    @mock.patch.object(cluster_utils, "adopt_identity_platform")
    @mock.patch.object(cluster_utils, "ensure_cluster_id")
    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "unlabel_job")
    @mock.patch.object(ansible_runner, "get_outputs_from_job")
    @mock.patch.object(ansible_runner, "get_job_completed_state")
    @mock.patch.object(ansible_runner, "get_update_job_for_cluster")
    @mock.patch.object(ansible_runner, "is_create_job_running")
    async def test_cluster_update_spots_job_success(
        self,
        mock_create_job,
        mock_update_job,
        mock_completed,
        mock_outputs,
        mock_unlabel,
        mock_update,
        mock_ensure_cluster_id,
        mock_adopt_identity_platform,
        mock_ensure_lease,
    ):
        mock_create_job.return_value = False
        mock_update_job.return_value = "update-job"
        mock_completed.return_value = True
        mock_outputs.return_value = {"asdf": 42}

        fake_body = cluster_crd.get_fake_dict()

        await operator.cluster_update(fake_body, "cluster1", "ns", {})

        cluster = cluster_crd.Cluster(**fake_body)
        mock_ensure_cluster_id.assert_awaited_once_with(operator.K8S_CLIENT, cluster)
        mock_adopt_identity_platform.assert_awaited_once_with(
            operator.K8S_CLIENT, cluster
        )
        mock_update.assert_awaited_once_with(
            operator.K8S_CLIENT,
            "cluster1",
            "ns",
            cluster_crd.ClusterPhase.READY,
            outputs={"asdf": 42},
        )
        mock_outputs.assert_awaited_once_with(operator.K8S_CLIENT, "update-job")
        mock_update_job.assert_awaited_once_with(operator.K8S_CLIENT, "cluster1", "ns")
        mock_completed.assert_called_once_with("update-job")
        mock_unlabel.assert_awaited_once_with(operator.K8S_CLIENT, "update-job")
        mock_ensure_lease.assert_awaited_once_with(operator.K8S_CLIENT, cluster)

    @mock.patch.object(lease_utils, "ensure_lease_active")
    @mock.patch.object(cluster_utils, "adopt_identity_platform")
    @mock.patch.object(cluster_utils, "ensure_cluster_id")
    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "unlabel_job")
    @mock.patch.object(ansible_runner, "get_job_error_message")
    @mock.patch.object(ansible_runner, "get_outputs_from_job")
    @mock.patch.object(ansible_runner, "get_job_completed_state")
    @mock.patch.object(ansible_runner, "get_update_job_for_cluster")
    @mock.patch.object(ansible_runner, "is_create_job_running")
    async def test_cluster_update_spots_job_failure(
        self,
        mock_create_job,
        mock_update_job,
        mock_completed,
        mock_outputs,
        mock_error,
        mock_unlabel,
        mock_update,
        mock_ensure_cluster_id,
        mock_adopt_identity_platform,
        mock_ensure_lease,
    ):
        mock_create_job.return_value = False
        mock_update_job.return_value = "update-job"
        mock_completed.return_value = False
        mock_outputs.return_value = {"asdf": 42}
        mock_error.return_value = "oops"

        fake_body = cluster_crd.get_fake_dict()

        await operator.cluster_update(fake_body, "cluster1", "ns", {})

        cluster = cluster_crd.Cluster(**fake_body)
        mock_ensure_cluster_id.assert_awaited_once_with(operator.K8S_CLIENT, cluster)
        mock_adopt_identity_platform.assert_awaited_once_with(
            operator.K8S_CLIENT, cluster
        )
        mock_update.assert_awaited_once_with(
            operator.K8S_CLIENT,
            "cluster1",
            "ns",
            cluster_crd.ClusterPhase.FAILED,
            error="Failed to update the platform. To retry please click patch. "
            "Possible reason for the failure was: oops",
            outputs={"asdf": 42},
        )
        mock_update_job.assert_awaited_once_with(operator.K8S_CLIENT, "cluster1", "ns")
        mock_completed.assert_called_once_with("update-job")
        mock_unlabel.assert_awaited_once_with(operator.K8S_CLIENT, "update-job")
        mock_ensure_lease.assert_awaited_once_with(operator.K8S_CLIENT, cluster)

    @mock.patch.object(lease_utils, "ensure_lease_active")
    @mock.patch.object(cluster_utils, "adopt_identity_platform")
    @mock.patch.object(cluster_utils, "ensure_cluster_id")
    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "start_job")
    @mock.patch.object(ansible_runner, "get_update_job_for_cluster")
    @mock.patch.object(ansible_runner, "is_create_job_running")
    async def test_cluster_update_creates_update_job_and_raise(
        self,
        mock_create_job,
        mock_update_job,
        mock_start,
        mock_update,
        mock_ensure_cluster_id,
        mock_adopt_identity_platform,
        mock_ensure_lease,
    ):
        mock_create_job.return_value = False
        mock_update_job.return_value = None

        fake_body = cluster_crd.get_fake_dict()
        fake_cluster = cluster_crd.Cluster(**fake_body)

        with self.assertRaises(kopf.TemporaryError) as ctx:
            await operator.cluster_update(fake_body, "cluster1", "ns", {})

        self.assertEqual(
            "Need to wait for update job to complete for cluster1 in ns",
            str(ctx.exception),
        )

        mock_ensure_cluster_id.assert_awaited_once_with(
            operator.K8S_CLIENT, fake_cluster
        )
        mock_adopt_identity_platform.assert_awaited_once_with(
            operator.K8S_CLIENT, fake_cluster
        )
        mock_start.assert_awaited_once_with(
            operator.K8S_CLIENT, fake_cluster, "ns", update=True
        )
        mock_update.assert_awaited_once_with(
            operator.K8S_CLIENT,
            "cluster1",
            "ns",
            cluster_crd.ClusterPhase.CONFIG,
            extra_vars=fake_cluster.spec.extraVars,
        )
        mock_update_job.assert_awaited_once_with(operator.K8S_CLIENT, "cluster1", "ns")
        mock_ensure_lease.assert_awaited_once_with(operator.K8S_CLIENT, fake_cluster)

    @mock.patch.object(cluster_utils, "update_cluster_flavors")
    @mock.patch.object(lease_utils, "ensure_lease_active")
    @mock.patch.object(cluster_utils, "adopt_identity_platform")
    @mock.patch.object(cluster_utils, "ensure_cluster_id")
    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "get_outputs_from_job")
    @mock.patch.object(ansible_runner, "get_job_error_message")
    @mock.patch.object(ansible_runner, "get_job_completed_state")
    @mock.patch.object(ansible_runner, "get_create_job_for_cluster")
    async def test_cluster_create_raise_on_failed_jobs(
        self,
        mock_get_jobs,
        mock_success,
        mock_error,
        mock_outputs,
        mock_update,
        mock_ensure_cluster_id,
        mock_adopt_identity_platform,
        mock_ensure_lease,
        mock_update_flavors,
    ):
        # TODO(johngarbutt): should generate a working fake job list!
        mock_get_jobs.return_value = "fakejob"
        mock_success.return_value = False
        fake_body = cluster_crd.get_fake_dict()
        mock_error.return_value = "oops"
        mock_outputs.return_value = {"asdf": 42}

        await operator.cluster_create(fake_body, "cluster1", "ns", {})

        cluster = cluster_crd.Cluster(**fake_body)
        mock_ensure_cluster_id.assert_awaited_once_with(operator.K8S_CLIENT, cluster)
        mock_adopt_identity_platform.assert_awaited_once_with(
            operator.K8S_CLIENT, cluster
        )
        mock_update.assert_awaited_once_with(
            operator.K8S_CLIENT,
            "cluster1",
            "ns",
            cluster_crd.ClusterPhase.FAILED,
            error="Failed to create platform. "
            "To retry please click patch. "
            "Possible reason for the failure was: oops",
            outputs={"asdf": 42},
        )
        mock_get_jobs.assert_awaited_once_with(operator.K8S_CLIENT, "cluster1", "ns")
        mock_success.assert_called_once_with("fakejob")
        mock_outputs.assert_awaited_once_with(operator.K8S_CLIENT, "fakejob")
        mock_error.assert_awaited_once_with(operator.K8S_CLIENT, "fakejob")
        mock_ensure_lease.assert_awaited_once_with(operator.K8S_CLIENT, cluster)
        mock_update_flavors.assert_awaited_once_with(
            operator.K8S_CLIENT, cluster, mock.ANY
        )

    @mock.patch.object(cluster_utils, "update_cluster_flavors")
    @mock.patch.object(lease_utils, "ensure_lease_active")
    @mock.patch.object(cluster_utils, "adopt_identity_platform")
    @mock.patch.object(cluster_utils, "ensure_cluster_id")
    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "get_job_completed_state")
    @mock.patch.object(ansible_runner, "get_create_job_for_cluster")
    async def test_cluster_create_waits_for_job_to_complete(
        self,
        mock_get_jobs,
        mock_success,
        mock_update,
        mock_ensure_cluster_id,
        mock_adopt_identity_platform,
        mock_ensure_lease,
        mock_update_flavors,
    ):
        mock_get_jobs.return_value = "fakejob"
        mock_success.return_value = None
        fake_body = cluster_crd.get_fake_dict()

        with self.assertRaises(kopf.TemporaryError) as ctx:
            await operator.cluster_create(fake_body, "cluster1", "ns", {})

        self.assertEqual(
            "Waiting for create job to complete for cluster1 in ns", str(ctx.exception)
        )
        cluster = cluster_crd.Cluster(**fake_body)
        mock_ensure_cluster_id.assert_awaited_once_with(operator.K8S_CLIENT, cluster)
        mock_adopt_identity_platform.assert_awaited_once_with(
            operator.K8S_CLIENT, cluster
        )
        mock_update.assert_awaited_once_with(
            operator.K8S_CLIENT, "cluster1", "ns", cluster_crd.ClusterPhase.CREATING
        )
        mock_ensure_lease.assert_awaited_once_with(operator.K8S_CLIENT, cluster)
        mock_update_flavors.assert_awaited_once_with(
            operator.K8S_CLIENT, cluster, mock.ANY
        )

    @mock.patch.object(cluster_utils, "ensure_cluster_id")
    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "start_job")
    @mock.patch.object(ansible_runner, "get_delete_job_for_cluster")
    @mock.patch.object(ansible_runner, "ensure_create_jobs_finished")
    async def test_cluster_delete_creates_job_and_raises(
        self,
        mock_create_finsish,
        mock_get_jobs,
        mock_start,
        mock_update,
        mock_ensure_cluster_id,
    ):
        # testing the zero jobs case
        mock_get_jobs.return_value = None
        fake_body = cluster_crd.get_fake_dict()

        with self.assertRaises(kopf.TemporaryError) as ctx:
            await operator.cluster_delete(fake_body, "cluster1", "ns", {})

        self.assertEqual(
            "Wait for delete job to complete for cluster1 in ns", str(ctx.exception)
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
        mock_ensure_cluster_id.assert_awaited_once_with(operator.K8S_CLIENT, cluster)

    @mock.patch.object(ansible_runner, "purge_job_resources")
    @mock.patch.object(lease_utils, "release_lease")
    @mock.patch.object(ansible_runner, "delete_secret")
    @mock.patch.object(ansible_runner, "get_job_completed_state")
    @mock.patch.object(cluster_utils, "ensure_cluster_id")
    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "start_job")
    @mock.patch.object(ansible_runner, "get_delete_job_for_cluster")
    @mock.patch.object(ansible_runner, "ensure_create_jobs_finished")
    async def test_cluster_delete_finishes(
        self,
        mock_create_finsish,
        mock_get_jobs,
        mock_start,
        mock_update,
        mock_ensure_cluster_id,
        mock_get_job_state,
        mock_delete_secret,
        mock_release_lease,
        mock_purge_job_resources,
    ):
        mock_get_jobs.return_value = "fakejob"
        mock_get_job_state.return_value = True
        fake_body = cluster_crd.get_fake_dict()
        del fake_body["spec"]["leaseName"]

        await operator.cluster_delete(fake_body, "cluster1", "ns", {})

        mock_create_finsish.assert_awaited_once_with(
            operator.K8S_CLIENT, "cluster1", "ns"
        )
        mock_get_jobs.assert_awaited_once_with(operator.K8S_CLIENT, "cluster1", "ns")
        cluster = cluster_crd.Cluster(**fake_body)
        mock_start.assert_not_called()
        mock_update.assert_not_called()
        mock_ensure_cluster_id.assert_awaited_once_with(operator.K8S_CLIENT, cluster)
        mock_delete_secret.assert_awaited_once_with(operator.K8S_CLIENT, cluster, "ns")
        mock_release_lease.assert_not_called()
        mock_purge_job_resources.assert_awaited_once_with(operator.K8S_CLIENT, cluster)

    @mock.patch.object(ansible_runner, "get_job_completed_state")
    @mock.patch.object(cluster_utils, "ensure_cluster_id")
    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "start_job")
    @mock.patch.object(ansible_runner, "get_delete_job_for_cluster")
    @mock.patch.object(ansible_runner, "ensure_create_jobs_finished")
    async def test_cluster_delete_waits_on_running_jobs(
        self,
        mock_create_finsish,
        mock_get_jobs,
        mock_start,
        mock_update,
        mock_ensure_cluster_id,
        mock_get_job_state,
    ):
        mock_get_jobs.return_value = "fakejob"
        mock_get_job_state.return_value = None
        fake_body = cluster_crd.get_fake_dict()

        with self.assertRaises(kopf.TemporaryError) as ctx:
            await operator.cluster_delete(fake_body, "cluster1", "ns", {})

        self.assertEqual(
            "Wait for delete job to complete for cluster1 in ns", str(ctx.exception)
        )
        mock_create_finsish.assert_awaited_once_with(
            operator.K8S_CLIENT, "cluster1", "ns"
        )
        mock_get_jobs.assert_awaited_once_with(operator.K8S_CLIENT, "cluster1", "ns")
        cluster = cluster_crd.Cluster(**fake_body)
        mock_start.assert_not_called()
        mock_update.assert_awaited_once_with(
            operator.K8S_CLIENT, "cluster1", "ns", cluster_crd.ClusterPhase.DELETING
        )
        mock_ensure_cluster_id.assert_awaited_once_with(operator.K8S_CLIENT, cluster)

    @mock.patch.object(ansible_runner, "get_failed_delete_jobs_for_cluster")
    @mock.patch.object(ansible_runner, "unlabel_delete_job")
    @mock.patch.object(ansible_runner, "get_job_error_message")
    @mock.patch.object(ansible_runner, "get_job_completed_state")
    @mock.patch.object(cluster_utils, "ensure_cluster_id")
    @mock.patch.object(cluster_utils, "update_cluster")
    @mock.patch.object(ansible_runner, "start_job")
    @mock.patch.object(ansible_runner, "get_delete_job_for_cluster")
    @mock.patch.object(ansible_runner, "ensure_create_jobs_finished")
    async def test_cluster_delete_trigger_retry_on_error(
        self,
        mock_create_finsish,
        mock_get_jobs,
        mock_start,
        mock_update,
        mock_ensure_cluster_id,
        mock_get_job_state,
        mock_get_error,
        mock_unlabel_delete_job,
        mock_failed_jobs,
    ):
        mock_get_jobs.return_value = "fakejob"
        mock_get_job_state.return_value = False
        mock_get_error.return_value = "Problem with job."
        fake_body = cluster_crd.get_fake_dict()
        mock_failed_jobs.return_value = ["failedjob1", "failedjob2"]

        with self.assertRaises(kopf.TemporaryError) as ctx:
            await operator.cluster_delete(fake_body, "cluster1", "ns", {})

        self.assertEqual(
            "Delete job failed for cluster1 in ns retrying in 120 seconds "
            "because: Problem with job.",
            str(ctx.exception),
        )
        mock_create_finsish.assert_awaited_once_with(
            operator.K8S_CLIENT, "cluster1", "ns"
        )
        mock_get_jobs.assert_awaited_once_with(operator.K8S_CLIENT, "cluster1", "ns")
        cluster = cluster_crd.Cluster(**fake_body)
        mock_start.assert_not_called()
        mock_update.assert_awaited_once_with(
            operator.K8S_CLIENT,
            "cluster1",
            "ns",
            cluster_crd.ClusterPhase.DELETING,
            error="Failure when trying to delete platform. "
            "Possible reason for the failure was: Problem with job.",
        )
        mock_ensure_cluster_id.assert_awaited_once_with(operator.K8S_CLIENT, cluster)
        mock_unlabel_delete_job.assert_awaited_once_with(operator.K8S_CLIENT, "fakejob")
        mock_failed_jobs.assert_awaited_once_with(operator.K8S_CLIENT, "cluster1", "ns")

    @mock.patch("aiohttp.ClientSession.get")
    async def test_fetch_ui_meta_from_url_success(self, mock_get):
        mock_response = mock.MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.text = mock.AsyncMock()
        mock_response.text.return_value = """
name: "quicktest"
label: "Quick Test"
description: Very quick test
logo: https://logo1

requires_ssh_key: false

parameters:
  - name: appliance_lifetime_hrs
    label: "Select appliance lifetime (hrs)"
    description: The appliance will be deleted after this time
    immutable: true
    kind: choice
    default: 12
    options:
      choices:
        - 1
        - 8
        - 12

  - name: cluster_volume_size
    label: "Data volume size (GB)"
    description: The data volume will be available at `/data`.
    kind: integer
    default: 10
    immutable: true

usage_template: 
    available using the [Monitoring service]({{ monitoring.url }}).

services:
  - name: webconsole
    label: Web console
    icon_url: https://icon2
"""

        mock_get.return_value.__aenter__.return_value = mock_response

        result = await operator._fetch_ui_meta_from_url("url")
        self.assertEqual(
            {
                "name": "quicktest",
                "label": "Quick Test",
                "description": "Very quick test",
                "logo": "https://logo1",
                "requires_ssh_key": False,
                "parameters": [
                    {
                        "name": "appliance_lifetime_hrs",
                        "label": "Select appliance lifetime (hrs)",
                        "description": "The appliance will be deleted after this time",
                        "immutable": True,
                        "kind": "choice",
                        "default": 12,
                        "options": {
                            "choices": [1, 8, 12],
                        },
                    },
                    {
                        "name": "cluster_volume_size",
                        "label": "Data volume size (GB)",
                        "description": "The data volume will be available at `/data`.",
                        "kind": "integer",
                        "default": 10,
                        "immutable": True,
                    },
                ],
                "usage_template": (
                    "available using the [Monitoring service]({{ monitoring.url }})."
                ),
                "services": [
                    {
                        "name": "webconsole",
                        "label": "Web console",
                        "icon_url": "https://icon2",
                    },
                ],
            },
            result,
        )
