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
    HYPERV = "hyperv"          # Microsoft Hyper-V via WinRM (adapter, real; PXE-staged)
    ESXI = "esxi"             # standalone ESXi host (real; VsphereProvider subclass)
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


# Package / role sets from Ansible (Debian appserver|dbserver, RHEL graphical, …).
PACKAGE_ROLES = frozenset({"minimal", "appserver", "dbserver", "graphical"})


@dataclass(frozen=True)
class InstallSettings:
    """OS answer-file knobs derived from ansible/roles/pxe (must be WebUI-settable)."""

    timezone: str = "Etc/UTC"
    locale: str = "en_US.UTF-8"
    keyboard: str = "us"
    admin_user: str = "systronaut"
    admin_password: str = ""       # plaintext from form; hashed at render time only
    ssh_pubkey: str = ""
    disk_passphrase: str = ""      # LUKS; also accepted via PXE_DISK_ENCRYPTION_PASSPHRASE
    disk_device: str = "sda"
    ntp_server: str = ""
    rhsm_org: str = ""
    rhsm_activation_key: str = ""
    package_role: str = "minimal"  # minimal | appserver | dbserver | graphical
    # Windows (Ansible windows/ Vorlagen): workgroup + UNC share path after \\host\.
    workgroup: str = "WORKGROUP"
    samba_share: str = r"share\win2022"

    @staticmethod
    def from_form(form) -> "InstallSettings":
        return InstallSettings(
            timezone=v.timezone(form.get("timezone", "Etc/UTC")),
            locale=v.locale(form.get("locale", "en_US.UTF-8")),
            keyboard=v.keyboard(form.get("keyboard", "us")),
            admin_user=v.admin_user(form.get("admin_user", "systronaut")),
            admin_password=v.optional_password(form.get("admin_password", "")),
            ssh_pubkey=v.optional_ssh_pubkey(form.get("ssh_pubkey", "")),
            disk_passphrase=v.optional_secret(
                form.get("disk_passphrase", ""), name="disk_passphrase", maximum=128),
            disk_device=v.disk_device(form.get("disk_device", "sda")),
            ntp_server=v.optional_secret(
                form.get("ntp_server", ""), name="ntp_server", maximum=253),
            rhsm_org=v.optional_secret(form.get("rhsm_org", ""), name="rhsm_org"),
            rhsm_activation_key=v.optional_secret(
                form.get("rhsm_activation_key", ""), name="rhsm_activation_key"),
            package_role=v.one_of(
                form.get("package_role", "minimal"), PACKAGE_ROLES, name="package_role"),
            workgroup=v.workgroup(form.get("workgroup", "WORKGROUP")),
            samba_share=v.samba_share(form.get("samba_share", r"share\win2022")),
        )

    def public_dict(self) -> dict:
        """Safe for API/UI — secrets redacted."""
        return {
            "timezone": self.timezone,
            "locale": self.locale,
            "keyboard": self.keyboard,
            "admin_user": self.admin_user,
            "admin_password_set": bool(self.admin_password),
            "ssh_pubkey_set": bool(self.ssh_pubkey),
            "disk_passphrase_set": bool(self.disk_passphrase),
            "disk_device": self.disk_device,
            "ntp_server": self.ntp_server,
            "rhsm_org_set": bool(self.rhsm_org),
            "rhsm_activation_key_set": bool(self.rhsm_activation_key),
            "package_role": self.package_role,
            "workgroup": self.workgroup,
            "samba_share": self.samba_share,
        }


@dataclass(frozen=True)
class DeploymentSpec:
    """Validated deployment intent. Construction implies the inputs are clean."""

    hostname: str
    os_key: str
    provider: Provider
    security_profile: str
    network: NetworkSpec
    install: InstallSettings = field(default_factory=InstallSettings)
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
        install = InstallSettings.from_form(form)
        # PXE pins the install to a NIC, so a MAC is mandatory there.
        if provider == Provider.PXE and not net.mac:
            raise v.ValidationError("A MAC address is required for PXE deployments.")
        if not install.admin_password and not install.ssh_pubkey:
            raise v.ValidationError(
                "Provide an admin password and/or an SSH public key for the install.")
        return DeploymentSpec(
            hostname=v.hostname(form.get("hostname")),
            os_key=os_key,
            provider=provider,
            security_profile=profile,
            network=net,
            install=install,
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
        return security.evaluate(
            self.security_profile, self.image,
            disk_passphrase=self.install.disk_passphrase,
            package_role=self.install.package_role,
        )


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
                "install": self.spec.install.public_dict(),
            },
        }
