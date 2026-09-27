"""
NLP Service v2 — Enhanced pipeline with HuggingFace Transformers:
  1. Language detection
  2. Text cleaning
  3. Transformer multi-label classification (distilbert / newer HF models)
  4. spaCy NER (location entities, persons)
  5. Custom entity ruler (local landmarks / district names)
  6. Geocoding (best location entity → lat/lng)
  7. Structured output

Falls back to spaCy keyword rules if the transformer model is absent.

LLM structured extraction lives in the AI Gateway
(`app.services.report_parser` / `ai_gateway.parse_report`) — this module
is deliberately deterministic so classification confidence is auditable.
"""
import json
import re
from pathlib import Path
from typing import Optional

import spacy
import structlog
from langdetect import detect, LangDetectException

from app.core.config import get_settings
from app.services.geocoding import geocode
from app.agents.detection import DISASTER_KEYWORDS

logger = structlog.get_logger()
settings = get_settings()

# ── spaCy model ───────────────────────────────────────────────
_nlp = None

# ── Transformer model ─────────────────────────────────────────
_tokenizer = None
_model = None
_label_map: dict[str, str] = {}
_use_transformer = False


def _get_nlp():
    global _nlp
    if _nlp is None:
        logger.info("Loading spaCy model")
        _nlp = spacy.load("en_core_web_sm")
        # Add custom entity ruler for known Indian disaster zones / landmarks
        ruler = _nlp.add_pipe("entity_ruler", before="ner")
        patterns = [
            {"label": "GPE", "pattern": "Vadodara"},
            {"label": "GPE", "pattern": "Vishwamitri"},
            {"label": "GPE", "pattern": "Alkapuri"},
            {"label": "GPE", "pattern": "Fatehgunj"},
            {"label": "GPE", "pattern": "Sayajigunj"},
            {"label": "GPE", "pattern": "Raopura"},
            {"label": "GPE", "pattern": "Manjalpur"},
        ]
        ruler.add_patterns(patterns)
    return _nlp


def _load_transformer():
    global _tokenizer, _model, _label_map, _use_transformer
    model_path = Path(settings.nlp_model_path)
    label_map_path = model_path / "label_map.json"

    if not model_path.exists() or not (model_path / "config.json").exists():
        logger.warning(
            "Transformer model not found, falling back to keyword rules",
            path=str(model_path),
        )
        _use_transformer = False
        return

    try:
        from transformers import DistilBertTokenizerFast, DistilBertForSequenceClassification
        import torch

        logger.info("Loading distilbert NLP model", path=str(model_path))
        _tokenizer = DistilBertTokenizerFast.from_pretrained(str(model_path))
        _model = DistilBertForSequenceClassification.from_pretrained(str(model_path))
        _model.eval()

        if label_map_path.exists():
            with open(label_map_path) as f:
                _label_map = json.load(f)
        else:
            _label_map = {str(i): v for i, v in enumerate(DISASTER_KEYWORDS.keys())}

        _use_transformer = True
        logger.info("distilbert model loaded successfully")
    except Exception as e:
        logger.error("Failed to load transformer model", error=str(e))
        _use_transformer = False


def _keyword_classify(text: str) -> tuple[str, float, bool]:
    """Fallback: keyword-based disaster type + informative flag."""
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for dtype, keywords in DISASTER_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text_lower)
        if count:
            scores[dtype] = count

    if not scores:
        return "not_disaster", 0.4, False

    best = max(scores, key=scores.get)
    confidence = min(0.5 + scores[best] * 0.1, 0.85)
    return best, confidence, True


def _transformer_classify(text: str) -> tuple[str, float, bool]:
    """distilbert multi-label classifier."""
    import torch

    inputs = _tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=128,
        padding=True,
    )
    with torch.no_grad():
        outputs = _model(**inputs)
        probs = torch.sigmoid(outputs.logits)[0]

    # Find best label
    best_idx = int(probs.argmax().item())
    best_prob = float(probs[best_idx].item())
    best_label = _label_map.get(str(best_idx), "not_disaster")

    is_informative = best_label != "not_disaster" and best_prob > 0.45

    return best_label, round(best_prob, 3), is_informative


def _extract_location(text: str) -> Optional[str]:
    """Use spaCy NER to find the most confident GPE/LOC entity."""
    nlp = _get_nlp()
    doc = nlp(text[:512])  # cap for performance
    locations = [ent.text for ent in doc.ents if ent.label_ in ("GPE", "LOC", "FAC")]
    return locations[0] if locations else None


def _clean_text(text: str) -> str:
    """Strip URLs, mentions, hashtags; normalise unicode."""
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"#(\w+)", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _detect_language(text: str) -> str:
    try:
        return detect(text[:200])
    except LangDetectException:
        return "unknown"


# ── Public API ────────────────────────────────────────────────

def init():
    """Load all models at startup (called from lifespan)."""
    _get_nlp()
    _load_transformer()


async def process(text: str) -> dict:
    """
    Full NLP pipeline. Returns:
    {
        "disaster_type": str,
        "nlp_confidence": float,
        "informative_flag": bool,
        "language_code": str,
        "location_string": str | None,
        "lat": float | None,
        "lng": float | None,
        "nlp_model_version": str,
    }
    """
    if not text or not text.strip():
        return {
            "disaster_type": None,
            "nlp_confidence": 0.0,
            "informative_flag": False,
            "language_code": "unknown",
            "location_string": None,
            "lat": None,
            "lng": None,
            "nlp_model_version": "v0_keyword",
        }

    # Step 1: Language detection
    language = _detect_language(text)

    # Step 2: Clean text
    clean = _clean_text(text)

    # Step 3: Classification
    if _use_transformer:
        disaster_type, confidence, informative = _transformer_classify(clean)
        model_version = "v1_distilbert"
    else:
        disaster_type, confidence, informative = _keyword_classify(clean)
        model_version = "v0_keyword"

    # Step 4+5: NER — extract location
    location_string = _extract_location(text)  # use raw text for NER

    # Step 6: Geocode
    lat, lng = None, None
    geocoding_confidence = None
    if location_string:
        geo = await geocode(location_string)
        if geo:
            lat = geo["lat"]
            lng = geo["lng"]
            geocoding_confidence = geo.get("confidence")

    # NOTE: Structured LLM extraction / translation is handled by the AI
    # AI Gateway in the orchestrator pipeline — not here. Keeping this
    # service deterministic means nlp_confidence is always model-auditable.

    return {
        "disaster_type": disaster_type if informative else None,
        "nlp_confidence": confidence,
        "informative_flag": informative,
        "language_code": language,
        "location_string": location_string,
        "lat": lat,
        "lng": lng,
        "geocoding_confidence": geocoding_confidence,
        "nlp_model_version": model_version,
        "llm_enhanced": False,
    }
