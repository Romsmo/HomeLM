# Sandbox-Worker für run_python. Läuft ohne Netzwerk (siehe docker-compose.yml).
# Optionales Build-Secret "extra_ca": zusätzliche CA, falls ein Virenscanner TLS aufbricht.
FROM python:3.12-slim
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/extra_ca > /tmp/ca.pem; \
      export PIP_CERT=/tmp/ca.pem; \
    fi; \
    pip install --no-cache-dir "numpy>=2,<3" "matplotlib>=3.9,<4"
RUN useradd --system --uid 10001 sandbox
COPY worker.py /opt/worker.py
WORKDIR /tmp
USER sandbox
CMD ["python", "-I", "/opt/worker.py"]
