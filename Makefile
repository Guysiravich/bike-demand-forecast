# Bike Rental Demand Forecast — ITCS355 capstone.
# Target names follow the course repository, so each one does what the lab of the same name did.
# `make reproduce` is the one command a grader runs: it needs Docker, make and git, nothing else.
# On Windows, run everything from WSL2 — this Makefile assumes bash.

SHELL := /bin/bash
# python3 where `python` does not exist (a grader's plain Linux host has only python3).
PYTHON ?= $(shell command -v python >/dev/null 2>&1 && echo python || echo python3)
IMAGE ?= bike-train
JOB_IMAGE ?= bike-job
TAG   ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)
PLATFORM ?= linux/amd64
SEED ?= 20260920
ALIAS ?= production
LAB ?=
BASE_IMAGE := python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534
UV := uv==0.12.23

.PHONY: help setup lock cloud-check data validate test lint portability-audit scan-secrets check \
        train image image-push reproduce verify runs seeds compare register promote rollback models reload-check \
        train-remote job-image deploy run-now freeze unfreeze inject simulate simulate-freeze false-alarms stale-study \
        pipeline gate cost teardown teardown-verify clean

help:
	@grep -E "^[a-zA-Z_-]+:.*?## .*$$" $(MAKEFILE_LIST) | awk -F":.*?## " "{printf \"  %-18s %s\\n\", \$$1, \$$2}"

# --- Lab 1: reproducible training --------------------------------------------------------
setup: ## Install the pinned dependencies into the active environment
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install --require-hashes -r requirements.txt
	@echo "environment ok"

lock: ## Compile every requirements*.in to a hash-pinned lock, inside the pinned base image
	docker run --rm -v "$$PWD:/w" -w /w $(BASE_IMAGE) sh -c "pip install -q $(UV) && \
	  for f in requirements requirements-job requirements-cloud; do \
	    uv pip compile --generate-hashes --python-version 3.11 \
	      --python-platform x86_64-manylinux_2_28 --output-file \$$f.txt \$$f.in || exit 1; done"

cloud-check: ## Resolve the eight capability slots
	$(PYTHON) scripts/cloud_check.py

# Fetched inside the training image, so a grader needs Docker and nothing else. Runs as the
# invoking user so the file it writes into data/ stays theirs. sha256-verified against UCI.
data: image ## Fetch hour.csv from UCI, checksum verified, inside the training image (or: dvc pull)
	@mkdir -p data/raw
	docker run --rm --user "$$(id -u):$$(id -g)" -e HOME=/tmp \
	  -v "$$PWD/data:/app/data" --entrypoint python \
	  $(IMAGE):$(TAG) scripts/download_data.py

validate: ## Check the data contract on data/raw/hour.csv
	$(PYTHON) -c "from src import config, data; p = data.validate(data.load_raw(config.load(strict=False).raw_path)); print('\n'.join(p) or 'DATA CONTRACT PASSED'); raise SystemExit(bool(p))"

test: ## All tests: unit, data contract, model behaviour, the frozen-feed alert
	$(PYTHON) -m pytest -q tests/

lint: ## ruff, pinned in requirements.txt
	$(PYTHON) -m ruff check src/ cloudlayer/ scripts/ tests/

portability-audit: ## Fail if provider strings leak outside cloudlayer/
	$(PYTHON) scripts/portability_audit.py

scan-secrets: ## Scan the whole Git history for credential-shaped values
	$(PYTHON) scripts/scan_secrets.py

check: scan-secrets lint portability-audit test ## Everything CI's test job runs, in CI's order

train: ## Train locally, outside the container; writes reports/metrics.json
	$(PYTHON) -m src.train --seed $(SEED) --metrics-out reports/metrics.json

image: ## Build the training image for linux/amd64
	docker buildx build --platform $(PLATFORM) -t $(IMAGE):$(TAG) --load .

image-push: image ## Push the training image to CONTAINER_REGISTRY via the adapter
	$(PYTHON) -c "from src import config; from cloudlayer.factory import get_adapter; \
	print(get_adapter(config.load()).push_image('$(IMAGE):$(TAG)'))"

# The image runs as non-root uid 10001, which cannot write into a bind-mounted reports/
# owned by whoever cloned the repository. Open it before mounting (course Lab 1 notes).
reproduce: image data ## THE ONE COMMAND. Train inside the image and write reports/metrics.json
	@mkdir -p reports && chmod a+rwx reports
	docker run --rm \
	  -v "$$PWD/data:/app/data:ro" \
	  -v "$$PWD/reports:/app/reports" \
	  -e MLFLOW_TRACKING_URI=sqlite:////app/reports/mlflow.db \
	  $(IMAGE):$(TAG) --seed $(SEED) --metrics-out /app/reports/metrics.json

verify: ## Check reports/metrics.json against the claim line in README.md
	$(PYTHON) scripts/verify_metric.py

runs: ## The five tracked runs in README.md, varying max_leaf_nodes
	@for leaves in 7 15 31 63 127; do \
	  $(PYTHON) -m src.train --seed $(SEED) --max-leaf-nodes $$leaves --run-name leaves-$$leaves; \
	done

seeds: ## Seed variance: the default configuration at seeds 1-5 (sets the gate's margin)
	@for seed in 1 2 3 4 5; do 	  $(PYTHON) -m src.train --seed $$seed --run-name seed-$$seed; 	done

compare: ## Tables of the tracked runs and the seed variance: reports/runs.md
	$(PYTHON) scripts/compare_runs.py

# --- Lab 2: tracking and registry ---------------------------------------------------------
register: ## Register a run with lineage: make register RUN_ID=<id> (default: the last `make train`)
	$(PYTHON) scripts/register_model.py --run-id $(or $(RUN_ID),$$($(PYTHON) -c "import json; print(json.load(open('reports/metrics.json'))['run_id'])"))

promote: ## Point an alias at a version: make promote VERSION=<n> [ALIAS=staging|production]
	$(PYTHON) scripts/register_model.py --version $(VERSION) --alias $(ALIAS)

rollback: ## Bad model: point ALIAS (default production) back at the previous version
	$(PYTHON) -m src.registry rollback --alias $(ALIAS)

models: ## Registered versions, their aliases and lineage
	$(PYTHON) -m src.registry show

reload-check: ## Load a registered version from the registry and score rows: VERSION=<n>
	$(PYTHON) scripts/reload_check.py --version $(VERSION)

train-remote: image ## Train as an Azure ML command job on TRAINING_TARGET
	$(PYTHON) scripts/train_remote.py --image $(IMAGE):$(TAG)

# --- Lab 3: deployment (batch) -------------------------------------------------------------
job-image: ## Build the hourly job image (runtime dependencies only)
	docker buildx build --platform $(PLATFORM) -f Dockerfile.job -t $(JOB_IMAGE):$(TAG) --load .

deploy: job-image ## Push the job image; create or update the feeder and forecast jobs
	$(PYTHON) scripts/deploy.py --image $(JOB_IMAGE):$(TAG) --alias $(ALIAS)

run-now: ## One execution of a job now: make run-now JOB=bike-forecast
	$(PYTHON) scripts/deploy.py --run-now $(JOB)

freeze: ## The planned failure: freeze the weather feed (wherever BLOB_URI points)
	$(PYTHON) -m src.feeder --mode frozen

unfreeze: ## Back to a live feed
	$(PYTHON) -m src.feeder --mode normal

inject: ## Unexpected input: make inject TEXT='<anything>' (or FILE=<path>) as the weather reading
	$(PYTHON) scripts/inject_reading.py $(if $(FILE),--file $(FILE),--text '$(TEXT)')

simulate: ## Twelve simulated hours, healthy feed, on this machine
	$(PYTHON) scripts/simulate.py --ticks 12

simulate-freeze: ## The planned failure on this machine: the feed freezes at hour 3
	$(PYTHON) scripts/simulate.py --ticks 12 --freeze-at 3

false-alarms: ## How often real weather repeats by chance (the cost of the repeat rule)
	$(PYTHON) scripts/feed_false_alarms.py

stale-study: ## How long the model may forecast from a stale reading: reports/stale-reading-study.md
	$(PYTHON) scripts/stale_reading_study.py

# --- Lab 5: pipeline, cost, teardown --------------------------------------------------------
pipeline: ## Run pipeline/pipeline.yaml: validate, train, gate, register, promote to staging
	$(PYTHON) scripts/run_pipeline.py

gate: ## The registration gate alone, against reports/metrics.json
	$(PYTHON) scripts/evaluation_gate.py --metrics reports/metrics.json

cost: ## Cost per 1,000 forecasts: make cost DURATION=<s per run> [ACTUAL=<THB from billing>]
	$(PYTHON) scripts/cost_report.py --duration-s $(or $(DURATION),30) $(if $(ACTUAL),--actual-thb $(ACTUAL),)

teardown: ## Delete every resource tagged lab=$(LAB): make teardown LAB=capstone [DRY_RUN=1]
	@test -n "$(LAB)" || { echo "refusing to run without LAB=<tag>: make teardown LAB=capstone"; exit 1; }
	$(PYTHON) scripts/teardown.py --lab $(LAB) $(if $(DRY_RUN),--dry-run,)

teardown-verify: ## List anything still tagged lab=capstone; run again 24 h later
	$(PYTHON) scripts/teardown_verify.py --lab capstone

clean: ## Remove local state and caches (not the data, not mlflow.db)
	rm -rf .local-store .pytest_cache .ruff_cache reports/metrics.json
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
