# azimuth-caas-operator
![tox](https://github.com/stackhpc/azimuth-caas-operator/actions/workflows/tox.yaml/badge.svg?branch=main)
![tox](https://github.com/stackhpc/azimuth-caas-operator/actions/workflows/functional.yaml/badge.svg?branch=main)

K8s operator to create clusters using K8s CRDs

This is still very much work in progress!!

## Installation of Operator

The `azimuth-caas-operator` can be installed using [Helm](https://helm.sh):

```sh
helm repo add azimuth-caas-operator https://stackhpc.github.io/azimuth-caas-operator

# check for the latest versions
helm repo update
helm search repo azimuth-caas-operator --devel

# Use the most recent chart
helm upgrade \
  azimuth-caas-operator \
  azimuth-caas-operator/azimuth-caas-operator \
  -n azimuth-caas-operator \
  -i \
  --version ">=0.1.0"
```

Once the operator is up and running you will then need to create
CRDs to configure the appropriate Cluster templates.
For testing you can create a cluster and run ansible jobs,
without actually creating any openstack infrastructure,
try this:

```sh
# check crds have been created by the operator
kubectl get crds

# add the test cluster type
kubectl apply -f tools/test_cluster_type.yaml
kubectl wait --for=jsonpath='{.status.phase}'=Available clustertype quick-test
kubectl get clustertype quick-test -o yaml
```

To try this manually without using the Azimuth UI,
you can create a test cluster of the above by running:

```sh
# create shared deploy ssh key
ssh-keygen -f id_rsa -P ""
kubectl create secret generic azimuth-sshkey --from-file=id_rsa --from-file=id_rsa.pub -n azimuth-caas-operator

# add reqired cluster specific app cred
# this secret will be deleted when the cluster is deleted
echo "foo" >clouds.yaml
kubectl create secret generic openstack --from-file=clouds.yaml

# create the cluster
kubectl apply -f tools/test_quick.yaml
kubectl wait --for=jsonpath='{.status.phase}'=Ready cluster quick-test --timeout=2m
kubectl get cluster -o yaml
kubectl get job
kubectl get pod
```

To delete the cluster, you can simple delete the Cluster CRD
we just created:

```sh
kubectl delete -f tools/test_quick.yaml
```

Note the above is very similar to what is run in the
functional test scripts.

## Config

*This is a WIP, and not yet in the helm chart.*

You can set the following environment variables,
if the default does not work for your setup:

* `CONSUL_HTTP_ADDR=zenith-consul-server.zenith:8500`
* `ARA_API_SERVER=http://azimuth-ara.azimuth-caas-operator:8000`

## Run unit tests

We tox, and uses python3.9:

    pip install tox
    tox

## Test opertor locally using tox

You can test it with tox too:

    # test with k3s on a VM reachable from the platforms you want to deploy
    curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik" sh -s -

    # reach that k3s on your dev box, via ssh tunnel or otherwise
    k3s kubectl get node

    # ingress and zenith only needed when platforms need zenith
    helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
    helm upgrade ingress-nginx ingress-nginx/ingress-nginx \
      --version 4.4.0 --create-namespace --namespace ingress-nginx \
      -i -f tools/nginx_values.yaml
    helm repo add zenith https://stackhpc.github.io/zenith
    # TODO: this is broken, need consul client enabled? or update sshd config
    helm upgrade zenith zenith/zenith-server \
      --version 0.1.0-dev.0.update-consul.169 -i -f tools/zenith_values.yaml \
      --create-namespace --namespace zenith

    # test you can hit zenith's internal API
    kubectl port-forward -n zenith svc/zenith-zenith-server-registrar 8000:80
    curl -X POST -s http://localhost:8000/admin/reserve
    # check public associate endpoint
    curl -X POST -s http://registrar.128-232-227-193.sslip.io

    kubectl create secret generic openstack --from-file=clouds.yaml
    ssh-keygen -f id_rsa -P ""
    kubectl create namespace azimuth-caas-operator
    kubectl create secret generic azimuth-sshkey --from-file=id_rsa \
        --from-file=id_rsa.pub -n azimuth-caas-operator

    tox -e kopf &
    kubctl apply -f tools/test_cluster_type.yaml
    kubctl apply -f tools/test_quick.yaml

    kubectl wait --for=jsonpath='{.status.phase}'=Creating cluster quick-test
    kubectl wait --for=jsonpath='{.status.phase}'=Ready cluster quick-test
    kubectl get jobs
    kubctl delete -f tools/test_quick.yaml
