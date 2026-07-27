FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml .
COPY vgm_bridge ./vgm_bridge
COPY config.example.json ./config.example.json
COPY policy.example.json ./policy.example.json
COPY README.md ./README.md

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data

USER appuser
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "vgm_bridge.cli", "run"]
