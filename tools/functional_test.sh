#!/bin/bash

set -eux

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

tox -e kopf &
until [ `kubectl get crds | grep cluster | wc -l` -gt 2 ]; do echo "wait for crds"; done

kubectl create -f $SCRIPT_DIR/test_cluster_type.yaml
kubectl create -f $SCRIPT_DIR/test_quick.yaml

kubectl wait --for=jsonpath='{.status.phase}'=Creating cluster quick-test
kubectl wait --for=jsonpath='{.status.phase}'=Ready cluster quick-test

kubectl delete -f $SCRIPT_DIR/test_quick.yam
kubectl wait --for=jsonpath='{.status.phase}'=Deleting cluster quick-test
kubectl wait --for=delete cluster quick-test

kill %1
