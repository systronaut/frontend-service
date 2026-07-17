# Author: Systronaut
# Control plane (UI + REST API). Runs as a non-root user under gunicorn.
FROM python:3.12-slim

ARG APP_VERSION=dev
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 APP_VERSION=${APP_VERSION}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Optional: libvirt/KVM provider -----------------------------------------
# libvirt-python is a C extension coupled to the host libvirt version, so it is
# NOT in the default image (keeps the build fast + reliable). To enable the
# libvirt adapter, build with: --build-arg ENABLE_LIBVIRT=1
ARG ENABLE_LIBVIRT=0
RUN if [ "$ENABLE_LIBVIRT" = "1" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends gcc pkg-config libvirt-dev \
      && pip install --no-cache-dir "libvirt-python==9.0.0" \
      && apt-get purge -y gcc pkg-config libvirt-dev \
      && apt-get install -y --no-install-recommends libvirt0 \
      && apt-get autoremove -y \
      && rm -rf /var/lib/apt/lists/*; \
    fi

COPY app ./app
COPY wsgi.py .

# Non-root + writable data dir for the SQLite store.
RUN useradd -r -u 10001 systronaut \
    && mkdir -p /data && chown -R systronaut:systronaut /data /app
USER systronaut

EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/healthz').status==200 else 1)"

# 3 sync workers is plenty for a control plane; the SQLite store is lock-guarded.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "3", "--timeout", "60", "wsgi:app"]
