from __future__ import annotations

from cloudlayer.base import CloudAdapter
from src.config import Config


def get_adapter(cfg: Config) -> CloudAdapter:
    if cfg.provider == "local":
        from cloudlayer.local import LocalAdapter
        return LocalAdapter(cfg)
    if cfg.provider == "azure":
        from cloudlayer.azure import AzureAdapter
        return AzureAdapter(cfg)
    raise ValueError(f"Unknown CLOUD_PROVIDER {cfg.provider!r}; expected local or azure")
