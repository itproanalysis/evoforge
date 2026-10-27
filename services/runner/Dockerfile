# EvoForge isolated Runner — secretless execution (no secret mounts).
# Build context root = repo root.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# git: reconstruct the base-only repo from the posted bundle.
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 evoforge
WORKDIR /app

COPY services/runner/requirements.txt /app/services/runner/requirements.txt
RUN pip install --no-cache-dir -r /app/services/runner/requirements.txt

# Only the Runner app (no API code, no contracts, no secrets).
COPY services/runner/ /app/services/runner/

WORKDIR /app/services/runner
USER evoforge
EXPOSE 8081
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8081"]
