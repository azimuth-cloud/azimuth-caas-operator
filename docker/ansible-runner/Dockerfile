FROM ubuntu:22.04

RUN apt-get update && apt-get upgrade -y && apt-get install python3-pip unzip git wget -y && apt-get clean
RUN pip install ansible-runner==2.3.1 ansible==7.1.0 ansible-core==2.14.1 ara==1.6.1 openstacksdk==1.0.0 python-openstackclient==6.0.0
RUN pip install "configomatic @ git+https://github.com/stackhpc/configomatic.git@3a7e88693e8f44530ac4f1f5ee3d64977cf3784d"
RUN pip install "easykube @ git+https://github.com/stackhpc/easykube.git@f8212a0b412b1eb2d7d015508b0ee49b6c2a5eb2"

RUN for dir in \
      /home/runner \
      /home/runner/.ansible \
      /home/runner/.ansible/tmp \
      /runner \
      /home/runner \
      /runner/env \
      /runner/inventory \
      /runner/project \
      /runner/artifacts ; \
    do mkdir -m 0775 -p $dir ; chmod -R g+rwx $dir ; chgrp -R root $dir ; done && \
    for file in \
      /home/runner/.ansible/galaxy_token \
      /etc/passwd \
      /etc/group ; \
    do touch $file ; chmod g+rw $file ; chgrp root $file ; done

ENV HOME=/home/runner

ENV TF_PLUGIN_CACHE_DIR=/home/runner/.terraform.d/plugin-cache
ARG terraform_version=1.3.7
RUN wget https://releases.hashicorp.com/terraform/${terraform_version}/terraform_${terraform_version}_linux_amd64.zip && \
    unzip terraform_${terraform_version}_linux_amd64.zip && rm terraform_${terraform_version}_linux_amd64.zip && \
    mv terraform /usr/local/bin && \
    mkdir -p /home/runner/terraform_setup && \
    mkdir -p $TF_PLUGIN_CACHE_DIR
COPY main.tf /home/runner/terraform_setup/main.tf
RUN cd /home/runner/terraform_setup && terraform init

COPY requirements.yaml /home/runner/terraform_setup/requirements.yaml
RUN ansible-galaxy install -r /home/runner/terraform_setup/requirements.yaml

WORKDIR /runner
CMD ["ansible-runner", "run", "/runner", "-j"]
