# Author: Systronaut
# Provider abstraction. A Provider turns a validated DeploymentSpec into a real
# install, applying the security profile's controls through whatever mechanism
# the target supports (PXE answer files, vSphere guest customization, ...).
#
# PXE, libvirt, Proxmox, vSphere, ESXi and Hyper-V are implemented. OpenStack
# remains a stub (Nova needs a hardened image + cloud-init path, not PXE).

import hashlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..models import DeploymentSpec
from ..security import ComplianceResult


def derive_mac(seed: str) -> str:
    """Deterministic, locally-administered unicast MAC for a hostname.

    Hypervisor adapters that PXE-boot their guests assign this MAC at VM-create
    time so the pxe-engine reservation and the guest agree without a post-create
    read. Deterministic on the seed keeps create() idempotent: re-running for the
    same hostname yields the same MAC (and thus the same reservation).
    """
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    # First octet 0x02 -> locally administered, unicast (bit0=0, bit1=1).
    octets = [0x02, *digest[:5]]
    return ":".join(f"{o:02x}" for o in octets)


@dataclass
class ProviderResult:
    """What a provider returns from create()."""

    ok: bool
    provider_ref: str = ""     # opaque handle (PXE: MAC; vSphere: moref; ...)
    message: str = ""


class ProviderError(RuntimeError):
    """Recoverable provider failure with a user-safe message."""


@dataclass(frozen=True)
class VmInfo:
    """One guest as reported by a hypervisor."""

    name: str
    state: str = "unknown"     # running | stopped | unknown
    vcpu: int = 0
    memory_mb: int = 0
    disk_gb: int = 0
    ref: str = ""              # provider handle (vmid / uuid / moref)


@dataclass(frozen=True)
class HypervisorInventory:
    """A hypervisor's capacity + the VMs on it, for the Hypervisors view."""

    provider: str
    endpoint: str              # host / URI shown in the table
    connected: bool
    cpu_total: int = 0         # logical cores
    memory_mb: int = 0         # host RAM
    storage_gb: int = 0        # host storage
    vms: tuple[VmInfo, ...] = ()
    message: str = ""          # error/context when not connected
    # Optional live gauges for the Dashboard charts (best-effort; 0 if unknown).
    cpu_used_pct: float = 0.0
    memory_used_mb: int = 0

    @property
    def running(self) -> int:
        return sum(1 for v in self.vms if v.state == "running")

    def with_usage_estimate(self) -> "HypervisorInventory":
        """Fill cpu_used_pct / memory_used_mb from running VMs when providers omit gauges."""
        if not self.connected or (self.cpu_used_pct or self.memory_used_mb):
            return self
        used_mem = sum(v.memory_mb for v in self.vms if v.state == "running")
        used_vcpu = sum(v.vcpu for v in self.vms if v.state == "running")
        cpu_pct = 0.0
        if self.cpu_total > 0 and used_vcpu:
            cpu_pct = min(100.0, 100.0 * used_vcpu / self.cpu_total)
        return HypervisorInventory(
            provider=self.provider, endpoint=self.endpoint, connected=self.connected,
            cpu_total=self.cpu_total, memory_mb=self.memory_mb, storage_gb=self.storage_gb,
            vms=self.vms, message=self.message,
            cpu_used_pct=cpu_pct, memory_used_mb=used_mem,
        )


class Provider(ABC):
    """Lifecycle interface every backend implements."""

    name: str = "base"
    #: True once the adapter can really provision. Stubs set this False so the UI
    #: can show "preview only" without pretending the deploy happened.
    implemented: bool = False

    @abstractmethod
    def preflight(self, spec: DeploymentSpec) -> list[str]:
        """Return a list of human-readable warnings/blockers (empty == good)."""

    @abstractmethod
    def create(self, spec: DeploymentSpec, compliance: ComplianceResult) -> ProviderResult:
        """Stage/begin the deployment. Idempotent on (hostname, mac) where possible."""

    @abstractmethod
    def status(self, provider_ref: str) -> str:
        """Best-effort current status string for an existing deployment."""

    @abstractmethod
    def destroy(self, provider_ref: str) -> ProviderResult:
        """Tear down / deregister the deployment."""


_REGISTRY: dict[str, Provider] = {}


def register(provider: Provider) -> None:
    _REGISTRY[provider.name] = provider


def get(name: str) -> Provider:
    if name not in _REGISTRY:
        raise ProviderError(f"No provider registered for {name!r}.")
    return _REGISTRY[name]


def available() -> dict[str, Provider]:
    return dict(_REGISTRY)
