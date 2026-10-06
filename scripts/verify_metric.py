"""Compare the metric just produced against the claim in README.md (course Lab 1).

    make reproduce && make verify

Stdlib only, so any `python` on the PATH will do. If it fails for you, it fails for the grader.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "reports" / "metrics.json"
README = ROOT / "README.md"

CLAIM = re.compile(
    r"expected\s+test_mae\s*[:=]\s*(?P<value>[0-9.]+)\s*(?:±|\+/-)\s*(?P<tol>[0-9.]+)",
    re.IGNORECASE,
)


def main() -> int:
    if not METRICS.exists():
        print("FAIL  reports/metrics.json missing — run `make reproduce` first")
        return 1
    match = CLAIM.search(README.read_text(encoding="utf-8"))
    if not match:
        print("FAIL  README.md has no claim line. Add one, exactly in this form:\n"
              "        expected test_mae: 55.76 ± 0.05")
        return 1

    claimed, tol = float(match.group("value")), float(match.group("tol"))
    actual = json.loads(METRICS.read_text(encoding="utf-8"))["test_mae"]
    delta = abs(actual - claimed)
    print(f"claimed  {claimed:.4f} ± {tol:.4f}")
    print(f"actual   {actual:.4f}")
    print(f"delta    {delta:.4f}")
    if delta <= tol:
        print("\nPASS  reproduced within tolerance")
        return 0
    print("\nFAIL  outside tolerance. `make reproduce` pins the seed, so this is not seed\n"
          "      variance: either the claim is stale, or something moved under the pins.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
