#!/bin/sh
# Systronaut PXE engine entrypoint.
# Renders the dnsmasq runtime config from env, then runs dnsmasq + nginx + API.
# Does NOT run ansible -- the os_pxe_lab tree is a read-only content lookup.
set -eu

# Fail closed: the API must never run without a shared token.
if [ -z "${PXE_ENGINE_TOKEN:-}" ]; then
  echo "[pxe-engine] FATAL: PXE_ENGINE_TOKEN is required. Set it in .env." >&2
  exit 1
fi

PXE_INTERFACE="${PXE_INTERFACE:-eth0}"
PXE_SUBNET="${PXE_SUBNET:-192.168.0.0}"
PXE_HOST_IP="${PXE_HOST_IP:-}"
PXE_BOOTFILE="${PXE_BOOTFILE:-snponly.efi}"

mkdir -p /etc/dnsmasq.d/hosts /var/www/html/host /var/www/html/install /var/lib/tftpboot /data

# Build the OS install trees automatically, in-container, in the background so
# DHCP/TFTP/HTTP/API come up immediately. Idempotent + cached (see provision.sh).
sh /engine/provision/provision.sh &

# Runtime overlay appended to the static base config.
{
  echo "interface=${PXE_INTERFACE}"
  echo "dhcp-range=${PXE_SUBNET},proxy"
  [ -n "${PXE_HOST_IP}" ] && echo "listen-address=127.0.0.1,${PXE_HOST_IP}"
  echo "pxe-service=X86-64_EFI,\"PXE Boot (UEFI 64-bit)\",${PXE_BOOTFILE}"
} > /etc/dnsmasq.d/runtime.conf

echo "[pxe-engine] starting nginx (HTTP install tree :80)"
nginx

echo "[pxe-engine] starting dnsmasq (proxyDHCP/TFTP on ${PXE_INTERFACE})"
dnsmasq --conf-file=/etc/dnsmasq.conf --conf-dir=/etc/dnsmasq.d,*.conf --keep-in-foreground &

echo "[pxe-engine] starting API :8081"
exec gunicorn --bind 0.0.0.0:8081 --workers 2 --chdir /engine api:app
