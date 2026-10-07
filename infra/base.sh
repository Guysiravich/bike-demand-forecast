#!/usr/bin/env bash
# The shared base this project runs on, from nothing. COSTS MONEY (the registry bills daily).
#
#   bash infra/base.sh            # then infra/tracking-server/provision_azure.sh, then provision.sh
#
# For this team these resources already exist — they were built in the course labs and the
# project reuses them — so this script is the record of exactly what they are, with the
# settings read back from Azure on 2026-10-08, and the way anyone else rebuilds them. Each is
# tagged the way the labs tagged it, so the project's teardown (lab=capstone) never deletes it.
#
#   resource group     itcs355-<id>, eastasia (Azure for Students cannot deploy to southeastasia)
#   budget             25 USD a month, alerts at the subscription's defaults
#   storage account    Standard_LRS StorageV2, anonymous read of single blobs allowed;
#                      container itcs355 (public access: blob — the DVC read remote below)
#   container registry Basic, admin user disabled (images are pulled by managed identity)
#   Azure ML workspace with its key vault, Application Insights and Log Analytics
#   compute cluster    ded-ds2: Standard_DS2_v2, dedicated, 0-1 nodes, scale down after 120 s,
#                      system-assigned identity with AcrPull on the registry. Dedicated, not
#                      low-priority: this subscription's low-priority quota is 0
#   tracking server    MLflow on a VM: infra/tracking-server/ (run separately, below)
set -euo pipefail

STUDENT="${STUDENT:-6688067}"
RG="${RG:-itcs355-${STUDENT}}"
REGION="${REGION:-eastasia}"
SA="${SA:-itcs355${STUDENT}}"           # storage account: lowercase, digits, no hyphens
ACR="${ACR:-itcs355${STUDENT}}"
WS="${WS:-itcs355-${STUDENT}-ml}"
CLUSTER="${CLUSTER:-ded-ds2}"

echo "== resource group and budget"
az group create -n "$RG" -l "$REGION" --tags course=itcs355 "student=${STUDENT}" -o none
az consumption budget create --budget-name itcs355 --amount 25 --category Cost --time-grain Monthly \
  --start-date "$(date +%Y-%m-01)" --end-date "$(date -d '+1 year' +%Y-%m-01)" -o none

echo "== storage, registry"
az storage account create -n "$SA" -g "$RG" -l "$REGION" --sku Standard_LRS --kind StorageV2 \
  --allow-blob-public-access true --tags course=itcs355 "student=${STUDENT}" lab=1 -o none
az role assignment create --role "Storage Blob Data Contributor" \
  --assignee "$(az ad signed-in-user show --query id -o tsv)" \
  --scope "$(az storage account show -n "$SA" -g "$RG" --query id -o tsv)" -o none
az storage container create -n itcs355 --account-name "$SA" --auth-mode login \
  --public-access blob -o none
az acr create -n "$ACR" -g "$RG" -l "$REGION" --sku Basic \
  --tags course=itcs355 "student=${STUDENT}" lab=1 -o none

echo "== Azure ML workspace and the training cluster"
az ml workspace create -n "$WS" -g "$RG" -l "$REGION" --tags course=itcs355 "student=${STUDENT}" lab=2 -o none
az ml compute create -n "$CLUSTER" -g "$RG" -w "$WS" --type AmlCompute --size Standard_DS2_v2 \
  --tier dedicated --min-instances 0 --max-instances 1 --idle-time-before-scale-down 120 \
  --identity-type SystemAssigned -o none
CLUSTER_PRINCIPAL="$(az ml compute show -n "$CLUSTER" -g "$RG" -w "$WS" --query identity.principal_id -o tsv)"
az role assignment create --assignee-object-id "$CLUSTER_PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role AcrPull --scope "$(az acr show -n "$ACR" -g "$RG" --query id -o tsv)" -o none

cat <<NEXT

Base ready. Next, in order:
  1. RG=$RG STORAGE=$SA bash infra/tracking-server/provision_azure.sh
     (then on the VM: make_secrets.sh, docker compose up -d --build — the script prints how)
  2. GITHUB_REPO=<owner>/<repo> bash infra/provision.sh
  3. fill cloud.env from both scripts' output; make cloud-check
NEXT
