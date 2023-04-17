#!/bin/bash

set -ex

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

tox -e kopf &
sleep 10

# add required secrets, not that they care used for this test
echo "foo" >clouds.yaml
kubectl create secret generic openstack --from-file=clouds.yaml
ssh-keygen -f id_rsa -P ""
kubectl create namespace azimuth-caas-operator
kubectl create secret generic azimuth-sshkey --from-file=id_rsa --from-file=id_rsa.pub -n azimuth-caas-operator

until [ `kubectl get crds | grep cluster | wc -l` -gt 1 ]; do echo "wait for crds"; sleep 5; done
kubectl get crds

kubectl apply -f $SCRIPT_DIR/test_cluster_type.yaml
until kubectl wait --for=jsonpath='{.status.phase}'=Available clustertype quick-test; do echo "wait for status to appear"; sleep 5; done
kubectl get clustertype quick-test -o yaml

# find the correct version a sub it into the test
cluster_version=$(kubectl get clustertype quick-test -ojsonpath='{.metadata.resourceVersion}')
sed -i "s/REPLACE_ME_VERSION/${cluster_version}/" tools/test_quick.yaml
kubectl create -f $SCRIPT_DIR/test_quick.yaml

until kubectl wait --for=jsonpath='{.status.phase}'=Creating cluster quick-test; do echo "wait for status to appear"; sleep 5; done

kubectl get cluster
kubectl get clustertype
kubectl get jobs
kubectl get pods

until kubectl wait --for=jsonpath='{.status.phase}'=Ready cluster quick-test; do echo "wait for created"; sleep 5; kubectl describe pods; done

kubectl get cluster
kubectl get clustertype
kubectl get jobs
kubectl get pods
kubectl get jobs -o yaml
kubectl get pods -o yaml

kubectl delete -f $SCRIPT_DIR/test_quick.yaml
sleep 10

kubectl get cluster
kill %1
