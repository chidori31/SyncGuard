#!/usr/bin/env python3
"""Build a deterministic release archive from a Git commit."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

if __package__:
    from .check_secrets import GitScannerError, scan_repository
    from .release_archive import source_archive
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.check_secrets import GitScannerError, scan_repository
    from tools.release_archive import source_archive

MAX_BLOB = 10 * 1024 * 1024
MAX_TOTAL = 50 * 1024 * 1024
_TIMEOUT = 30


def _git(root: Path, *args: str) -> bytes:
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        raise ValueError("git command could not complete") from None
    if r.returncode != 0:
        raise ValueError("git operation failed")
    return r.stdout


def build_release(root: Path, output: Path, ref: str = "HEAD") -> dict:
    root = root.resolve()
    toplevel = Path(_git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    root = toplevel
    commit = _git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        raise ValueError("invalid Git commit")
    findings = scan_repository(toplevel, commit)
    if findings:
        raise ValueError(f"security scan found {len(findings)} issue(s)")
    raw = _git(root, "ls-tree", "-r", "-z", commit)
    entries = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        meta, path = item.split(b"\t", 1)
        parts = meta.decode().split()
        if len(parts) != 3 or parts[1] != "blob" or parts[0] not in {"100644", "100755"}:
            raise ValueError("unsupported Git tree entry")
        entries.append((parts[2], path.decode()))
    total = 0
    for sha, path in entries:
        size = int(_git(root, "cat-file", "-s", sha).decode().strip())
        if not 0 <= size <= MAX_BLOB:
            raise ValueError("blob exceeds 10MiB limit")
        total += size
        if total > MAX_TOTAL:
            raise ValueError("total blob size exceeds 50MiB limit")
    files = {path: _git(root, "cat-file", "blob", sha) for sha, path in entries}
    output = output.absolute()
    if os.path.lexists(output):
        raise ValueError("output path already exists")
    output = output.parent.resolve() / output.name
    if output.is_relative_to(toplevel):
        raise ValueError("output must be outside the repository")
    if not output.parent.is_dir():
        raise ValueError("output parent directory does not exist")
    sha_file = output.parent / (output.name + ".sha256")
    if os.path.lexists(output) or os.path.lexists(sha_file):
        raise ValueError("output path already exists")
    data = source_archive(files, commit)
    digest = hashlib.sha256(data).hexdigest()
    created = []
    try:
        with open(output, "xb") as f:
            created.append(output)
            f.write(data)
        with open(sha_file, "xb") as f:
            created.append(sha_file)
            f.write((digest + "\n").encode("ascii"))
    except BaseException:
        for p in created:
            try:
                p.unlink()
            except OSError:
                pass
        raise
    return {"commit": commit, "path": str(output), "sha256": digest, "file_count": len(files)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build release archive")
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = ap.parse_args(argv)
    try:
        r = build_release(args.root, args.output, args.ref)
        print(json.dumps(r, ensure_ascii=True))
    except (ValueError, GitScannerError, OSError):
        print("Release failed: check Git ref, scanner findings and output permissions.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
