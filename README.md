# azimuth-caas-operator

K8s operator to create clusters using K8s CRDs

This is still very much work in progress!!

## Run unit tests

We tox, and uses python3.9:

  pip install tox
  tox

## Test opertor locally

You can test it with tox too:

   minkube start
   tox -e kopf &
   kubctl apply -f tools/test_job.yaml
   kubctl apply -f tools/test_cluster_type.yaml
   kubctl apply -f tools/test_cluster.yaml
