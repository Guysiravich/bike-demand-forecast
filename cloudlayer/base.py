"""The seam between the service and a cloud provider.

src/ talks only to this interface. Everything provider-specific — SDKs, hostnames, URI
schemes — lives in the implementations beside it, and `make portability-audit` fails the
build if it leaks into src/. This follows the course's three-layer contract; the method set
is the course adapter's, narrowed to what a scheduled batch forecaster needs, plus
read_json/write_json because the job's inputs and outputs are small documents in storage.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.config import Config


class CloudAdapter(ABC):
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    # --- storage: the job's inputs (weather, control) and outputs (forecasts, state) -----
    @abstractmethod
    def read_json(self, key: str) -> dict[str, Any] | None:
        """The document at `key`, or None when there is none."""

    @abstractmethod
    def write_json(self, key: str, document: dict[str, Any]) -> str:
        """Store `document` at `key`. Returns where it went."""

    # --- observability ----------------------------------------------------------------------
    @abstractmethod
    def emit_metric(self, name: str, value: float,
                    dimensions: dict[str, str] | None = None) -> None:
        """One data point. The dashboard and the alert rules read these."""

    # --- build and run: implemented per provider once the cloud work is approved --------------
    def push_image(self, local_tag: str) -> str:
        raise NotImplementedError("push_image: provider adapter, after proposal approval")

    def submit_training(self, image_uri: str, args: dict[str, Any]) -> str:
        raise NotImplementedError("submit_training: provider adapter, after proposal approval")

    def register_model(self, model_uri: str, name: str) -> str:
        raise NotImplementedError("register_model: provider adapter, after proposal approval")

    def deploy_job(self, image_uri: str, schedule: str, args: dict[str, Any]) -> str:
        raise NotImplementedError("deploy_job: provider adapter, after proposal approval")

    def teardown(self, tags: dict[str, str], dry_run: bool = False) -> list[str]:
        raise NotImplementedError("teardown: provider adapter, after proposal approval")
