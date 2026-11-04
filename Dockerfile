# Public demo: one process serves the API and the exported frontend.
# SONICDNA_PUBLIC is on here, and .dockerignore keeps .env out, so no key can reach this image.

FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN SONICDNA_EXPORT=1 npm run build

FROM python:3.11-slim
WORKDIR /srv/sonicdna
ENV PYTHONUNBUFFERED=1 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    NUMBA_CACHE_DIR=/srv/sonicdna/numba-cache \
    NUMBA_CPU_NAME=generic \
    SONICDNA_WARM_START=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    SONICDNA_PUBLIC=1 \
    SONICDNA_RUNS_DIR=/srv/sonicdna/demo \
    SONICDNA_LIVE_DIR=/tmp/sonicdna-live \
    SONICDNA_STATIC_DIR=/srv/sonicdna/static-site
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
COPY scripts/make_targets.py scripts/warm_cache.py scripts/
COPY demo/ demo/
COPY --from=frontend /frontend/out static-site/
RUN python scripts/make_targets.py
# Compiled here so a wake-up on a slow CPU doesn't repeat it. generic keeps the cache portable.
RUN python scripts/warm_cache.py
RUN useradd --create-home sonicdna && chown -R sonicdna numba-cache
USER sonicdna
CMD ["sh", "-c", "exec uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-10000}"]
