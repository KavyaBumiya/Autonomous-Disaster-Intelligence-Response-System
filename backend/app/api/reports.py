"""
Report ingestion and listing endpoints.
Handles text JSON, voice multipart/form-data, and listing with filters.
"""
import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, Query
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.models.audio_upload import AudioUpload
from app.models.report import Report
from app.agents.orchestrator import process_report
from app.services import nlp_service, gis_service

logger = structlog.get_logger()
settings = get_settings()
router = APIRouter()

ALLOWED_AUDIO_TYPES = {"audio/wav", "audio/mpeg", "audio/ogg", "audio/mp4", "audio/x-m4a"}
MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10MB hard limit


class TextReportRequest(BaseModel):
    message_text: str
    reporter_id: str | None = None
    location_string: str | None = None
    lat: float | None = None
    lng: float | None = None
    device_type: str | None = None


async def _ingest_report(report: Report, db: AsyncSession, background: BackgroundTasks) -> None:
    """Shared post-save pipeline: moderate → NLP → save → orchestrate."""
    # ── Input moderation (Prompt Guard layer, PRD §4/§23) ─────────────────
    # Flags prompt-injection / abuse; never hard-drops a distress report.
    text = report.message_text or report.transcript or ""
    if text:
        try:
            from app.services.moderation_service import moderate_text, apply_moderation_to_report
            mod = await moderate_text(text)
            apply_moderation_to_report(report, mod)
        except Exception as mod_exc:
            logger.warning("moderation_skipped", error=str(mod_exc))

    # Run NLP if not already enriched
    if text and not report.disaster_type:
        nlp = await nlp_service.process(text)
        report.disaster_type = nlp.get("disaster_type")
        report.nlp_confidence = nlp.get("nlp_confidence")
        report.informative_flag = nlp.get("informative_flag")
        report.language_code = nlp.get("language_code")
        report.nlp_model_version = nlp.get("nlp_model_version", "v0_keyword")
        if not report.location_string:
            report.location_string = nlp.get("location_string")
        if not report.lat and nlp.get("lat"):
            report.lat = nlp["lat"]
            report.lng = nlp["lng"]
            # Confidence describes the stored coordinates' provenance —
            # only recorded when NLP geocoding actually supplied them (§10).
            report.geocoding_confidence = nlp.get("geocoding_confidence")

    db.add(report)
    await db.flush()
    await gis_service.set_report_geometry(db, report.id, report.lat, report.lng)
    await db.commit()
    await db.refresh(report)

    # Run orchestration pipeline in background (non-blocking)
    # Suppressed (flagged) reports still enter verification with low trust —
    # the Decision Engine decides whether they move priority, not the LLM.
    background.add_task(_run_pipeline, report.id)


async def _run_pipeline(report_id: str) -> None:
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Report).where(Report.id == report_id))
        report = result.scalar_one_or_none()
        if report:
            await process_report(report, db)
            await db.commit()


@router.post("", status_code=201)
async def ingest_text_report(
    body: TextReportRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Accept a text-based citizen report."""
    reporter_id = body.reporter_id or hashlib.sha256(
        f"anon:{uuid.uuid4()}".encode()
    ).hexdigest()[:32]

    report = Report(
        id=str(uuid.uuid4()),
        reporter_id=reporter_id,
        message_text=body.message_text,
        location_string=body.location_string,
        lat=body.lat,
        lng=body.lng,
        device_type=body.device_type,
        source="citizen_text",
        created_at=datetime.now(timezone.utc),
    )
    await _ingest_report(report, db, background)
    return {
        "report_id": report.id,
        "status": "created",
        "source": "citizen_text",
        "suppressed": bool(report.suppressed),
    }


@router.post("/voice", status_code=202)
async def ingest_voice_report(
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    audio_file: UploadFile = File(...),
    reporter_id: str = Form(default=""),
    location_string: str = Form(default=""),
    lat: float = Form(default=None),
    lng: float = Form(default=None),
):
    """Accept a voice audio upload; transcribes via Groq Whisper (or local fallback) in background."""
    if audio_file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(415, detail=f"Unsupported audio type: {audio_file.content_type}")

    content = await audio_file.read()
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(413, detail="Audio file too large (max 10MB)")

    # Save audio to disk
    media_dir = Path(settings.media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    file_id = str(uuid.uuid4())
    suffix = Path(audio_file.filename or "audio.wav").suffix or ".wav"
    file_path = media_dir / f"{file_id}{suffix}"

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    rid = reporter_id or hashlib.sha256(f"anon:{uuid.uuid4()}".encode()).hexdigest()[:32]

    report = Report(
        id=str(uuid.uuid4()),
        reporter_id=rid,
        location_string=location_string or None,
        lat=lat,
        lng=lng,
        source="citizen_voice",
        audio_url=f"/media/{file_path.name}",
        created_at=datetime.now(timezone.utc),
    )
    db.add(report)
    await db.flush()
    await gis_service.set_report_geometry(db, report.id, report.lat, report.lng)

    # Save audio_upload record
    audio_upload = AudioUpload(
        id=str(uuid.uuid4()),
        report_id=report.id,
        file_path=str(file_path),
        file_size_bytes=len(content),
        whisper_model=(
            settings.groq_stt_model
            if (settings.stt_provider or "").lower() == "groq" and settings.groq_api_key
            else settings.whisper_model
        ),
    )
    db.add(audio_upload)
    await db.commit()

    # Transcribe + pipeline in background
    background.add_task(_transcribe_and_pipeline, report.id, str(file_path), audio_upload.id)

    return {
        "report_id": report.id,
        "status": "processing",
        "source": "citizen_voice",
        "transcript": None,
        "stt_provider": settings.stt_provider,
        "message": "Audio received. Transcription in progress.",
    }


async def _transcribe_and_pipeline(report_id: str, file_path: str, audio_upload_id: str) -> None:
    from app.core.database import AsyncSessionLocal
    from app.services.stt_service import transcribe

    async with AsyncSessionLocal() as db:
        report_result = await db.execute(select(Report).where(Report.id == report_id))
        report = report_result.scalar_one_or_none()
        au_result = await db.execute(select(AudioUpload).where(AudioUpload.id == audio_upload_id))
        audio_upload = au_result.scalar_one_or_none()

        if not report:
            return

        try:
            result = await transcribe(file_path)
            report.transcript = result["transcript"]
            report.language_code = result["language"]
            if audio_upload:
                # Record which provider actually served this transcription
                audio_upload.whisper_model = result.get(
                    "model", audio_upload.whisper_model
                )
                audio_upload.duration_seconds = result["duration_seconds"]
                audio_upload.transcription_ms = result["transcription_ms"]
            logger.info(
                "voice_transcribed",
                report_id=report.id,
                provider=result.get("provider"),
                model=result.get("model"),
                language=result.get("language"),
            )
        except ValueError as e:
            logger.warning("Transcription rejected", report_id=report_id, reason=str(e))
            report.transcript = None
        except Exception as e:
            logger.error("Transcription failed", report_id=report_id, error=str(e))
            report.transcript = None

        await db.flush()

        if report.transcript:
            await _run_pipeline_in_session(report, db)

        await db.commit()


async def _run_pipeline_in_session(report: Report, db: AsyncSession) -> None:
    # Moderate voice transcripts before enrichment (same policy as text path)
    text = report.transcript or ""
    if text:
        try:
            from app.services.moderation_service import moderate_text, apply_moderation_to_report
            mod = await moderate_text(text)
            apply_moderation_to_report(report, mod)
        except Exception as mod_exc:
            logger.warning("voice_moderation_skipped", error=str(mod_exc))

        nlp = await nlp_service.process(text)
        report.disaster_type = nlp.get("disaster_type")
        report.nlp_confidence = nlp.get("nlp_confidence")
        report.informative_flag = nlp.get("informative_flag")
        report.language_code = report.language_code or nlp.get("language_code")
        report.nlp_model_version = nlp.get("nlp_model_version", "v0_keyword")
        if not report.location_string and nlp.get("location_string"):
            report.location_string = nlp.get("location_string")
        if not report.lat and nlp.get("lat"):
            report.lat = nlp["lat"]
            report.lng = nlp["lng"]
            # Confidence describes the stored coordinates' provenance —
            # only recorded when NLP geocoding actually supplied them (§10).
            report.geocoding_confidence = nlp.get("geocoding_confidence")
    await process_report(report, db)


@router.get("")
async def list_reports(
    zone_id: str | None = Query(None),
    source: str | None = Query(None),
    min_trust: float = Query(0.25),
    include_suppressed: bool = Query(False),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Only commanders can see suppressed reports
    if include_suppressed and current_user["role"] != "commander":
        raise HTTPException(403, detail="Only commanders can view suppressed reports")

    filters = []
    if zone_id:
        filters.append(Report.zone_id == zone_id)
    if source:
        filters.append(Report.source == source)
    if not include_suppressed:
        filters.append(Report.suppressed == False)
        filters.append(
            (Report.trust_score >= min_trust) | (Report.trust_score.is_(None))
        )

    query = select(Report)
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(Report.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    reports = result.scalars().all()

    from sqlalchemy import func
    count_q = select(func.count(Report.id))
    if filters:
        count_q = count_q.where(and_(*filters))
    count_result = await db.execute(count_q)
    total = count_result.scalar()

    return {
        "reports": [_report_to_dict(r) for r in reports],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _report_to_dict(r: Report) -> dict:
    return {
        "report_id": r.id,
        "zone_id": r.zone_id,
        "source": r.source,
        "trust_score": r.trust_score,
        "suppressed": r.suppressed,
        "disaster_type": r.disaster_type,
        "informative": r.informative_flag,
        "summary": (r.message_text or r.transcript or "")[:140],
        "lat": r.lat,
        "lng": r.lng,
        "language_code": r.language_code,
        "nlp_model_version": r.nlp_model_version,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
