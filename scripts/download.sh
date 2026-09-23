#!/usr/bin/env bash
# Downloads fine-tuned distilbert NLP model weights for AEGIS-AI
# Place model artefacts in models/nlp/v1/ (tracked via Git LFS)

set -e

MODEL_DIR="$(dirname "$0")/nlp/v1"
mkdir -p "$MODEL_DIR"

echo "Downloading AEGIS-AI NLP model weights to $MODEL_DIR ..."

# Replace the URL below with your actual model artefact source
# e.g. HuggingFace Hub, S3, or GCS
# Example:
# curl -L "https://your-model-host/nlp-v1.tar.gz" | tar -xz -C "$MODEL_DIR"

echo "Done. Place your fine-tuned distilbert weights in: $MODEL_DIR"
