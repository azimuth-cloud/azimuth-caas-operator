# azimuth-caas-operator
![tox](https://github.com/stackhpc/azimuth-caas-operator/actions/workflows/tox.yaml/badge.svg?branch=main)

K8s operator to create clusters using K8s CRDs

This is still very much work in progress!!

## Run unit tests

We tox, and uses python3.9:

    pip install tox
    tox

## Test opertor locally

You can test it with tox too:

    minkube start
    minikube addons enable ingress

    helm repo add hashicorp https://helm.releases.hashicorp.com
    helm install consul hashicorp/consul --set global.name=consul \
        --create-namespace --namespace consul

    helm repo add zenith https://stackhpc.github.io/zenith
    helm upgrade zenith zenith/zenith-server \
      --version 0.1.0-dev.0.main.163 -i -f tools/zenith_values.yaml \
      --create-namespace --namespace zenith

    kubectl create secret generic openstack --from-file=clouds.yaml
    ssh-keygen -f id_rsa -P ""
    kubectl create secret generic azimuth-sshkey --from-file=id_rsa --from-file=id_rsa.pub

    tox -e kopf &
    kubctl apply -f tools/test_cluster_type.yaml
    kubctl apply -f tools/test_cluster.yaml

    kubectl wait --for=jsonpath='{.status.phase}'=Creating cluster test1
    kubectl wait --for=jsonpath='{.status.phase}'=Ready cluster test1
    kubectl wait --for=jsonpath='{.status.phase}'=Failed cluster test1
    kubctl delete -f tools/test_cluster.yaml
