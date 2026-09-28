FROM python:3.11-slim

# Render streams container logs through a pipe: without PYTHONUNBUFFERED the
# startup tracebacks are lost when the process dies.
ENV PYTHONUNBUFFERED=1

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

# Schema bootstrap (create_all + column reconcile + alembic stamp + seed) takes
# ~30s, so the grace period has to outlast it.
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD curl -f "http://localhost:${PORT:-8000}/api/health" || exit 1

STOPSIGNAL SIGTERM

# exec keeps uvicorn as PID 1 so SIGTERM reaches it and the lifespan runs its
# shutdown hook instead of being killed outright.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:socket_app --host 0.0.0.0 --port ${PORT:-8000}"]
