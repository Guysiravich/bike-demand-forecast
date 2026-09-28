# Bike Rental Demand Forecast — ITCS355 capstone.
# Everything here runs on one machine with no cloud account. Cloud targets arrive after the
# proposal is approved, and each will have a matching teardown.

SHELL := /bin/bash
PYTHON ?= python
IMAGE ?= bike-forecast
TAG   ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)
BASE_IMAGE := python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

.PHONY: help setup lock data validate test lint portability-audit scan-secrets check \
        train register simulate simulate-freeze false-alarms image clean

help:
	@grep -E "^[a-zA-Z_-]+:.*?## .*$$" $(MAKEFILE_LIST) | awk -F":.*?## " "{printf \"  %-18s %s\\n\", \$$1, \$$2}"

setup: ## Install the pinned dependencies into the active environment
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

lock: ## Recompile requirements.txt with hashes, inside the pinned base image
	docker run --rm -v "$$PWD:/w" -w /w $(BASE_IMAGE) sh -c \
	  "pip install -q pip-tools && pip-compile --allow-unsafe --generate-hashes --strip-extras \
	   --output-file=requirements.txt requirements.in"

data: ## Fetch hour.csv from UCI, checksum verified (or: dvc pull)
	$(PYTHON) scripts/download_data.py

validate: ## Check the data contract on data/raw/hour.csv
	$(PYTHON) -c "from src import config, data; p = data.validate(data.load_raw(config.load().raw_path)); print('\n'.join(p) or 'DATA CONTRACT PASSED'); raise SystemExit(bool(p))"

test: ## Run the test suite (synthetic data; real-data checks run when data/ is present)
	$(PYTHON) -m pytest -q

lint: ## ruff, pinned
	$(PYTHON) -m ruff check src/ cloudlayer/ scripts/ tests/

portability-audit: ## Fail if provider details leak outside cloudlayer/
	$(PYTHON) scripts/portability_audit.py

scan-secrets: ## Scan the whole Git history for credential-shaped values
	$(PYTHON) scripts/scan_secrets.py

check: lint portability-audit scan-secrets test ## Everything CI runs

train: ## Train, evaluate against the baseline, log to MLflow
	$(PYTHON) -m src.train

register: ## Train and register a version with lineage
	$(PYTHON) -m src.train --register

simulate: ## Twelve simulated hours with a healthy feed
	$(PYTHON) scripts/simulate.py --ticks 12

simulate-freeze: ## The planned failure: freeze the weather feed at hour 3
	$(PYTHON) scripts/simulate.py --ticks 12 --freeze-at 3

false-alarms: ## How often real weather repeats by chance (the cost of the repeat rule)
	$(PYTHON) scripts/feed_false_alarms.py

image: ## Build the job image for linux/amd64
	docker buildx build --platform linux/amd64 -t $(IMAGE):$(TAG) --load .

clean: ## Remove local state and caches (not the data, not mlflow.db)
	rm -rf .local-store .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
