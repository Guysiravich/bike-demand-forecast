#!/usr/bin/env bash
# Provision what the capstone adds to the shared base (infra/base.sh). Run 2026-10-07, from WSL,
# logged in with `az login`.
#
#   bash infra/provision.sh
#
# Reuses the shared base (infra/base.sh, not created here): resource group, storage account, container registry,
# the MLflow tracking server and the Azure ML workspace. Creates, all tagged
# course=itcs355 student=<id> lab=capstone so `make teardown LAB=capstone` finds them:
#
#   bike-job-id     user-assigned identity the two scheduled jobs run as
#   bike-gha-id     user-assigned identity GitHub Actions logs in as (OIDC, no secret)
#   bike-logs       Log Analytics workspace for the jobs' stdout, 30-day retention
#   blob container `bike` — not taggable, so infra/teardown.sh deletes it by name
#
# Least privilege (course Lab 5, Task 2) — every role is scoped to the one resource it needs:
#
#   identity      role                              scope            why
#   bike-job-id   AcrPull                           registry         pull the job image by digest
#   bike-job-id   Storage Blob Data Contributor     container `bike` read clock/weather/control, write forecasts and state
#   bike-job-id   Monitoring Metrics Publisher      forecast job     emit_metric (granted in alerts.sh, after the job exists)
#   bike-gha-id   AcrPush                           registry         CD pushes the job image
#   bike-gha-id   Storage Blob Data Contributor     container `bike` CD uploads hour.csv; the smoke test reads state/last_run.json
#   bike-gha-id   Contributor                       the two jobs     CD updates image and settings (alerts.sh, after the jobs exist)
#   bike-gha-id   Managed Identity Operator         bike-job-id      CD attaches the job identity to a job it updates
#   bike-gha-id   Reader                            resource group   CD looks up the environment, jobs and identity before updating
#
# The training identity is the labs' compute-cluster identity, which already has AcrPull on the
# registry. It gets Storage Blob Data Contributor on container `bike` here: the job mounts the
# data from it and writes its outputs back (without it: HTTP 403 on the mount, as in Lab 2).
set -euo pipefail

RG="${RG:-itcs355-6688067}"
REGION="${REGION:-eastasia}"
STUDENT="${STUDENT:-6688067}"
STORAGE="${STORAGE:-itcs3556688067}"
ACR="${ACR:-itcs3556688067}"
CONTAINER="${CONTAINER:-bike}"
GITHUB_REPO="${GITHUB_REPO:?set GITHUB_REPO=<owner>/<repo>}"
TAGS=(course=itcs355 "student=${STUDENT}" lab=capstone)

echo "== providers =="
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait

echo "== storage container ${CONTAINER} =="
az storage container create --name "$CONTAINER" --account-name "$STORAGE" --auth-mode login -o none
STORAGE_ID="$(az storage account show -g "$RG" -n "$STORAGE" --query id -o tsv)"
CONTAINER_SCOPE="${STORAGE_ID}/blobServices/default/containers/${CONTAINER}"
ACR_ID="$(az acr show -g "$RG" -n "$ACR" --query id -o tsv)"

echo "== identities =="
for id in bike-job-id bike-gha-id; do
  az identity create -g "$RG" -n "$id" -l "$REGION" --tags "${TAGS[@]}" -o none
done
JOB_PRINCIPAL="$(az identity show -g "$RG" -n bike-job-id --query principalId -o tsv)"
GHA_PRINCIPAL="$(az identity show -g "$RG" -n bike-gha-id --query principalId -o tsv)"
JOB_ID_RESOURCE="$(az identity show -g "$RG" -n bike-job-id --query id -o tsv)"

grant() {  # principal role scope
  az role assignment create --assignee-object-id "$1" --assignee-principal-type ServicePrincipal \
    --role "$2" --scope "$3" -o none
}
echo "== roles: each scoped to one resource =="
grant "$JOB_PRINCIPAL" AcrPull "$ACR_ID"
grant "$JOB_PRINCIPAL" "Storage Blob Data Contributor" "$CONTAINER_SCOPE"
grant "$GHA_PRINCIPAL" AcrPush "$ACR_ID"
grant "$GHA_PRINCIPAL" "Storage Blob Data Contributor" "$CONTAINER_SCOPE"
grant "$GHA_PRINCIPAL" "Managed Identity Operator" "$JOB_ID_RESOURCE"
grant "$GHA_PRINCIPAL" Reader "$(az group show -n "$RG" --query id -o tsv)"
CLUSTER_PRINCIPAL="$(az ml compute show -g "$RG" -w "${WORKSPACE:-itcs355-6688067-ml}"   -n "${CLUSTER:-ded-ds2}" --query identity.principal_id -o tsv)"
grant "$CLUSTER_PRINCIPAL" "Storage Blob Data Contributor" "$CONTAINER_SCOPE"

echo "== GitHub OIDC: trust only this repository's production environment =="
# GitHub's subject carries the owner and repository IDs, not only their names (course Lab 4:
# a name-only subject was refused with AADSTS700213).
OWNER="${GITHUB_REPO%/*}"
OWNER_ID="$(curl -s "https://api.github.com/users/${OWNER}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
REPO_ID="$(curl -s "https://api.github.com/repos/${GITHUB_REPO}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
az identity federated-credential create -g "$RG" --identity-name bike-gha-id -n github-production \
  --issuer https://token.actions.githubusercontent.com --audiences api://AzureADTokenExchange \
  --subject "repo:${OWNER}@${OWNER_ID}/${GITHUB_REPO#*/}@${REPO_ID}:environment:production" -o none

echo "== Log Analytics workspace for the jobs' logs =="
az monitor log-analytics workspace create -g "$RG" -n bike-logs -l "$REGION" \
  --retention-time 30 --tags "${TAGS[@]}" -o none
LOGS_ID="$(az monitor log-analytics workspace show -g "$RG" -n bike-logs --query id -o tsv)"

cat <<NEXT

Provisioned. Put these in cloud.env (and the CLOUD_ENV secret for CD):
  CLOUD_PROVIDER=azure
  BLOB_URI=https://${STORAGE}.blob.core.windows.net/${CONTAINER}/bike
  CONTAINER_REGISTRY=${ACR}.azurecr.io/bike
  IDENTITY_REF=${JOB_ID_RESOURCE}
  JOB_LOG_WORKSPACE=${LOGS_ID}
GitHub secrets for CD (identifiers, not credentials):
  AZURE_CLIENT_ID=$(az identity show -g "$RG" -n bike-gha-id --query clientId -o tsv)
  AZURE_TENANT_ID=$(az account show --query tenantId -o tsv)
  AZURE_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
Then: make cloud-check && make deploy && bash infra/alerts.sh
NEXT
