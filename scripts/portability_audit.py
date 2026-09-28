"""Fail the build if provider-specific strings leak outside cloudlayer/.

Adapted from the ITCS355 course repository's scripts/portability_audit.py: the same rule and
the same patterns, scanning this project's layer-1 folders.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNED = ["src", "tests"]

FORBIDDEN = [
    (r"s3://", "S3 URI"),
    (r"gs://", "GCS URI"),
    (r"abfss?://", "ADLS URI"),
    (r"wasbs?://", "Azure Blob URI"),
    (r"amazonaws\.com", "AWS hostname"),
    (r"blob\.core\.windows\.net", "Azure hostname"),
    (r"azurecontainerapps\.io", "Azure Container Apps hostname"),
    (r"googleapis\.com", "GCP hostname"),
    (r"azurecr\.io", "ACR hostname"),
    (r"dkr\.ecr\.", "ECR hostname"),
    (r"pkg\.dev", "Artifact Registry hostname"),
    (r"\bimport boto3\b", "AWS SDK"),
    (r"\bfrom azure\b|\bimport azure\b", "Azure SDK"),
    (r"\bfrom google\.cloud\b", "GCP SDK"),
    (r"^\s*[\"']?/(home|Users|mnt)/", "absolute path from a developer machine"),
    (r"[A-Za-z]:\\\\", "Windows absolute path"),
]


def main() -> int:
    hits: list[str] = []
    for folder in SCANNED:
        for path in (ROOT / folder).rglob("*.py"):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue  # comments may name providers; code may not
                for pattern, label in FORBIDDEN:
                    if re.search(pattern, line):
                        hits.append(f"{path.relative_to(ROOT)}:{lineno}  {label}  ->  "
                                    f"{line.strip()[:80]}")
    if hits:
        print("PORTABILITY AUDIT FAILED — provider details leaked outside cloudlayer/\n")
        for hit in hits:
            print("  " + hit)
        return 1
    print(f"PORTABILITY AUDIT PASSED — {', '.join(SCANNED)} contain no provider-specific strings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
