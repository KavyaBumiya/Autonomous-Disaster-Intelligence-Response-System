"""
AEGIS-AI — Speech-to-Text service
==================================
Transcription for citizen voice reports.

The AI provider is NVIDIA NIM's OpenAI-compatible chat-completions endpoint,
which serves text models only — it has no speech-to-text model. Transcription
therefore runs locally through openai-whisper:

  STT_PROVIDER=local     → local openai-whisper (default)
  STT_PROVIDER=disabled  → voice reports are rejected with an honest error
                           instead of loading a ~150 MB model

To add cloud STT later, implement one more branch here and return the same
shape; the ingestion pipeline is provider-agnostic:

  {
    "transcript": str,
    "language": str,
    "duration_seconds": float,
    "transcription_ms": int,
    "provider": "local",
    "model": str,
  }

Whisper runs on CPU in a thread executor, so it never blocks the event loop.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from app.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

ALLOWED_STT_SUFFIXES = {".wav", ".mp3", ".ogg", ".m4a", ".webm", ".flac", ".mp4"}


async def transcribe(audio_path: str | Path) -> dict:
    """
    Transcribe an audio file.

    Order of preference is driven by `settings.stt_provider`. Raises
    FileNotFoundError / ValueError with the same semantics as the legacy local
    Whisper helper (duration cap enforced before transcription starts).
    """
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    provider = (settings.stt_provider or "local").lower()

    if provider == "disabled":
        raise RuntimeError(
            "Speech-to-text is disabled on this deployment "
            "(STT_PROVIDER=disabled). Submit the report as text instead."
        )

    return await asyncio.get_event_loop().run_in_executor(None, _transcribe_local, path)


# ── Local openai-whisper ─────────────────────────────────────────────────

def _transcribe_local(path: Path) -> dict:
    import whisper

    from app.services.whisper_stt import transcribe as local_transcribe

    # Duration guard matches legacy whisper_stt.transcribe behaviour
    audio = whisper.load_audio(str(path))
    duration = len(audio) / whisper.audio.SAMPLE_RATE
    max_dur = settings.whisper_max_duration_seconds
    if duration > max_dur:
        raise ValueError(
            f"Audio duration {duration:.1f}s exceeds maximum {max_dur}s"
        )

    result = local_transcribe(path)
    result["provider"] = "local"
    result["model"] = settings.whisper_model
    return result
