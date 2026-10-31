# One image for the API, the Celery worker and the migration job.
FROM python:3.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Tesseract reads scanned pages and photos (English, Hindi, Gujarati). It is only used by the
# worker, but the API, worker and migration share this image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-guj \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml alembic.ini ./
COPY libs ./libs
COPY services ./services
COPY infra/migrations ./infra/migrations

RUN pip install .

RUN useradd --create-home app
USER app
