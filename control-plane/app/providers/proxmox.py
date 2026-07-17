# Author: Systronaut
# Real provider: Proxmox VE (QEMU/KVM) via the Proxmox REST API (proxmoxer).
#
# Same PXE-staging contract as the vSphere/libvirt adapters: create an
# OVMF/Secure-Boot VM whose net0 sits on the PXE bridge (a Linux bridge that
# reaches the pxe-engine), pin it to a deterministic MAC, register that MAC +
# the hardened per-host artifacts via the shared stage_host(), then start the VM
# so it network-boots into the same NIS2/ISO-27001/CIS install.
#
# Auth prefers an API token (PROXMOX_TOKEN_NAME + PROXMOX_TOKEN_VALUE); falls
# back to password. proxmoxer is imported lazily so the module loads without it.

import os

from .base import (Provider, ProviderResult, ProviderError, derive_mac,
                   HypervisorInventory, VmInfo)
from .pxe import stage_host
from ..models import DeploymentSpec, Provider as ProviderKind
from ..security import ComplianceResult


class ProxmoxProvider(Provider):
    name = ProviderKind.PROXMOX.value
    implemented = True
    required_env = ("PROXMOX_HOST", "PROXMOX_USER", "PROXMOX_NODE")

    def __init__(self):
        self.host = os.environ.get("PROXMOX_HOST", "")
        self.user = os.environ.get("PROXMOX_USER", "")          # e.g. root@pam
        self.password = os.environ.get("PROXMOX_PASSWORD", "")
        self.token_name = os.environ.get("PROXMOX_TOKEN_NAME", "")
        self.token_value = os.environ.get("PROXMOX_TOKEN_VALUE", "")
        self.node = os.environ.get("PROXMOX_NODE", "")
        self.storage = os.environ.get("PROXMOX_STORAGE", "local-lvm")
        self.bridge = os.environ.get("PROXMOX_BRIDGE", "vmbr0")  # PXE LAN bridge
        self.disk_gb = int(os.environ.get("PROXMOX_DISK_GB", "40"))
        # TLS verified by default; set PROXMOX_INSECURE=1 only for dev self-signed.
        self.verify_ssl = os.environ.get("PROXMOX_INSECURE", "0") != "1"

    # -- helpers --------------------------------------------------------------
    def _connect(self):
        try:
            from proxmoxer import ProxmoxAPI
        except ImportError as exc:
            raise ProviderError("proxmoxer is not installed (pip install proxmoxer).") from exc
        kwargs = {"user": self.user, "verify_ssl": self.verify_ssl}
        if self.token_name and self.token_value:
            kwargs["token_name"] = self.token_name
            kwargs["token_value"] = self.token_value
        elif self.password:
            kwargs["password"] = self.password
        else:
            raise ProviderError(
                "Proxmox needs PROXMOX_TOKEN_NAME+PROXMOX_TOKEN_VALUE or PROXMOX_PASSWORD.")
        try:
            return ProxmoxAPI(self.host, **kwargs)
        except Exception as exc:
            raise ProviderError(f"Proxmox connection failed: {exc}") from exc

    def _find_vmid(self, prox, hostname: str) -> int | None:
        """Return the VMID of an existing VM with this name (idempotency)."""
        try:
            for vm in prox.nodes(self.node).qemu.get():
                if vm.get("name") == hostname:
                    return int(vm["vmid"])
        except Exception:
            return None
        return None

    # -- lifecycle ------------------------------------------------------------
    def preflight(self, spec: DeploymentSpec) -> list[str]:
        warnings: list[str] = []
        missing = [n for n in self.required_env if not os.environ.get(n)]
        if missing:
            warnings.append("Missing Proxmox settings: " + ", ".join(missing) + ".")
        if not (self.token_name and self.token_value) and not self.password:
            warnings.append("Set a PROXMOX API token (preferred) or PROXMOX_PASSWORD.")
        try:
            import proxmoxer  # noqa: F401
        except ImportError:
            warnings.append("proxmoxer not installed; Proxmox deploys will fail until "
                            "you `pip install proxmoxer`.")
        warnings.append(f"net0 uses bridge {self.bridge!r}; it must reach the pxe-engine, "
                        "and the VM boots UEFI Secure Boot into the hardened install.")
        return warnings

    def create(self, spec: DeploymentSpec, compliance: ComplianceResult) -> ProviderResult:
        mac = (spec.network.mac or derive_mac(spec.hostname)).upper()
        prox = self._connect()
        node = prox.nodes(self.node)

        vmid = self._find_vmid(prox, spec.hostname)
        if vmid is None:
            try:
                vmid = int(prox.cluster.nextid.get())
            except Exception as exc:
                raise ProviderError(f"Could not allocate a VMID: {exc}") from exc
            config = {
                "vmid": vmid,
                "name": spec.hostname,
                "memory": spec.memory_mb,
                "cores": spec.cpu,
                "sockets": 1,
                "cpu": "host",
                "machine": "q35",
                "ostype": "l26",
                "bios": "ovmf",
                # Secure Boot: OVMF + efidisk with pre-enrolled MS keys.
                "efidisk0": f"{self.storage}:0,efitype=4m,pre-enrolled-keys=1",
                "scsihw": "virtio-scsi-single",
                "scsi0": f"{self.storage}:{self.disk_gb}",
                "net0": f"virtio={mac},bridge={self.bridge},firewall=0",
                "boot": "order=net0;scsi0",
                "agent": "enabled=1",
            }
            try:
                node.qemu.create(**config)
            except Exception as exc:
                raise ProviderError(f"Proxmox VM create failed: {exc}") from exc

        # Stage the hardened per-MAC install on the PXE engine, then start.
        stage_host(spec, compliance, mac=mac.lower())
        try:
            node.qemu(vmid).status.start.post()
        except Exception as exc:
            raise ProviderError(f"Proxmox VM start failed: {exc}") from exc

        return ProviderResult(
            ok=True, provider_ref=f"{self.node}/{vmid}",
            message=f"VM {vmid} on {self.bridge}; PXE-installing as {mac.lower()}.")

    def status(self, provider_ref: str) -> str:
        node_name, vmid = self._split_ref(provider_ref)
        if vmid is None:
            return "unknown"
        try:
            prox = self._connect()
            cur = prox.nodes(node_name).qemu(vmid).status.current.get()
        except (ProviderError, Exception):
            return "unknown"
        return "ready" if cur.get("status") == "running" else "scheduled"

    def destroy(self, provider_ref: str) -> ProviderResult:
        node_name, vmid = self._split_ref(provider_ref)
        if vmid is None:
            raise ProviderError(f"Malformed Proxmox ref {provider_ref!r}.")
        prox = self._connect()
        vm = prox.nodes(node_name).qemu(vmid)
        try:
            if vm.status.current.get().get("status") == "running":
                vm.status.stop.post()
            vm.delete()
        except Exception as exc:
            raise ProviderError(f"Proxmox destroy failed: {exc}") from exc
        return ProviderResult(ok=True, provider_ref=provider_ref, message="VM destroyed.")

    @staticmethod
    def _split_ref(provider_ref: str):
        parts = provider_ref.split("/", 1)
        if len(parts) != 2 or not parts[1].isdigit():
            return provider_ref, None
        return parts[0], int(parts[1])

    # -- inventory (Hypervisors view) ----------------------------------------
    def inventory(self) -> HypervisorInventory | None:
        if not (self.host and self.node):
            return None
        try:
            prox = self._connect()
            node = prox.nodes(self.node)
            st = node.status.get()
            vms = [
                VmInfo(
                    name=vm.get("name") or str(vm.get("vmid")),
                    state="running" if vm.get("status") == "running" else "stopped",
                    vcpu=int(vm.get("cpus", 0) or 0),
                    memory_mb=int((vm.get("maxmem", 0) or 0) // (1024 * 1024)),
                    disk_gb=int((vm.get("maxdisk", 0) or 0) // (1024 ** 3)),
                    ref=str(vm.get("vmid")))
                for vm in node.qemu.get()
            ]
        except (ProviderError, Exception) as exc:
            return HypervisorInventory(provider=self.name, endpoint=self.host,
                                       connected=False, message=str(exc))
        cpu_total = int((st.get("cpuinfo", {}) or {}).get("cpus", 0) or 0)
        mem_total = int(((st.get("memory", {}) or {}).get("total", 0) or 0) // (1024 * 1024))
        storage_gb = 0
        try:
            for s in node.storage.get():
                storage_gb += int((s.get("total", 0) or 0) // (1024 ** 3))
        except Exception:
            pass
        return HypervisorInventory(
            provider=self.name, endpoint=f"{self.host} ({self.node})", connected=True,
            cpu_total=cpu_total, memory_mb=mem_total, storage_gb=storage_gb, vms=tuple(vms))
