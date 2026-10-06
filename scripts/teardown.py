"""Delete the project's resources, by tag, through the adapter (course Lab 3/5).

    make teardown LAB=capstone              # delete
    make teardown LAB=capstone DRY_RUN=1    # list only

Scoped by tag, never by resource group: the group also holds the labs' storage, registry and
tracking server. The lab is explicit and required — as the course provided it, the target
hardcoded lab=1 and would have deleted Lab 1's storage and registry.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudlayer.factory import get_adapter
from src import config

# Azure ML schedules are workspace objects without resource tags, so the tag search below never
# finds them — and a schedule that outlives its job keeps starting runs (course Lab 4). They are
# deleted by name, explicitly.
SCHEDULES = {"capstone": ["bike-retrain"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lab", required=True, help="lab tag whose resources to delete")
    ap.add_argument("--dry-run", action="store_true", help="list what would be deleted")
    args = ap.parse_args()

    cfg = config.load()
    tags = cfg.tags(args.lab)
    print(f"teardown scope: {tags}")
    adapter = get_adapter(cfg)
    if cfg.training_target:
        for name in SCHEDULES.get(args.lab, []):
            if args.dry_run:
                print(f"would delete schedule {name}")
            else:
                print(f"deleted schedule {adapter.schedule(name, '', {}, '')}")
    deleted = adapter.teardown(tags, dry_run=args.dry_run)
    if not deleted:
        print("nothing carried those tags")
    for item in deleted:
        print(("would delete " if args.dry_run else "deleted ") + item)
    print("Deletion is asynchronous: run `make teardown-verify`, check the portal, check the bill.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
