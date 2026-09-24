"""
AEGIS-AI — Speech-to-Text service
==================================
Dual-provider transcription for citizen voice reports:

  STT_PROVIDER=groq  → Groq cloud Whisper (whisper-large-v3-turbo)  [preferred]
                       fallback → local openai-whisper when Groq fails/offline
  STT_PROVIDER=local → local openai-whisper only

Both paths return the same shape so the ingestion pipeline is provider-agnostic:

  {
    "transcript": str,
    "language": str,
    "duration_seconds": float,
    "transcription_ms": int,
    "provider": "groq" | "local",
    "model": str,
  }

The Groq API key never leaves the backend process (PRD §3).
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import structlog

from app.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

ALLOWED_STT_SUFFIXES = {".wav", ".mp3", ".ogg", ".m4a", ".webm", ".flac", ".mp4"}


async def transcribe(audio_path: str | Path) -> dict:
    """
    Transcribe an audio file.

    Order of preference is driven by `settings.stt_provider` and Groq availability.
    Raises FileNotFoundError / ValueError with the same semantics as the legacy
    local Whisper helper (duration cap enforced only on the local path).
    """
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    provider = (settings.stt_provider or "groq").lower()

    if provider == "groq":
        try:
            return await _transcribe_groq(path)
        except Exception as exc:
            logger.warning(
                "groq_stt_failed_fallback_local",
                path=path.name,
                error=str(exc),
            )
            return await asyncio.get_event_loop().run_in_executor(
                None, _transcribe_local, path
            )

    return await asyncio.get_event_loop().run_in_executor(None, _transcribe_local, path)


# ── Groq cloud Whisper ───────────────────────────────────────────────────

async def _transcribe_groq(path: Path) -> dict:
    from groq import AsyncGroq

    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY not configured")

    client = AsyncGroq(api_key=settings.groq_api_key)
    model = settings.groq_stt_model

    t0 = time.perf_counter()
    with path.open("rb") as audio_file:
        result = await client.audio.transcriptions.create(
            file=(path.name, audio_file),
            model=model,
            # response_format verbose_json gives language + duration when supported
            response_format="verbose_json",
        )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # groq SDK returns an object; tolerate dict-shaped responses too
    if isinstance(result, dict):
        transcript = (result.get("text") or "").strip()
        language = result.get("language") or "unknown"
        duration = float(result.get("duration") or 0.0)
    else:
        transcript = (getattr(result, "text", "") or "").strip()
        language = getattr(result, "language", None) or "unknown"
        duration = float(getattr(result, "duration", 0.0) or 0.0)

    if not transcript:
        raise RuntimeError("Groq STT returned empty transcript")

    logger.info(
        "groq_stt_complete",
        path=path.name,
        model=model,
        language=language,
        duration_s=round(duration, 2),
        elapsed_ms=elapsed_ms,
        chars=len(transcript),
    )

    return {
        "transcript": transcript,
        "language": language,
        "duration_seconds": round(duration, 2),
        "transcription_ms": elapsed_ms,
        "provider": "groq",
        "model": model,
    }


# ── Local openai-whisper (offline / degraded fallback) ───────────────────

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
