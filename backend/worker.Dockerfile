# syntax=docker/dockerfile:1.7.0
FROM pgvector/pgvector:0.8.7-pg18-bookworm@sha256:2358fcba361ed2233a5ed81b5fe4ca779ccb304120ce531a3bf51c0ed7e2bc11 AS pgtools
RUN mkdir -p /pg-tools/lib && cp /usr/lib/postgresql/18/bin/pg_dump /pg-tools/ && \
    ldd /usr/lib/postgresql/18/bin/pg_dump | awk '$3 ~ /^\// {print $3} $1 ~ /^\// {print $1}' | xargs -r cp -L -t /pg-tools/lib

FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
COPY --from=pgtools /pg-tools /opt/pg-tools
COPY --chmod=755 deploy/pg-dump.sh /usr/local/bin/pg_dump
WORKDIR /app
COPY backend/requirements-worker.lock /app/requirements-worker.lock
RUN --mount=type=secret,id=proxy_ca \
    set -eu; apt-get update -qq && apt-get install -y --no-install-recommends \
    libgomp1=12.2.0-14+deb12u1 libglib2.0-0=2.74.6-2+deb12u9 libgl1=1.6.0-1 \
    && rm -rf /var/lib/apt/lists/*; \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir --require-hashes -r /app/requirements-worker.lock
COPY --chmod=755 backend/ /app/
ENV OMP_NUM_THREADS=2 PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True PADDLE_PDX_CACHE_HOME=/data/models/paddlex \
    HF_HOME=/data/models/huggingface PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
CMD ["python", "-m", "app.worker.runner"]

