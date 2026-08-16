# Author: Systronaut
# Boundary input validation. Never trust request data: every value that reaches
# a provider, an answer file, or dnsmasq is validated here first. Validation is
# allow-list / regex based and fails fast with a clear message.

import ipaddress
import re

# A hostname label per RFC 1123 (letters, digits, hyphen; not leading/trailing -).
_HOSTNAME_RE = re.compile(r"^(?=.{1,63}$)[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$")
# MAC address, colon or dash separated.
_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")
# Lease like "72h", "infinite", "3600".
_LEASE_RE = re.compile(r"^(infinite|\d+[smhd]?)$")
# Domain/zone.
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$")


class ValidationError(ValueError):
    """Raised when a boundary value is rejected. Message is user-safe."""


def hostname(value: str) -> str:
    value = (value or "").strip()
    if not _HOSTNAME_RE.match(value):
        raise ValidationError("Invalid hostname (RFC 1123 label, 1-63 chars).")
    return value.lower()


def domain(value: str) -> str:
    value = (value or "").strip().lower()
    if not _DOMAIN_RE.match(value):
        raise ValidationError("Invalid domain (e.g. corp.example.com).")
    return value


def mac(value: str) -> str:
    value = (value or "").strip()
    if not _MAC_RE.match(value):
        raise ValidationError("Invalid MAC address (e.g. 00:0A:95:9D:68:16).")
    return value.lower().replace("-", ":")


def ipv4(value: str) -> str:
    value = (value or "").strip()
    try:
        addr = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        raise ValidationError(f"Invalid IPv4 address: {value!r}.")
    return str(addr)


def lease(value: str) -> str:
    value = (value or "").strip() or "12h"
    if not _LEASE_RE.match(value):
        raise ValidationError("Invalid lease (e.g. 12h, 3600, infinite).")
    return value


def positive_int(value, *, name: str, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} must be an integer.")
    if n < minimum or (maximum is not None and n > maximum):
        bound = f">= {minimum}" + (f" and <= {maximum}" if maximum is not None else "")
        raise ValidationError(f"{name} must be {bound}.")
    return n


def one_of(value: str, allowed, *, name: str) -> str:
    value = (value or "").strip()
    if value not in allowed:
        raise ValidationError(f"Invalid {name}: {value!r}.")
    return value


# Timezone / locale / keyboard — reject shell metacharacters / traversal.
_TZ_RE = re.compile(r"^[A-Za-z0-9_/+-]{1,64}$")
_LOCALE_RE = re.compile(r"^[a-z]{2}_[A-Z]{2}(\.UTF-8)?$")
_KEYBOARD_RE = re.compile(r"^[a-z0-9_-]{1,16}$")
_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_DISK_RE = re.compile(r"^(sd[a-z]+|vd[a-z]+|nvme[0-9]+n[0-9]+|xvd[a-z]+)$")
_SSH_KEY_RE = re.compile(
    r"^(ssh-(ed25519|rsa|ecdsa)|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh\.com)"
    r" [A-Za-z0-9+/=]+( .+)?$"
)


def timezone(value: str) -> str:
    value = (value or "").strip() or "Etc/UTC"
    if not _TZ_RE.match(value) or ".." in value:
        raise ValidationError("Invalid timezone (e.g. Etc/UTC, Europe/Berlin).")
    return value


def locale(value: str) -> str:
    value = (value or "").strip() or "en_US.UTF-8"
    if not _LOCALE_RE.match(value):
        raise ValidationError("Invalid locale (e.g. en_US.UTF-8).")
    return value


def keyboard(value: str) -> str:
    value = (value or "").strip().lower() or "us"
    if not _KEYBOARD_RE.match(value):
        raise ValidationError("Invalid keyboard layout (e.g. us, de).")
    return value


def admin_user(value: str) -> str:
    value = (value or "").strip().lower() or "systronaut"
    if not _USER_RE.match(value) or value in {"root", "nobody"}:
        raise ValidationError("Invalid admin username.")
    return value


def optional_password(value: str, *, minimum: int = 14) -> str:
    """Optional install password; empty allowed (SSH-key-only). Enforces length when set."""
    value = value or ""
    if not value:
        return ""
    if len(value) < minimum:
        raise ValidationError(f"Admin password must be at least {minimum} characters.")
    if len(value) > 128:
        raise ValidationError("Admin password is too long.")
    return value


def optional_ssh_pubkey(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if not _SSH_KEY_RE.match(value) or len(value) > 8192:
        raise ValidationError("Invalid SSH public key (ssh-ed25519 / ssh-rsa / ecdsa).")
    return value


def disk_device(value: str) -> str:
    value = (value or "").strip().lower() or "sda"
    if value.startswith("/dev/"):
        value = value[5:]
    if not _DISK_RE.match(value):
        raise ValidationError("Invalid disk device (e.g. sda, vda, nvme0n1).")
    return value


def optional_secret(value: str, *, name: str, maximum: int = 256) -> str:
    value = (value or "").strip()
    if len(value) > maximum:
        raise ValidationError(f"{name} is too long.")
    if any(c in value for c in "\n\r\0"):
        raise ValidationError(f"{name} contains invalid characters.")
    return value


# Windows NetBIOS workgroup (1–15); Samba UNC path segment after \\host\.
_WORKGROUP_RE = re.compile(r"^[A-Za-z0-9_-]{1,15}$")
_SAMBA_SHARE_RE = re.compile(r"^[A-Za-z0-9_./\\-]{1,128}$")


def workgroup(value: str) -> str:
    value = (value or "").strip() or "WORKGROUP"
    if not _WORKGROUP_RE.match(value):
        raise ValidationError("Invalid workgroup (1–15 alphanumeric / _ / -).")
    return value.upper()


def samba_share(value: str) -> str:
    """Relative share path (e.g. share\\win2022) — no leading backslash."""
    value = (value or "").strip().strip("\\/") or r"share\win2022"
    value = value.replace("/", "\\")
    if not _SAMBA_SHARE_RE.match(value) or ".." in value:
        raise ValidationError(r"Invalid Samba share path (e.g. share\win2022).")
    return value
