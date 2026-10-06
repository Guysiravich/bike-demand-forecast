"""Adapter selection. The only place that maps CLOUD_PROVIDER to an implementation."""
from __future__ import annotations

from cloudlayer.base import CloudAdapter


def get_adapter(cfg) -> CloudAdapter:
    provider = (cfg.provider or "local").lower()
    if provider == "local":
        from cloudlayer.local import LocalAdapter
        return LocalAdapter(cfg)
    if provider == "azure":
        from cloudlayer.azure import AzureAdapter
        return AzureAdapter(cfg)
    raise ValueError(f"Unknown CLOUD_PROVIDER={provider!r}. Use azure, or local.")
