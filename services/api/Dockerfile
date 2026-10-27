# Build context root = C:\evo_forge (repo root) so reference_impl + contracts are available.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# git: server-side checkout of the configured GitHub repo (repo_source) and bundles for the Runner.
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 evoforge
WORKDIR /app

COPY services/api/requirements.txt /app/services/api/requirements.txt
RUN pip install --no-cache-dir -r /app/services/api/requirements.txt

# App code + trust-kernel reference impl + SQL contracts (read-only at runtime).
COPY services/api/ /app/services/api/
COPY docs/evoforge-v4.2/reference_impl/ /app/docs/evoforge-v4.2/reference_impl/
COPY docs/evoforge-v4.2/contracts/ /app/docs/evoforge-v4.2/contracts/
# Sealed eval set v0 (server-only; HTTP view is redacted by sealed_eval.public_suites).
COPY evals/sealed_v0/ /app/evals/sealed_v0/

WORKDIR /app/services/api
USER evoforge
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
