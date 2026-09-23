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
RUN python -m spacy download en_core_web_sm

# Pre-download Whisper base model weights into image layer
RUN python -c "import whisper; whisper.load_model('base')"

COPY . .

# Create media directory for audio uploads
RUN mkdir -p /app/media/audio

EXPOSE 8000

CMD ["uvicorn", "app.main:socket_app", "--host", "0.0.0.0", "--port", "8000"]
