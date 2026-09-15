FROM quay.io/fedora/fedora:44

RUN --mount=type=cache,target=/var/cache/dnf,sharing=locked \
      dnf update -y \
      && dnf install -y \
        gcc \
        libpq \
        libpq-devel \
        mariadb-connector-c \
        mariadb-devel \
        postgresql \
        postgresql-devel \
        python3-pip \
        python3-wheel \
        python3-devel \
        which
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install "ara[server,postgresql,mysql]" gunicorn "django-health-check<4.0.0"

ENV ARA_BASE_DIR=/opt/ara

CMD bash -c '/usr/local/bin/ara-manage migrate && python3 -m gunicorn --workers=4 --threads=4 --worker-class gthread --access-logfile - --bind 0.0.0.0:8000 ara.server.wsgi'

EXPOSE 8000
