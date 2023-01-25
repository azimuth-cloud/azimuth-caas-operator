# azimuth-caas-operator
![tox](https://github.com/stackhpc/azimuth-caas-operator/actions/workflows/tox.yaml/badge.svg?branch=main)
![tox](https://github.com/stackhpc/azimuth-caas-operator/actions/workflows/functional.yaml/badge.svg?branch=main)

K8s operator to create clusters using K8s CRDs

This is still very much work in progress!!

## Run unit tests

We tox, and uses python3.9:

    pip install tox
    tox

## Test opertor locally

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
