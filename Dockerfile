# Docling Vault Tool -- Dashboard-Container fuer den Headless-Betrieb.
#
# Build:   docker build -t docling-vault-tool .
# Start:   docker compose up -d        (empfohlen, siehe docker-compose.yml)
# Zugriff: http://<server-ip>:8501
#
# CPU-only-Variante: PyTorch kommt aus dem CPU-Index (deutlich kleineres
# Image). Fuer GPU-Betrieb den torch-Install durch die CUDA-Variante ersetzen
# und das Compose-File um "gpus: all" ergaenzen.

FROM python:3.12-slim

# libgl1/libglib2.0-0: OpenCV-Abhaengigkeiten von Doclings OCR-Stack;
# curl: Healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Torch zuerst und CPU-only -- verhindert, dass docling das grosse
# CUDA-Torch als Abhaengigkeit zieht.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY pyproject.toml README.md LICENSE ./
COPY docling_worker.py job_manager.py app_streamlit.py dashboard_launcher.py file_transfer.py vault_builder.py ./
RUN pip install --no-cache-dir ".[watch]"

# Alle veraenderlichen Daten unter /data (Volumes, siehe docker-compose.yml):
#   /data/source  -> Quelldokumente     /data/vault -> Ziel-Vault
#   /data/archive -> optionales Archiv  /data/config -> Jobs/Manifeste
#   /data/models  -> Docling-/HuggingFace-Modellcache (erster Lauf laedt Modelle)
ENV DOCLING_VAULT_HOME=/data/config \
    HF_HOME=/data/models \
    DOCLING_SOURCE_DIR=/data/source \
    DOCLING_TARGET_DIR=/data/vault \
    DOCLING_ARCHIVE_DIR=/data/archive \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data/source /data/vault /data/archive /data/config /data/models

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

CMD ["docling-vault-ui", "--server.address=0.0.0.0", "--server.port=8501"]
