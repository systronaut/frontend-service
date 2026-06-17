# Systronaut Deploy

Self-hosted platform to deploy **hardened, NIS2- & ISO 27001-compliant** virtual
machines and bare-metal hosts — Windows and Linux — from a single SYSTRONAUT web
console. One `docker compose up`. Built for end users (operators) and
administrators.

It unifies three formerly separate pieces:

| Was | Now |
|-----|-----|
| `webapp/` (SYSTRONAUT Flask UI, stubs) | **`control-plane/`** — UI + REST API, real deploy flow |
| `dnsmasq/` + `dnsmasq-master` (insecure `os.system` API) | **`pxe-engine/`** — hardened dnsmasq + iPXE + nginx + API |
| `os_pxe_lab` (Ansible/iPXE answer files) | **`ansible/`** — read-only OS lookup (served, **not executed**) |
| `designer/` (drawio) | unchanged — architecture designer |

## Architecture

```
                ┌──────────────────────────┐
 operator/admin │  control-plane  :5000     │  SYSTRONAUT UI + REST API /api/v1
   browser  ───▶│  Flask · SQLite · audit   │  role-based auth, compliance engine
                └─────────────┬────────────┘
                              │ HTTP (Bearer)
                ┌─────────────▼────────────┐
                │  pxe-engine (host net)    │  dnsmasq proxyDHCP + TFTP
   PXE target ─▶│  dnsmasq · iPXE · nginx   │  nginx serves ansible/ answer files
   (UEFI boot)  │  hardened API :8081       │  writes per-MAC reservation + iPXE
                └───────────────────────────┘
```

Providers are pluggable. **PXE** (bare-metal / any hypervisor via network boot)
is fully implemented. **vSphere, ESXi, OpenStack** are first-class adapters with
real contracts and credential surfaces, stubbed at the `create()` call (no fake
successes) — see `control-plane/app/providers/cloud.py`.

## Compliance (must-have)

Every deployment selects a **security profile**. The default `compliant` profile
bundles controls mapped to **ISO/IEC 27001:2022 Annex A** and **NIS2 Art. 21(2)**
(disk encryption, Secure Boot, minimal install, host firewall, hardened remote
access, patching, audit logging, time sync, …). The platform records, per
deployment, exactly which controls were enforced and which were gaps — stored as
machine-readable **compliance evidence** and viewable at `/compliance` and on each
deployment. All state changes are written to an append-only **audit log**
(`/audit`, admin only). See `control-plane/app/security.py`.

## Quick start (Linux host)

```bash
cp .env.example .env
# generate secrets:
#   CONTROL_PLANE_SECRET = openssl rand -hex 32
#   API_*_TOKEN / PXE_ENGINE_TOKEN = openssl rand -hex 24
# set ADMIN_PASSWORD, OPERATOR_PASSWORD, and PXE_INTERFACE / PXE_SUBNET / PXE_HOST_IP
$EDITOR .env

docker compose up --build
```

- Console:  http://HOST:5000  (sign in as admin or operator)
- Designer: http://HOST:8082
- PXE engine API: http://HOST:8081/api/v1/health (host network)

> **Linux only for PXE.** `pxe-engine` uses `network_mode: host` because
> proxyDHCP/TFTP/PXE must run at layer 2 on the real LAN. proxyDHCP coexists with
> your existing DHCP server (it only answers boot options). Boot targets in
> **UEFI** mode.

## Deploy flow

1. **Deploy** → pick OS (10 supported), provider, size, network (DHCP/static, MAC
   for PXE), and security profile.
2. The control plane validates input, computes compliance, and calls the provider.
3. For PXE it registers a per-MAC dnsmasq reservation + iPXE chain on the engine;
   the target network-boots and installs unattended, already hardened.
4. Track status, compliance evidence, and audit trail in the console or via the API.

## REST API

`/api/v1` — Bearer token (operator or admin). Mirrors the UI.

```
GET    /api/v1/health
GET    /api/v1/catalog | /profiles | /providers
POST   /api/v1/deployments          # create
GET    /api/v1/deployments          # list
GET    /api/v1/deployments/{id}     # status
GET    /api/v1/deployments/{id}/compliance
DELETE /api/v1/deployments/{id}     # admin
GET    /api/v1/audit                # admin
```

## Supported operating systems

Windows Server 2022 · RHEL 9.7 / 10.1 · Rocky 9.7 / 10.1 · Oracle Linux 10.1 ·
Ubuntu 24.04 LTS · Debian 13.4 · SLES 15 SP7 / 16.0 (from the `os_pxe_lab` iPXE
catalog). See `control-plane/app/catalog.py`.

## Security notes

- No shell/command injection: the engine validates all input and uses argument
  lists, never `os.system` string concatenation (the original API was vulnerable).
- Bearer-token auth on the engine; role-based session auth + token API on the
  control plane; CSP, HSTS (behind TLS), and clickjacking headers set.
- Run the control plane behind a TLS reverse proxy and set `SESSION_COOKIE_SECURE=1`.

## Implementing a cloud provider

Drop the SDK call in `control-plane/app/providers/cloud.py` (pyVmomi for
vSphere/ESXi, openstacksdk for OpenStack), set credentials in `.env`, flip
`implemented = True`. Attach the new guest to the PXE network so it follows the
same hardened install path as bare metal.
