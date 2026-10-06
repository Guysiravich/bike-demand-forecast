"""The pipeline's gate must be reachable (course Lab 5: "a pipeline that always registers has no
gate; the grader will try to make yours fail"). These make it fail on purpose."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import evaluation_gate  # noqa: E402
import run_pipeline  # noqa: E402

GOOD = {"val_mae": 50.0, "test_mae": 52.0, "val_mae_h1": 45.0, "val_baseline_mae_h1": 56.0}


def test_first_candidate_that_beats_the_baseline_passes():
    assert evaluation_gate.decide(GOOD, incumbent=None)[0]


def test_a_candidate_worse_than_the_baseline_fails():
    worse = {**GOOD, "val_mae_h1": 57.0}
    passed, lines = evaluation_gate.decide(worse, incumbent=None)
    assert not passed and "fallback" in lines[-1]


def test_an_improvement_within_seed_noise_fails():
    within_noise = 50.0 + evaluation_gate.MIN_IMPROVEMENT / 2
    passed, lines = evaluation_gate.decide(GOOD, incumbent=within_noise)
    assert not passed and "noise" in lines[-1]


def test_a_real_improvement_passes():
    assert evaluation_gate.decide(GOOD, incumbent=50.0 + 2 * evaluation_gate.MIN_IMPROVEMENT)[0]


def write_spec(tmp_path, gate_says: str) -> Path:
    (tmp_path / "reports").mkdir()
    py = sys.executable
    spec = {"steps": [
        {"name": "validate", "command": [py, "-c", "pass"], "on_failure": "abort"},
        {"name": "evaluate", "depends_on": ["validate"], "on_failure": "continue",
         "command": [py, "-c", f"open('reports/gate-decision.txt','w').write('{gate_says}')"]},
        {"name": "register", "depends_on": ["evaluate"],
         "condition": "gate_decision == 'pass'",
         "command": [py, "-c", "open('reports/registered','w').write('yes')"]},
    ]}
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(spec))
    return path


def test_a_failed_gate_skips_registration(tmp_path):
    outcome = run_pipeline.run(write_spec(tmp_path, "fail"), root=tmp_path)
    assert outcome["register"] == "skipped (condition)"
    assert not (tmp_path / "reports" / "registered").exists()


def test_a_passed_gate_registers(tmp_path):
    outcome = run_pipeline.run(write_spec(tmp_path, "pass"), root=tmp_path)
    assert outcome["register"] == "ok"


def test_a_failed_contract_aborts_everything_after_it(tmp_path):
    spec_path = write_spec(tmp_path, "pass")
    spec = yaml.safe_load(spec_path.read_text())
    spec["steps"][0]["command"] = [sys.executable, "-c", "raise SystemExit(1)"]
    spec_path.write_text(yaml.safe_dump(spec))
    outcome = run_pipeline.run(spec_path, root=tmp_path)
    assert outcome["validate"] == "failed"
    assert outcome["register"].startswith("skipped")
