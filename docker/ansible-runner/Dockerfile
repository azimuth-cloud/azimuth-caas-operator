FROM ubuntu:22.04

RUN apt-get update && apt-get upgrade -y && apt-get install python3-pip unzip -y && apt-get clean
RUN pip install ansible-runner==2.3.1 ansible==7.1.0 ansible-core==2.14.1

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

WORKDIR /runner
ENV HOME=/home/runner

CMD ["ansible-runner", "run", "/runner", "-j"]
