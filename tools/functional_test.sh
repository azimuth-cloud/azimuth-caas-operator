#!/bin/bash

set -ex

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

tox -e kopf &
sleep 10

# add required secrets, not that they care used for this test
echo "foo" >clouds.yaml
kubectl create secret generic openstack --from-file=clouds.yaml || true
ssh-keygen -f id_rsa -P ""
kubectl create namespace azimuth-caas || true
kubectl create secret generic azimuth-sshkey --from-file=id_rsa --from-file=id_rsa.pub -n azimuth-caas || true

until [ `kubectl get crds | grep cluster | wc -l` -gt 1 ]; do echo "wait for crds"; sleep 5; done
kubectl get crds

kubectl apply -f $SCRIPT_DIR/test_cluster_type.yaml
until kubectl wait --for=jsonpath='{.status.phase}'=Available clustertype quick-test; do echo "wait for status to appear"; sleep 5; done
kubectl get clustertype quick-test -o yaml

# find the correct version a sub it into the tests
cluster_version=$(kubectl get clustertype quick-test -ojsonpath='{.metadata.resourceVersion}')
sed -i "s/REPLACE_ME_VERSION/${cluster_version}/" tools/test_quick.yaml
kubectl create -f $SCRIPT_DIR/test_quick.yaml

sed -i "s/REPLACE_ME_VERSION/${cluster_version}/" tools/test_quick_delete_failure.yaml
kubectl create secret generic openstack2 --from-file=clouds.yaml || true
kubectl create -f $SCRIPT_DIR/test_quick_delete_failure.yaml

until kubectl wait --for=jsonpath='{.status.phase}'=Creating cluster quick-test; do echo "wait for status to appear"; sleep 2; done

kubectl get cluster
kubectl get clustertype
kubectl get jobs
kubectl get pods

until kubectl wait --for=jsonpath='{.status.phase}'=Ready cluster quick-test; do echo "wait for created"; sleep 2; kubectl describe pods; done

kubectl get cluster
kubectl get clustertype
kubectl get jobs
kubectl get pods

# kick off failed delete
until kubectl wait --for=jsonpath='{.status.phase}'=Ready cluster quick-test-fail-delete; do echo "wait for created"; sleep 2; done
kubectl delete -f $SCRIPT_DIR/test_quick_delete_failure.yaml --wait=false

# wait for delete we expect to work
kubectl delete -f $SCRIPT_DIR/test_quick.yaml

# look at the other cluster, test for a delete error
until kubectl wait --for=jsonpath='{.status.phase}'=Failed cluster quick-test-fail-delete; do echo "wait for delete error"; kubectl get jobs; sleep 2; done

kubectl get cluster
kill %1
