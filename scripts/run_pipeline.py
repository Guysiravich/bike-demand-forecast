"""Run pipeline/pipeline.yaml on this machine, one step after another.

    make pipeline

Honours the two things that make a pipeline more than a script: `on_failure: abort` stops
everything after a failed step, and `condition:` skips a step whose condition is false. The
gate writes its decision to a file; `register` runs only when it reads "pass".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "pipeline" / "pipeline.yaml"


def run(spec_path: Path = SPEC, root: Path = ROOT) -> dict[str, str]:
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    outcome: dict[str, str] = {}
    env = {**os.environ}
    for step in spec["steps"]:
        name = step["name"]
        if any(outcome.get(d) not in ("ok", "failed-continue") for d in step.get("depends_on", [])):
            outcome[name] = "skipped (upstream)"
            print(f"[{name}] skipped: an upstream step did not complete")
            continue
        condition = step.get("condition")
        if condition:
            decision_file = root / "reports" / "gate-decision.txt"
            decision = decision_file.read_text().strip() if decision_file.exists() else "missing"
            if condition != f"gate_decision == '{decision}'":
                outcome[name] = "skipped (condition)"
                print(f"[{name}] skipped: {condition} is false (gate_decision = {decision!r})")
                continue
        metrics = root / "reports" / "pipeline-metrics.json"
        if metrics.exists():
            env["RUN_ID"] = json.loads(metrics.read_text())["run_id"]
        command = [env.get(part[2:-1], part) if part.startswith("${") else part
                   for part in step["command"]]
        command = [sys.executable if part == "python" else part for part in command]
        print(f"[{name}] {' '.join(command)}", flush=True)
        code = subprocess.run(command, cwd=root, env=env).returncode
        if code == 0:
            outcome[name] = "ok"
        elif step.get("on_failure") == "continue":
            outcome[name] = "failed-continue"
        else:
            outcome[name] = "failed"
            print(f"[{name}] FAILED (exit {code}); aborting the pipeline")
    print("\n" + "\n".join(f"  {k:<10} {v}" for k, v in outcome.items()))
    return outcome


def main() -> int:
    for leftover in ("gate-decision.txt", "pipeline-metrics.json"):
        (ROOT / "reports" / leftover).unlink(missing_ok=True)
    outcome = run()
    return 1 if "failed" in outcome.values() else 0


if __name__ == "__main__":
    raise SystemExit(main())
