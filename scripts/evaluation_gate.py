"""The registration gate (course Lab 5, Task 1).

    python scripts/evaluation_gate.py --metrics reports/metrics.json

Exits non-zero when the candidate should NOT be registered, which is what makes the pipeline's
condition real rather than decorative. Two checks, both on VALIDATION error — choosing on the
test set would leave no honest estimate (course Session 2); test error is reported, not used:

  1. The candidate beats the baseline it falls back to ("same hour last week") at 1 hour
     ahead. A model that cannot is worse than having no model.
  2. The candidate beats the version `production` serves by more than seed noise. MIN_IMPROVEMENT
     is twice the standard deviation of val_mae across seeds 1-5 of the same configuration
     (reports/runs.md): a smaller margin promotes noise, a larger one blocks real gains.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MIN_IMPROVEMENT = 1.66        # rentals/hour of val_mae: 2 x 0.829, the seed std (reports/runs.md)


def incumbent_val_mae(alias: str) -> float | None:
    """val_mae of the version the alias names, read from the registry. None on a first run."""
    import mlflow

    from src import config, registry

    cfg = config.load(strict=False)
    try:
        version = registry._client(cfg).get_model_version_by_alias(cfg.model_registry_name, alias)
    except mlflow.exceptions.MlflowException:
        return None
    return float(version.tags["metric_val"])


def decide(metrics: dict, incumbent: float | None) -> tuple[bool, list[str]]:
    lines = [f"candidate val_mae {metrics['val_mae']:.3f}  (test_mae {metrics['test_mae']:.3f}, "
             "reported, not used)"]
    model_h1, baseline_h1 = metrics["val_mae_h1"], metrics["val_baseline_mae_h1"]
    lines.append(f"1-hour val_mae {model_h1:.3f} against baseline {baseline_h1:.3f}")
    if model_h1 >= baseline_h1:
        return False, [*lines, "GATE FAIL  does not beat the fallback it would replace"]
    if incumbent is None:
        return True, [*lines, "no incumbent — first registration", "GATE PASS"]
    gain = incumbent - metrics["val_mae"]
    lines.append(f"incumbent val_mae {incumbent:.3f}  gain {gain:+.3f}  required "
                 f"{MIN_IMPROVEMENT:+.3f}")
    if gain < MIN_IMPROVEMENT:
        return False, [*lines, "GATE FAIL  improvement within seed noise; not registering"]
    return True, [*lines, "GATE PASS"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics", type=Path, required=True)
    ap.add_argument("--alias", default="production", help="the incumbent to beat")
    ap.add_argument("--incumbent", type=float, default=None,
                    help="incumbent val_mae; omit to read it from the registry")
    ap.add_argument("--decision-out", type=Path, default=None)
    args = ap.parse_args()

    metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
    incumbent = args.incumbent if args.incumbent is not None else incumbent_val_mae(args.alias)
    passed, lines = decide(metrics, incumbent)
    print("\n".join(lines))
    if args.decision_out:
        args.decision_out.write_text("pass" if passed else "fail", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
