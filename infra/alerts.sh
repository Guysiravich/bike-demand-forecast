#!/usr/bin/env bash
# Alert rules and the dashboard, as code (course Lab 4, Tasks 4-5). Run 2026-10-07.
# Run after `make deploy`, when the two jobs exist:
#
#   ALERT_EMAILS="a@student.mahidol.ac.th b@student.mahidol.ac.th" bash infra/alerts.sh
#   WINDOW=15m bash infra/alerts.sh          # the demo, with the jobs ticking every 5 minutes
#
# The rules are the ones the job evaluates itself (src/monitor.py) and CI tests, here as Azure
# Monitor metric alerts on the custom metrics emit_metric() posts (namespace `bike`, on the
# forecast job). Thresholds come from the same place as the code's: cloud.env.
set -euo pipefail

RG="${RG:-itcs355-6688067}"
STUDENT="${STUDENT:-6688067}"
ALERT_EMAILS="${ALERT_EMAILS:?set ALERT_EMAILS to both team members addresses}"
WINDOW="${WINDOW:-1h}"                 # one point per run: hourly runs need an hour's window
WEATHER_MAX_AGE_MIN="${WEATHER_MAX_AGE_MIN:-60}"
JOB_MAX_DURATION_S="${JOB_MAX_DURATION_S:-300}"
# The production version's own threshold (mae_alert_threshold on the version; `make models`).
MAE_ALERT="${MAE_ALERT:-76.1}"
TAGS=(course=itcs355 "student=${STUDENT}" lab=capstone)

FORECAST_ID="$(az containerapp job show -g "$RG" -n bike-forecast --query id -o tsv)"
FEEDER_ID="$(az containerapp job show -g "$RG" -n bike-feeder --query id -o tsv)"
JOB_PRINCIPAL="$(az identity show -g "$RG" -n bike-job-id --query principalId -o tsv)"
GHA_PRINCIPAL="$(az identity show -g "$RG" -n bike-gha-id --query principalId -o tsv)"

grant() {  # principal role scope
  az role assignment create --assignee-object-id "$1" --assignee-principal-type ServicePrincipal \
    --role "$2" --scope "$3" -o none
}
echo "== roles that need the jobs to exist =="
grant "$JOB_PRINCIPAL" "Monitoring Metrics Publisher" "$FORECAST_ID"
grant "$GHA_PRINCIPAL" Contributor "$FORECAST_ID"
grant "$GHA_PRINCIPAL" Contributor "$FEEDER_ID"
# Updating a job also needs Microsoft.App/managedEnvironments/join/action on its environment
# (LinkedAuthorizationFailed on the first CD run with secrets): Contributor on that one resource.
grant "$GHA_PRINCIPAL" Contributor "$(az containerapp env show -g "$RG" -n bike-env --query id -o tsv)"

echo "== action group: email both of us =="
receivers=()
i=0
for email in $ALERT_EMAILS; do
  receivers+=(--action email "person$i" "$email")
  i=$((i + 1))
done
az monitor action-group create -g "$RG" -n bike-oncall --short-name bikeoncall \
  "${receivers[@]}" --tags "${TAGS[@]}" -o none
GROUP_ID="$(az monitor action-group show -g "$RG" -n bike-oncall --query id -o tsv)"

alert() {  # name severity condition description
  az monitor metrics alert create -g "$RG" -n "$1" --scopes "$FORECAST_ID" \
    --severity "$2" --condition "$3" --description "$4" \
    --window-size "$WINDOW" --evaluation-frequency 5m --action "$GROUP_ID" \
    --tags "${TAGS[@]}" -o none
  echo "  $1: $3"
}
echo "== alert rules (src/monitor.py, as metric alerts) =="
alert bike-weather-stale 1 "max bike.weather_age_min > ${WEATHER_MAX_AGE_MIN}" \
  "The weather feed is stale: the forecast is degraded. Fix the feed; do not retrain."
alert bike-accuracy 2 "avg bike.rolling_mae_1h > ${MAE_ALERT}" \
  "Live 1-hour error above the production version's threshold. Check the feed first, then make rollback."
alert bike-job-failed 1 "min bike.job_success < 1" \
  "A forecast run failed. The last structured log line names the exception."
alert bike-job-slow 3 "max bike.job_duration_s > ${JOB_MAX_DURATION_S}" \
  "A forecast run took longer than the SLO; the platform kills it at the same limit."

echo "== dashboard: monitoring/workbook.json as an Azure Monitor workbook =="
WORKBOOK_NAME="$(python3 -c 'import uuid; print(uuid.uuid5(uuid.NAMESPACE_URL, "bike-forecast-dashboard"))')"
BODY_FILE="$(mktemp)"
FORECAST_ID="$FORECAST_ID" python3 - "$BODY_FILE" <<'PY'
import json, os, sys
content = open("monitoring/workbook.json", encoding="utf-8").read()
content = content.replace("{forecast_job_id}", os.environ["FORECAST_ID"])
body = {
    "location": os.environ.get("REGION", "eastasia"),
    "kind": "shared",
    "tags": {"course": "itcs355", "student": os.environ.get("STUDENT", "6688067"), "lab": "capstone"},
    "properties": {"displayName": "Bike forecast", "category": "workbook",
                   "serializedData": content,
                   # "azure monitor" lists it in Monitor > Workbooks; a resource id here hides
                   # it under that one resource's blade (found when the gallery showed nothing).
                   "sourceId": "azure monitor"},
}
json.dump(body, open(sys.argv[1], "w"))
PY
az rest --method put   --url "https://management.azure.com$(az group show -n "$RG" --query id -o tsv)/providers/Microsoft.Insights/workbooks/${WORKBOOK_NAME}?api-version=2022-04-01"   --body "@${BODY_FILE}" -o none
rm -f "$BODY_FILE"
echo "Done. Test it: make freeze, wait two ticks, and the stale-weather email should arrive."
