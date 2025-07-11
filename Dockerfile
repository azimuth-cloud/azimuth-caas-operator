FROM ubuntu:24.04 AS python-builder

RUN apt-get update && \
    apt-get install -y python3 python3-venv git

RUN python3 -m venv /venv && \
    /venv/bin/pip install -U pip setuptools

COPY requirements.txt /app/requirements.txt
RUN  /venv/bin/pip install --requirement /app/requirements.txt

COPY . /app
RUN /venv/bin/pip install /app


FROM ubuntu:24.04 AS run-image

# Don't buffer stdout and stderr as it breaks realtime logging
ENV PYTHONUNBUFFERED=1

# Create the user that will be used to run the app
ENV APP_UID=1001
ENV APP_GID=1001
ENV APP_USER=app
ENV APP_GROUP=app
RUN groupadd --gid $APP_GID $APP_GROUP && \
    useradd \
      --no-create-home \
      --no-user-group \
      --gid $APP_GID \
      --shell /sbin/nologin \
      --uid $APP_UID \
      $APP_USER

RUN apt-get update && \
    apt-get install --no-install-recommends -y ca-certificates python3 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=python-builder /venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Make httpx use the system trust roots
# By default, this means we use the CAs from the ca-certificates package
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

USER $APP_UID
CMD ["python", "-m", "azimuth_caas_operator"]
