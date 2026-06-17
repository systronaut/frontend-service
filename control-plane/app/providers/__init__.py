# Author: Systronaut
# Provider package: register every backend exactly once on import.

from .base import Provider, ProviderResult, ProviderError, register, get, available
from .pxe import PxeProvider
from .cloud import VsphereProvider, EsxiProvider, OpenstackProvider

_REGISTERED = False


def init_providers() -> None:
    """Idempotently register all providers. Called from the app factory."""
    global _REGISTERED
    if _REGISTERED:
        return
    register(PxeProvider())
    register(VsphereProvider())
    register(EsxiProvider())
    register(OpenstackProvider())
    _REGISTERED = True


__all__ = [
    "Provider", "ProviderResult", "ProviderError",
    "register", "get", "available", "init_providers",
]
