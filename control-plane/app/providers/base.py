# Author: Systronaut
# Provider abstraction. A Provider turns a validated DeploymentSpec into a real
# install, applying the security profile's controls through whatever mechanism
# the target supports (PXE answer files, vSphere guest customization, ...).
#
# Only the PXE provider is fully implemented. The cloud/hypervisor adapters are
# scaffolded with the right shape + credential surface and raise NotImplemented
# at the create step, so the contract is real even though the call is a stub.

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import DeploymentSpec
from ..security import ComplianceResult


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
