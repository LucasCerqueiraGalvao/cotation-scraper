FROM mcr.microsoft.com/playwright/python:v1.52.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MAERSK_BROWSER_CHANNEL=bundled

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/requirements.txt

COPY . /app

RUN mkdir -p /app/artifacts/output /app/artifacts/logs /app/artifacts/runtime /app/artifacts/sync_out

CMD ["python", "src/orchestration/daily_pipeline_runner.py"]
