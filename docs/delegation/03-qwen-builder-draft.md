FILE: tools/build_release.py
```text
#!/usr/bin/env python3
"""Build a deterministic release archive from a Git commit."""
import argparse, hashlib, os, subprocess, sys
from pathlib import Path

if __package__:
    from .release_archive import source_archive
    from .check_secrets import scan_repository
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.release_archive import source_archive
    from tools.check_secrets import scan_repository

MAX_BLOB = 10 * 1024 * 1024
MAX_TOTAL = 50 * 1024 * 1024
_TIMEOUT = 30


def _git(root: Path, *args: str) -> bytes:
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise ValueError("git command timed out")
    if r.returncode != 0:
        raise ValueError("git operation failed")
    return r.stdout


def build_release(root: Path, output: Path, ref: str = "HEAD") -> dict:
    root = root.resolve()
    toplevel = Path(_git(root, "rev-parse", "--show-toplevel").decode().strip())
    commit = _git(root, "rev-parse", "--verify", "--end-of-options",
                  f"{ref}^{{commit}}").decode().strip()
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
        if parts[1] != "blob":
            continue
        entries.append((parts[2], path.decode()))
    total = 0
    for sha, path in entries:
        size = int(_git(root, "cat-file", "-s", sha).decode().strip())
        if size > MAX_BLOB:
            raise ValueError(f"blob {path} exceeds 10MiB limit")
        total += size
        if total > MAX_TOTAL:
            raise ValueError("total blob size exceeds 50MiB limit")
    files = {path: _git(root, "cat-file", "blob", sha) for sha, path in entries}
    output = output.resolve()
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
            f.write(data)
        created.append(output)
        with open(sha_file, "xb") as f:
            f.write(digest + "\n")
        created.append(sha_file)
    except BaseException:
        for p in created:
            try:
                p.unlink()
            except OSError:
                pass
        raise
    return {"commit": commit, "path": str(output), "sha256": digest, "file_count": len(files)}


def main():
    ap = argparse.ArgumentParser(description="Build release archive")
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = ap.parse_args()
    try:
        r = build_release(args.root, args.output, args.ref)
        for k, v in r.items():
            print(f"{k}={v}")
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

FILE: tools/tests/test_build_release.py
```text
import hashlib, subprocess, zipfile
from pathlib import Path

import pytest

from tools.build_release import build_release


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=r, check=True, capture_output=True)

    git("init")
    git("config", "user.email", "test@test.com")
    git("config", "user.name", "Test")
    return r, git


def _commit(r, git, files):
    for name, content in files.items():
        p = r / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    git("add", "-A")
    git("commit", "-m", "test")


def _out_dir(repo_dir):
    d = repo_dir.parent / "out"
    d.mkdir(exist_ok=True)
    return d


def test_modified_working_file_excluded(repo):
    r, git = repo
    _commit(r, git, {"hello.txt": "original"})
    (r / "hello.txt").write_text("modified")
    out = _out_dir(r) / "release.zip"
    result = build_release(r, out)
    with zipfile.ZipFile(out) as zf:
        assert zf.read("hello.txt") == b"original"
    assert result["file_count"] == 1


def test_untracked_env_excluded(repo):
    r, git = repo
    _commit(r, git, {"app.py": "print(1)"})
    (r / ".env").write_text("SECRET=[REDACTED]
    out = _out_dir(r) / "release.zip"
    result = build_release(r, out)
    with zipfile.ZipFile(out) as zf:
        assert ".env" not in zf.namelist()
    assert result["file_count"] == 1


def test_tracked_env_rejected(repo):
    r, git = repo
    _commit(r, git, {".env": "SECRET=[REDACTED], "app.py": "print(1)"})
    out = _out_dir(r) / "release.zip"
    with pytest.raises(ValueError, match="security scan"):
        build_release(r, out)


def test_existing_output_preserved(repo):
    r, git = repo
    _commit(r, git, {"a.txt": "data"})
    out = _out_dir(r) / "release.zip"
    out.write_bytes(b"existing")
    with pytest.raises(ValueError, match="already exists"):
        build_release(r, out)
    assert out.read_bytes() == b"existing"


def test_output_inside_repo_rejected(repo):
    r, git = repo
    _commit(r, git, {"a.txt": "data"})
    out = r / "release.zip"
    with pytest.raises(ValueError, match="outside"):
        build_release(r, out)
    assert not out.exists()


def test_no_artifact_on_failure(repo):
    r, git = repo
    _commit(r, git, {".env": "SECRET=[REDACTED]})
    out = _out_dir(r) / "release.zip"
    with pytest.raises(ValueError):
        build_release(r, out)
    assert not out.exists()
    assert not (out.parent / "release.zip.sha256").exists()


def test_zip_manifest_consistent(repo):
    r, git = repo
    _commit(r, git, {"a.txt": "hello", "b.txt": "world"})
    out = _out_dir(r) / "release.zip"
    result = build_release(r, out)
    data = out.read_bytes()
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    assert result["file_count"] == 2
    assert (out.parent / "release.zip.sha256").read_text().strip() == result["sha256"]
    with zipfile.ZipFile(out) as zf:
        assert zf.read("a.txt") == b"hello"
        assert zf.read("b.txt") == b"world"
        names = zf.namelist()
        assert "a.txt" in names and "b.txt" in names
    # commit in result is a valid 40-char hex string
    assert len(result["commit"]) == 40
    assert all(c in "0123456789abcdef" for c in result["commit"])
```
