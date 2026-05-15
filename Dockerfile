FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    IMPORT_DIR=/import \
    APP_HOST=0.0.0.0 \
    APP_PORT=12006

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libreoffice \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-swe \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY README.md .

RUN mkdir -p /data/uploads /data/derived /data/exports /data/import_failed /data/keys /data/indexes /data/logs /import

EXPOSE 12006

CMD ["sh", "-c", "uvicorn app.main:app --host ${APP_HOST:-0.0.0.0} --port ${APP_PORT:-12006}"]
