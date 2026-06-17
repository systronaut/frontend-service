# Author: Systronaut
# PXE engine: dnsmasq (proxyDHCP/TFTP) + nginx (HTTP install tree) + hardened API.
# Runs with network_mode: host on a Linux gateway (see docker-compose.yml).
FROM alpine:3.20

RUN apk add --no-cache dnsmasq nginx python3 py3-pip tftp-hpa \
    curl libarchive-tools xorriso wimlib \
    && rm -rf /var/cache/apk/*

# API runtime.
WORKDIR /engine
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt
COPY api.py .

# Service configs.
COPY etc/dnsmasq.conf /etc/dnsmasq.conf
COPY nginx/pxe.conf /etc/nginx/http.d/default.conf
COPY entrypoint.sh /engine/entrypoint.sh
# CIS Benchmark hardening scripts served read-only over HTTP for answer files.
COPY hardening/ /var/www/html/hardening/
# Top-level iPXE entry that chains to each backend-rendered per-host script.
COPY www/autoexec.ipxe /var/www/html/autoexec.ipxe
# Automatic in-container install-tree provisioner (downloads + extracts ISOs).
COPY provision/ /engine/provision/
RUN chmod +x /engine/entrypoint.sh /engine/provision/provision.sh \
    && mkdir -p /etc/dnsmasq.d/hosts /var/www/html/host /var/www/html/install /var/lib/tftpboot /data

# DHCP/proxyDHCP (67/4011), TFTP (69), HTTP (80), API (8081).
EXPOSE 69/udp 80/tcp 8081/tcp 4011/udp
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8081/api/v1/health >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/engine/entrypoint.sh"]
