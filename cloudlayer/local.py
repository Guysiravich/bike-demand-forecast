"""A filesystem stand-in for cloud storage and metrics, for development and CI.

Documents live under STORE_URI (default .local-store/, gitignored). Metrics append to
<store>/metrics.jsonl, one JSON object per line, so a test can read them back.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from cloudlayer.base import CloudAdapter


class LocalAdapter(CloudAdapter):
    @property
    def root(self) -> Path:
        return Path(self.cfg.store_uri)

    def read_json(self, key: str) -> dict[str, Any] | None:
        path = self.root / key
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def write_json(self, key: str, document: dict[str, Any]) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2, default=str), encoding="utf-8")
        return str(path)

    def emit_metric(self, name: str, value: float,
                    dimensions: dict[str, str] | None = None) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        record = {"ts": time.time(), "name": name, "value": value, "dimensions": dimensions or {}}
        with (self.root / "metrics.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def metrics(self) -> list[dict[str, Any]]:
        """Everything emitted so far. Local only — tests use it to read the signals back."""
        path = self.root / "metrics.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]
