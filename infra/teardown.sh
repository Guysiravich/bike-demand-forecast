#!/usr/bin/env bash
# Delete everything the capstone created, and only that. Not run yet: it runs after grading.
#
#   bash infra/teardown.sh            # then, 24 hours later: make teardown-verify
#
# By tag (lab=capstone): the jobs, their environment, both identities, the log workspace, the
# action group, the alert rules and the workbook. By name: what carries no tags — the blob
# container and the retraining schedule (scripts/teardown.py handles the schedule). The labs'
# storage account, registry and tracking server carry other tags and are not touched.
set -euo pipefail

RG="${RG:-itcs355-6688067}"
STORAGE="${STORAGE:-itcs3556688067}"
CONTAINER="${CONTAINER:-bike}"

# Jobs before their environment: an environment with jobs in it refuses to delete.
for job in bike-forecast bike-feeder; do
  az containerapp job delete -g "$RG" -n "$job" --yes -o none 2>/dev/null || true
done
make teardown LAB=capstone
# Role assignments of deleted identities are left behind as "Identity not found"; remove them.
for id in $(az role assignment list --all --query "[?principalName==''].id" -o tsv); do
  az role assignment delete --ids "$id" -o none
done
az storage container delete --name "$CONTAINER" --account-name "$STORAGE" --auth-mode login -o none
echo "Deletion is asynchronous. Run \`make teardown-verify\` now and again in 24 hours, then"
echo "screenshot the resource group in the portal: that screenshot is a submission item."
