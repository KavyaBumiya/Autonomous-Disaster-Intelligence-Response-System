FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir "setuptools<70" \
    && pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu --no-build-isolation -r requirements.txt

COPY . .

RUN mkdir -p /app/media/audio

RUN useradd -m -r aegis && chown -R aegis:aegis /app
USER aegis

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

STOPSIGNAL SIGTERM

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:socket_app --host 0.0.0.0 --port ${PORT}"]
