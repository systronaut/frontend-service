#!/usr/bin/env bash
# Systronaut Deploy -- safe in-place update.
#   1. back up the SQLite data volume
#   2. pull the latest code
#   3. rebuild + recreate containers (version baked from VERSION)
#   4. prune dangling images
#
# Idempotent and safe to re-run. Requires: git, docker compose v2.
set -euo pipefail

cd "$(dirname "$0")"

compose() { docker compose "$@"; }

log() { printf '\033[0;36m[update]\033[0m %s\n' "$*"; }
die() { printf '\033[0;31m[update] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

command -v git >/dev/null    || die "git not found"
docker compose version >/dev/null 2>&1 || die "docker compose v2 not found"
[ -f .env ] || die ".env not found -- copy .env.example to .env first"

# 1) Back up the control-plane data volume (deployments + audit log).
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="backups"
mkdir -p "$BACKUP_DIR"
log "backing up control-plane data -> $BACKUP_DIR/data-$STAMP.tar.gz"
docker run --rm \
  -v "$(basename "$PWD")_control-plane-data":/data:ro \
  -v "$PWD/$BACKUP_DIR":/backup \
  alpine sh -c "tar czf /backup/data-$STAMP.tar.gz -C /data ." \
  || log "backup skipped (volume not present yet)"

# 2) Pull latest code (fast-forward only; abort on local divergence).
OLD_VERSION="$(cat VERSION 2>/dev/null || echo unknown)"
if [ -d .git ]; then
  log "pulling latest code"
  git pull --ff-only || die "git pull failed (local changes? resolve, then re-run)"
fi
NEW_VERSION="$(cat VERSION 2>/dev/null || echo unknown)"
export APP_VERSION="$NEW_VERSION"
log "version: $OLD_VERSION -> $NEW_VERSION"

# 3) Rebuild + recreate (APP_VERSION flows into the control-plane image/env).
log "building images"
compose build
log "recreating containers"
compose up -d

# 4) Tidy up.
log "pruning dangling images"
docker image prune -f >/dev/null || true

log "done. Console: http://localhost:5000  (now running $NEW_VERSION)"
