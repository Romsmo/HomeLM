# Optionales Build-Secret "extra_ca": zusätzliche CA im PEM-Format, z. B. wenn ein lokaler
# Virenscanner TLS aufbricht. Ohne Secret verhält sich der Build normal.

# --- Frontend bauen ---
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca; fi; \
    npm ci
COPY frontend/ ./
RUN npm run build

# --- Backend-Abhängigkeiten ---
FROM python:3.12-slim AS deps
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/extra_ca > /tmp/ca.pem; \
      export SSL_CERT_FILE=/tmp/ca.pem PIP_CERT=/tmp/ca.pem; \
    fi; \
    pip install --no-cache-dir uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/extra_ca > /tmp/ca.pem; \
      export SSL_CERT_FILE=/tmp/ca.pem; \
    fi; \
    uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
# Baut das Projekt selbst (zieht hatchling aus dem Index, daher auch hier das optionale Secret).
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/extra_ca > /tmp/ca.pem; \
      export SSL_CERT_FILE=/tmp/ca.pem; \
    fi; \
    uv sync --frozen --no-dev --no-editable

# --- Laufzeit ---
FROM python:3.12-slim
RUN useradd --system --uid 10001 --create-home cat
WORKDIR /app
COPY --from=deps /app/.venv /app/.venv
COPY --from=frontend /frontend/dist /app/static
ENV PATH="/app/.venv/bin:$PATH" \
    CAT_STATIC_DIR=/app/static \
    CAT_DATA_DIR=/data \
    PYTHONUNBUFFERED=1
RUN mkdir /data && chown cat /data
USER cat
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["uvicorn", "cat.main:app", "--host", "0.0.0.0", "--port", "8000"]
