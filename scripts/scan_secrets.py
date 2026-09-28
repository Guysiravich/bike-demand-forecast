"""Scan the whole Git history for values shaped like credentials.

    python scripts/scan_secrets.py        # exit 0 clean, 1 found something, 2 cannot run

Committing a credential is an automatic deduction in the project brief. The patterns match
the shape of a VALUE, not the word beside it — the approach of the course repository's
scanner — so documentation that says "password" does not trip it, and a real key does.
Refuses to run on a shallow clone, where it would see one commit and pass by accident.
"""
from __future__ import annotations

import re
import subprocess

PATTERNS = [
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private-key-block", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
    ("azure-storage-account-key", re.compile(r"AccountKey\s*=\s*[A-Za-z0-9+/]{86}==")),
    ("azure-sas-signature", re.compile(r"[?&]sig=[A-Za-z0-9%+/]{40,}")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b")),
    ("generic-assigned-secret", re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)\b\s*[:=]\s*"
        r"[\"']([^\"'\s$<{]{12,})[\"']")),
]


def main() -> int:
    try:
        shallow = subprocess.run(["git", "rev-parse", "--is-shallow-repository"],
                                 capture_output=True, text=True, check=True).stdout.strip()
        if shallow == "true":
            print("REFUSING: shallow clone. Fetch the full history (fetch-depth: 0).")
            return 2
        log = subprocess.run(["git", "log", "-p", "--all", "--no-color"], capture_output=True,
                             text=True, check=True, encoding="utf-8", errors="replace").stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"cannot read git history: {exc}")
        return 2
    hits = []
    for lineno, line in enumerate(log.splitlines(), 1):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for name, pattern in PATTERNS:
            if pattern.search(line):
                hits.append(f"{name}: history line {lineno}")
    if hits:
        print("SECRET SCAN FAILED\n  " + "\n  ".join(hits))
        return 1
    print("CLEAN  no credential-shaped value in history")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
