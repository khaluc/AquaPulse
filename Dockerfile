# AquaPulse backend (API + web pages). Build from the repo root:
#   docker build -t aquapulse-api .
# The two serving ONNX models and the face detector are included in the repository.
# Training checkpoints, datasets and local storage are excluded (see .gitignore).
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    AQUAPULSE_PHOTO_DIR=/data/photos PORT=8000

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 aquapulse \
    && mkdir -p /data/photos && chown aquapulse /data/photos

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

# Same layout as the repo, so the default model and migration paths work unchanged.
COPY db/migrations db/migrations
COPY db/data db/data
COPY ml/runs/n_clean/weights/best.onnx ml/runs/n_clean/weights/best.onnx
COPY ml/runs/n_clean/eval/report.json ml/runs/n_clean/eval/report.json
COPY ml/runs/water_seg_s/weights/best.onnx ml/runs/water_seg_s/weights/best.onnx
COPY backend/models backend/models
COPY backend/scripts backend/scripts
COPY backend/app backend/app

USER aquapulse
WORKDIR /app/backend
EXPOSE 8000
# Photos are written to /data/photos: mount a volume there, or they go with the container.
VOLUME ["/data/photos"]
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
