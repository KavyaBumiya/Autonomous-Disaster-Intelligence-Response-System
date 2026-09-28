FROM python:3.11-slim

# System dependencies: ffmpeg for audio processing, libpq for asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir "setuptools<70" \
    && pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu --no-build-isolation -r requirements.txt

# Download spaCy English model
RUN pip install --no-cache-dir https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl

# Pre-download Whisper base model weights into image layer
RUN python -c "import whisper; whisper.load_model('base')"

COPY . .

# Create media directory for audio uploads
RUN mkdir -p /app/media/audio

# Create non-root user for security
RUN useradd -m -r aegis && chown -R aegis:aegis /app
USER aegis

ENV PORT=8000
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Graceful shutdown handling
STOPSIGNAL SIGTERM

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:socket_app --host 0.0.0.0 --port ${PORT}"]
