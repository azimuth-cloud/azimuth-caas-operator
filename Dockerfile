FROM ubuntu:jammy as build-image

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install --no-install-recommends python3.10-venv git -y && \
    rm -rf /var/lib/apt/lists/*

# build into a venv we can copy across
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY ./requirements.txt /azimuth-caas-operator/requirements.txt
RUN pip install -U pip setuptools
RUN pip install --requirement /azimuth-caas-operator/requirements.txt

COPY . /azimuth-caas-operator
RUN pip install /azimuth-caas-operator

#
# Now the image we run with
#
FROM ubuntu:jammy as run-image

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install --no-install-recommends python3 tini ca-certificates -y && \
    rm -rf /var/lib/apt/lists/*

# Copy accross the venv
COPY --from=build-image /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create the user that will be used to run the app
ENV APP_UID 1001
ENV APP_GID 1001
ENV APP_USER app
ENV APP_GROUP app
RUN groupadd --gid $APP_GID $APP_GROUP && \
    useradd \
      --no-create-home \
      --no-user-group \
      --gid $APP_GID \
      --shell /sbin/nologin \
      --uid $APP_UID \
      $APP_USER

# Don't buffer stdout and stderr as it breaks realtime logging
ENV PYTHONUNBUFFERED 1

# By default, run the operator using kopf
USER $APP_UID
ENTRYPOINT ["tini", "-g", "--"]
CMD ["kopf", "run", "--module", "azimuth_caas_operator.operator", "--all-namespaces"]
