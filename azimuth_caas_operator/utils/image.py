import os

DEFAULT_ANSIBLE_RUNNER_IMAGE = "ghcr.io/stackhpc/azimuth-caas-operator-ar:v0.1.0"


def get_ansible_runner_image():
    return os.environ.get("ANSIBLE_RUNNER_IMAGE", DEFAULT_ANSIBLE_RUNNER_IMAGE)
