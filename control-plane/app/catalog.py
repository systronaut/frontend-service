# Author: Systronaut
# OS catalog -- single source of truth for deployable operating systems.
#
# Derived directly from the working iPXE menu in ansible/roles/pxe (os_pxe_lab).
# Each entry maps a UI selection to the answer-file template + iPXE chain that
# the PXE engine serves. Keep this in sync with
# ansible/roles/pxe/files/ipxe/autoexec.ipxe.j2.

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class OsImage:
    """An installable operating system the platform can deploy."""

    key: str                     # stable id, e.g. "rhel101"
    family: str                  # "linux" | "windows"
    distro: str                  # "rhel", "rocky", "debian", "windows", ...
    label: str                   # human label for the UI
    version: str
    # Provisioning artifacts (relative to the PXE HTTP root / TFTP root).
    ipxe_chain: str              # iPXE script served over HTTP
    answer_template: str         # kickstart / preseed / autoinstall / autounattend
    firmware: str = "uefi"       # os_pxe_lab is UEFI-only
    arch: str = "x86_64"
    # Which secure-deployment knobs this OS understands. The security module
    # only renders profile settings an OS can actually enforce.
    supports_disk_encryption: bool = True
    supports_secure_boot: bool = True
    notes: str = ""


# Ordered exactly like the iPXE boot menu so the UI mirrors the lab.
CATALOG: tuple[OsImage, ...] = (
    OsImage(
        key="win2022", family="windows", distro="windows",
        label="Windows Server 2022", version="2022",
        ipxe_chain="windows/wim.ipxe",
        answer_template="windows/pxe_autounattend.xml",
        supports_disk_encryption=True,  # BitLocker via runonce
        notes="WinPE + autounattend.xml, install tree over Samba share.",
    ),
    OsImage(
        key="rhel97", family="linux", distro="rhel", label="Red Hat Enterprise Linux 9.7",
        version="9.7", ipxe_chain="rhel97/rhel97.ipxe",
        answer_template="rhel97/rhel97_ks.cfg",
        notes="Requires a valid Red Hat offline token / activation key.",
    ),
    OsImage(
        key="rhel101", family="linux", distro="rhel", label="Red Hat Enterprise Linux 10.1",
        version="10.1", ipxe_chain="rhel101/rhel101.ipxe",
        answer_template="rhel101/rhel101_ks.cfg",
        notes="Requires a valid Red Hat offline token / activation key.",
    ),
    OsImage(
        key="rocky97", family="linux", distro="rocky", label="Rocky Linux 9.7",
        version="9.7", ipxe_chain="rocky97/rocky97.ipxe",
        answer_template="rocky97/rocky97_ks.cfg",
    ),
    OsImage(
        key="rocky101", family="linux", distro="rocky", label="Rocky Linux 10.1",
        version="10.1", ipxe_chain="rocky101/rocky101.ipxe",
        answer_template="rocky101/rocky101_ks.cfg",
    ),
    OsImage(
        key="debian13", family="linux", distro="debian", label="Debian 13.4",
        version="13.4", ipxe_chain="debian-installer/debian13.ipxe",
        answer_template="debian-installer/appserver.cfg",
        notes="preseed; package_role appserver/dbserver/graphical/minimal.",
    ),
    OsImage(
        key="ubuntu2404", family="linux", distro="ubuntu", label="Ubuntu 24.04 LTS",
        version="24.04", ipxe_chain="ubuntu2404/ubuntu2404.ipxe",
        answer_template="ubuntu2404/user-data",
        supports_disk_encryption=True,  # Subiquity LVM layout password → LUKS
        notes="cloud-init autoinstall; LUKS when passphrase set; late-commands apply CIS. "
              "Needs >= 8 GB RAM (live ISO).",
    ),
    OsImage(
        key="oracle101", family="linux", distro="oracle", label="Oracle Linux 10.1 (UEK)",
        version="10.1", ipxe_chain="oracle101/oracle101.ipxe",
        answer_template="oracle101/oracle101_ks.cfg",
    ),
    OsImage(
        key="sles157", family="linux", distro="sles", label="SUSE Linux Enterprise 15 SP7",
        version="15.7", ipxe_chain="sles/sles157.ipxe",
        answer_template="sles/sles15sp7.xml",
        notes="AutoYaST; LUKS when passphrase set. CIS via chroot-scripts.",
    ),
    OsImage(
        key="sles160", family="linux", distro="sles", label="SUSE Linux Enterprise 16.0",
        version="16.0", ipxe_chain="sles/sles160.ipxe",
        answer_template="sles/sles160.json",
        supports_disk_encryption=True,  # Agama generate.encryption.luks2
        notes="Agama JSON; LUKS2 when passphrase set; post scripts apply CIS.",
    ),
)

_BY_KEY = {image.key: image for image in CATALOG}


def all_images() -> tuple[OsImage, ...]:
    return CATALOG


def get_image(key: str) -> Optional[OsImage]:
    return _BY_KEY.get(key)


def is_valid_key(key: str) -> bool:
    return key in _BY_KEY
