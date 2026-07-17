# Author: Systronaut
# Read-only browser for the os_pxe_lab answer-file tree (kickstart / preseed /
# autoinstall / autounattend / iPXE). The tree is mounted read-only at
# PXE_LOOKUP_DIR; this module exposes a *safe* listing + file read so the UI and
# REST API can show operators exactly what will be provisioned for each OS.
#
# Security: this is view-only. There is no write path. Every read is confined to
# the base dir with a resolved-path containment check (no traversal, no symlink
# escape), size-capped, and binary-aware. Callers are always authenticated.

import os
from dataclasses import dataclass
from pathlib import Path

from . import catalog

# Same tree templating.py renders from; mounted read-only (see docker-compose).
BASE_DIR = Path(os.environ.get("PXE_LOOKUP_DIR", "/srv/lookup"))

_MAX_VIEW_BYTES = 512 * 1024        # refuse to inline anything larger
_SHARED = "shared"                  # bucket for infra files not tied to one OS

# Extension / name -> (kind label, syntax hint) for the viewer.
_KINDS: dict[str, tuple[str, str]] = {
    ".cfg": ("Answer file", "ini"),
    ".ks": ("Kickstart", "ini"),
    ".xml": ("Answer file (XML)", "xml"),
    ".json": ("Autoinstall (JSON)", "json"),
    ".yaml": ("Cloud-init", "yaml"),
    ".yml": ("Cloud-init", "yaml"),
    ".j2": ("Jinja2 template", "jinja"),
    ".ipxe": ("iPXE script", "ipxe"),
    ".sh": ("Shell script", "bash"),
    ".ps1": ("PowerShell", "powershell"),
    ".cmd": ("Batch script", "batch"),
    ".png": ("Image", "binary"),
}


@dataclass(frozen=True)
class AnswerFile:
    name: str            # basename, e.g. "rhel101_ks.cfg"
    relpath: str         # POSIX path relative to BASE_DIR, e.g. "rhel101/rhel101_ks.cfg"
    kind: str            # human label
    syntax: str          # viewer hint
    size: int            # bytes
    is_binary: bool


@dataclass(frozen=True)
class OsRef:
    key: str
    label: str


@dataclass(frozen=True)
class AnswerGroup:
    directory: str                 # top-level dir, or _SHARED for loose files
    title: str                     # OS label(s) if mapped, else the dir name
    os_refs: tuple[OsRef, ...]     # catalog entries this group provisions
    files: tuple[AnswerFile, ...]


def _kind_for(name: str) -> tuple[str, str]:
    # Compound extensions like ".ipxe.j2": prefer the more specific inner one.
    lower = name.lower()
    if lower.endswith(".ipxe.j2"):
        return "iPXE template", "jinja"
    ext = Path(lower).suffix
    if ext in _KINDS:
        return _KINDS[ext]
    if name in ("user-data", "meta-data"):
        return "Cloud-init", "yaml"
    return "File", "text"


def _dir_to_os() -> dict[str, list[OsRef]]:
    """Map each top-level source directory to the catalog entries it serves.

    Derived from the catalog's answer_template + ipxe_chain paths so the mapping
    never drifts from what actually gets deployed.
    """
    mapping: dict[str, list[OsRef]] = {}
    for img in catalog.all_images():
        ref = OsRef(key=img.key, label=img.label)
        for path in (img.answer_template, img.ipxe_chain):
            top = path.split("/", 1)[0] if "/" in path else ""
            if not top:
                continue
            bucket = mapping.setdefault(top, [])
            if not any(r.key == ref.key for r in bucket):
                bucket.append(ref)
    return mapping


def _within_base(candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(BASE_DIR.resolve())
        return True
    except (ValueError, OSError):
        return False


def _looks_binary(sample: bytes) -> bool:
    if b"\x00" in sample:
        return True
    try:
        sample.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


def list_groups() -> list[AnswerGroup]:
    """Return the answer-file tree grouped by directory, OS-annotated.

    Directories mapped to catalog OSes come first (ordered like the catalog);
    infra/loose files land in a trailing 'shared' group. Missing base dir yields
    an empty list rather than an error.
    """
    base = BASE_DIR
    if not base.is_dir():
        return []

    dir_os = _dir_to_os()
    by_dir: dict[str, list[AnswerFile]] = {}
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if not _within_base(path):        # defend against symlink escape
            continue
        rel = path.relative_to(base).as_posix()
        top = rel.split("/", 1)[0] if "/" in rel else _SHARED
        kind, syntax = _kind_for(path.name)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        is_binary = syntax == "binary"
        by_dir.setdefault(top, []).append(AnswerFile(
            name=path.name, relpath=rel, kind=kind, syntax=syntax,
            size=size, is_binary=is_binary))

    # Order: catalog-mapped dirs in catalog order, then the rest, then shared.
    ordered_dirs: list[str] = []
    for img in catalog.all_images():
        for path in (img.answer_template, img.ipxe_chain):
            top = path.split("/", 1)[0] if "/" in path else ""
            if top and top in by_dir and top not in ordered_dirs:
                ordered_dirs.append(top)
    for top in sorted(by_dir):
        if top not in ordered_dirs and top != _SHARED:
            ordered_dirs.append(top)
    if _SHARED in by_dir:
        ordered_dirs.append(_SHARED)

    groups: list[AnswerGroup] = []
    for top in ordered_dirs:
        refs = tuple(dir_os.get(top, ()))
        if top == _SHARED:
            title = "Shared / boot infrastructure"
        elif refs:
            title = ", ".join(r.label for r in refs)
        else:
            title = top
        groups.append(AnswerGroup(
            directory=top, title=title, os_refs=refs,
            files=tuple(sorted(by_dir[top], key=lambda f: f.name)),
        ))
    return groups


@dataclass(frozen=True)
class FileView:
    relpath: str
    name: str
    kind: str
    syntax: str
    size: int
    is_binary: bool
    too_large: bool
    content: str        # empty when binary/too large


def read_file(relpath: str) -> FileView | None:
    """Safely read a single answer file for viewing.

    Returns None if the path is invalid, escapes the base dir, or does not exist.
    Binary or oversized files return a FileView with empty content and the
    corresponding flag set (so the caller can render a placeholder).
    """
    if not relpath or relpath.startswith(("/", "\\")) or ".." in relpath.split("/"):
        return None
    candidate = BASE_DIR / relpath
    if not _within_base(candidate) or not candidate.is_file():
        return None

    kind, syntax = _kind_for(candidate.name)
    try:
        size = candidate.stat().st_size
    except OSError:
        return None

    too_large = size > _MAX_VIEW_BYTES
    is_binary = syntax == "binary"
    content = ""
    if not too_large and not is_binary:
        try:
            data = candidate.read_bytes()
        except OSError:
            return None
        if _looks_binary(data[:4096]):
            is_binary = True
        else:
            content = data.decode("utf-8", errors="replace")

    return FileView(
        relpath=candidate.relative_to(BASE_DIR).as_posix(), name=candidate.name,
        kind=kind, syntax=syntax, size=size, is_binary=is_binary,
        too_large=too_large, content=content)
