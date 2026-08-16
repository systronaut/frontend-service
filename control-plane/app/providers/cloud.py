# Author: Systronaut
# Hypervisor / cloud adapters.
#   - vSphere : REAL (pyVmomi). Creates a UEFI/Secure-Boot VM on the PXE port
#               group, reads its generated MAC, stages the hardened install via
#               the shared PXE path, then powers on so it network-boots into the
#               same NIS2/ISO-27001/CIS install as bare metal.
#   - ESXi      : REAL (subclass of VsphereProvider; connects to standalone host).
#   - OpenStack : stubbed adapter (real contract + credential surface; no PXE path).
#
# pyVmomi is imported lazily inside methods so the module loads even when the SDK
# is absent; preflight() reports that clearly instead of crashing the app.

import os

from .base import (Provider, ProviderResult, ProviderError,
                   HypervisorInventory, VmInfo)
from .pxe import stage_host
from ..models import DeploymentSpec, Provider as ProviderKind
from ..security import ComplianceResult


# --- stubbed adapters --------------------------------------------------------
class _CloudStub(Provider):
    implemented = False
    required_env: tuple[str, ...] = ()
    sdk_hint: str = ""

    def preflight(self, spec: DeploymentSpec) -> list[str]:
        warnings = [f"Provider '{self.name}' is a preview adapter (not yet implemented)."]
        missing = [name for name in self.required_env if not os.environ.get(name)]
        if missing:
            warnings.append("Missing credentials: " + ", ".join(missing) + ".")
        return warnings

    def create(self, spec, compliance) -> ProviderResult:
        raise NotImplementedError(
            f"{self.name} provisioning is not implemented yet. Implement via "
            f"{self.sdk_hint} in providers/cloud.py, then attach the guest to the "
            f"PXE network so it follows the hardened install path.")

    def status(self, provider_ref: str) -> str:
        return "preview"

    def destroy(self, provider_ref: str) -> ProviderResult:
        raise NotImplementedError(f"{self.name} destroy is not implemented yet.")


class OpenstackProvider(_CloudStub):
    name = ProviderKind.OPENSTACK.value
    required_env = ("OS_AUTH_URL", "OS_USERNAME", "OS_PASSWORD", "OS_PROJECT_NAME")
    # NOTE: Nova instances do NOT PXE-boot, so OpenStack cannot reuse stage_host()
    # like libvirt/proxmox/vSphere. It needs a different hardened-install path:
    # a curated hardened base image + a config-drive/cloud-init payload that
    # applies the CIS/NIS2 controls on first boot. That second install path is
    # out of scope for this stub; see REQUIREMENTS.md ("OpenStack").
    sdk_hint = ("openstacksdk (connection.compute.create_server) with a hardened "
                "image + cloud-init rendering the compliance controls (no PXE)")


# --- real vSphere adapter ----------------------------------------------------
class VsphereProvider(Provider):
    name = ProviderKind.VSPHERE.value
    implemented = True
    required_env = ("VSPHERE_HOST", "VSPHERE_USER", "VSPHERE_PASSWORD",
                    "VSPHERE_DATACENTER", "VSPHERE_DATASTORE", "VSPHERE_NETWORK")

    def __init__(self):
        self.host = os.environ.get("VSPHERE_HOST", "")
        self.user = os.environ.get("VSPHERE_USER", "")
        self.password = os.environ.get("VSPHERE_PASSWORD", "")
        self.datacenter = os.environ.get("VSPHERE_DATACENTER", "")
        self.cluster = os.environ.get("VSPHERE_CLUSTER", "")
        self.datastore = os.environ.get("VSPHERE_DATASTORE", "")
        self.network = os.environ.get("VSPHERE_NETWORK", "")  # PXE port group
        self.folder = os.environ.get("VSPHERE_FOLDER", "")
        # TLS is verified by default. Only skip for self-signed dev certs by
        # explicitly setting VSPHERE_INSECURE=1 (prefer adding the CA to the
        # trust store instead).
        self.insecure = os.environ.get("VSPHERE_INSECURE", "0") == "1"

    # -- helpers --------------------------------------------------------------
    def _connect(self):
        try:
            from pyVim.connect import SmartConnect
            import ssl
        except ImportError as exc:
            raise ProviderError("pyVmomi is not installed (pip install pyvmomi).") from exc
        ctx = None
        if self.insecure:
            ctx = ssl._create_unverified_context()
        try:
            return SmartConnect(host=self.host, user=self.user, pwd=self.password,
                                sslContext=ctx)
        except Exception as exc:  # pyVmomi raises vim faults
            raise ProviderError(f"vCenter connection failed: {exc}") from exc

    @staticmethod
    def _find(content, vimtype, name):
        container = content.viewManager.CreateContainerView(
            content.rootFolder, [vimtype], True)
        try:
            for obj in container.view:
                if obj.name == name:
                    return obj
        finally:
            container.Destroy()
        return None

    # -- lifecycle ------------------------------------------------------------
    def preflight(self, spec: DeploymentSpec) -> list[str]:
        warnings: list[str] = []
        missing = [n for n in self.required_env if not os.environ.get(n)]
        if missing:
            warnings.append("Missing vSphere settings: " + ", ".join(missing) + ".")
        try:
            import pyVmomi  # noqa: F401
        except ImportError:
            warnings.append("pyVmomi not installed; vSphere deploys will fail until "
                            "you `pip install pyvmomi`.")
        warnings.append("The new VM must sit on the PXE port group and boot UEFI "
                        "Secure Boot to follow the hardened install path.")
        return warnings

    def create(self, spec: DeploymentSpec, compliance: ComplianceResult) -> ProviderResult:
        try:
            from pyVmomi import vim
        except ImportError as exc:
            raise ProviderError("pyVmomi is not installed (pip install pyvmomi).") from exc
        si = self._connect()
        content = si.RetrieveContent()

        dc = self._find(content, vim.Datacenter, self.datacenter)
        if dc is None:
            raise ProviderError(f"Datacenter {self.datacenter!r} not found.")
        datastore = self._find(content, vim.Datastore, self.datastore)
        if datastore is None:
            raise ProviderError(f"Datastore {self.datastore!r} not found.")
        network = self._find(content, vim.Network, self.network)
        if network is None:
            raise ProviderError(f"Network (port group) {self.network!r} not found.")
        cluster = (self._find(content, vim.ClusterComputeResource, self.cluster)
                   if self.cluster else None)
        pool = cluster.resourcePool if cluster else self._first_resource_pool(content)
        if pool is None:
            raise ProviderError("No resource pool found (set VSPHERE_CLUSTER).")
        vmfolder = (self._find(content, vim.Folder, self.folder)
                    if self.folder else dc.vmFolder)

        # NIC on the PXE port group.
        nic = vim.vm.device.VirtualDeviceSpec()
        nic.operation = vim.vm.device.VirtualDeviceSpec.Operation.add
        nic.device = vim.vm.device.VirtualVmxnet3()
        nic.device.backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo()
        nic.device.backing.network = network
        nic.device.backing.deviceName = self.network
        nic.device.connectable = vim.vm.device.VirtualDeviceConnectInfo()
        nic.device.connectable.startConnected = True
        nic.device.connectable.allowGuestControl = True

        files = vim.vm.FileInfo(vmPathName=f"[{self.datastore}]")
        boot = vim.vm.BootOptions(
            bootOrder=[vim.vm.BootOptions.BootableEthernetDevice()])
        config = vim.vm.ConfigSpec(
            name=spec.hostname,
            memoryMB=spec.memory_mb,
            numCPUs=spec.cpu,
            guestId="otherGuest64",
            firmware="efi",
            bootOptions=boot,
            files=files,
            deviceChange=[nic],
        )
        # Secure Boot (NIS2/ISO control). Available on recent vCenter.
        try:
            config.bootOptions.efiSecureBootEnabled = True
        except Exception:
            pass

        try:
            task = vmfolder.CreateVM_Task(config=config, pool=pool)
            vm = self._wait(task)
        except Exception as exc:
            raise ProviderError(f"CreateVM failed: {exc}") from exc

        mac = self._nic_mac(vm)
        if not mac:
            raise ProviderError("Could not read the new VM's MAC address.")

        # Stage the hardened install for this MAC on the PXE engine, then boot.
        stage_host(spec, compliance, mac=mac)
        try:
            self._wait(vm.PowerOnVM_Task())
        except Exception as exc:
            raise ProviderError(f"Power-on failed: {exc}") from exc

        return ProviderResult(ok=True, provider_ref=str(vm._moId),
                              message=f"VM created on {self.network}; PXE-installing as {mac}.")

    def status(self, provider_ref: str) -> str:
        try:
            from pyVmomi import vim
        except ImportError:
            return "unknown"
        try:
            si = self._connect()
            content = si.RetrieveContent()
            for vm in self._all(content, vim.VirtualMachine):
                if vm._moId == provider_ref:
                    return "ready" if vm.runtime.powerState == "poweredOn" else "scheduled"
        except ProviderError:
            return "unknown"
        return "unknown"

    def destroy(self, provider_ref: str) -> ProviderResult:
        try:
            from pyVmomi import vim
        except ImportError as exc:
            raise ProviderError("pyVmomi is not installed (pip install pyvmomi).") from exc
        si = self._connect()
        content = si.RetrieveContent()
        for vm in self._all(content, vim.VirtualMachine):
            if vm._moId == provider_ref:
                try:
                    if vm.runtime.powerState == "poweredOn":
                        self._wait(vm.PowerOffVM_Task())
                    self._wait(vm.Destroy_Task())
                except Exception as exc:
                    raise ProviderError(f"Destroy failed: {exc}") from exc
                return ProviderResult(ok=True, provider_ref=provider_ref,
                                      message="VM destroyed.")
        raise ProviderError(f"VM {provider_ref!r} not found.")

    # -- inventory (Hypervisors view) ----------------------------------------
    def inventory(self) -> HypervisorInventory | None:
        try:
            from pyVmomi import vim
        except ImportError:
            return HypervisorInventory(provider=self.name, endpoint=self.host,
                                       connected=False, message="pyVmomi not installed")
        try:
            si = self._connect()
            content = si.RetrieveContent()
        except ProviderError as exc:
            return HypervisorInventory(provider=self.name, endpoint=self.host,
                                       connected=False, message=str(exc))
        vms: list[VmInfo] = []
        for vm in self._all(content, vim.VirtualMachine):
            try:
                cfg, rt = vm.summary.config, vm.summary.runtime
                committed = getattr(vm.summary.storage, "committed", 0) or 0
                vms.append(VmInfo(
                    name=cfg.name or "vm",
                    state="running" if rt.powerState == "poweredOn" else "stopped",
                    vcpu=int(cfg.numCpu or 0), memory_mb=int(cfg.memorySizeMB or 0),
                    disk_gb=int(committed // (1024 ** 3)), ref=vm._moId))
            except Exception:
                continue
        cpu_total = mem_mb = storage_gb = 0
        for host in self._all(content, vim.HostSystem):
            try:
                hw = host.hardware
                cpu_total += int(getattr(hw.cpuInfo, "numCpuThreads", 0) or 0)
                mem_mb += int((hw.memorySize or 0) // (1024 * 1024))
            except Exception:
                continue
        for ds in self._all(content, vim.Datastore):
            try:
                storage_gb += int((ds.summary.capacity or 0) // (1024 ** 3))
            except Exception:
                continue
        return HypervisorInventory(provider=self.name, endpoint=self.host, connected=True,
                                   cpu_total=cpu_total, memory_mb=mem_mb, storage_gb=storage_gb,
                                   vms=tuple(vms))

    # -- low-level helpers ----------------------------------------------------
    @staticmethod
    def _wait(task):
        import time
        while task.info.state not in ("success", "error"):
            time.sleep(1)
        if task.info.state == "error":
            raise RuntimeError(getattr(task.info.error, "msg", "task error"))
        return task.info.result

    @staticmethod
    def _nic_mac(vm):
        from pyVmomi import vim
        for dev in vm.config.hardware.device:
            if isinstance(dev, vim.vm.device.VirtualEthernetCard) and dev.macAddress:
                return dev.macAddress.lower()
        return ""

    @staticmethod
    def _all(content, vimtype):
        view = content.viewManager.CreateContainerView(
            content.rootFolder, [vimtype], True)
        try:
            return list(view.view)
        finally:
            view.Destroy()

    def _first_resource_pool(self, content):
        from pyVmomi import vim
        return next(iter(self._all(content, vim.ResourcePool)), None)


# --- real standalone ESXi adapter -------------------------------------------
class EsxiProvider(VsphereProvider):
    """Standalone ESXi host (no vCenter). Reuses every pyVmomi path from the
    vSphere adapter but connects straight to the host, defaults to the single
    'ha-datacenter', and trusts the host's self-signed cert by default."""

    name = ProviderKind.ESXI.value
    implemented = True
    required_env = ("ESXI_HOST", "ESXI_USER", "ESXI_PASSWORD")

    def __init__(self):
        self.host = os.environ.get("ESXI_HOST", "")
        self.user = os.environ.get("ESXI_USER", "")
        self.password = os.environ.get("ESXI_PASSWORD", "")
        self.datacenter = os.environ.get("ESXI_DATACENTER", "ha-datacenter")
        self.cluster = ""                       # standalone: use the host's pool
        self.datastore = os.environ.get("ESXI_DATASTORE", "")
        self.network = os.environ.get("ESXI_NETWORK", "")
        self.folder = ""
        # ESXi ships a self-signed cert; default to skipping verification. Set
        # ESXI_INSECURE=0 once you have added the host CA to the trust store.
        self.insecure = os.environ.get("ESXI_INSECURE", "1") == "1"
