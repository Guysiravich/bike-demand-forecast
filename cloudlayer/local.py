"""Filesystem stand-in, so everything runs before — and without — a cloud account.

Acceptable for development, CI and the local drills. Not a deployment: the submitted service
runs on the provider adapter. Objects live under BLOB_URI, which for the local provider is a
directory (default .local-store/, gitignored). Metrics append to <BLOB_URI>/metrics.jsonl,
one JSON object per line, so a test can read them back.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from cloudlayer.base import CloudAdapter


class LocalAdapter(CloudAdapter):
    @property
    def root(self) -> Path:
        return Path(self.cfg.blob_uri)

    def upload(self, local_path: str, key: str) -> str:
        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, dest)
        return str(dest)

    def download(self, uri: str, local_path: str) -> None:
        src = Path(uri)
        if not src.is_file():
            raise FileNotFoundError(uri)
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, local_path)

    def push_image(self, local_tag: str) -> str:
        raise NotImplementedError(
            "LocalAdapter cannot push images. Set CLOUD_PROVIDER=azure in cloud.env."
        )

    def emit_metric(self, name: str, value: float, unit: str = "None") -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        record = {"ts": time.time(), "name": name, "value": value, "unit": unit}
        with (self.root / "metrics.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def metrics(self) -> list[dict[str, Any]]:
        """Everything emitted so far. Local only — tests use it to read the signals back."""
        path = self.root / "metrics.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def teardown(self, tags: dict[str, str], dry_run: bool = False) -> list[str]:
        """Nothing local carries tags; the store is deleted with `make clean`."""
        return []
