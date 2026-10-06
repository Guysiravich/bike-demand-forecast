"""The portability seam — the course's CloudAdapter, unchanged in shape.

Eleven methods, plus the two the course repository added in Lab 4 (`recent_inputs`,
`schedule`). Nothing outside cloudlayer/ may import a provider SDK; `make portability-audit`
fails the build if one does.

What this project adds is small and sits on top of the eleven: `read_json` and `write_json`,
because the hourly job's inputs (clock, weather reading, feed control) and outputs (forecasts,
state) are small documents in object storage. Both are built from `upload` and `download`,
so a provider adapter gets them for free and the job never learns where storage lives.

How the batch service maps onto the course's online-serving methods:

  deploy(model_ref, endpoint, instance)   create or update the scheduled forecast job
                                          (batch inference, project brief: "online or batch")
  invoke(endpoint, payload)               start one run of that job now — the demo's
                                          "next tick" — and return the execution id
"""
from __future__ import annotations

import json
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class CloudAdapter(ABC):
    """Provider-neutral interface. Everything in src/ and scripts/ calls only these."""

    def __init__(self, cfg) -> None:
        self.cfg = cfg

    # --- Lab 1 ---------------------------------------------------------------
    @abstractmethod
    def upload(self, local_path: str, key: str) -> str:
        """Upload a file under BLOB_URI. Returns the full URI of the stored object."""

    @abstractmethod
    def download(self, uri: str, local_path: str) -> None:
        """Fetch an object to a local path. Creates parent directories.
        Raises FileNotFoundError when there is no such object."""

    @abstractmethod
    def push_image(self, local_tag: str) -> str:
        """Push a locally built image to CONTAINER_REGISTRY. Returns the remote reference,
        which must be digest-pinned (repo@sha256:...), not tag-pinned."""

    # --- Lab 2 ---------------------------------------------------------------
    def submit_training(self, image_uri: str, args: dict[str, Any]) -> str:
        raise NotImplementedError("Lab 2")

    def wait_training(self, job_id: str) -> dict[str, Any]:
        raise NotImplementedError("Lab 2")

    def register_model(self, model_uri: str, name: str) -> str:
        """Register runs:/<run_id>/model under `name`, lineage copied onto the VERSION.
        The registry is MLflow on every provider, so the work is in src/registry.py."""
        from src import registry

        return registry.register_run(self.cfg, model_uri, name)

    # --- Lab 3 ---------------------------------------------------------------
    def deploy(self, model_ref: str, endpoint: str, instance: str) -> str:
        raise NotImplementedError("Lab 3")

    def invoke(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Lab 3")

    # --- Lab 4 ---------------------------------------------------------------
    def emit_metric(self, name: str, value: float, unit: str = "None") -> None:
        raise NotImplementedError("Lab 4")

    def recent_inputs(self, limit: int) -> list[dict[str, float]]:
        """The inputs of the last `limit` scored rows, newest first. Not used by this
        project: the job writes every forecast and the reading it used to storage."""
        raise NotImplementedError("Lab 4")

    def schedule(self, name: str, image_uri: str, args: dict[str, Any], cron: str) -> str:
        """Run submit_training(image_uri, args) on a cron schedule — scheduled retraining
        (Lab 5 Task 3). `cron` is five fields in UTC; cron="" deletes the schedule."""
        raise NotImplementedError("Lab 4")

    # --- Lab 5 ---------------------------------------------------------------
    def generate(self, prompt: str, params: dict[str, Any]) -> dict[str, Any]:
        """Not used: this service has no language-model step."""
        raise NotImplementedError("Lab 5")

    def teardown(self, tags: dict[str, str], dry_run: bool = False) -> list[str]:
        """Delete every resource carrying ALL of these tags. Returns what was deleted.
        Deletion is asynchronous — re-check, and check the bill."""
        raise NotImplementedError("Lab 5")

    # --- capstone: the job's documents, built on upload/download ---------------
    def object_uri(self, key: str) -> str:
        """The URI `upload(..., key)` writes to: BLOB_URI joined with the key."""
        return f"{self.cfg.blob_uri.rstrip('/')}/{key.lstrip('/')}"

    def read_json(self, key: str) -> dict[str, Any] | None:
        """The document at `key`, or None when there is none."""
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "doc.json"
            try:
                self.download(self.object_uri(key), str(local))
            except FileNotFoundError:
                return None
            return json.loads(local.read_text(encoding="utf-8"))

    def write_json(self, key: str, document: dict[str, Any]) -> str:
        """Store `document` at `key`. Returns where it went."""
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "doc.json"
            local.write_text(json.dumps(document, indent=2, default=str), encoding="utf-8")
            return self.upload(str(local), key)
