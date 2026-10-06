#!/usr/bin/env bash
# Integration test (course Lab 4, Task 1): build both images, train and register in the
# training image, then run the feeder and the forecast job in the JOB image — the bytes that
# deploy — and assert on what they write. Then freeze the feed and assert the job degrades.
#
#   bash scripts/integration_test.sh <tag>        (CI passes the commit SHA)
#
# Nothing here touches a cloud account: CLOUD_PROVIDER=local, storage is a mounted directory.
set -euo pipefail

TAG="${1:-dev}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
chmod a+rwx "$WORK"
mkdir -p "$WORK/store" && chmod a+rwx "$WORK/store"

# The same absolute path in both containers, so MLflow's artifact paths resolve in each.
COMMON=(-v "$PWD/data:/app/data:ro" -v "$WORK:/work" -w /work
        -e MLFLOW_TRACKING_URI=sqlite:////work/mlflow.db -e CLOUD_PROVIDER=local
        -e BLOB_URI=/work/store -e MODEL_REGISTRY_NAME=bike-it -e GIT_COMMIT="$TAG")

echo "== train in the training image"
docker run --rm "${COMMON[@]}" "bike-train:$TAG" --max-iter 40 --metrics-out /work/metrics.json
RUN_ID=$(python3 -c "import json; print(json.load(open('$WORK/metrics.json'))['run_id'])")

echo "== register and promote to production"
docker run --rm "${COMMON[@]}" --entrypoint python "bike-train:$TAG" \
  /app/scripts/register_model.py --run-id "$RUN_ID" --alias production

echo "== three healthy ticks in the job image"
for _ in 1 2 3; do
  docker run --rm "${COMMON[@]}" "bike-job:$TAG" src.feeder
  docker run --rm "${COMMON[@]}" "bike-job:$TAG" src.forecast
done
python3 - "$WORK/store/forecasts/latest.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
assert doc["status"] == "ok", doc["reasons"]
assert doc["model_version"] == "1", doc["model_version"]
assert len(doc["rows"]) == 24 and all(r["forecast"] >= 0 for r in doc["rows"])
print("healthy: status ok, model version 1, 24 non-negative rows")
PY

echo "== freeze the feed: within three ticks the job must degrade"
docker run --rm "${COMMON[@]}" "bike-job:$TAG" src.feeder --mode frozen
for _ in 1 2 3; do
  docker run --rm "${COMMON[@]}" "bike-job:$TAG" src.feeder
  docker run --rm "${COMMON[@]}" "bike-job:$TAG" src.forecast
done
python3 - "$WORK/store/forecasts/latest.json" "$WORK/store/alerts" <<'PY'
import json, pathlib, sys
doc = json.load(open(sys.argv[1]))
assert doc["status"] == "degraded" and doc["source"].startswith("baseline"), doc
assert any(pathlib.Path(sys.argv[2]).glob("*.json")), "no alert was written"
print("frozen: status degraded, baseline served, alert written —", "; ".join(doc["reasons"]))
PY
echo "integration test passed"
