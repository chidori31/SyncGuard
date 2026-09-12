"""Real-Git tests adapted from the Qwen delegated draft; expected rejection is mandatory."""

import subprocess

import pytest

from tools.check_secrets import GitScannerError, main, scan_repository


def git(root, *args, input=None):
    return subprocess.run(["git", "-C", str(root), *args], input=input, capture_output=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Synthetic Test")
    git(tmp_path, "config", "user.email", "test@example.test")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "config", "core.autocrlf", "false")
    return tmp_path


def stage(repo, name, content):
    path = repo / name
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(content, encoding="utf-8")
    git(repo, "add", "--", name)


def test_staged_credential_cannot_hide_in_clean_working_copy(repo):
    stage(repo, "config.txt", "gsk_" + "A" * 45)
    (repo / "config.txt").write_text("clean", encoding="utf-8")
    assert scan_repository(repo) == ["config.txt"]


def test_committed_snapshot_ignores_untracked_and_later_staged_data(repo):
    stage(repo, "clean.txt", "clean")
    git(repo, "commit", "-m", "baseline")
    stage(repo, "staged.txt", "gsk_" + "A" * 45)
    (repo / ".env").write_text("private local placeholder", encoding="utf-8")
    assert scan_repository(repo, "HEAD") == []
    assert scan_repository(repo) == ["staged.txt"]


@pytest.mark.parametrize("name", [".env", "nested/.env.local", "a space.txt"])
def test_forbidden_environment_files_and_space_paths(repo, name):
    stage(repo, name, "gsk_" + "A" * 45 if name.endswith("txt") else "innocuous")
    assert scan_repository(repo) == [name]


def test_example_is_allowed_but_not_exempt_from_content_scan(repo):
    stage(repo, ".env.example", "MY_VALUE=")
    assert scan_repository(repo) == []
    stage(repo, ".env.example", "ghp_" + "B" * 40)
    assert scan_repository(repo) == [".env.example"]


def test_symlink_is_rejected_without_following_it(repo):
    digest = git(repo, "hash-object", "-w", "--stdin", input=b"/outside/private").decode().strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"120000,{digest},pointer")
    assert scan_repository(repo) == ["pointer"]


def test_unmerged_entries_fail_closed(repo):
    digest = git(repo, "hash-object", "-w", "--stdin", input=b"clean").decode().strip()
    git(
        repo,
        "update-index",
        "--index-info",
        input=f"100644 {digest} 1\tconflict.txt\n100644 {digest} 2\tconflict.txt\n".encode(),
    )
    assert scan_repository(repo) == ["conflict.txt"]


def test_empty_repository_does_not_claim_a_clean_release(repo):
    with pytest.raises(GitScannerError):
        scan_repository(repo)


def test_subdirectory_scans_entire_repository(repo):
    stage(repo, "outer.txt", "gsk_" + "A" * 45)
    (repo / "nested").mkdir()
    assert scan_repository(repo / "nested") == ["outer.txt"]


@pytest.mark.parametrize("ref", ["missing-ref", "--help"])
def test_invalid_revision_fails_safely(repo, ref):
    stage(repo, "clean.txt", "clean")
    git(repo, "commit", "-m", "baseline")
    with pytest.raises(GitScannerError):
        scan_repository(repo, ref)


def test_private_key_in_regular_file_is_rejected(repo):
    stage(repo, "material.txt", "-----BEGIN " + "RSA " + "PRIVATE " + "KEY-----")
    assert scan_repository(repo) == ["material.txt"]


def test_cli_reports_filename_only(repo, capsys):
    value = "gsk_" + "A" * 45
    stage(repo, "config.txt", value)
    assert main([str(repo)]) == 1
    output = capsys.readouterr().out
    assert "config.txt" in output and value not in output


def test_nonrepository_cli_returns_safe_error(tmp_path, capsys):
    assert main([str(tmp_path)]) == 2
    assert str(tmp_path) not in capsys.readouterr().err
