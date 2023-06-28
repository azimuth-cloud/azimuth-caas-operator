import os


DEFAULT_ANSIBLE_RUNNER_IMAGE_REPO = "ghcr.io/stackhpc/azimuth-caas-operator-ee"
DEFAULT_ANSIBLE_RUNNER_IMAGE_TAG = "latest"


def get_ansible_runner_image():
    if "ANSIBLE_RUNNER_IMAGE" in os.environ:
        return os.environ["ANSIBLE_RUNNER_IMAGE"]
    else:
        repo = os.environ.get(
            "ANSIBLE_RUNNER_IMAGE_REPO", DEFAULT_ANSIBLE_RUNNER_IMAGE_REPO
        )
        tag = os.environ.get(
            "ANSIBLE_RUNNER_IMAGE_TAG", DEFAULT_ANSIBLE_RUNNER_IMAGE_TAG
        )
        return f"{repo}:{tag}"
