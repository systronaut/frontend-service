# Author: Systronaut
# Security & compliance core.
#
# Maps concrete VM-hardening controls to the standards the platform must satisfy:
#   - NIS2  : Directive (EU) 2022/2555, Article 21(2) risk-management measures
#   - ISO 27001:2022 Annex A controls
#
# A SecurityProfile is a named bundle of Controls. When a deployment is created
# the platform records exactly which controls were enforced for which OS, so the
# resulting deployment carries machine-readable compliance evidence. Controls a
# given OS cannot enforce are reported as gaps rather than silently dropped.

from dataclasses import dataclass, field
from typing import Optional

from .catalog import OsImage


@dataclass(frozen=True)
class Control:
    """A single hardening control with its standards lineage."""

    id: str                          # internal id, e.g. "disk-encryption"
    title: str
    description: str
    iso27001: tuple[str, ...]        # ISO 27001:2022 Annex A refs, e.g. ("A.8.24",)
    nis2: tuple[str, ...]            # NIS2 Art.21(2) refs, e.g. ("21(2)(h)",)
    applies_to: tuple[str, ...] = ("linux", "windows")  # OS families
    # How the control is technically realized at install time. The PXE provider
    # turns these into answer-file directives; cloud providers into image/guest
    # customization. Kept as a stable key the providers branch on.
    mechanism: str = ""
    requires_encryption_support: bool = False
    requires_secure_boot_support: bool = False


# --- Control catalog ---------------------------------------------------------
# IDs are stable; standards references follow ISO/IEC 27001:2022 Annex A and the
# NIS2 Article 21(2) lettered measures.

CONTROLS: tuple[Control, ...] = (
    Control(
        id="disk-encryption",
        title="Full-disk encryption at rest",
        description="Root/system volume encrypted (LUKS2 on Linux, BitLocker on Windows).",
        iso27001=("A.8.24", "A.8.10"),
        nis2=("21(2)(h)",),                       # cryptography / encryption
        mechanism="disk_encryption",
        requires_encryption_support=True,
    ),
    Control(
        id="secure-boot",
        title="UEFI Secure Boot enforced",
        description="Only signed bootloaders/kernels execute; tamper resistance for boot chain.",
        iso27001=("A.8.9",),
        nis2=("21(2)(e)",),                       # security in acquisition/development/maintenance
        mechanism="secure_boot",
        requires_secure_boot_support=True,
    ),
    Control(
        id="minimal-install",
        title="Minimal install / attack-surface reduction",
        description="No GUI/extra packages by default; only required services installed.",
        iso27001=("A.8.9", "A.8.19"),
        nis2=("21(2)(e)",),
        mechanism="minimal_install",
    ),
    Control(
        id="host-firewall",
        title="Host firewall default-deny",
        description="Inbound default-deny; only explicitly allowed management ports open.",
        iso27001=("A.8.20", "A.8.22"),
        nis2=("21(2)(a)",),                       # risk analysis & information system security
        mechanism="host_firewall",
    ),
    Control(
        id="ssh-hardening",
        title="Hardened remote access",
        description="Key-only SSH, root login disabled (Linux); RDP NLA enforced (Windows).",
        iso27001=("A.8.5", "A.5.17", "A.8.4"),
        nis2=("21(2)(i)", "21(2)(j)"),            # access control / MFA & secure auth
        mechanism="remote_access_hardening",
    ),
    Control(
        id="no-weak-passwords",
        title="Strong credential policy",
        description="Reject weak passwords; enforce length/complexity for local accounts.",
        iso27001=("A.5.17",),
        nis2=("21(2)(i)",),
        mechanism="password_policy",
    ),
    Control(
        id="auto-updates",
        title="Automatic security patching",
        description="Unattended security updates enabled at install (dnf-automatic / unattended-upgrades / WU).",
        iso27001=("A.8.8",),
        nis2=("21(2)(e)",),                       # vulnerability handling & disclosure
        mechanism="auto_updates",
    ),
    Control(
        id="audit-logging",
        title="Audit logging & remote forwarding",
        description="auditd/Event Log enabled; logs forwarded to a central collector.",
        iso27001=("A.8.15", "A.8.16"),
        nis2=("21(2)(g)",),                       # security of network/info systems incl. logging
        mechanism="audit_logging",
    ),
    Control(
        id="time-sync",
        title="Trusted time synchronization",
        description="NTP/chrony to an authorized server; correct logs & cert validation.",
        iso27001=("A.8.17",),
        nis2=("21(2)(g)",),
        mechanism="time_sync",
    ),
    Control(
        id="cis-baseline",
        title="CIS / STIG configuration baseline",
        description="Apply a recognized hardening baseline (CIS Benchmark / DISA STIG).",
        iso27001=("A.8.9",),
        nis2=("21(2)(a)", "21(2)(e)"),
        mechanism="cis_baseline",
    ),
)

_CONTROL_BY_ID = {c.id: c for c in CONTROLS}


@dataclass(frozen=True)
class SecurityProfile:
    """A named bundle of controls plus the standards it claims to address."""

    name: str
    label: str
    description: str
    control_ids: tuple[str, ...]
    standards: tuple[str, ...]       # e.g. ("NIS2", "ISO 27001")

    def controls(self) -> list[Control]:
        return [_CONTROL_BY_ID[cid] for cid in self.control_ids if cid in _CONTROL_BY_ID]


# --- Profiles ----------------------------------------------------------------
# "compliant" is the default and the must-have: it carries the full NIS2 +
# ISO 27001 control set. "baseline" is a lighter dev/test profile.

_ALL_IDS = tuple(c.id for c in CONTROLS)

PROFILES: tuple[SecurityProfile, ...] = (
    SecurityProfile(
        name="baseline",
        label="Baseline (dev/test)",
        description="Sensible defaults only. NOT sufficient for regulated workloads.",
        control_ids=("minimal-install", "host-firewall", "ssh-hardening",
                     "no-weak-passwords", "time-sync"),
        standards=(),
    ),
    SecurityProfile(
        name="compliant",
        label="NIS2 + ISO 27001 compliant",
        description="Full hardening set mapped to NIS2 Art.21(2) and ISO 27001:2022 Annex A.",
        control_ids=_ALL_IDS,
        standards=("NIS2", "ISO 27001"),
    ),
    SecurityProfile(
        name="high",
        label="High assurance (compliant + CIS/STIG)",
        description="Compliant profile with an enforced CIS/STIG baseline and Secure Boot required.",
        control_ids=_ALL_IDS,
        standards=("NIS2", "ISO 27001", "CIS", "DISA STIG"),
    ),
)

_PROFILE_BY_NAME = {p.name: p for p in PROFILES}
DEFAULT_PROFILE = "compliant"


def all_profiles() -> tuple[SecurityProfile, ...]:
    return PROFILES


def get_profile(name: str) -> Optional[SecurityProfile]:
    return _PROFILE_BY_NAME.get(name)


def is_valid_profile(name: str) -> bool:
    return name in _PROFILE_BY_NAME


@dataclass
class ComplianceResult:
    """Outcome of applying a profile to a specific OS image."""

    profile: str
    standards: tuple[str, ...]
    applied: list[Control] = field(default_factory=list)   # enforceable on this OS
    gaps: list[tuple[Control, str]] = field(default_factory=list)  # (control, reason)

    @property
    def is_fully_compliant(self) -> bool:
        return not self.gaps

    def to_evidence(self) -> dict:
        """Machine-readable compliance evidence stored with the deployment."""
        return {
            "profile": self.profile,
            "standards": list(self.standards),
            "fully_compliant": self.is_fully_compliant,
            "applied_controls": [
                {
                    "id": c.id,
                    "title": c.title,
                    "iso27001": list(c.iso27001),
                    "nis2": list(c.nis2),
                    "mechanism": c.mechanism,
                }
                for c in self.applied
            ],
            "gaps": [
                {"id": c.id, "title": c.title, "reason": reason}
                for c, reason in self.gaps
            ],
        }


def evaluate(profile_name: str, image: OsImage) -> ComplianceResult:
    """Resolve which controls a profile can enforce on a given OS image.

    A control becomes a *gap* (not silently dropped) when the OS family is out of
    scope or the image lacks a required capability (e.g. disk encryption).
    """
    profile = get_profile(profile_name)
    if profile is None:
        raise ValueError(f"unknown security profile: {profile_name!r}")

    result = ComplianceResult(profile=profile.name, standards=profile.standards)
    for control in profile.controls():
        if image.family not in control.applies_to:
            result.gaps.append((control, f"not applicable to {image.family}"))
            continue
        if control.requires_encryption_support and not image.supports_disk_encryption:
            result.gaps.append((control, "image does not support disk encryption"))
            continue
        if control.requires_secure_boot_support and not image.supports_secure_boot:
            result.gaps.append((control, "image does not support Secure Boot"))
            continue
        result.applied.append(control)
    return result
