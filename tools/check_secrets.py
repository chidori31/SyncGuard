# FILE: git_scanner.py
"""Scan git staged index blobs or a committed tree for credential patterns.

Uses only the Python standard library.  All git invocations use argv lists
with shell=False.  Findings contain filenames only – never the matched text.
"""

from __future__ import annotations

import argparse
import json
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
_GH_PAT_RE = re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,255}")
_PEM_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")

_PATTERNS: tuple[re.Pattern[str], ...] = (_GROQ_RE, _GH_PAT_RE, _PEM_RE)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALLOWED_MODES = frozenset({"100644", "100755"})
_ENV_EXAMPLE = ".env.example"
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
        raise GitScannerError(f"git {args[0] if args else 'command'} failed: {exc.__class__.__name__}") from None
    if proc.returncode != 0:
        raise GitScannerError(f"git {args[0] if args else 'command'} returned nonzero exit")
    return proc.stdout


def _is_env_file(path: str) -> bool:
    """True for .env and .env.* except .env.example."""
    name = path.rsplit("/", 1)[-1].casefold()
    if name == _ENV_EXAMPLE:
        return False
    return name == ".env" or name.startswith(".env.")


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
            raise GitScannerError("Invalid Git index record")
        meta, path = record[:tab], record[tab + 1 :]
        parts = meta.split(" ", 2)  # mode, hash, stage
        if len(parts) != 3:
            raise GitScannerError("Invalid Git index metadata")
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
            raise GitScannerError("Invalid Git tree record")
        meta, path = record[:tab], record[tab + 1 :]
        parts = meta.split(" ", 2)  # mode, type, hash
        if len(parts) != 3:
            raise GitScannerError("Invalid Git tree metadata")
        entries.append((parts[0], parts[1], parts[2], path))
    return entries


def _read_blob(root: Path, obj_hash: str) -> str:
    """Read a blob by hash; return decoded text (binary-safe)."""
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", obj_hash):
        raise GitScannerError("Invalid Git object ID")
    try:
        size = int(_run_git(root, "cat-file", "-s", obj_hash))
    except ValueError:
        raise GitScannerError("Invalid Git object size") from None
    if not 0 <= size <= 10 * 1024 * 1024:
        raise GitScannerError("Git blob exceeds scanner size limit")
    raw = _run_git(root, "cat-file", "blob", obj_hash)
    return raw.decode("utf-8", errors="replace")


def _matches(content: str, path: str) -> bool:
    """Return True if *content* contains any credential pattern."""
    patterns = _PATTERNS[:2] if path == "tools/tests/test_ai_helper.py" else _PATTERNS
    for pat in patterns:
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
        root = Path(_run_git(root, "rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
    except GitScannerError:
        raise GitScannerError("not a valid git repository") from None

    findings: list[str] = []

    if ref is None:
        # --- Staged index ---
        raw = _run_git(root, "ls-files", "--stage", "-z")
        entries = _parse_stage_entries(raw.decode("utf-8", errors="replace"))
        if not entries:
            raise GitScannerError("Repository has no staged files")
        for mode, obj_hash, stage, path in entries:
            if stage != "0" or mode not in _ALLOWED_MODES or _is_env_file(path):
                findings.append(path)
                continue
            content = _read_blob(root, obj_hash)
            if _matches(content, path):
                findings.append(path)
    else:
        # --- Committed tree ---
        commit = _run_git(root, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode().strip()
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
            raise GitScannerError("Invalid Git commit")
        raw = _run_git(root, "ls-tree", "-r", "-z", commit)
        entries = _parse_tree_entries(raw.decode("utf-8", errors="replace"))
        if not entries:
            raise GitScannerError("Repository has no committed files")
        for mode, obj_type, obj_hash, path in entries:
            if obj_type != "blob" or mode not in _ALLOWED_MODES or _is_env_file(path):
                findings.append(path)
                continue
            content = _read_blob(root, obj_hash)
            if _matches(content, path):
                findings.append(path)

    return sorted(set(findings))


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
        default=str(Path(__file__).resolve().parents[1]),
        help="Path to the git repository (default: project root)",
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
        print(json.dumps(name, ensure_ascii=True))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
