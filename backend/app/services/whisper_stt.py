"""
Whisper Speech-to-Text service.
Loads the model on first use and exposes `transcribe(path)`.
"""
import time
from pathlib import Path

import structlog

from app.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

_model = None


def _require_whisper():
    """Import openai-whisper on demand.

    The package is optional: it is absent from slim deployments, so importing
    it at module scope would take down every module that touches this one.
    """
    try:
        import whisper
    except ImportError as exc:  # pragma: no cover - depends on deployment extras
        raise RuntimeError(
            "openai-whisper is not installed on this deployment. "
            "Speech-to-text is unavailable; submit the report as text instead."
        ) from exc
    return whisper


def get_whisper_model():
    global _model
    if _model is None:
        whisper = _require_whisper()
        logger.info("Loading Whisper model", model=settings.whisper_model)
        _model = whisper.load_model(settings.whisper_model)
        logger.info("Whisper model loaded", model=settings.whisper_model)
    return _model


def transcribe(audio_path: str | Path) -> dict:
    """
    Transcribe an audio file and return:
    {
        "transcript": str,
        "language": str,
        "duration_seconds": float,
        "transcription_ms": int,
    }
    Raises ValueError if duration exceeds the configured maximum.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    model = get_whisper_model()
    whisper = _require_whisper()

    # Load audio and check duration before inference
    audio = whisper.load_audio(str(audio_path))
    duration = len(audio) / whisper.audio.SAMPLE_RATE

    max_dur = settings.whisper_max_duration_seconds
    if duration > max_dur:
        raise ValueError(
            f"Audio duration {duration:.1f}s exceeds maximum {max_dur}s"
        )

    start = time.monotonic()
    result = model.transcribe(str(audio_path), fp16=False, verbose=False)
    elapsed_ms = int((time.monotonic() - start) * 1000)

    transcript = result.get("text", "").strip()
    language = result.get("language", "unknown")

    logger.info(
        "Transcription complete",
        duration_s=round(duration, 2),
        language=language,
        elapsed_ms=elapsed_ms,
        chars=len(transcript),
    )

    return {
        "transcript": transcript,
        "language": language,
        "duration_seconds": round(duration, 2),
        "transcription_ms": elapsed_ms,
    }
