"""Configuration. The ONLY module in src/ allowed to read the environment.

Nothing under src/ may name a bucket, a provider hostname, or an absolute path from a
developer machine. Everything arrives through here, from cloud.env (gitignored) or from
variables already exported, which win — so CI and the cloud job can override the file.
`make portability-audit` enforces this.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / "cloud.env"


def _load_env_file(path: Path = ENV_FILE) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.split("#", 1)[0].strip())


_load_env_file()


@dataclass(frozen=True)
class Config:
    provider: str
    project_id: str
    region: str
    store_uri: str
    container_registry: str
    mlflow_tracking_uri: str
    model_name: str
    model_version: str
    identity_ref: str
    # Service levels from the proposal. Changing these changes what the alerts mean.
    weather_max_age_min: int = 60
    feed_repeat_alert: int = 3
    job_max_duration_s: int = 300
    forecast_horizon_h: int = 24
    seed: int = 20260920
    data_dir: Path = field(default=REPO_ROOT / "data")
    reports_dir: Path = field(default=REPO_ROOT / "reports")

    @property
    def raw_path(self) -> Path:
        return self.data_dir / "raw" / "hour.csv"

    def tags(self) -> dict[str, str]:
        """Every cloud resource carries these. `make teardown` finds resources by tag."""
        return {"course": "itcs355", "project": "bike", "owner": self.project_id}


def load() -> Config:
    def get(key: str, default: str = "") -> str:
        # An empty value in cloud.env means "not set", so it falls back to the default.
        return os.environ.get(key) or default

    return Config(
        provider=get("CLOUD_PROVIDER", "local"),
        project_id=get("PROJECT_ID", "itcs355-bike"),
        region=get("REGION", "local"),
        store_uri=get("STORE_URI", str(REPO_ROOT / ".local-store")),
        container_registry=get("CONTAINER_REGISTRY", ""),
        mlflow_tracking_uri=get("MLFLOW_TRACKING_URI", f"sqlite:///{REPO_ROOT / 'mlflow.db'}"),
        model_name=get("MODEL_NAME", "bike-demand"),
        model_version=get("MODEL_VERSION", ""),
        identity_ref=get("IDENTITY_REF", ""),
        weather_max_age_min=int(get("WEATHER_MAX_AGE_MIN", "60")),
        feed_repeat_alert=int(get("FEED_REPEAT_ALERT", "3")),
        job_max_duration_s=int(get("JOB_MAX_DURATION_S", "300")),
    )
