# Training image (course Lab 1). `make reproduce` builds this and trains inside it.
#
# Base image pinned BY DIGEST, not by tag: `python:3.11-slim` today is not `python:3.11-slim`
# next month; a digest names exact bytes. The same bytes the course labs use.
FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534 AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /build
# Dependencies first, so this layer caches independently of the source.
COPY requirements.txt ./
# --require-hashes: a substituted package becomes a build failure, not a silent change.
RUN pip install --require-hashes --prefix=/install -r requirements.txt


FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534 AS runtime

# Non-root. A training container has no reason to run as root.
RUN useradd --create-home --uid 10001 runner
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app
COPY --from=builder /install /usr/local
WORKDIR /app
COPY --chown=runner:runner src/ ./src/
COPY --chown=runner:runner cloudlayer/ ./cloudlayer/
COPY --chown=runner:runner scripts/ ./scripts/
COPY --chown=runner:runner pipeline/ ./pipeline/
# MLflow writes ./mlruns relative to the workdir, and `make data` writes data/ — the runner
# must own /app (course Lab 1 notes: the provided image failed here on Linux).
RUN mkdir -p /app/mlruns /app/data /app/reports && chown -R runner:runner /app
USER runner

# Credentials NEVER enter an image layer. They arrive at run time from the platform's
# secret store or its managed identity.
ENTRYPOINT ["python", "-m", "src.train"]
