# Build context root = C:\evo_forge (repo root) so reference_impl + contracts are available.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY services/api/requirements.txt /app/services/api/requirements.txt
RUN pip install --no-cache-dir -r /app/services/api/requirements.txt

# App code + trust-kernel reference impl + SQL contracts (read-only at runtime).
COPY services/api/ /app/services/api/
COPY docs/evoforge-v4.2/reference_impl/ /app/docs/evoforge-v4.2/reference_impl/
COPY docs/evoforge-v4.2/contracts/ /app/docs/evoforge-v4.2/contracts/

WORKDIR /app/services/api
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
