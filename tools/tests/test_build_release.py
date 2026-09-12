import builtins
import hashlib
import json
import subprocess
import zipfile

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
    git("config", "commit.gpgsign", "false")
    git("config", "core.autocrlf", "false")
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
        assert zf.read("SyncGuard/hello.txt") == b"original"
    assert result["file_count"] == 1


def test_untracked_env_excluded(repo):
    r, git = repo
    _commit(r, git, {"app.py": "print(1)"})
    (r / ".env").write_text("local configuration")
    out = _out_dir(r) / "release.zip"
    result = build_release(r, out)
    with zipfile.ZipFile(out) as zf:
        assert "SyncGuard/.env" not in zf.namelist()
    assert result["file_count"] == 1


def test_tracked_env_rejected(repo):
    r, git = repo
    _commit(r, git, {".env": "local configuration", "app.py": "print(1)"})
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
    _commit(r, git, {".env": "local configuration"})
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
        assert zf.read("SyncGuard/a.txt") == b"hello"
        assert zf.read("SyncGuard/b.txt") == b"world"
        names = zf.namelist()
        assert "SyncGuard/a.txt" in names and "SyncGuard/b.txt" in names
        manifest = json.loads(zf.read("SyncGuard/RELEASE-MANIFEST.json"))
        assert manifest == {
            "commit": result["commit"],
            "files": {
                name: hashlib.sha256(content).hexdigest()
                for name, content in {"a.txt": b"hello", "b.txt": b"world"}.items()
            },
        }
    # commit in result is a valid 40-char hex string
    assert len(result["commit"]) == 40
    assert all(c in "0123456789abcdef" for c in result["commit"])


def test_subdirectory_includes_entire_committed_tree(repo):
    r, git = repo
    _commit(r, git, {"root.txt": "root", "nested/a.txt": "nested"})
    out = _out_dir(r) / "release.zip"
    build_release(r / "nested", out)
    with zipfile.ZipFile(out) as zf:
        assert zf.read("SyncGuard/root.txt") == b"root"
        assert zf.read("SyncGuard/nested/a.txt") == b"nested"


@pytest.mark.parametrize("failed_suffix", [".zip", ".sha256"])
def test_partial_write_cleans_only_created_files(repo, monkeypatch, failed_suffix):
    r, git = repo
    _commit(r, git, {"a.txt": "data"})
    out = _out_dir(r) / "release.zip"
    preserved = out.parent / "keep.txt"
    preserved.write_bytes(b"keep")
    real_open = builtins.open

    class FailingWriter:
        def __init__(self, file):
            self.file = file

        def __enter__(self):
            return self

        def write(self, data):
            self.file.write(data[:2])
            raise OSError("injected disk failure")

        def __exit__(self, *args):
            self.file.close()

    def failing_open(path, mode="r", *args, **kwargs):
        file = real_open(path, mode, *args, **kwargs)
        return FailingWriter(file) if mode == "xb" and str(path).endswith(failed_suffix) else file

    monkeypatch.setattr(builtins, "open", failing_open)
    with pytest.raises(OSError):
        build_release(r, out)
    assert not out.exists()
    assert not out.with_name(out.name + ".sha256").exists()
    assert preserved.read_bytes() == b"keep"


def test_existing_checksum_preserved(repo):
    r, git = repo
    _commit(r, git, {"a.txt": "data"})
    out = _out_dir(r) / "release.zip"
    checksum = out.with_name(out.name + ".sha256")
    checksum.write_bytes(b"existing")
    with pytest.raises(ValueError, match="already exists"):
        build_release(r, out)
    assert checksum.read_bytes() == b"existing"
    assert not out.exists()
