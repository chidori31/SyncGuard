## CRITICAL ISSUES

None in the design as specified. The approach of reading blobs via `git cat-file blob <hash>` (argv, `shell=False`) is correct and avoids path-injection through filenames.

## RISKS

- **Binary blobs**: `cat-file blob` may return non-UTF-8 bytes. Decoding with `errors="replace"` is safe for regex matching (binary won't match text patterns) but I note it explicitly.
- **Large blobs**: Reading an entire blob into memory could be problematic for multi-GB objects. For a credential scanner this is acceptable (you'd want to stream, but the stdlib-only constraint and typical repo sizes make this fine). A `--max-blob-size` guard could be added later.
- **`git ls-files --stage -z` on a repo with a sparse index or `SKIP_WORKTREE` bit**: The entries still appear in the index; the scanner reads the blob by hash, so it works regardless of working-tree state. This is the desired behaviour.

## SUGGESTIONS

- Consider adding a `--max-blob-size` flag (e.g. 10 MiB) to skip huge blobs.
- The PEM pattern `-----BEGIN [A-Z ]*PRIVATE KEY-----` will also match `[SYNTHETIC PEM HEADER REMOVED]`. That's intentional (encrypted keys are still sensitive).
- For production hardening, run the scanner in a restricted umask and ensure the temp directory for tests is `0700`.

## TESTS

Covered below: clean, staged-then-cleaned, committed-ref-ignores-untracked, space-in-filename, synthetic symlink, `.env` refusal, non-repo, unmerged index.

---

```text
# FILE: tests/test_git_scanner.py
"""Tests for git_scanner using temporary git repositories."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from git_scanner import GitScannerError, scan_repository  # noqa: E402

# --- Synthetic credential fragments (no contiguous realistic secret in source) ---

def _groq_key() -> str:
    return "gsk_" + "aB" * 20  # gsk_ + 40 alphanumerics

def _gh_pat() -> str:
    return "ghp_" + "Zz" * 18  # ghp_ + 36 alphanumerics

def _pem_block() -> str:
    return "-----BEGIN " + "RSA " + "PRIVATE " + "KEY-----"

# --- Helpers ---

def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
    )

def _init_repo(root: Path) -> None:
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")

# --- Tests ---

def test_clean_contents(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "readme.txt").write_text("hello world\n")
    _git(repo, "add", "readme.txt")
    _git(repo, "commit", "-m", "init")

    findings = scan_repository(repo)
    assert findings == []


def test_staged_secret_cleaned_working_file(tmp_path: Path) -> None:
    """Secret is staged; working copy is deleted. Index blob still contains it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    f = repo / "config.yaml"
    f.write_text(f"api_key: [REDACTED]}\n")
    _git(repo, "add", "config.yaml")
    # Clean the working file – the blob remains in the index
    f.write_text("api_key: [REDACTED]

    findings = scan_repository(repo)
    assert findings == ["config.yaml"]


def test_committed_ref_ignores_untracked(tmp_path: Path) -> None:
    """Scanning a committed ref must not see untracked files."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "clean.txt").write_text("nothing here\n")
    _git(repo, "add", "clean.txt")
    _git(repo, "commit", "-m", "init")
    # Untracked file with a secret
    (repo / "secrets.txt").write_text(f"token=[REDACTED]}\n")

    findings = scan_repository(repo, ref="HEAD")
    assert findings == []


def test_space_in_filename(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    fname = "my config.txt"
    (repo / fname).write_text(f"key=[REDACTED]}\n")
    _git(repo, "add", fname)

    findings = scan_repository(repo)
    assert findings == [fname]


def test_symlink_rejected(tmp_path: Path) -> None:
    """A mode-120000 entry in the index must be skipped."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    # Create a blob to use as the symlink target hash
    (repo / "target.txt").write_text("link target\n")
    _git(repo, "add", "target.txt")
    _git(repo, "commit", "-m", "add target")
    # Get the blob hash
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD:target.txt"],
        capture_output=True, text=True, check=True,
    )
    blob_hash = result.stdout.strip()
    # Remove from index, re-add as symlink
    _git(repo, "rm", "--cached", "target.txt")
    _git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob_hash},link_name")

    findings = scan_repository(repo)
    assert findings == []


def test_env_file_rejected(tmp_path: Path) -> None:
    """Tracked .env files must be skipped even if they contain secrets."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / ".env").write_text(f"GROQ_KEY=[REDACTED]}\n")
    _git(repo, "add", ".env")

    findings = scan_repository(repo)
    assert findings == []


def test_env_example_not_rejected(tmp_path: Path) -> None:
    """.env.example is allowed and scanned normally."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / ".env.example").write_text(f"KEY=[REDACTED]}\n")
    _git(repo, "add", ".env.example")

    findings = scan_repository(repo)
    assert findings == [".env.example"]


def test_not_a_git_repo(tmp_path: Path) -> None:
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    (plain / "file.txt").write_text("hello\n")

    with pytest.raises(GitScannerError, match="not a valid git repository"):
        scan_repository(plain)


def test_unmerged_index_skipped(tmp_path: Path) -> None:
    """Entries with stage != 0 (unmerged) must be skipped."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    # Create two blobs
    (repo / "a.txt").write_text(f"secret=[REDACTED]}\n")
    (repo / "b.txt").write_text("clean\n")
    _git(repo, "add", "a.txt", "b.txt")
    _git(repo, "commit", "-m", "init")
    # Remove both from index
    _git(repo, "rm", "--cached", "a.txt", "b.txt")
    # Re-add as unmerged stages via --index-info
    hash_a = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD:a.txt"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    hash_b = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD:b.txt"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    index_info = f"100644 {hash_a} 1\ta.txt\n100644 {hash_b} 2\ta.txt\n"
    subprocess.run(
        ["git", "-C", str(repo), "update-index", "--index-info"],
        input=index_info,
        text=True,
        check=True,
        capture_output=True,
    )

    findings = scan_repository(repo)
    assert findings == []


def test_pem_detection(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "key.pem").write_text(_pem_block() + "\n" + "MIIEpAIBAAKCAQEA\n" + "-----END " + "RSA " + "PRIVATE " + "KEY-----\n")
    _git(repo, "add", "key.pem")

    findings = scan_repository(repo)
    assert findings == ["key.pem"]


def test_executable_mode_scanned(tmp_path: Path) -> None:
    """Mode 100755 blobs are scanned like 100644."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    script = repo / "deploy.sh"
    script.write_text(f"#!/bin/sh\nexport GROQ={_groq_key()}\n")
    script.chmod(0o755)
    _git(repo, "add", "deploy.sh")

    findings = scan_repository(repo)
    assert findings == ["deploy.sh"]
```

```text
# FILE: git_scanner.py
"""Scan git staged index blobs or a committed tree for credential patterns.

Uses only the Python standard library.  All git invocations use argv lists
with shell=False.  Findings contain filenames only – never the matched text.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

__all__ = ["GitScannerError", "scan_repository", "main"]

# ---------------------------------------------------------------------------
# Credential patterns (built from short fragments; no contiguous realistic
# credential appears in this source file).
# ---------------------------------------------------------------------------

_GROQ_RE = re.compile(r"gsk_[A-Za-z0-9]{40,}")
_GH_PAT_RE = re.compile(
    r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,255}"
)
_PEM_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")

_PATTERNS: tuple[re.Pattern[str], ...] = (_GROQ_RE, _GH_PAT_RE, _PEM_RE)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALLOWED_MODES = frozenset({"100644", "100755"})
_ENV_EXAMPLE = ".env.example"
_ENV_RE = re.compile(r"^\.env(\..+)?$")
_GIT_TIMEOUT = 30  # seconds


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class GitScannerError(Exception):
    """Unrecoverable scanner error (bad repo, git failure, etc.)."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_git(root: Path, *args: str) -> bytes:
    """Execute a git sub-command; return raw stdout bytes.

    Raises GitScannerError on any failure without exposing stderr.
    """
    cmd = ["git", "-C", str(root), *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            shell=False,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitScannerError(
            f"git {args[0] if args else 'command'} failed: {exc.__class__.__name__}"
        ) from None
    if proc.returncode != 0:
        raise GitScannerError(
            f"git {args[0] if args else 'command'} returned nonzero exit"
        )
    return proc.stdout


def _is_env_file(path: str) -> bool:
    """True for .env and .env.* except .env.example."""
    if path == _ENV_EXAMPLE:
        return False
    return bool(_ENV_RE.match(path))


def _parse_stage_entries(data: str) -> list[tuple[str, str, str, str]]:
    """Parse `git ls-files --stage -z` NUL-delimited records.

    Each record: ``<mode> SP <hash> SP <stage> TAB <path> NUL``
    Returns list of (mode, hash, stage, path).
    """
    entries: list[tuple[str, str, str, str]] = []
    for record in data.split("\0"):
        if not record:
            continue
        tab = record.find("\t")
        if tab < 0:
            continue
        meta, path = record[:tab], record[tab + 1:]
        parts = meta.split(" ", 2)  # mode, hash, stage
        if len(parts) != 3:
            continue
        entries.append((parts[0], parts[1], parts[2], path))
    return entries


def _parse_tree_entries(data: str) -> list[tuple[str, str, str, str]]:
    """Parse `git ls-tree -r -z <ref>` NUL-delimited records.

    Each record: ``<mode> SP <type> SP <hash> TAB <path> NUL``
    Returns list of (mode, type, hash, path).
    """
    entries: list[tuple[str, str, str, str]] = []
    for record in data.split("\0"):
        if not record:
            continue
        tab = record.find("\t")
        if tab < 0:
            continue
        meta, path = record[:tab], record[tab + 1:]
        parts = meta.split(" ", 2)  # mode, type, hash
        if len(parts) != 3:
            continue
        entries.append((parts[0], parts[1], parts[2], path))
    return entries


def _read_blob(root: Path, obj_hash: str) -> str:
    """Read a blob by hash; return decoded text (binary-safe)."""
    raw = _run_git(root, "cat-file", "blob", obj_hash)
    return raw.decode("utf-8", errors="replace")


def _matches(content: str) -> bool:
    """Return True if *content* contains any credential pattern."""
    for pat in _PATTERNS:
        if pat.search(content):
            return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_repository(root: Path, ref: str | None = None) -> list[str]:
    """Scan the git index (staged) or a committed tree for credentials.

    Parameters
    ----------
    root:
        Path to the repository (or a sub-directory within it).
    ref:
        If *None*, scan the staged index.  Otherwise scan the tree at
        *ref* (branch, tag, commit, etc.).

    Returns
    -------
    list[str]
        Filenames (relative to repo root) where a credential pattern was
        detected.  The matched text is never returned or printed.

    Raises
    ------
    GitScannerError
        If *root* is not a valid git repository or a git command fails.
    """
    root = Path(root).resolve()

    # Validate repository
    try:
        _run_git(root, "rev-parse", "--git-dir")
    except GitScannerError:
        raise GitScannerError("not a valid git repository") from None

    findings: list[str] = []

    if ref is None:
        # --- Staged index ---
        raw = _run_git(root, "ls-files", "--stage", "-z")
        entries = _parse_stage_entries(raw.decode("utf-8", errors="replace"))
        for mode, obj_hash, stage, path in entries:
            if stage != "0":
                continue  # unmerged
            if mode not in _ALLOWED_MODES:
                continue  # symlink, submodule, etc.
            if _is_env_file(path):
                continue
            content = _read_blob(root, obj_hash)
            if _matches(content):
                findings.append(path)
    else:
        # --- Committed tree ---
        raw = _run_git(root, "ls-tree", "-r", "-z", ref)
        entries = _parse_tree_entries(raw.decode("utf-8", errors="replace"))
        for mode, obj_type, obj_hash, path in entries:
            if obj_type != "blob":
                continue  # commit (submodule), tree, etc.
            if mode not in _ALLOWED_MODES:
                continue
            if _is_env_file(path):
                continue
            content = _read_blob(root, obj_hash)
            if _matches(content):
                findings.append(path)

    return findings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Entry point.  Returns 0 (clean), 1 (findings), 2 (error)."""
    parser = argparse.ArgumentParser(
        prog="git-scanner",
        description="Scan git index or tree for credential patterns.",
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Path to the git repository (default: current directory)",
    )
    parser.add_argument(
        "--ref",
        default=None,
        help="Git ref to scan (default: staged index)",
    )
    args = parser.parse_args(argv)

    try:
        findings = scan_repository(Path(args.root), args.ref)
    except GitScannerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    for name in findings:
        print(name)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## Notes on the design choices

| Concern | Decision |
|---|---|
| **No shell** | Every `subprocess.run` call uses a list (argv) and `shell=False`. |
| **NUL-delimited paths** | `-z` flag on both `ls-files` and `ls-tree`; parsing splits on `\0` then `\t`. Handles spaces, newlines, Unicode in filenames. |
| **Mode filtering** | Only `100644` / `100755` pass. `120000` (symlink), `160000` (submodule/commit), `040000` (tree) are all rejected. |
| **Unmerged stages** | `ls-files --stage` exposes the stage column; anything ≠ `0` is skipped. |
| **`.env` policy** | `.env` and `.env.*` are skipped; `.env.example` is explicitly allowed. |
| **No secret leakage** | Findings are filenames only. `GitScannerError` messages contain no stderr. `main()` prints filenames to stdout. |
| **Binary blobs** | Decoded with `errors="replace"`; regexes won't match replacement characters, so binary files are effectively skipped. |
| **Credential fragments** | Every test credential is assembled at runtime from short repeated fragments (`"aB" * 20`, `"Zz" * 18`, `"RSA " + "PRIVATE " + "KEY"`), so no contiguous realistic token exists in the source. |
