#!/bin/bash

set -ex

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# Install the CaaS operator from the chart we are about to ship
# Make sure to use the images that we just built
helm upgrade azimuth-caas-operator ./charts/operator \
  --dependency-update \
  --namespace azimuth-caas-operator \
  --create-namespace \
  --install \
  --wait \
  --timeout 10m \
  --set-string image.tag=${GITHUB_SHA::7} \
  --set-string config.ansibleRunnerImage.tag=${GITHUB_SHA::7} \
  --set-string ara.image.tag=${GITHUB_SHA::7} \
  --set-string config.consulUrl=fakeconsul

# add required secrets, not that they care used for this test
echo "foo" >clouds.yaml
kubectl create secret generic openstack --from-file=clouds.yaml || true
ssh-keygen -f id_rsa -P ""
kubectl create namespace azimuth-caas || true
kubectl create secret generic azimuth-sshkey --from-file=id_rsa --from-file=id_rsa.pub -n azimuth-caas || true

until [ `kubectl get crds | grep cluster | wc -l` -gt 1 ]; do echo "wait for crds"; sleep 5; done
kubectl get crds

kubectl apply -f $SCRIPT_DIR/test_cluster_type.yaml
sleep 5
kubectl get pods -n azimuth-caas-operator
kubectl logs -n azimuth-caas-operator deplyment/azimuth-caas-operator
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
# TODO: check app cred still exists

kubectl get cluster
kubectl get cluster -o yaml
