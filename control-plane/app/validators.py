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
