"""Scan tracked source for common credential formats without printing matches."""

import re
import subprocess
from pathlib import Path

PATTERNS = [
    re.compile(rb"gsk_[A-Za-z0-9]{40,}"),
    re.compile(rb"(?:ghp|github_pat)_[A-Za-z0-9_]{30,}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def main():
    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True).stdout
    files = [root / name.decode("utf-8") for name in tracked.split(b"\0") if name]
    failures = []
    for path in files:
        if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
            failures.append(path.relative_to(root).as_posix())
            continue
        if not path.is_file():
            continue
        # Synthetic sanitizer tests intentionally contain a fake private-key marker.
        patterns = PATTERNS[:2] if path.parts[-3:] == ("tools", "tests", "test_ai_helper.py") else PATTERNS
        if any(pattern.search(path.read_bytes()) for pattern in patterns):
            failures.append(path.relative_to(root).as_posix())
    if failures:
        raise SystemExit("Potential secret or environment file: " + ", ".join(failures))
    print(f"Scanned {len(files)} tracked files: no recognized credentials or private environment files.")


if __name__ == "__main__":
    main()
