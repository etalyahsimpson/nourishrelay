# NourishRelay API image — Python 3.12, pinned dependencies.
# Build context is the REPOSITORY ROOT (see docker-compose.yml) because the
# worker/beat containers share this image and need both services/api and workers/.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv/services/api:/srv/workers

WORKDIR /srv/services/api

COPY services/api/requirements.lock.txt /srv/requirements.lock.txt
RUN pip install --no-cache-dir -r /srv/requirements.lock.txt

COPY services/api /srv/services/api
COPY workers /srv/workers

EXPOSE 8000

# Container entrypoint runs versioned migrations + idempotent seed before serving.
CMD ["sh", "-c", "python services/api/scripts/migrate.py && python services/api/scripts/seed.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
