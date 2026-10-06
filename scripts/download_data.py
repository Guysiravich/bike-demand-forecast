"""Fetch the UCI Bike Sharing Dataset and keep hour.csv, checksum verified.

    python scripts/download_data.py

Source: UCI Machine Learning Repository, dataset 275, Fanaee-T, H. and Gama, J. (2013),
licence CC BY 4.0. Once the file is tracked by DVC, `dvc pull` is the normal way to get it;
this script is how the tracked copy was made, and how anyone can rebuild it from the source.
"""
from __future__ import annotations

import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config

URL = "https://archive.ics.uci.edu/static/public/275/bike+sharing+dataset.zip"
# Recorded from the first download. If UCI ever changes the file, this stops the build
# instead of silently training on different data.
EXPECTED_SHA256 = "e03de4ee4ef4dc376ac6e04bf829673c6269e8eba5c60fa121640fa2f829504f"


def main() -> int:
    target = config.load().raw_path
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {URL}")
    with urllib.request.urlopen(URL, timeout=60) as response:
        archive = zipfile.ZipFile(io.BytesIO(response.read()))
    content = archive.read("hour.csv")
    digest = hashlib.sha256(content).hexdigest()
    if EXPECTED_SHA256 and digest != EXPECTED_SHA256:
        print(f"CHECKSUM MISMATCH: expected {EXPECTED_SHA256}, got {digest}")
        return 1
    target.write_bytes(content)
    print(f"wrote {target} ({len(content):,} bytes), sha256 {digest}")
    if not EXPECTED_SHA256:
        print("EXPECTED_SHA256 is empty: record the value above in this script.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
