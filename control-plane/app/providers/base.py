# Author: Systronaut
# Provider abstraction. A Provider turns a validated DeploymentSpec into a real
# install, applying the security profile's controls through whatever mechanism
# the target supports (PXE answer files, vSphere guest customization, ...).
#
# Only the PXE provider is fully implemented. The cloud/hypervisor adapters are
# scaffolded with the right shape + credential surface and raise NotImplemented
# at the create step, so the contract is real even though the call is a stub.

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass

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
