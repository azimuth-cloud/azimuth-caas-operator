#!/bin/bash

set -ex

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

tox -e kopf &
sleep 10

until [ `kubectl get crds | grep cluster | wc -l` -gt 1 ]; do echo "wait for crds"; sleep 5; done
kubectl get crds

kubectl apply -f $SCRIPT_DIR/test_cluster_type.yaml
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
