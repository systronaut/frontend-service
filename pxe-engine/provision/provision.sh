#!/bin/sh
# Systronaut PXE engine -- automatic install-tree provisioner.
#
# Runs inside the container (launched in the background by the entrypoint).
# Downloads + extracts each enabled OS into the served install tree with NO
# admin/user interaction. Idempotent: a per-OS marker in the data volume means
# completed trees are never re-downloaded. Safe to run on every container start.
set -u

MANIFEST="${PXE_MANIFEST:-/engine/provision/images.conf}"
INSTALL_ROOT="${PXE_INSTALL_ROOT:-/var/www/html/install}"
CACHE="${PXE_ISO_CACHE:-/data/iso}"
MARKERS="${PXE_PROVISION_MARKERS:-/data/provisioned}"

mkdir -p "$INSTALL_ROOT" "$CACHE" "$MARKERS"

log() { echo "[provision] $*"; }

extract() {  # mode file dest
  case "$1" in
    netboot) bsdtar -xzf "$2" -C "$3" ;;
    iso|windows) bsdtar -xf "$2" -C "$3" ;;   # libarchive reads ISO9660 directly
    *) log "unknown mode: $1"; return 1 ;;
  esac
}

provision_one() {
  key="$1"; mode="$2"; url="$3"
  if [ -f "$MARKERS/$key.done" ]; then
    log "$key: already provisioned, skipping"
    return 0
  fi
  if [ -z "$url" ]; then
    log "$key: no URL configured, skipping (set one in images.conf)"
    return 0
  fi
  tree="$INSTALL_ROOT/$key"
  dl="$CACHE/$key.download"
  log "$key: downloading $url"
  if ! curl -fSL --retry 3 --retry-delay 5 -C - -o "$dl" "$url"; then
    log "$key: download FAILED (will retry on next start)"
    return 1
  fi
  rm -rf "$tree"; mkdir -p "$tree"
  log "$key: extracting ($mode)"
  if ! extract "$mode" "$dl" "$tree"; then
    log "$key: extract FAILED"
    return 1
  fi
  rm -f "$dl"
  touch "$MARKERS/$key.done"
  log "$key: ready -> $tree"
}

[ "${PXE_PROVISION:-1}" = "1" ] || { log "PXE_PROVISION=0, provisioner disabled"; exit 0; }
[ -f "$MANIFEST" ] || { log "no manifest at $MANIFEST"; exit 0; }

log "starting provisioning pass"
# Parse: key|mode|url|enabled  (whitespace around fields is trimmed)
while IFS='|' read -r key mode url enabled; do
  key=$(printf '%s' "$key" | tr -d '[:space:]')
  case "$key" in ''|\#*) continue ;; esac
  mode=$(printf '%s' "$mode" | tr -d '[:space:]')
  url=$(printf '%s' "$url" | tr -d '[:space:]')
  enabled=$(printf '%s' "$enabled" | tr -d '[:space:]')
  [ "$enabled" = "1" ] || { log "$key: disabled"; continue; }
  provision_one "$key" "$mode" "$url"
done < "$MANIFEST"
log "provisioning pass complete"
