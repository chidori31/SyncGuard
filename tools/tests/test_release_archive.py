# FILE tools/tests/test_release_archive.py
import hashlib
import io
import json
import zipfile

import pytest

from tools.release_archive import source_archive


def test_zip_metadata_has_fixed_platform():
    with zipfile.ZipFile(io.BytesIO(source_archive({"file.txt": b"data"}, "a" * 40))) as archive:
        assert all(info.create_system == 3 for info in archive.infolist())


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
        "safe\x00.py",
        ".GIT/config",
        ".ENV",
        "README.md.",
        "folder/name ",
        "folder/con.txt",
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


def test_file_and_directory_collision():
    with pytest.raises(ValueError):
        source_archive({"a": b"file", "A/b.txt": b"nested"}, VALID_COMMIT)


def test_commit_cannot_contain_trailing_newline():
    with pytest.raises(ValueError):
        source_archive({"a.txt": b"file"}, VALID_COMMIT + "\n")


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
