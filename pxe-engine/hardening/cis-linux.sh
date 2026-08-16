#!/bin/sh
# Systronaut -- CIS Benchmark baseline (Linux), applied at install time.
#
# Served read-only by the PXE engine. An OS answer file fetches and runs this in
# its post-install hook, sourcing the per-host hardening overlay first, e.g.:
#
#   curl -sf http://<engine>/host/<mac>/hardening.env -o /tmp/h.env
#   curl -sf http://<engine>/hardening/cis-linux.sh   -o /tmp/cis.sh
#   . /tmp/h.env ; sh /tmp/cis.sh
#
# Each control is gated by a HARDEN_* flag from the overlay, so the deployment's
# selected security profile decides what is enforced. Idempotent; safe to re-run.
# This is a pragmatic CIS-aligned subset (distro-agnostic). Map to a full CIS
# Benchmark / OpenSCAP profile for formal certification.
#
# HARDEN_DISK_ENCRYPTION is intentionally NOT handled here: Linux FDE (LUKS)
# must be set at install time via the answer file (kickstart/preseed). Post-
# install encryption would be a different, disruptive operation.
set -eu

log() { echo "[cis] $*"; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- CIS baseline (always on when this script runs) --------------------------
if [ "${HARDEN_CIS_BASELINE:-0}" = "1" ]; then
  log "applying CIS baseline"

  # 1.1 Filesystem: restrict core dumps, randomize address space.
  printf '* hard core 0\n' >> /etc/security/limits.conf
  printf 'kernel.randomize_va_space = 2\n' > /etc/sysctl.d/60-cis.conf

  # 3.x Network kernel params (CIS network hardening).
  cat >> /etc/sysctl.d/60-cis.conf <<'SYSCTL'
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.all.log_martians = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv6.conf.all.accept_redirects = 0
SYSCTL
  have sysctl && sysctl --system >/dev/null 2>&1 || true

  # 5.x Strong password policy (CIS).
  if [ -f /etc/security/pwquality.conf ]; then
    sed -i 's/^# *minlen.*/minlen = 14/; s/^# *dcredit.*/dcredit = -1/; s/^# *ucredit.*/ucredit = -1/; s/^# *ocredit.*/ocredit = -1/; s/^# *lcredit.*/lcredit = -1/' /etc/security/pwquality.conf || true
  fi

  # 5.4 Restrictive default umask.
  printf 'umask 027\n' > /etc/profile.d/cis-umask.sh
fi

# --- SSH hardening (CIS 5.2) -------------------------------------------------
if [ "${HARDEN_REMOTE_ACCESS_HARDENING:-0}" = "1" ] && [ -f /etc/ssh/sshd_config ]; then
  log "hardening sshd"
  for kv in "PermitRootLogin no" "PasswordAuthentication no" "X11Forwarding no" \
            "MaxAuthTries 4" "ClientAliveInterval 300" "ClientAliveCountMax 0" \
            "LoginGraceTime 60"; do
    key=${kv%% *}
    sed -i "/^#\?${key} /d" /etc/ssh/sshd_config
    echo "$kv" >> /etc/ssh/sshd_config
  done
fi

# --- Host firewall default-deny (CIS 3.5) -----------------------------------
if [ "${HARDEN_HOST_FIREWALL:-0}" = "1" ]; then
  log "enabling host firewall (default-deny inbound)"
  if have firewall-cmd; then
    systemctl enable --now firewalld 2>/dev/null || true
    firewall-cmd --permanent --set-default-zone=drop 2>/dev/null || true
    firewall-cmd --permanent --add-service=ssh 2>/dev/null || true
    firewall-cmd --reload 2>/dev/null || true
  elif have ufw; then
    ufw --force default deny incoming
    ufw allow OpenSSH || ufw allow 22/tcp
    ufw --force enable
  fi
fi

# --- Automatic security updates (CIS 1.8) -----------------------------------
if [ "${HARDEN_AUTO_UPDATES:-0}" = "1" ]; then
  log "enabling automatic security updates"
  if have dnf; then
    dnf install -y dnf-automatic >/dev/null 2>&1 || true
    sed -i 's/^apply_updates.*/apply_updates = yes/' /etc/dnf/automatic.conf 2>/dev/null || true
    systemctl enable --now dnf-automatic.timer 2>/dev/null || true
  elif have apt-get; then
    apt-get install -y unattended-upgrades >/dev/null 2>&1 || true
    echo 'APT::Periodic::Unattended-Upgrade "1";' > /etc/apt/apt.conf.d/20auto-upgrades
  elif have zypper; then
    zypper -n install yast2-online-update-configuration >/dev/null 2>&1 || true
  fi
fi

# --- Audit logging (CIS 4.1) ------------------------------------------------
if [ "${HARDEN_AUDIT_LOGGING:-0}" = "1" ]; then
  log "enabling auditd"
  have dnf && dnf install -y audit >/dev/null 2>&1 || true
  have apt-get && apt-get install -y auditd >/dev/null 2>&1 || true
  systemctl enable --now auditd 2>/dev/null || true
fi

# --- Time sync (CIS 2.1) -----------------------------------------------------
if [ "${HARDEN_TIME_SYNC:-0}" = "1" ]; then
  log "enabling time sync"
  systemctl enable --now chronyd 2>/dev/null || systemctl enable --now systemd-timesyncd 2>/dev/null || true
fi

log "done"
