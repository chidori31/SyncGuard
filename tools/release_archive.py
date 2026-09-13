# FILE tools/release_archive.py
"""Build a deterministic in-memory ZIP archive of source files."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile

_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_FIXED_DATE = (1980, 1, 1, 0, 0, 0)
_MAX_FILE = 10 * 1024 * 1024
_MAX_TOTAL = 50 * 1024 * 1024
_RESERVED = frozenset({"RELEASE-MANIFEST.json"})


def _validate_name(name: str) -> None:
    if not isinstance(name, str):
        raise TypeError("filename must be text")
    if not name or name.startswith("/") or "\\" in name or ":" in name:
        raise ValueError(f"unsafe filename: {name!r}")
    if any(ord(char) < 32 or char in '<>"|?*' for char in name):
        raise ValueError("filename contains unsupported characters")
    for part in name.split("/"):
        folded = part.casefold()
        if (
            folded in ("", ".", "..", ".git")
            or folded in {item.casefold() for item in _RESERVED}
            or part.endswith((".", " "))
        ):
            raise ValueError(f"unsafe filename: {name!r}")
        if folded == ".env" or (folded.startswith(".env.") and folded != ".env.example"):
            raise ValueError(f"unsafe filename: {name!r}")
        if folded.split(".")[0] in {
            "con",
            "prn",
            "aux",
            "nul",
            *(f"com{i}" for i in range(1, 10)),
            *(f"lpt{i}" for i in range(1, 10)),
        }:
            raise ValueError("filename is reserved on Windows")


def source_archive(files: dict[str, bytes], commit: str) -> bytes:
    if not isinstance(files, dict):
        raise TypeError("files must be a mapping")
    if not files:
        raise ValueError("files must not be empty")
    if not isinstance(commit, str) or not _COMMIT_RE.fullmatch(commit):
        raise ValueError("commit must be 40 or 64 lowercase hex characters")

    total = 0
    for name, content in files.items():
        if not isinstance(content, bytes):
            raise TypeError(f"content for {name!r} must be bytes, got {type(content).__name__}")
        _validate_name(name)
        if len(content) > _MAX_FILE:
            raise ValueError(f"file {name!r} exceeds 10 MiB limit")
        total += len(content)
    if total > _MAX_TOTAL:
        raise ValueError("total content exceeds 50 MiB limit")

    seen: dict[str, str] = {}
    for name in files:
        folded = name.casefold()
        if folded in seen:
            raise ValueError(f"case-insensitive collision: {name!r} vs {seen[folded]!r}")
        seen[folded] = name
    for name in seen:
        parts = name.split("/")
        if any("/".join(parts[:index]) in seen for index in range(1, len(parts))):
            raise ValueError("file and directory paths collide")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            info = zipfile.ZipInfo(f"SyncGuard/{name}", date_time=_FIXED_DATE)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, files[name])
        manifest = {
            "commit": commit,
            "files": {n: hashlib.sha256(files[n]).hexdigest() for n in sorted(files)},
        }
        info = zipfile.ZipInfo("SyncGuard/RELEASE-MANIFEST.json", date_time=_FIXED_DATE)
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8"))
    return buf.getvalue()
