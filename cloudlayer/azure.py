"""Azure implementation — written after the proposal is approved.

Planned mapping (see the project PLAN):
  read_json / write_json   Blob Storage, container `bike`, through DefaultAzureCredential
  emit_metric              Azure Monitor custom metrics
  push_image               ACR, returns registry/repo@sha256:...
  submit_training          Azure ML command job on the existing cluster
  register_model           the self-hosted MLflow registry, lineage on the version
  deploy_job               Container Apps Job on a cron schedule
  teardown                 delete by tag, never by resource group
"""
from __future__ import annotations

from typing import Any

from cloudlayer.base import CloudAdapter


class AzureAdapter(CloudAdapter):
    def read_json(self, key: str) -> dict[str, Any] | None:
        raise NotImplementedError("Azure storage: after proposal approval")

    def write_json(self, key: str, document: dict[str, Any]) -> str:
        raise NotImplementedError("Azure storage: after proposal approval")

    def emit_metric(self, name: str, value: float,
                    dimensions: dict[str, str] | None = None) -> None:
        raise NotImplementedError("Azure Monitor: after proposal approval")
