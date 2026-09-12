```text
# FILE tools/tests/test_release_archive.py
import hashlib
import io
import json
import zipfile

import pytest

from tools.release_archive import source_archive

VALID_COMMIT = "a" * 40
VALID_COMMIT_64 = "b" * 64


def _read_zip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {i.filename: zf.read(i.filename) for i in zf.infolist()}


def test_exact_bytes_in_zip():
    content = b"print('hello')"
    result = source_archive({"src/main.py": content}, VALID_COMMIT)
    entries = _read_zip(result)
    assert entries["SyncGuard/src/main.py"] == content
    manifest = json.loads(entries["SyncGuard/RELEASE-MANIFEST.json"])
    assert manifest == {"commit": VALID_COMMIT, "files": {"src/main.py": hashlib.sha256(content).hexdigest()}}


def test_deterministic_despite_insertion_order():
    a = {"b.py": b"2", "a.py": b"1"}
    b = {"a.py": b"1", "b.py": b"2"}
    assert source_archive(a, VALID_COMMIT) == source_archive(b, VALID_COMMIT)


def test_manifest_sha_independent():
    content = b"some content"
    entries = _read_zip(source_archive({"file.txt": content}, VALID_COMMIT))
    manifest = json.loads(entries["SyncGuard/RELEASE-MANIFEST.json"])
    assert manifest["files"]["file.txt"] == hashlib.sha256(content).hexdigest()


def test_64_char_commit_accepted():
    result = source_archive({"a.txt": b"x"}, VALID_COMMIT_64)
    manifest = json.loads(_read_zip(result)["SyncGuard/RELEASE-MANIFEST.json"])
    assert manifest["commit"] == VALID_COMMIT_64


@pytest.mark.parametrize(
    "name",
    [
        "/etc/passwd",
        "",
        "a\\b",
        "a:b",
        "a/./b",
        "a/../b",
        "a//b",
        ".git/config",
        "a/.git/b",
        ".env",
        "a/.env",
        ".env.local",
        "a/.env.secrets",
        "RELEASE-MANIFEST.json",
        "a/RELEASE-MANIFEST.json",
    ],
)
def test_unsafe_filenames_rejected(name):
    with pytest.raises(ValueError):
        source_archive({name: b"data"}, VALID_COMMIT)


def test_env_example_allowed():
    result = source_archive({".env.example": b"X=1"}, VALID_COMMIT)
    assert "SyncGuard/.env.example" in _read_zip(result)


def test_case_insensitive_collision():
    with pytest.raises(ValueError):
        source_archive({"Foo.txt": b"1", "foo.txt": b"2"}, VALID_COMMIT)


def test_wrong_content_type():
    with pytest.raises(TypeError):
        source_archive({"a.txt": "not bytes"}, VALID_COMMIT)


def test_empty_map_rejected():
    with pytest.raises(ValueError):
        source_archive({}, VALID_COMMIT)


@pytest.mark.parametrize("commit", ["A" * 40, "a" * 39, "a" * 41, "g" * 40, "", "a" * 63, "a" * 65])
def test_bad_commit_rejected(commit):
    with pytest.raises(ValueError):
        source_archive({"a.txt": b"data"}, commit)


def test_file_size_exceeded():
    with pytest.raises(ValueError):
        source_archive({"big.txt": b"x" * (10 * 1024 * 1024 + 1)}, VALID_COMMIT)


def test_total_size_exceeded():
    files = {f"f{i}.txt": b"x" * (10 * 1024 * 1024) for i in range(5)}
    files["extra.txt"] = b"y"
    with pytest.raises(ValueError):
        source_archive(files, VALID_COMMIT)
```

```text
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
    if not name or name.startswith("/") or "\\" in name or ":" in name:
        raise ValueError(f"unsafe filename: {name!r}")
    for part in name.split("/"):
        if part in ("", ".", "..", ".git") or part in _RESERVED:
            raise ValueError(f"unsafe filename: {name!r}")
        if part == ".env" or (part.startswith(".env.") and part != ".env.example"):
            raise ValueError(f"unsafe filename: {name!r}")


def source_archive(files: dict[str, bytes], commit: str) -> bytes:
    if not files:
        raise ValueError("files must not be empty")
    if not isinstance(commit, str) or not _COMMIT_RE.match(commit):
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
        key = [REDACTED]
        if key in seen:
            raise ValueError(f"case-insensitive collision: {name!r} vs {seen[key]!r}")
        seen[key] = name

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            info = zipfile.ZipInfo(f"SyncGuard/{name}", date_time=_FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, files[name])
        manifest = {
            "commit": commit,
            "files": {n: hashlib.sha256(files[n]).hexdigest() for n in sorted(files)},
        }
        info = zipfile.ZipInfo("SyncGuard/RELEASE-MANIFEST.json", date_time=_FIXED_DATE)
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, json.dumps(manifest, sort_keys=[REDACTED]
    return buf.getvalue()
```
