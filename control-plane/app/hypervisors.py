# Author: Systronaut
# Runtime hypervisor registry: turns a stored (encrypted) hypervisor record into
# a configured provider adapter, so operators/admins can add hypervisors from the
# UI instead of editing .env. Credentials are decrypted here only to build the
# live adapter; they are never persisted or returned in plaintext.

from dataclasses import dataclass

from . import crypto
from .providers.base import HypervisorInventory

# Kinds a user can register + the extra config fields the add-form collects.
# (host/username/password are always collected; these are kind-specific extras.)
KINDS: dict[str, dict] = {
    "esxi":    {"label": "VMware ESXi (standalone)",
                "fields": [("datastore", "Datastore", False), ("network", "VM network / port group", False)],
                "insecure_default": True},
    "vsphere": {"label": "VMware vCenter",
                "fields": [("datacenter", "Datacenter", True), ("datastore", "Datastore", False),
                           ("network", "Port group", False), ("cluster", "Cluster", False)],
                "insecure_default": False},
    "proxmox": {"label": "Proxmox VE",
                "fields": [("node", "Node", True), ("storage", "Storage", False),
                           ("bridge", "Bridge", False)],
                "insecure_default": False},
    "libvirt": {"label": "libvirt / KVM (host = URI)",
                "fields": [("bridge", "Bridge", False), ("network", "libvirt network", False),
                           ("pool", "Storage pool", False)],
                "insecure_default": False},
    "hyperv":  {"label": "Microsoft Hyper-V",
                "fields": [("switch", "Virtual switch", False), ("vhd_path", "VHD path", False)],
                "insecure_default": True},
}


@dataclass(frozen=True)
class HypervisorRef:
    id: str
    name: str
    kind: str
    host: str


def _truthy(v) -> bool:
    return str(v).lower() not in ("0", "false", "no", "off", "")


def build_provider(record: dict):
    """Instantiate the provider adapter for a stored hypervisor record.

    Decrypts the secret and patches the adapter's connection attributes so the
    same code paths (inventory/create/...) work for env- or UI-configured hosts.
    """
    kind = record["kind"]
    secret = crypto.decrypt(record["secret_enc"])
    host = record["host"]
    user = record["username"]
    cfg = record.get("config", {}) or {}

    if kind in ("esxi", "vsphere"):
        from .providers.cloud import EsxiProvider, VsphereProvider
        p = EsxiProvider() if kind == "esxi" else VsphereProvider()
        p.host, p.user, p.password = host, user, secret
        p.datacenter = cfg.get("datacenter", "ha-datacenter" if kind == "esxi" else "")
        p.datastore = cfg.get("datastore", "")
        p.network = cfg.get("network", "")
        p.cluster = cfg.get("cluster", "")
        p.insecure = _truthy(cfg.get("insecure", kind == "esxi"))
        return p
    if kind == "proxmox":
        from .providers.proxmox import ProxmoxProvider
        p = ProxmoxProvider()
        p.host, p.user, p.password = host, user, secret
        p.token_name = cfg.get("token_name", "")
        p.token_value = cfg.get("token_value", "")
        p.node = cfg.get("node", "")
        p.storage = cfg.get("storage", "local-lvm")
        p.bridge = cfg.get("bridge", "vmbr0")
        p.verify_ssl = not _truthy(cfg.get("insecure", False))
        return p
    if kind == "libvirt":
        from .providers.libvirt_provider import LibvirtProvider
        p = LibvirtProvider()
        p.uri = host                      # for libvirt the "host" field is the URI
        p.bridge = cfg.get("bridge", "")
        p.network = cfg.get("network", "")
        p.pool = cfg.get("pool", "default")
        return p
    if kind == "hyperv":
        from .providers.hyperv import HypervProvider
        p = HypervProvider()
        p.host, p.user, p.password = host, user, secret
        p.switch = cfg.get("switch", "")
        p.vhd_dir = cfg.get("vhd_path", p.vhd_dir)
        p.use_ssl = not _truthy(cfg.get("no_ssl", False))
        p.verify = not _truthy(cfg.get("insecure", False))
        return p
    raise ValueError(f"Unknown hypervisor kind {kind!r}")


# Network-related config keys shown on the Hypervisor → Network tab (read-only).
_NET_FIELDS: dict[str, list[tuple[str, str]]] = {
    "esxi":    [("network", "VM network / port group"), ("datastore", "Datastore")],
    "vsphere": [("network", "Port group"), ("datacenter", "Datacenter"), ("cluster", "Cluster")],
    "proxmox": [("bridge", "Bridge"), ("node", "Node"), ("storage", "Storage")],
    "libvirt": [("bridge", "Bridge"), ("network", "libvirt network"), ("pool", "Storage pool")],
    "hyperv":  [("switch", "Virtual switch"), ("vhd_path", "VHD path")],
}


def network_fields_for(kind: str) -> list[tuple[str, str]]:
    return list(_NET_FIELDS.get(kind, []))


def inventory_for(record: dict) -> HypervisorInventory:
    """Read-only inventory for one registered hypervisor (never raises)."""
    try:
        p = build_provider(record)
        inv = p.inventory()
        if inv is None:
            return HypervisorInventory(provider=record["kind"], endpoint=record["host"],
                                       connected=False, message="inventory not supported")
        return inv.with_usage_estimate()
    except Exception as exc:  # keep the page resilient to a single bad host
        return HypervisorInventory(provider=record["kind"], endpoint=record.get("host", ""),
                                   connected=False, message=str(exc))
