# Author: Systronaut
# Real provider: KVM/QEMU via libvirt.
#
# Mirrors the vSphere adapter's contract on the PXE-staging path: define a
# UEFI/Secure-Boot domain whose NIC sits on the PXE L2 (a host bridge or a
# libvirt network that reaches the pxe-engine), pin it to a deterministic MAC,
# register that MAC + the hardened per-host artifacts on the PXE engine via the
# shared stage_host(), then start the domain so it network-boots into the same
# NIS2/ISO-27001/CIS install as bare metal and vSphere.
#
# libvirt-python is imported lazily inside methods so the module loads even when
# the SDK/host libs are absent; preflight() reports that instead of crashing.

import os
from xml.sax.saxutils import escape

from .base import Provider, ProviderResult, ProviderError, derive_mac
from .pxe import stage_host
from ..models import DeploymentSpec, Provider as ProviderKind
from ..security import ComplianceResult


class LibvirtProvider(Provider):
    name = ProviderKind.LIBVIRT.value
    implemented = True
    # LIBVIRT_BRIDGE (host bridge on the PXE LAN) OR LIBVIRT_NETWORK (libvirt net)
    # must reach the pxe-engine; one of the two is required.
    required_env = ("LIBVIRT_URI",)

    def __init__(self):
        self.uri = os.environ.get("LIBVIRT_URI", "qemu:///system")
        self.bridge = os.environ.get("LIBVIRT_BRIDGE", "")
        self.network = os.environ.get("LIBVIRT_NETWORK", "")
        self.pool = os.environ.get("LIBVIRT_POOL", "default")
        self.disk_gb = int(os.environ.get("LIBVIRT_DISK_GB", "40"))

    # -- helpers --------------------------------------------------------------
    def _connect(self):
        try:
            import libvirt
        except ImportError as exc:
            raise ProviderError(
                "libvirt-python is not installed (pip install libvirt-python; "
                "needs system libvirt libs).") from exc
        try:
            conn = libvirt.open(self.uri)
        except libvirt.libvirtError as exc:
            raise ProviderError(f"libvirt connection to {self.uri!r} failed: {exc}") from exc
        if conn is None:
            raise ProviderError(f"Could not open libvirt connection to {self.uri!r}.")
        return conn

    def _nic_xml(self, mac: str) -> str:
        if self.bridge:
            source = f"<source bridge='{escape(self.bridge)}'/>"
            iface_type = "bridge"
        else:
            source = f"<source network='{escape(self.network)}'/>"
            iface_type = "network"
        return (
            f"<interface type='{iface_type}'>"
            f"<mac address='{mac}'/>{source}"
            f"<model type='virtio'/></interface>"
        )

    def _ensure_volume(self, conn, name: str) -> str:
        """Create an empty qcow2 volume in the configured pool; return its path.

        Idempotent: if the volume already exists it is reused (so re-running
        create() for the same hostname does not error)."""
        try:
            import libvirt
            pool = conn.storagePoolLookupByName(self.pool)
        except libvirt.libvirtError as exc:
            raise ProviderError(f"Storage pool {self.pool!r} not found: {exc}") from exc
        vol_name = f"{name}.qcow2"
        try:
            return pool.storageVolLookupByName(vol_name).path()
        except libvirt.libvirtError:
            pass  # not present yet -> create below
        capacity = self.disk_gb * 1024 * 1024 * 1024
        vol_xml = (
            f"<volume><name>{escape(vol_name)}</name>"
            f"<capacity unit='bytes'>{capacity}</capacity>"
            f"<target><format type='qcow2'/></target></volume>"
        )
        try:
            return pool.createXML(vol_xml, 0).path()
        except libvirt.libvirtError as exc:
            raise ProviderError(f"Volume create failed: {exc}") from exc

    def _domain_xml(self, spec: DeploymentSpec, mac: str, disk_path: str) -> str:
        return (
            "<domain type='kvm'>"
            f"<name>{escape(spec.hostname)}</name>"
            f"<memory unit='MiB'>{spec.memory_mb}</memory>"
            f"<vcpu>{spec.cpu}</vcpu>"
            # firmware autoselect with Secure Boot + pre-enrolled keys (NIS2/ISO).
            "<os firmware='efi'>"
            "<type arch='x86_64' machine='q35'>hvm</type>"
            "<firmware>"
            "<feature enabled='yes' name='secure-boot'/>"
            "<feature enabled='yes' name='enrolled-keys'/>"
            "</firmware>"
            "<boot dev='network'/><boot dev='hd'/>"
            "</os>"
            # SMM is required for Secure Boot on q35.
            "<features><acpi/><apic/><smm state='on'/></features>"
            "<cpu mode='host-passthrough'/>"
            "<devices>"
            "<disk type='file' device='disk'>"
            "<driver name='qemu' type='qcow2'/>"
            f"<source file='{escape(disk_path)}'/>"
            "<target dev='vda' bus='virtio'/></disk>"
            f"{self._nic_xml(mac)}"
            "<graphics type='vnc' port='-1'/>"
            "<video><model type='virtio'/></video>"
            "<console type='pty'/>"
            "</devices>"
            "</domain>"
        )

    def _lookup(self, conn, provider_ref: str):
        import libvirt
        try:
            return conn.lookupByUUIDString(provider_ref)
        except libvirt.libvirtError:
            return None

    # -- lifecycle ------------------------------------------------------------
    def preflight(self, spec: DeploymentSpec) -> list[str]:
        warnings: list[str] = []
        try:
            import libvirt  # noqa: F401
        except ImportError:
            warnings.append("libvirt-python not installed; libvirt deploys will fail "
                            "until you `pip install libvirt-python`.")
        if not self.bridge and not self.network:
            warnings.append("Set LIBVIRT_BRIDGE (host bridge on the PXE LAN) or "
                            "LIBVIRT_NETWORK; the guest NIC must reach the pxe-engine.")
        warnings.append("The guest must UEFI Secure-Boot on the PXE L2 to follow the "
                        "hardened install path.")
        return warnings

    def create(self, spec: DeploymentSpec, compliance: ComplianceResult) -> ProviderResult:
        mac = spec.network.mac or derive_mac(spec.hostname)
        conn = self._connect()
        try:
            disk_path = self._ensure_volume(conn, spec.hostname)
            xml = self._domain_xml(spec, mac, disk_path)
            try:
                dom = conn.defineXML(xml)
            except Exception as exc:
                raise ProviderError(f"Domain define failed: {exc}") from exc
            # Stage the hardened per-MAC install on the PXE engine, then boot.
            stage_host(spec, compliance, mac=mac)
            try:
                dom.create()
            except Exception as exc:
                raise ProviderError(f"Domain start failed: {exc}") from exc
            return ProviderResult(
                ok=True, provider_ref=dom.UUIDString(),
                message=f"Domain {spec.hostname!r} started; PXE-installing as {mac}.")
        finally:
            conn.close()

    def status(self, provider_ref: str) -> str:
        try:
            conn = self._connect()
            import libvirt
        except (ProviderError, ImportError):
            return "unknown"
        try:
            dom = self._lookup(conn, provider_ref)
            if dom is None:
                return "unknown"
            state = dom.state()[0]
            return "ready" if state == libvirt.VIR_DOMAIN_RUNNING else "scheduled"
        except libvirt.libvirtError:
            return "unknown"
        finally:
            conn.close()

    # -- inventory (Hypervisors view) ----------------------------------------
    def inventory(self):
        from .base import HypervisorInventory, VmInfo
        try:
            import libvirt
            conn = self._connect()
        except (ProviderError, ImportError) as exc:
            return HypervisorInventory(provider=self.name, endpoint=self.uri,
                                       connected=False, message=str(exc))
        try:
            vms = []
            for dom in conn.listAllDomains():
                info = dom.info()   # [state, maxMem KiB, memory, nrVirtCpu, cpuTime]
                vms.append(VmInfo(
                    name=dom.name(),
                    state="running" if info[0] == libvirt.VIR_DOMAIN_RUNNING else "stopped",
                    vcpu=int(info[3] or 0), memory_mb=int((info[1] or 0) // 1024),
                    ref=dom.UUIDString()))
            ni = conn.getInfo()     # [model, memoryMB, cpus, mhz, ...]
            return HypervisorInventory(provider=self.name, endpoint=self.uri, connected=True,
                                       cpu_total=int(ni[2] or 0), memory_mb=int(ni[1] or 0),
                                       vms=tuple(vms))
        except Exception as exc:
            return HypervisorInventory(provider=self.name, endpoint=self.uri,
                                       connected=False, message=str(exc))
        finally:
            conn.close()

    def destroy(self, provider_ref: str) -> ProviderResult:
        conn = self._connect()  # raises ProviderError if libvirt-python is absent
        import libvirt
        try:
            dom = self._lookup(conn, provider_ref)
            if dom is None:
                raise ProviderError(f"Domain {provider_ref!r} not found.")
            try:
                if dom.isActive():
                    dom.destroy()  # force power-off (no graceful guest here)
                # Remove the domain and its owned storage volume.
                flags = (libvirt.VIR_DOMAIN_UNDEFINE_NVRAM |
                         libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE)
                dom.undefineFlags(flags)
            except libvirt.libvirtError as exc:
                raise ProviderError(f"Destroy failed: {exc}") from exc
            return ProviderResult(ok=True, provider_ref=provider_ref,
                                  message="Domain destroyed.")
        finally:
            conn.close()
