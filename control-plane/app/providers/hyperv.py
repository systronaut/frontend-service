# Author: Systronaut
# Real provider: Microsoft Hyper-V via WinRM / PowerShell (pypsrp).
#
# Same PXE-staging contract as the libvirt/proxmox/vSphere adapters: create a
# Generation-2 (UEFI/Secure-Boot) VM on the PXE virtual switch, pin its MAC,
# register that MAC + the hardened per-host artifacts via the shared
# stage_host(), then start the VM so it network-boots into the hardened install.
#
# The control plane runs on Linux, so it drives the remote Hyper-V host over
# WinRM by executing Hyper-V PowerShell cmdlets. pypsrp is imported lazily so the
# module loads without it; preflight() reports clearly when it is missing.

import os

from .base import (Provider, ProviderResult, ProviderError, derive_mac,
                   HypervisorInventory, VmInfo)
from .pxe import stage_host
from ..models import DeploymentSpec, Provider as ProviderKind
from ..security import ComplianceResult


def _hv_mac(mac: str) -> str:
    """Hyper-V wants a 12-hex-digit MAC, no separators, upper-case."""
    return mac.replace(":", "").replace("-", "").upper()


class HypervProvider(Provider):
    name = ProviderKind.HYPERV.value
    implemented = True
    required_env = ("HYPERV_HOST", "HYPERV_USER", "HYPERV_PASSWORD", "HYPERV_SWITCH")

    def __init__(self):
        self.host = os.environ.get("HYPERV_HOST", "")
        self.user = os.environ.get("HYPERV_USER", "")
        self.password = os.environ.get("HYPERV_PASSWORD", "")
        self.switch = os.environ.get("HYPERV_SWITCH", "")          # PXE vSwitch
        self.vhd_dir = os.environ.get("HYPERV_VHD_PATH", "C:\\ProgramData\\Systronaut\\vhd")
        self.disk_gb = int(os.environ.get("HYPERV_DISK_GB", "40"))
        self.use_ssl = os.environ.get("HYPERV_SSL", "1") != "0"    # 5986 by default
        # TLS verified by default; opt out only for dev self-signed WinRM certs.
        self.verify = os.environ.get("HYPERV_INSECURE", "0") != "1"

    # -- helpers --------------------------------------------------------------
    def _client(self):
        try:
            from pypsrp.client import Client
        except ImportError as exc:
            raise ProviderError("pypsrp is not installed (pip install pypsrp).") from exc
        try:
            return Client(self.host, username=self.user, password=self.password,
                          ssl=self.use_ssl, cert_validation=self.verify, auth="negotiate")
        except Exception as exc:
            raise ProviderError(f"Hyper-V WinRM connection failed: {exc}") from exc

    def _ps(self, script: str) -> str:
        """Run a PowerShell script on the host; raise ProviderError on failure."""
        client = self._client()
        try:
            output, streams, had_errors = client.execute_ps(script)
        except Exception as exc:
            raise ProviderError(f"Hyper-V PowerShell error: {exc}") from exc
        if had_errors:
            err = "; ".join(str(getattr(e, "message", e)) for e in (streams.error or []))
            raise ProviderError(f"Hyper-V command failed: {err or 'unknown error'}")
        return output or ""

    # -- lifecycle ------------------------------------------------------------
    def preflight(self, spec: DeploymentSpec) -> list[str]:
        warnings: list[str] = []
        missing = [n for n in self.required_env if not os.environ.get(n)]
        if missing:
            warnings.append("Missing Hyper-V settings: " + ", ".join(missing) + ".")
        try:
            import pypsrp  # noqa: F401
        except ImportError:
            warnings.append("pypsrp not installed; Hyper-V deploys will fail until "
                            "you `pip install pypsrp`.")
        warnings.append(f"VM is created Generation 2 on vSwitch {self.switch!r}; it must "
                        "reach the pxe-engine and Secure-Boot into the hardened install.")
        return warnings

    def create(self, spec: DeploymentSpec, compliance: ComplianceResult) -> ProviderResult:
        name = spec.hostname
        mac = _hv_mac(spec.network.mac or derive_mac(name))
        vhd = f"{self.vhd_dir}\\{name}.vhdx"
        mem_mb = spec.memory_mb
        # Gen-2 VM, PXE vSwitch, static MAC, Secure Boot on, boot from network.
        script = f"""
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path '{self.vhd_dir}' | Out-Null
if (-not (Get-VM -Name '{name}' -ErrorAction SilentlyContinue)) {{
  New-VM -Name '{name}' -MemoryStartupBytes {mem_mb}MB -Generation 2 `
    -SwitchName '{self.switch}' -NewVHDPath '{vhd}' -NewVHDSizeBytes {self.disk_gb}GB | Out-Null
}}
Set-VM -Name '{name}' -ProcessorCount {spec.cpu} -AutomaticStartAction Nothing
Set-VMNetworkAdapter -VMName '{name}' -StaticMacAddress '{mac}'
Set-VMFirmware -VMName '{name}' -EnableSecureBoot On `
  -SecureBootTemplate 'MicrosoftUEFICertificateAuthority'
$nic = Get-VMNetworkAdapter -VMName '{name}'
Set-VMFirmware -VMName '{name}' -FirstBootDevice $nic
(Get-VM -Name '{name}').Id.Guid
"""
        vm_id = self._ps(script).strip().splitlines()[-1].strip() if True else ""

        # Stage the hardened per-MAC install on the PXE engine, then start.
        stage_host(spec, compliance, mac=(spec.network.mac or derive_mac(name)))
        self._ps(f"Start-VM -Name '{name}'")

        return ProviderResult(
            ok=True, provider_ref=name,
            message=f"Hyper-V VM '{name}' ({vm_id}) started on {self.switch}; "
                    f"PXE-installing as {mac}.")

    def status(self, provider_ref: str) -> str:
        try:
            state = self._ps(
                f"(Get-VM -Name '{provider_ref}' -ErrorAction SilentlyContinue).State"
            ).strip()
        except ProviderError:
            return "unknown"
        if state == "Running":
            return "ready"
        if state:
            return "scheduled"
        return "unknown"

    def destroy(self, provider_ref: str) -> ProviderResult:
        self._ps(f"""
$ErrorActionPreference = 'Stop'
$vm = Get-VM -Name '{provider_ref}' -ErrorAction SilentlyContinue
if ($vm) {{
  if ($vm.State -eq 'Running') {{ Stop-VM -Name '{provider_ref}' -TurnOff -Force }}
  $disks = (Get-VMHardDiskDrive -VMName '{provider_ref}').Path
  Remove-VM -Name '{provider_ref}' -Force
  foreach ($d in $disks) {{ Remove-Item -Path $d -Force -ErrorAction SilentlyContinue }}
}}
""")
        return ProviderResult(ok=True, provider_ref=provider_ref, message="Hyper-V VM destroyed.")

    # -- inventory (Hypervisors view) ----------------------------------------
    def inventory(self) -> HypervisorInventory | None:
        if not all(os.environ.get(n) for n in self.required_env):
            return None
        try:
            raw = self._ps(r"""
$ErrorActionPreference = 'Stop'
$vms = Get-VM | ForEach-Object {
  '{0}|{1}|{2}|{3}' -f $_.Name, $_.State, $_.ProcessorCount, [int]($_.MemoryStartup/1MB)
}
$h = Get-VMHost
'#HOST|{0}|{1}' -f $h.LogicalProcessorCount, [int]((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1MB)
$vms
""")
        except ProviderError as exc:
            return HypervisorInventory(provider=self.name, endpoint=self.host,
                                       connected=False, message=str(exc))
        cpu_total = mem_total = 0
        vms: list[VmInfo] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#HOST|"):
                _, cpus, mem = line.split("|", 2)
                cpu_total, mem_total = int(cpus or 0), int(mem or 0)
                continue
            parts = line.split("|")
            if len(parts) == 4:
                vms.append(VmInfo(
                    name=parts[0], state="running" if parts[1] == "Running" else "stopped",
                    vcpu=int(parts[2] or 0), memory_mb=int(parts[3] or 0), ref=parts[0]))
        return HypervisorInventory(
            provider=self.name, endpoint=self.host, connected=True,
            cpu_total=cpu_total, memory_mb=mem_total, vms=tuple(vms))
