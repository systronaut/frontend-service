# Author: Systronaut
# Real provider: network-boot (PXE/iPXE) bare-metal & hypervisor-agnostic.
#
# This adapter does NOT run ansible. It talks to the pxe-engine container's
# hardened HTTP API, which serves the os_pxe_lab answer-file tree (read-only
# lookup) and renders a per-MAC iPXE config. We hand the engine the host
# reservation, the chosen OS, and the list of security-control mechanisms to
# weave into the answer file. The target then network-boots and installs
# unattended, already hardened.

import os

import requests

from .base import Provider, ProviderResult, ProviderError
from ..models import DeploymentSpec, Provider as ProviderKind
from ..security import ComplianceResult
from ..catalog import get_image
from .. import templating


def stage_host(spec: DeploymentSpec, compliance: ComplianceResult, *,
               mac: str | None = None, base_url: str | None = None,
               token: str | None = None, host_ip: str | None = None,
               timeout: float = 10.0) -> str:
    """Render per-host artifacts (backend Jinja2) and register them + a dnsmasq
    reservation on the PXE engine. Shared by the PXE provider and any hypervisor
    provider that boots its guests over the network. Returns the MAC used.

    Raises ProviderError on transport/engine failure.
    """
    import os as _os
    base_url = (base_url or _os.environ.get("PXE_ENGINE_URL", "http://pxe-engine:8081")).rstrip("/")
    token = token if token is not None else _os.environ.get("PXE_ENGINE_TOKEN", "")
    host_ip = host_ip or templating.host_ip_default()
    use_mac = (mac or spec.network.mac)
    if not use_mac:
        raise ProviderError("A MAC address is required to stage a network install.")

    image = get_image(spec.os_key)
    files = templating.render_host_artifacts(spec, compliance, host_ip)
    payload = {
        "mac": use_mac,
        "hostname": spec.hostname,
        "ip": spec.network.ip,
        "lease": spec.network.lease,
        "domain": spec.network.domain,
        "ipxe_chain": image.ipxe_chain if image else "",
        "hardening": [c.mechanism for c in compliance.applied],
        "files": files,
    }
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.post(f"{base_url}/api/v1/hosts", json=payload,
                             headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise ProviderError(f"PXE engine unreachable: {exc}") from exc
    if resp.status_code not in (200, 201):
        raise ProviderError(f"PXE engine rejected host ({resp.status_code}): {resp.text[:200]}")
    return use_mac


class PxeProvider(Provider):
    name = ProviderKind.PXE.value
    implemented = True

    def __init__(self, base_url: str | None = None, token: str | None = None,
                 timeout: float = 10.0):
        self.base_url = (base_url or os.environ.get(
            "PXE_ENGINE_URL", "http://pxe-engine:8081")).rstrip("/")
        self.token = token or os.environ.get("PXE_ENGINE_TOKEN", "")
        self.timeout = timeout

    # -- helpers --------------------------------------------------------------
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    # -- lifecycle ------------------------------------------------------------
    def preflight(self, spec: DeploymentSpec) -> list[str]:
        warnings: list[str] = []
        if not spec.network.mac:
            warnings.append("PXE requires a MAC address to pin the install.")
        image = get_image(spec.os_key)
        if image and image.firmware == "uefi":
            warnings.append("Target firmware must be set to UEFI (Secure Boot capable).")
        if image and image.notes:
            warnings.append(image.notes)
        try:
            requests.get(self._url("/api/v1/health"), timeout=self.timeout)
        except requests.RequestException:
            warnings.append("PXE engine is not reachable; deployment will be queued.")
        return warnings

    def create(self, spec: DeploymentSpec, compliance: ComplianceResult) -> ProviderResult:
        if get_image(spec.os_key) is None:
            raise ProviderError(f"Unknown OS image {spec.os_key!r}.")
        mac = stage_host(spec, compliance, base_url=self.base_url,
                         token=self.token, timeout=self.timeout)
        return ProviderResult(ok=True, provider_ref=mac,
                              message="Host reserved; target will install on next network boot.")

    def status(self, provider_ref: str) -> str:
        try:
            resp = requests.get(self._url(f"/api/v1/hosts/{provider_ref}"),
                                headers=self._headers(), timeout=self.timeout)
        except requests.RequestException:
            return "unknown"
        if resp.status_code == 200:
            return resp.json().get("status", "scheduled")
        return "unknown"

    def destroy(self, provider_ref: str) -> ProviderResult:
        try:
            resp = requests.delete(self._url(f"/api/v1/hosts/{provider_ref}"),
                                   headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as exc:
            raise ProviderError(f"PXE engine unreachable: {exc}") from exc
        if resp.status_code not in (200, 204):
            raise ProviderError(f"Failed to deregister host: {resp.status_code}")
        return ProviderResult(ok=True, provider_ref=provider_ref, message="Host deregistered.")
