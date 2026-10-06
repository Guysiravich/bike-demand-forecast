"""Register a run's model with lineage, and promote a version (course Lab 2, Task 4).

    python scripts/register_model.py --run-id <run id>                    # register only
    python scripts/register_model.py --version <n> --alias staging        # promote

Registration goes through the adapter (`register_model`), which copies the eight lineage
fields onto the model VERSION and refuses to register if any is missing. Promotion is a
separate, deliberate step: `staging` to check, `production` to serve (README, "Promotion").
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudlayer.factory import get_adapter
from src import config, registry


def main() -> int:
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-id", help="register runs:/<run-id>/model as a new version")
    group.add_argument("--version", help="an existing version to promote")
    ap.add_argument("--alias", default=None, help="promote the version to this alias")
    args = ap.parse_args()

    cfg = config.load()
    name = cfg.model_registry_name
    version = args.version
    if args.run_id:
        version = get_adapter(cfg).register_model(f"runs:/{args.run_id}/model", name)
        print(f"registered {name} version {version}")
        tags = registry._client(cfg).get_model_version(name, version).tags
        for key in (*registry.LINEAGE_FIELDS, *registry.EXTRA_FIELDS):
            print(f"  {key} = {tags.get(key)}")
    if args.alias:
        before = registry.promote(cfg, version, args.alias)
        print(f"promoted {name} version {version} -> alias '{args.alias}' "
              f"(was {before or 'unset'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
