# Author: Systronaut
# Domain models for a VM deployment request and its lifecycle record.
#
# A DeploymentSpec is the validated, immutable intent ("deploy this OS, on this
# target, with this network and this security profile"). A Deployment is the
# stored record with status + compliance evidence. Timestamps are ISO 8601 UTC.

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from . import validators as v
from . import catalog
from . import security


class Provider(str, Enum):
    PXE = "pxe"                 # bare-metal / any hypervisor via network boot (real)
    VSPHERE = "vsphere"        # VMware vCenter (adapter, real; PXE-staged)
    LIBVIRT = "libvirt"        # KVM/QEMU via libvirt (adapter, real; PXE-staged)
    PROXMOX = "proxmox"        # Proxmox VE (adapter, real; PXE-staged)
    ESXI = "esxi"             # standalone ESXi host (adapter, stubbed)
    OPENSTACK = "openstack"    # OpenStack Nova (adapter, stubbed; image/cloud-init path)


class DeploymentStatus(str, Enum):
    PENDING = "pending"        # accepted, not yet handed to provider
    SCHEDULED = "scheduled"    # provider staged install (e.g. PXE entry written)
    INSTALLING = "installing"
    READY = "ready"
    FAILED = "failed"
    DESTROYED = "destroyed"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class NetworkSpec:
    mode: str                      # "dhcp" | "static"
    mac: str = ""                  # required for PXE host reservation
    ip: str = ""
    netmask: str = "255.255.255.0"
    gateway: str = ""
    dns: str = ""
    domain: str = ""
    lease: str = "12h"

    @staticmethod
    def from_form(form) -> "NetworkSpec":
        mode = v.one_of(form.get("net_mode", "dhcp"), {"dhcp", "static"}, name="net_mode")
        mac = v.mac(form.get("mac")) if form.get("mac") else ""
        domain = v.domain(form.get("domain")) if form.get("domain") else ""
        lease = v.lease(form.get("lease", "12h"))
        if mode == "static":
            return NetworkSpec(
                mode="static",
                mac=mac,
                ip=v.ipv4(form.get("ip")),
                netmask=v.ipv4(form.get("netmask", "255.255.255.0")),
                gateway=v.ipv4(form.get("gateway")) if form.get("gateway") else "",
                dns=v.ipv4(form.get("dns")) if form.get("dns") else "",
                domain=domain, lease=lease,
            )
        return NetworkSpec(mode="dhcp", mac=mac, domain=domain, lease=lease)


@dataclass(frozen=True)
class DeploymentSpec:
    """Validated deployment intent. Construction implies the inputs are clean."""

    hostname: str
    os_key: str
    provider: Provider
    security_profile: str
    network: NetworkSpec
    cpu: int = 2
    memory_mb: int = 4096
    disk_gb: int = 40
    requested_by: str = "unknown"

    @staticmethod
    def from_form(form, *, requested_by: str = "unknown") -> "DeploymentSpec":
        os_key = v.one_of(form.get("os_key", ""),
                          {i.key for i in catalog.all_images()}, name="os_key")
        provider = Provider(v.one_of(form.get("provider", "pxe"),
                                     {p.value for p in Provider}, name="provider"))
        profile = v.one_of(form.get("security_profile", security.DEFAULT_PROFILE),
                           {p.name for p in security.all_profiles()}, name="security_profile")
        net = NetworkSpec.from_form(form)
        # PXE pins the install to a NIC, so a MAC is mandatory there.
        if provider == Provider.PXE and not net.mac:
            raise v.ValidationError("A MAC address is required for PXE deployments.")
        return DeploymentSpec(
            hostname=v.hostname(form.get("hostname")),
            os_key=os_key,
            provider=provider,
            security_profile=profile,
            network=net,
            cpu=v.positive_int(form.get("cpu", 2), name="cpu", minimum=1, maximum=128),
            memory_mb=v.positive_int(form.get("memory_mb", 4096), name="memory_mb",
                                     minimum=512, maximum=1048576),
            disk_gb=v.positive_int(form.get("disk_gb", 40), name="disk_gb",
                                   minimum=8, maximum=65536),
            requested_by=requested_by,
        )

    @property
    def image(self) -> catalog.OsImage:
        return catalog.get_image(self.os_key)

    def compliance(self) -> security.ComplianceResult:
        return security.evaluate(self.security_profile, self.image)


@dataclass
class Deployment:
    """Persisted lifecycle record for a deployment."""

    id: str
    spec: DeploymentSpec
    status: DeploymentStatus = DeploymentStatus.PENDING
    message: str = ""
    compliance_evidence: dict = field(default_factory=dict)
    provider_ref: str = ""          # opaque handle from the provider (e.g. moref)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def touch(self, status: Optional[DeploymentStatus] = None, message: str = "") -> None:
        if status is not None:
            self.status = status
        if message:
            self.message = message
        self.updated_at = _now()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status.value,
            "message": self.message,
            "provider_ref": self.provider_ref,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "compliance_evidence": self.compliance_evidence,
            "spec": {
                "hostname": self.spec.hostname,
                "os_key": self.spec.os_key,
                "provider": self.spec.provider.value,
                "security_profile": self.spec.security_profile,
                "cpu": self.spec.cpu,
                "memory_mb": self.spec.memory_mb,
                "disk_gb": self.spec.disk_gb,
                "requested_by": self.spec.requested_by,
                "network": asdict(self.spec.network),
            },
        }
