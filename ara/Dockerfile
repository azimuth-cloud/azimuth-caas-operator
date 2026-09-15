FROM quay.io/fedora/fedora:44

RUN dnf update -y \
    && dnf install -y \
        which \
        python3-pip \
        python3-wheel \
        postgresql \
        libpq \
        mariadb-connector-c \
        gcc \
        python3-devel \
        postgresql-devel \
        libpq-devel \
        mariadb-devel \
    && dnf clean all \
    && rm -rf /var/cache/dnf

RUN python3 -m pip install "ara[server,postgresql,mysql]" gunicorn "django-health-check<4.0.0"

ENV ARA_BASE_DIR=/opt/ara

CMD bash -c '/usr/local/bin/ara-manage migrate && python3 -m gunicorn --workers=4 --threads=4 --worker-class gthread --access-logfile - --bind 0.0.0.0:8000 ara.server.wsgi'

EXPOSE 8000
