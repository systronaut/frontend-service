# Author: Systronaut
# Backend-owned PXE templating. The Jinja2 templates live here (app/pxe_templates)
# and are rendered by the control plane -- NOT by the engine. The control plane
# holds the deployment spec + host IP + the resolved security controls, so it is
# the right place to produce the per-host boot script and hardening overlay. The
# engine only persists/serves what it is given.

import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import DeploymentSpec
from .security import ComplianceResult

_TEMPLATE_DIR = Path(__file__).parent / "pxe_templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=(), default=False),
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)

# Read-only os_pxe_lab answer-file/iPXE tree, mounted into the control plane.
# The backend renders the OS-level *.ipxe.j2 (which only need host_ip) here, so
# nothing ships an unrendered Jinja2 template to the target.
_LOOKUP_DIR = Path(os.environ.get("PXE_LOOKUP_DIR", "/srv/lookup"))


def _render_os_ipxe(ipxe_chain: str, host_ip: str) -> str | None:
    """Render the OS installer iPXE script from the lookup tree, if present.

    os_pxe_lab ships e.g. rhel101/rhel101.ipxe.j2; we substitute host_ip and
    return the rendered text. Returns None when the tree is not mounted.
    """
    if not ipxe_chain:
        return None
    candidates = [_LOOKUP_DIR / f"{ipxe_chain}.j2", _LOOKUP_DIR / ipxe_chain]
    for path in candidates:
        try:
            if path.is_file():
                from jinja2 import Template
                return Template(path.read_text(), keep_trailing_newline=True).render(
                    host_ip=host_ip)
        except OSError:
            continue
    return None


def _slug(mac: str) -> str:
    return mac.replace(":", "-")


def render_host_artifacts(spec: DeploymentSpec, compliance: ComplianceResult,
                          host_ip: str) -> dict[str, str]:
    """Render the per-host files the engine should serve under host/<slug>/.

    Returns a {filename: content} map. Filenames are flat (no slashes); the
    engine writes them verbatim after validating the name.
    """
    image = spec.image
    mac = spec.network.mac
    ctx = {
        "hostname": spec.hostname,
        "mac": mac,
        "slug": _slug(mac),
        "os_key": spec.os_key,
        "os_label": image.label if image else spec.os_key,
        "ipxe_chain": image.ipxe_chain if image else "",
        "security_profile": spec.security_profile,
        "host_ip": host_ip,
        "net_mode": spec.network.mode,
        "ip": spec.network.ip,
        "netmask": spec.network.netmask,
        "gateway": spec.network.gateway,
        "dns": spec.network.dns,
    }
    # autoescape is intentionally off: these render iPXE/shell text, not HTML, and
    # every interpolated value (hostname/ip/mac/...) is already validated upstream.
    os_ipxe = _render_os_ipxe(ctx["ipxe_chain"], host_ip)
    ctx["have_os_ipxe"] = os_ipxe is not None
    boot_ipxe = _env.get_template("boot.ipxe.j2").render(**ctx)

    # hardening.env: HARDEN_* flags + the CIS script URLs the answer file fetches.
    base = f"http://{host_ip}"
    flags = "".join(f"HARDEN_{c.mechanism.upper()}=1\n" for c in compliance.applied)
    hardening_env = (
        f"# Security controls for {spec.hostname} -- {', '.join(compliance.standards) or 'baseline'}\n"
        f"CIS_LINUX_URL={base}/hardening/cis-linux.sh\n"
        f"CIS_WINDOWS_URL={base}/hardening/cis-windows.ps1\n"
        f"{flags}"
    )
    artifacts = {"boot.ipxe": boot_ipxe, "hardening.env": hardening_env}
    if os_ipxe is not None:
        artifacts["os.ipxe"] = os_ipxe
    return artifacts


def host_ip_default() -> str:
    return os.environ.get("PXE_HOST_IP", "")
