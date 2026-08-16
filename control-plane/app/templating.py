# Author: Systronaut
# Backend-owned PXE templating. The Jinja2 templates live here (app/pxe_templates)
# and under PXE_LOOKUP_DIR (*.j2). The control plane renders per-host boot, OS
# iPXE, answer files, and hardening.env -- NOT the engine. The engine only
# persists/serves what it is given.
#
# Secure-install contract: answer-file %post / late-commands MUST fetch
# hardening.env + the CIS script so NIS2/ISO 27001 controls are applied on the
# target, not only recorded as evidence.
#
# Ansible roles/pxe = product Vorlage; WebUI settings flow in via DeploymentSpec.install.

import logging
import os
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Template, select_autoescape

from .models import DeploymentSpec
from .security import ComplianceResult, disk_encryption_passphrase

log = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "pxe_templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=(), default=False),
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)

# Read-only os_pxe_lab answer-file/iPXE tree, mounted into the control plane.
_LOOKUP_DIR = Path(os.environ.get("PXE_LOOKUP_DIR", "/srv/lookup"))

# Flat filenames written under host/<slug>/ on the engine.
_ANSWER_NAMES = {
    "windows": "autounattend.xml",
    "ubuntu": "user-data",
    "debian": "preseed.cfg",
    "sles": "autoyast.xml",
}

# Distros that use the shared Anaconda kickstart secure template.
_KICKSTART_DISTROS = frozenset({"rhel", "rocky", "oracle"})

# Backend-owned secure answer templates that must exist at startup.
_REQUIRED_ANSWER_TEMPLATES = (
    "answers/kickstart.j2",
    "answers/debian_preseed.j2",
    "answers/ubuntu_autoinstall.j2",
    "answers/windows_autounattend.j2",
    "answers/sles_autoyast.j2",
    "answers/sles_agama.j2",
    "boot.ipxe.j2",
)


def assert_answer_templates_present() -> None:
    """Fail closed at app factory if secure answer Jinja2 templates are missing."""
    missing = [rel for rel in _REQUIRED_ANSWER_TEMPLATES
               if not (_TEMPLATE_DIR / rel).is_file()]
    if missing:
        raise RuntimeError(
            "Missing required PXE answer templates under pxe_templates/: "
            + ", ".join(missing)
        )



def _slug(mac: str) -> str:
    return mac.replace(":", "-")


def _mechanisms(compliance: ComplianceResult) -> set[str]:
    return {c.mechanism for c in compliance.applied}


def _hash_password(password: str) -> str:
    """SHA-512 crypt hash for kickstart/preseed (openssl passwd -6)."""
    if not password:
        return ""
    try:
        out = subprocess.run(
            ["openssl", "passwd", "-6", "-stdin"],
            input=password.encode(), capture_output=True, check=True, timeout=5,
        )
        hashed = out.stdout.decode().strip()
        if not hashed:
            log.warning("_hash_password returned empty; account will be locked "
                        "(no plaintext embedded)")
        return hashed
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as exc:
        # Fail closed: do not embed plaintext into answer files.
        log.warning("_hash_password failed (%s); account will be locked "
                    "(no plaintext embedded)", exc.__class__.__name__)
        return ""


def _win_locale(locale: str) -> str:
    """Map Linux-style locale (en_US.UTF-8) to Windows BCP-47 (en-US)."""
    base = (locale or "en_US").split(".")[0]
    parts = base.replace("-", "_").split("_", 1)
    if len(parts) == 2:
        return f"{parts[0]}-{parts[1]}"
    return "en-US"


def _win_timezone(timezone: str) -> str:
    """Best-effort IANA → Windows TZ id; UTC fallback (honest, not exhaustive)."""
    tz = (timezone or "Etc/UTC").strip()
    known = {
        "Etc/UTC": "UTC",
        "UTC": "UTC",
        "Europe/Berlin": "W. Europe Standard Time",
        "Europe/Zurich": "W. Europe Standard Time",
        "Europe/Vienna": "W. Europe Standard Time",
        "America/New_York": "Eastern Standard Time",
    }
    return known.get(tz, "UTC")


def _build_ctx(spec: DeploymentSpec, compliance: ComplianceResult,
               host_ip: str) -> dict:
    image = spec.image
    mac = spec.network.mac
    mechs = _mechanisms(compliance)
    inst = spec.install
    passphrase = disk_encryption_passphrase(inst.disk_passphrase)
    package_role = getattr(inst, "package_role", "minimal") or "minimal"
    return {
        "hostname": spec.hostname,
        "mac": mac,
        "slug": _slug(mac),
        "os_key": spec.os_key,
        "os_label": image.label if image else spec.os_key,
        "os_family": image.family if image else "linux",
        "distro": image.distro if image else "",
        "ipxe_chain": image.ipxe_chain if image else "",
        "answer_template": image.answer_template if image else "",
        "security_profile": spec.security_profile,
        "standards": list(compliance.standards),
        "host_ip": host_ip,
        "net_mode": spec.network.mode,
        "ip": spec.network.ip,
        "netmask": spec.network.netmask,
        "gateway": spec.network.gateway,
        "dns": spec.network.dns,
        "domain": spec.network.domain,
        # InstallSettings (Ansible feature parity — WebUI functional).
        "timezone": inst.timezone,
        "locale": inst.locale,
        "locale_lang": (inst.locale or "en_US").split(".")[0],
        "keyboard": inst.keyboard,
        "admin_user": inst.admin_user,
        "admin_password_hash": _hash_password(inst.admin_password),
        "admin_password_plain": inst.admin_password,
        "ssh_pubkey": inst.ssh_pubkey,
        "disk_device": inst.disk_device,
        "ntp_server": inst.ntp_server,
        "rhsm_org": inst.rhsm_org,
        "rhsm_activation_key": inst.rhsm_activation_key,
        "package_role": package_role,
        "workgroup": getattr(inst, "workgroup", None) or "WORKGROUP",
        "samba_share": getattr(inst, "samba_share", None) or r"share\win2022",
        "win_locale": _win_locale(inst.locale),
        "win_timezone": _win_timezone(inst.timezone),
        # HARDEN_* mirrors (Jinja conditionals in answer files).
        "harden_disk_encryption": "disk_encryption" in mechs,
        "harden_secure_boot": "secure_boot" in mechs,
        "harden_minimal_install": "minimal_install" in mechs,
        "harden_host_firewall": "host_firewall" in mechs,
        "harden_remote_access": "remote_access_hardening" in mechs,
        "harden_password_policy": "password_policy" in mechs,
        "harden_auto_updates": "auto_updates" in mechs,
        "harden_audit_logging": "audit_logging" in mechs,
        "harden_time_sync": "time_sync" in mechs,
        "harden_cis_baseline": "cis_baseline" in mechs,
        "disk_passphrase": passphrase,
        "hardening_url": f"http://{host_ip}/host/{_slug(mac)}/hardening.env",
        "cis_linux_url": f"http://{host_ip}/hardening/cis-linux.sh",
        "cis_windows_url": f"http://{host_ip}/hardening/cis-windows.ps1",
        "answer_url": f"http://{host_ip}/host/{_slug(mac)}",
        # SLES AutoYaST TLS skip — only for HTTP lab via PXE_SLES_INSECURE=1.
        "sles_insecure": os.environ.get("PXE_SLES_INSECURE", "").strip().lower()
        in ("1", "true", "yes"),
    }


def _within_lookup(candidate: Path) -> bool:
    """Mirror answer_files._within_base — refuse path escape from PXE_LOOKUP_DIR."""
    try:
        return candidate.resolve().is_relative_to(_LOOKUP_DIR.resolve())
    except (ValueError, OSError):
        return False


def _lookup_candidates(relpath: str, *, j2_only: bool = False) -> list[Path]:
    """Prefer *.j2 next to / as the answer or iPXE path (path-contained)."""
    if not relpath or ".." in Path(relpath).parts:
        return []
    base = _LOOKUP_DIR / relpath
    raw: list[Path] = []
    if not str(relpath).endswith(".j2"):
        raw.append(Path(str(base) + ".j2"))
    if not j2_only:
        raw.append(base)
    return [p for p in raw if _within_lookup(p)]


def _render_lookup(relpath: str, ctx: dict, *, j2_only: bool = False) -> str | None:
    for path in _lookup_candidates(relpath, j2_only=j2_only):
        try:
            if not path.is_file():
                continue
            text = path.read_text()
            if path.name.endswith(".j2"):
                return Template(text, keep_trailing_newline=True).render(**ctx)
            if j2_only:
                continue
            # Static fallback (lab files without Jinja) — no per-host vars.
            return text
        except OSError:
            continue
    return None


def _answer_artifact_name(distro: str, answer_template: str, os_key: str = "") -> str:
    # SLES 16 Agama JSON must not reuse the AutoYaST filename.
    if distro == "sles":
        if os_key.startswith("sles16") or (answer_template or "").endswith(".json"):
            return "autoinstall.json"
        return "autoyast.xml"
    if distro in _ANSWER_NAMES:
        return _ANSWER_NAMES[distro]
    if answer_template.endswith(".cfg") or "ks" in Path(answer_template).name:
        return "ks.cfg"
    if answer_template.endswith(".xml"):
        return "autoyast.xml"
    if answer_template.endswith(".json"):
        return "autoinstall.json"
    return "answer.cfg"


def _render_secure_answer(ctx: dict) -> str | None:
    """Prefer backend-owned secure Jinja2; else Ansible lookup *.j2 (never static lab)."""
    distro = ctx.get("distro") or ""
    os_key = ctx.get("os_key") or ""
    if distro in _KICKSTART_DISTROS:
        path = _TEMPLATE_DIR / "answers" / "kickstart.j2"
        if path.is_file():
            return _env.get_template("answers/kickstart.j2").render(**ctx)
    if distro == "ubuntu":
        path = _TEMPLATE_DIR / "answers" / "ubuntu_autoinstall.j2"
        if path.is_file():
            return _env.get_template("answers/ubuntu_autoinstall.j2").render(**ctx)
    if distro == "debian":
        path = _TEMPLATE_DIR / "answers" / "debian_preseed.j2"
        if path.is_file():
            return _env.get_template("answers/debian_preseed.j2").render(**ctx)
    if distro == "windows":
        path = _TEMPLATE_DIR / "answers" / "windows_autounattend.j2"
        if path.is_file():
            return _env.get_template("answers/windows_autounattend.j2").render(**ctx)
    if distro == "sles":
        # SLES 16 = Agama JSON; SLES 15 = AutoYaST XML.
        if os_key.startswith("sles16") or (ctx.get("answer_template") or "").endswith(".json"):
            path = _TEMPLATE_DIR / "answers" / "sles_agama.j2"
            if path.is_file():
                return _env.get_template("answers/sles_agama.j2").render(**ctx)
        path = _TEMPLATE_DIR / "answers" / "sles_autoyast.j2"
        if path.is_file():
            return _env.get_template("answers/sles_autoyast.j2").render(**ctx)
    # Ansible Vorlage *.j2 only — skip static lab answers (hardcoded passwords).
    return _render_lookup(ctx.get("answer_template") or "", ctx, j2_only=True)


def render_host_artifacts(spec: DeploymentSpec, compliance: ComplianceResult,
                          host_ip: str) -> dict[str, str]:
    """Render the per-host files the engine should serve under host/<slug>/.

    Returns a {filename: content} map. Filenames are flat (no slashes); the
    engine writes them verbatim after validating the name.
    """
    ctx = _build_ctx(spec, compliance, host_ip)
    os_ipxe = _render_lookup(ctx["ipxe_chain"], ctx)
    ctx["have_os_ipxe"] = os_ipxe is not None
    ctx["have_answer"] = False
    ctx["answer_name"] = "ks.cfg"

    boot_ipxe = _env.get_template("boot.ipxe.j2").render(**ctx)

    base = f"http://{host_ip}"
    flags = "".join(f"HARDEN_{c.mechanism.upper()}=1\n" for c in compliance.applied)
    hardening_env = (
        f"# Security controls for {spec.hostname} -- "
        f"{', '.join(compliance.standards) or 'baseline'}\n"
        f"CIS_LINUX_URL={base}/hardening/cis-linux.sh\n"
        f"CIS_WINDOWS_URL={base}/hardening/cis-windows.ps1\n"
        f"{flags}"
    )
    artifacts = {"boot.ipxe": boot_ipxe, "hardening.env": hardening_env}

    try:
        artifacts["post-harden.sh"] = _env.get_template(
            "post_harden_linux.sh.j2").render(**ctx)
    except Exception:
        pass
    try:
        artifacts["post-harden.ps1"] = _env.get_template(
            "post_harden_windows.ps1.j2").render(**ctx)
    except Exception:
        pass

    answer = _render_secure_answer(ctx)
    # SLES 16: never ship without Agama JSON (iPXE else-branch is fail-closed).
    if answer is None and (ctx.get("os_key") or "").startswith("sles16"):
        raise RuntimeError(
            "SLES 16 requires rendered Agama answer (sles_agama.j2); "
            "refusing weak lab fallback"
        )
    if answer is not None:
        name = _answer_artifact_name(
            ctx["distro"], ctx["answer_template"], ctx.get("os_key") or "")
        artifacts[name] = answer
        ctx["have_answer"] = True
        ctx["answer_name"] = name
        # Re-render os.ipxe so inst.ks / autoinstall point at per-host answer.
        if ctx["ipxe_chain"]:
            os_ipxe = _render_lookup(ctx["ipxe_chain"], ctx)

    if ctx["distro"] == "ubuntu" and "user-data" in artifacts:
        artifacts["meta-data"] = (
            f"instance-id: {spec.hostname}\n"
            f"local-hostname: {spec.hostname}\n"
        )

    # Windows: per-host Samba UNC (WinPE mounts this via pxe_samba.txt).
    if ctx["distro"] == "windows":
        share = (ctx.get("samba_share") or r"share\win2022").lstrip("\\")
        artifacts["pxe_samba.txt"] = f"\\\\{host_ip}\\{share}\n"

    if os_ipxe is not None:
        artifacts["os.ipxe"] = os_ipxe
    return artifacts


def host_ip_default() -> str:
    return os.environ.get("PXE_HOST_IP", "")
