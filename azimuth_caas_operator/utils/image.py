import os

DEFAULT_ANSIBLE_RUNNER_IMAGE_REPO = "ghcr.io/azimuth-cloud/azimuth-caas-operator-ee"


def get_ansible_runner_image():
    if "ANSIBLE_RUNNER_IMAGE" in os.environ:
        return os.environ["ANSIBLE_RUNNER_IMAGE"]
    else:
        repo = os.environ.get(
            "ANSIBLE_RUNNER_IMAGE_REPO", DEFAULT_ANSIBLE_RUNNER_IMAGE_REPO
        )
        try:
            tag = os.environ["ANSIBLE_RUNNER_IMAGE_TAG"]
        except KeyError:
            raise RuntimeError("ANSIBLE_RUNNER_IMAGE_TAG is not set")
        return f"{repo}:{tag}"
