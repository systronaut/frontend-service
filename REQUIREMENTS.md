# Provider Requirements

Requirements, credentials, dependencies and the hardened-install contract for
every deploy backend. All hypervisor adapters that can network-boot their guests
reuse the shared PXE path (`control-plane/app/providers/pxe.py::stage_host`): they
create a UEFI/Secure-Boot VM whose NIC sits on the PXE L2, pin it to a MAC,
register that MAC + the per-host hardened artifacts on the `pxe-engine`, then
power on so the guest installs unattended and already hardened — the same
NIS2 / ISO 27001 / CIS install as bare metal.

## Shared contract (PXE-staged providers)

Every network-boot provider (`pxe`, `vsphere`, `libvirt`, `proxmox`) requires:

- A reachable **pxe-engine** (`PXE_ENGINE_URL`, `PXE_ENGINE_TOKEN`) on the same
  L2 as the target's NIC (proxyDHCP does not route across subnets).
- The guest NIC attached to the **PXE network segment** (bridge or port group)
  the `pxe-engine` serves.
- **UEFI Secure Boot** firmware on the guest (compliance control); the adapters
  request it at create time.
- A MAC address. If `spec.network.mac` is empty, adapters derive a deterministic,
  locally-administered MAC from the hostname (`base.derive_mac`) so `create()` is
  idempotent and the reservation matches the guest.

---

## PXE — real

| | |
|---|---|
| Dependencies | none beyond `requests` (talks to the pxe-engine API) |
| Credentials | `PXE_ENGINE_TOKEN` (shared bearer with the engine) |
| Network | `PXE_INTERFACE`, `PXE_SUBNET`, `PXE_HOST_IP`, `PXE_BOOTFILE` |
| Notes | A MAC is **mandatory** (pins the install to a NIC). |

## vSphere — real

| | |
|---|---|
| Dependencies | `pyvmomi` |
| Credentials | `VSPHERE_HOST`, `VSPHERE_USER`, `VSPHERE_PASSWORD` |
| Placement | `VSPHERE_DATACENTER`, `VSPHERE_DATASTORE`, `VSPHERE_NETWORK` (PXE port group); optional `VSPHERE_CLUSTER`, `VSPHERE_FOLDER` |
| TLS | verified by default; `VSPHERE_INSECURE=1` only for dev self-signed |
| Contract | creates a UEFI/Secure-Boot VM on the PXE port group, reads its generated MAC, stages the install, powers on. |

## libvirt / KVM — real

| | |
|---|---|
| Python dep | `libvirt-python` |
| System deps | build: `gcc`, `pkg-config`, `libvirt-dev`; runtime: `libvirt0` (handled in the control-plane Dockerfile) |
| Connection | `LIBVIRT_URI` (e.g. `qemu+ssh://root@kvm-host/system`, or `qemu:///system` on-host). For `qemu+ssh` the control-plane needs SSH access/keys to the KVM host. |
| Network | **`LIBVIRT_BRIDGE`** (host bridge on the PXE LAN, preferred) **or** `LIBVIRT_NETWORK` (libvirt network); the NIC must reach the pxe-engine |
| Storage | `LIBVIRT_POOL` (default `default`), `LIBVIRT_DISK_GB` (default 40) — an empty qcow2 boot volume is created per host |
| Firmware | firmware autoselect `efi` with `secure-boot` + `enrolled-keys`, `q35`, SMM on (Secure Boot needs OVMF with pre-enrolled keys on the host) |
| Contract | defines the domain, assigns the derived MAC, stages the install, starts the domain to network-boot. `provider_ref` = domain UUID. Destroy removes the domain (with NVRAM). |

## Proxmox VE — real

| | |
|---|---|
| Python dep | `proxmoxer` (+ `requests`, already present) |
| Auth | prefer an **API token**: `PROXMOX_USER` (e.g. `svc-deploy@pve`) + `PROXMOX_TOKEN_NAME` + `PROXMOX_TOKEN_VALUE`; fallback `PROXMOX_PASSWORD` |
| Target | `PROXMOX_HOST`, `PROXMOX_NODE` |
| Placement | `PROXMOX_STORAGE` (default `local-lvm`, holds efidisk + boot disk), `PROXMOX_BRIDGE` (default `vmbr0`, must reach the pxe-engine), `PROXMOX_DISK_GB` (default 40) |
| TLS | verified by default; `PROXMOX_INSECURE=1` only for dev self-signed |
| Firmware | `bios=ovmf` + `efidisk0` with `efitype=4m,pre-enrolled-keys=1` (Secure Boot), `machine=q35`, `boot=order=net0;scsi0` |
| Contract | allocates a VMID (idempotent on hostname), creates the VM with the derived MAC on `net0`, stages the install, starts it. `provider_ref` = `node/vmid`. |
| RBAC | the token/user needs `VM.Allocate`, `VM.Config.*`, `VM.PowerMgmt`, `Datastore.AllocateSpace` on the node/pool. |

## ESXi — real

| | |
|---|---|
| Dependencies | `pyvmomi` |
| Credentials | `ESXI_HOST`, `ESXI_USER`, `ESXI_PASSWORD` |
| Placement | `ESXI_DATASTORE`, `ESXI_NETWORK` (PXE port group); optional `ESXI_DATACENTER` (default `ha-datacenter`) |
| TLS | `ESXI_INSECURE=1` by default (self-signed host cert); set `0` once the CA is trusted |
| Contract | subclasses the vSphere adapter: UEFI/Secure-Boot VM on the PXE network, then `stage_host`. |

## OpenStack — stub (different install path)

**OpenStack is intentionally not on the shared PXE path.** Nova instances boot
from a Glance image, not the network, so they cannot reuse `stage_host()`. A
compliant OpenStack deploy needs a **second hardened-install path**:

1. A curated, CIS/NIS2-hardened **base image** in Glance, **or**
2. A `config-drive` / **cloud-init** payload rendered from the same compliance
   controls (`security.ComplianceResult`) that applies the hardening on first
   boot.

| | |
|---|---|
| Python dep | `openstacksdk` (currently commented in `requirements.txt`) |
| Credentials | `OS_AUTH_URL`, `OS_USERNAME`, `OS_PASSWORD`, `OS_PROJECT_NAME` (standard `OS_*` clouds vars) |
| To implement | `openstacksdk` `connection.compute.create_server()` with a hardened image + rendered cloud-init; map the compliance controls into the cloud-init/user-data instead of the PXE answer file. |

---

### Enabling a new provider (checklist)

1. Add the SDK to `control-plane/requirements.txt` (and any system libs to the
   Dockerfile — see libvirt).
2. Fill the provider's block in `.env` (copied from `.env.example`).
3. Ensure L2 reachability from the guest NIC to the `pxe-engine` (PXE-staged
   providers only).
4. The UI dropdown and `GET /api/v1/providers` pick the provider up automatically
   from the registry; `implemented=False` shows as *(preview)*.
