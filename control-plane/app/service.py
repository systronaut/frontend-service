# Author: Systronaut
# Deployment orchestration: the one place that turns a validated spec into a
# persisted, audited, provider-staged deployment. Both the web UI and the REST
# API funnel through here so behaviour and audit trail stay identical.

import logging

from . import providers
from .models import DeploymentSpec, Deployment, DeploymentStatus, Provider
from .providers.base import derive_mac
from .providers.pxe import unstage_host
from .store import Store

log = logging.getLogger(__name__)


class DeployService:
    def __init__(self, store: Store):
        self.store = store

    def create(self, spec: DeploymentSpec, actor: str) -> Deployment:
        """Create + persist a deployment and hand it to its provider."""
        dep = self.store.create_deployment(spec)
        self.store.audit(actor, "deployment.create", dep.id,
                         f"{spec.os_key} via {spec.provider.value} "
                         f"[{spec.security_profile}]")

        provider = providers.get(spec.provider.value)
        compliance = spec.compliance()
        try:
            result = provider.create(spec, compliance)
        except NotImplementedError as exc:
            # Stubbed cloud provider: record intent, do not pretend success.
            dep.touch(DeploymentStatus.PENDING, str(exc))
            dep.provider_ref = ""
            self.store.save(dep)
            self.store.audit(actor, "deployment.preview", dep.id, "provider not implemented")
            return dep
        except providers.ProviderError as exc:
            dep.touch(DeploymentStatus.FAILED, str(exc))
            self.store.save(dep)
            self.store.audit(actor, "deployment.failed", dep.id, str(exc))
            return dep

        dep.provider_ref = result.provider_ref
        dep.touch(DeploymentStatus.SCHEDULED if result.ok else DeploymentStatus.FAILED,
                  result.message)
        self.store.save(dep)
        self.store.audit(actor, "deployment.scheduled", dep.id, result.message)
        return dep

    def refresh_status(self, dep: Deployment) -> Deployment:
        if not dep.provider_ref or dep.status in (
                DeploymentStatus.DESTROYED, DeploymentStatus.FAILED):
            return dep
        provider = providers.get(dep.spec.provider.value)
        raw = provider.status(dep.provider_ref)
        mapping = {
            "scheduled": DeploymentStatus.SCHEDULED,
            "installing": DeploymentStatus.INSTALLING,
            "ready": DeploymentStatus.READY,
            "done": DeploymentStatus.READY,
        }
        new_status = mapping.get(raw)
        if new_status and new_status != dep.status:
            dep.touch(new_status, f"status from provider: {raw}")
            self.store.save(dep)
        return dep

    def destroy(self, dep: Deployment, actor: str) -> Deployment:
        provider = providers.get(dep.spec.provider.value)
        try:
            if dep.provider_ref:
                provider.destroy(dep.provider_ref)
            dep.touch(DeploymentStatus.DESTROYED, "Deployment destroyed.")
            self.store.audit(actor, "deployment.destroy", dep.id)
        except (providers.ProviderError, NotImplementedError) as exc:
            dep.touch(DeploymentStatus.FAILED, f"destroy failed: {exc}")
            self.store.audit(actor, "deployment.destroy_failed", dep.id, str(exc))
        # Scrub PXE-rendered answers (Windows autounattend plaintext etc.).
        # PXE provider.destroy already DELETEs by MAC; this covers HV adapters
        # and is idempotent when the engine already purged the host.
        self._scrub_pxe_artifacts(dep)
        self.store.save(dep)
        return dep

    @staticmethod
    def _scrub_pxe_artifacts(dep: Deployment) -> None:
        """Best-effort removal of engine host/<slug>/ after destroy."""
        if dep.spec.provider == Provider.OPENSTACK:
            return  # OpenStack never stages on the PXE engine
        mac = ""
        if dep.spec.provider == Provider.PXE:
            mac = dep.provider_ref or dep.spec.network.mac or ""
        else:
            mac = dep.spec.network.mac or derive_mac(dep.spec.hostname)
        try:
            unstage_host(mac=mac, hostname=dep.spec.hostname)
        except providers.ProviderError as exc:
            log.warning("PXE artifact scrub after destroy failed for %s: %s",
                        dep.id, exc)
