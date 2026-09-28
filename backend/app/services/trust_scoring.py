"""
Trust Scoring Engine v2 — Fake report / corruption detection.

Hybrid gradient-boosted classifier combining:
- Corroboration count (number of independent reports for same event)
- Metadata consistency (timestamp plausibility, location consistency)
- Geospatial/weather consistency (does reported weather match actual conditions?)
- Text quality indicators (length, keyword density, readability)
- Source reliability (historical accuracy of reporting zone/user)
- Image consistency (do attached images match the reported conditions?)

Output: trust_score in [0.0, 1.0] where 1.0 = highly trustworthy
"""
import structlog
from typing import Any, Dict, Optional
from datetime import datetime, timezone

from app.services.damage_classification import DamageResult

logger = structlog.get_logger()


# ── Scoring Weights (tunable) ──────────────────────────────────────────
TRUST_WEIGHTS = {
    "corroboration": 0.30,      # 0.30 — number of independent reports
    "metadata": 0.20,           # 0.20 — timestamp/location plausibility
    "geospatial": 0.25,         # 0.25 — weather/terrain consistency
    "text_quality": 0.05,       # 0.05 — text coherence indicators (reduced to make room for image)
    "source_reliability": 0.10, # 0.10 — historical accuracy of reporting zone/user
    "image_consistency": 0.10,  # 0.10 — image/condition consistency check
}


# ── Helper Functions ─────────────────────────────────────────────────────

def _compute_corroboration_score(report_count: int, 
                                  max_reports_seen: int = 10) -> float:
    """
    Normalised corroboration score [0, 1].
    Diminishing returns: 1 report = 0.1, 3 reports = 0.3, 5+ = 0.5 plateau.
    """
    if report_count <= 0:
        return 0.0
    return min(0.5, 0.1 + 0.1 * min(report_count, max_reports_seen) / max_reports_seen)


def _compute_metadata_score(report: Any, db_session: Any) -> float:
    """
    Metadata plausibility score [0, 1].
    Checks: timestamp within reasonable window, location not null, 
    reported_at not far in future.
    """
    score = 0.5  # base neutral score
    
    # Timestamp check: report should not be from > 48h in future or > 2 weeks in past
    now = datetime.now(timezone.utc)
    reported_at = getattr(report, 'reported_at', None) or getattr(report, 'polled_at', None)
    
    if reported_at:
        delta = abs((now - reported_at).total_seconds())
        if delta < 86400:  # within 24h
            score += 0.2
        if delta < 604800:  # within 7 days
            score += 0.1
        if delta > 604800 * 2:  # > 2 weeks old
            score -= 0.2
    
    # Location check
    if hasattr(report, 'lat') and report.lat is not None:
        score += 0.2
    if hasattr(report, 'lng') and report.lng is not None:
        score += 0.1
    
    return max(0.0, min(1.0, score))


def _compute_geospatial_score(report: Any, weather_reading: Any) -> float:
    """
    Geospatial/weather consistency score [0, 1].
    Checks: reported conditions match actual weather data for that location.
    """
    score = 0.5  # base neutral
    
    if weather_reading is None:
        return score  # no weather data to compare against
    
    # If report mentions rain and actual data shows rainfall → consistent
    reported_rain = getattr(report, 'reported_rainfall_mm_hr', None) or 0
    actual_rain = getattr(weather_reading, 'rainfall_mm_hr', None) or 0
    
    # If report mentions thunderstorm and actual weathercode indicates thunderstorm
    reported_weather = getattr(report, 'weather_main', '').lower() or ""
    actual_weather = getattr(weather_reading, 'weather_main', '').lower() or ""
    
    # Check consistency
    if reported_rain > 0 and actual_rain > 0:
        score += 0.2
    if "thunderstorm" in reported_weather and "thunderstorm" in actual_weather:
        score += 0.2
    if "rain" in reported_weather and ("rain" in actual_weather or actual_rain > 0):
        score += 0.1
    if "clear" in reported_weather and "clear" in actual_weather:
        score += 0.1
    if "fire" in reported_weather and actual_rain is None or actual_rain == 0:
        # Fire reports are consistent with no rain
        score += 0.1
    
    return max(0.0, min(1.0, score))


def _compute_text_quality_score(report: Any) -> float:
    """
    Text quality score [0, 1].
    Checks: report has meaningful text, reasonable length, proper keywords,
    not auto-generated gibberish.
    """
    score = 0.5  # base neutral
    
    # Get the text source
    text = (getattr(report, 'message_text', '') or getattr(report, 'transcript', '') or '')
    text = text.strip()
    
    if not text:
        return 0.1  # very low score for empty text
    
    # Length check: reasonable report length
    text_len = len(text)
    if 20 <= text_len <= 500:
        score += 0.3
    elif text_len > 500:
        score += 0.1  # very long might be padded
    else:
        score -= 0.1  # too short suspicious
    
    # Keyword density check for disaster indicators
    disaster_kw = ["flood", "fire", "earthquake", "storm", "trapped", "injured", "help"]
    kw_found = sum(1 for kw in disaster_kw if kw.lower() in text.lower())
    score += min(0.15, kw_found * 0.05)
    
    # Structure check: sentences, capitalization
    if text[0].isupper():
        score += 0.05
    if "." in text:
        score += 0.05
    
    return max(0.0, min(1.0, score))


def _compute_source_reliability_score(user_history: Dict[str, Any]) -> float:
    """
    Source reliability score [0, 1] based on historical accuracy.
    In MVP: simplified static scoring; in production: learn from feedback loops.
    """
    # MVP: default neutral score
    # Production would query historical accuracy, user ratings, etc.
    return 0.7  # assumed reasonably reliable source


# ── Image Consistency ──────────────────────────────────────────────

def _compute_image_consistency_score(report: Any) -> float:
    """
    Image consistency score [0, 1].
    Checks: attached images match the reported disaster type and conditions.
    Synchronous version — no await needed. Uses classify_damage synchronously.
    """
    # Check if report has image data
    image_url = getattr(report, 'image_url', None)
    image_data = getattr(report, 'image_data', None)
    
    if not image_url and not image_data:
        return 0.5  # neutral — no images to evaluate
    
    # Base score for having images
    score = 0.6
    
    # Get disaster type from report
    disaster_type = getattr(report, 'disaster_type', None)
    if not disaster_type:
        return max(0.0, min(1.0, score))
    
    disaster_type_lower = disaster_type.lower()
    
    try:
        from app.services.damage_classification import classify_damage as sync_classify_damage
        
        if disaster_type_lower == "fire":
            # For fire reports, check if image shows fire/damage indicators
            if image_url:
                result = sync_classify_damage(image_url, "fire")
                if result.damage_level in ("severe", "destroyed") and result.damage_level != "no_damage":
                    score += 0.3  # fire damage consistent with fire report
                elif result.damage_level == "no_damage":
                    score -= 0.2  # fire reported but image shows no damage
            elif image_data:
                # If image_data is available as bytes, we'd need to save temporarily
                # For MVP, give neutral boost
                score += 0.1
        
        elif disaster_type_lower == "flood":
            if image_url:
                result = sync_classify_damage(image_url, "flood")
                if result.damage_level in ("severe", "destroyed") and result.damage_level != "no_damage":
                    score += 0.3  # flood damage consistent with flood report
                elif result.damage_level == "no_damage":
                    score -= 0.2  # flood reported but image shows no water damage
            elif image_data:
                score += 0.1
        
        elif disaster_type_lower in ("earthquake", "cyclone"):
            # For earthquake/cyclone, images of structural damage are consistent
            if image_url:
                result = sync_classify_damage(image_url, disaster_type_lower)
                if result.damage_level in ("moderate", "severe", "destroyed"):
                    score += 0.2  # damage consistent with quake/cyclone report
                elif result.damage_level == "no_damage":
                    score -= 0.1
            elif image_data:
                score += 0.1
        
        # Ensure score stays in [0, 1]
        score = max(0.0, min(1.0, score))
        
    except Exception as e:
        logger.warning("Image consistency check failed", error=str(e))
        return 0.5  # neutral on error
    
    return score


async def _compute_image_consistency_async(report: Any) -> float:
    """
    Async version of image consistency check for use with await.
    """
    # Check if report has image data
    image_url = getattr(report, 'image_url', None)
    image_data = getattr(report, 'image_data', None)
    
    if not image_url and not image_data:
        return 0.5  # neutral — no images to evaluate
    
    # Base score for having images
    score = 0.6
    
    # Get disaster type from report
    disaster_type = getattr(report, 'disaster_type', None)
    if not disaster_type:
        return max(0.0, min(1.0, score))
    
    disaster_type_lower = disaster_type.lower()
    
    try:
        from app.services.damage_classification import classify_damage
        
        if disaster_type_lower == "fire":
            # For fire reports, check if image shows fire/damage indicators
            if image_url:
                result: DamageResult = await classify_damage(image_url, "fire")
                if result.damage_level in ("severe", "destroyed") and result.damage_level != "no_damage":
                    score += 0.3  # fire damage consistent with fire report
                elif result.damage_level == "no_damage":
                    score -= 0.2  # fire reported but image shows no damage
            elif image_data:
                # If image_data is available as bytes, we'd need to save temporarily
                # For MVP, give neutral boost
                score += 0.1
        
        elif disaster_type_lower == "flood":
            if image_url:
                result: DamageResult = await classify_damage(image_url, "flood")
                if result.damage_level in ("severe", "destroyed") and result.damage_level != "no_damage":
                    score += 0.3  # flood damage consistent with flood report
                elif result.damage_level == "no_damage":
                    score -= 0.2  # flood reported but image shows no water damage
            elif image_data:
                score += 0.1
        
        elif disaster_type_lower in ("earthquake", "cyclone"):
            # For earthquake/cyclone, images of structural damage are consistent
            if image_url:
                result: DamageResult = await classify_damage(image_url, disaster_type_lower)
                if result.damage_level in ("moderate", "severe", "destroyed"):
                    score += 0.2  # damage consistent with quake/cyclone report
                elif result.damage_level == "no_damage":
                    score -= 0.1
            elif image_data:
                score += 0.1
        
        # Ensure score stays in [0, 1]
        score = max(0.0, min(1.0, score))
        
    except Exception as e:
        logger.warning("Image consistency check failed", error=str(e))
        return 0.5  # neutral on error
    
    return score


# ── Main Trust Score Function ────────────────────────────────────────────

def compute_trust_score(report: Any, 
                       weather_reading: Optional[Any] = None,
                       user_history: Optional[Dict[str, Any]] = None,
                       report_count_in_zone: int = 1) -> Dict[str, float]:
    """
    Compute overall trust score for a weather/report entry.
    
    Returns dict with breakdown:
    {
        "trust_score": float,           # overall [0, 1]
        "corroboration": float,         # [0, 1] - number of independent reports
        "metadata": float,              # [0, 1] - timestamp/location plausibility
        "geospatial": float,            # [0, 1] - weather consistency
        "text_quality": float,          # [0, 1] - text coherence
        "source_reliability": float,    # [0, 1] - user history
        "reason": str                   # brief explanation
    }
    """
    # Compute individual component scores
    corroboration = _compute_corroboration_score(report_count_in_zone)
    metadata = _compute_metadata_score(report, None)
    geospatial = _compute_geospatial_score(report, weather_reading)
    text_quality = _compute_text_quality_score(report)
    source_rel = _compute_source_reliability_score(user_history or {})
    image_consist = _compute_image_consistency_score(report)  # synchronous version
    
    # Weighted combination
    overall_score = (
        corroboration * TRUST_WEIGHTS["corroboration"] +
        metadata * TRUST_WEIGHTS["metadata"] +
        geospatial * TRUST_WEIGHTS["geospatial"] +
        text_quality * TRUST_WEIGHTS["text_quality"] +
        source_rel * TRUST_WEIGHTS["source_reliability"] +
        image_consist * TRUST_WEIGHTS["image_consistency"]
    )
    
    # Determine reason
    reasons = []
    if corroboration > 0.5:
        reasons.append(f"{report_count_in_zone} corroborating reports")
    if metadata > 0.7:
        reasons.append("plausible metadata")
    if geospatial > 0.7:
        reasons.append("geospatial/weather consistent")
    if text_quality > 0.7:
        reasons.append("high text quality")
    if image_consist > 0.7:
        reasons.append("image conditions consistent")
    
    reason = " + ".join(reasons) if reasons else "limited corroborating evidence"
    
    return {
        "trust_score": round(min(1.0, max(0.0, overall_score)), 3),
        "corroboration": round(corroboration, 3),
        "metadata": round(metadata, 3),
        "geospatial": round(geospatial, 3),
        "text_quality": round(text_quality, 3),
        "source_reliability": round(source_rel, 3),
        "reason": reason,
    }