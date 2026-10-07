"""Put any text in place of the weather reading — the demo's "unexpected input".

    make inject TEXT='{"observed_at": "2012-10-08T03:00", "values": {"temp": "hot"}}'
    make inject TEXT='not json at all'
    make inject FILE=reading.json

The text goes in exactly as given, through the adapter, so the same command works against the
local store and the cloud one. The next forecast run reads it and either uses it or refuses it
with the reason in `forecasts/latest.json` and its log line; it never crashes on it
(tests/test_forecast.py). Then `make run-now JOB=bike-forecast`, or `python -m src.forecast`.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudlayer.factory import get_adapter
from src import config

KEY = "weather/latest.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--file", type=Path)
    args = ap.parse_args()

    text = args.text if args.text is not None else args.file.read_text(encoding="utf-8")
    adapter = get_adapter(config.load())
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "reading.json"
        local.write_text(text, encoding="utf-8")
        where = adapter.upload(str(local), KEY)
    print(f"wrote {len(text)} characters to {where}")
    print("next forecast run will read it; the reason it is used or refused is in "
          "forecasts/latest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
