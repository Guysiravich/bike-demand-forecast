# The hourly forecast job. One image, used by the training job and the scheduled forecast.
#
# Base image pinned BY DIGEST — the same bytes the course labs use. Dependencies installed
# with --require-hashes from the compiled lock file. Runs as a non-root user.
# Credentials NEVER enter a layer: they arrive at run time from the platform's secret store
# or its managed identity.
FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534 AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt ./
RUN pip install --require-hashes --prefix=/install -r requirements.txt

FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534 AS runtime
RUN useradd --create-home --uid 10001 runner
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
COPY --from=builder /install /usr/local
WORKDIR /app
COPY --chown=runner:runner src/ ./src/
COPY --chown=runner:runner cloudlayer/ ./cloudlayer/
COPY --chown=runner:runner scripts/ ./scripts/
RUN mkdir -p /app/data /app/reports && chown -R runner:runner /app
USER runner
ENTRYPOINT ["python", "-m", "src.forecast"]
