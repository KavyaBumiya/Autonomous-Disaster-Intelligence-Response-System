"""
Tests for AI pipelines (NLP + Vision).

Tests:
- NLP pipeline analysis
- NLP fallback behavior
- Vision pipeline analysis
- Vision fallback behavior
- Image validation
"""
import pytest
from app.ai.nlp.disaster_nlp import DisasterNLP, get_disaster_nlp
from app.ai.vision.image_analysis import ImageAnalysisPipeline, get_image_pipeline


class TestDisasterNLP:
    """Test NLP disaster report pipeline."""

    @pytest.mark.asyncio
    async def test_analyze_empty_text(self):
        nlp = DisasterNLP()
        result = await nlp.analyze("")
        assert result["fallback_used"] is True
        assert result["hazard_type"] is None

    @pytest.mark.asyncio
    async def test_analyze_flood_text(self):
        nlp = DisasterNLP()
        result = await nlp.analyze("Severe flooding in Vadodara, water rising fast")
        assert result["original_text"] == "Severe flooding in Vadodara, water rising fast"
        assert result["language"] is not None
        # Should classify as flood (via keyword fallback at minimum)
        assert result["hazard_type"] in ("flood", "unknown")

    @pytest.mark.asyncio
    async def test_keyword_classify_flood(self):
        nlp = DisasterNLP()
        result = nlp._keyword_classify("The city is flooded due to heavy rainfall")
        assert result == "flood"

    @pytest.mark.asyncio
    async def test_keyword_classify_earthquake(self):
        nlp = DisasterNLP()
        result = nlp._keyword_classify("Earthquake tremors felt in the city")
        assert result == "earthquake"

    @pytest.mark.asyncio
    async def test_keyword_classify_unknown(self):
        nlp = DisasterNLP()
        result = nlp._keyword_classify("Nice weather today")
        assert result == "unknown"

    @pytest.mark.asyncio
    async def test_estimate_severity_critical(self):
        nlp = DisasterNLP()
        result = nlp._estimate_severity("People trapped, buildings collapsed, emergency")
        assert result == "critical"

    @pytest.mark.asyncio
    async def test_estimate_severity_low(self):
        nlp = DisasterNLP()
        result = nlp._estimate_severity("Some minor disruption reported")
        assert result == "low"

    @pytest.mark.asyncio
    async def test_estimate_urgency_critical(self):
        nlp = DisasterNLP()
        result = nlp._estimate_urgency("SOS help needed urgently")
        assert result == "critical"

    @pytest.mark.asyncio
    async def test_credibility_score(self):
        nlp = DisasterNLP()
        result = nlp._credibility_score("Test text", {
            "language": "en",
            "hazard_type": "flood",
            "entities": [{"text": "Vadodara"}],
        })
        assert result > 0.5

    @pytest.mark.asyncio
    async def test_classify_returns_result(self):
        nlp = DisasterNLP()
        result = await nlp.classify("Flood in the city")
        assert result is not None
        assert hasattr(result, "confidence")
        assert hasattr(result, "fallback_used")

    @pytest.mark.asyncio
    async def test_singleton(self):
        n1 = get_disaster_nlp()
        n2 = get_disaster_nlp()
        assert n1 is n2


class TestImageAnalysisPipeline:
    """Test image analysis pipeline."""

    @pytest.mark.asyncio
    async def test_analyze_invalid_image(self):
        pipeline = ImageAnalysisPipeline()
        result = await pipeline.analyze("not-valid-base64!!!")
        assert result["fallback_used"] is True
        assert "Invalid" in result["explanation"]

    @pytest.mark.asyncio
    async def test_validate_image_bytes(self):
        pipeline = ImageAnalysisPipeline()
        result = pipeline._validate_image(b"test image data")
        assert result is not None
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_validate_image_base64(self):
        pipeline = ImageAnalysisPipeline()
        result = pipeline._validate_image("aGVsbG8gd29ybGQ=")
        assert result == "aGVsbG8gd29ybGQ="

    @pytest.mark.asyncio
    async def test_validate_image_data_url(self):
        pipeline = ImageAnalysisPipeline()
        result = pipeline._validate_image("data:image/png;base64,aGVsbG8gd29ybGQ=")
        assert result == "aGVsbG8gd29ybGQ="

    @pytest.mark.asyncio
    async def test_validate_image_invalid(self):
        pipeline = ImageAnalysisPipeline()
        result = pipeline._validate_image(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_with_hazard_context(self):
        pipeline = ImageAnalysisPipeline()
        result = await pipeline.analyze(
            "aGVsbG8gd29ybGQ=",  # dummy base64 (11 bytes decoded)
            image_type="drone",
            hazard_context="flood",
            lat=22.3,
            lng=73.2,
        )
        assert result["image_type"] == "drone"
        assert result["hazard_context"] == "flood"
        assert result["geolocation"]["lat"] == 22.3
        assert "validation" in result["processing_steps"]

    @pytest.mark.asyncio
    async def test_classify_damage(self):
        pipeline = ImageAnalysisPipeline()
        result = await pipeline.classify_damage("aGVsbG8=")
        assert result is not None
        assert hasattr(result, "confidence")

    @pytest.mark.asyncio
    async def test_detect_victims(self):
        pipeline = ImageAnalysisPipeline()
        result = await pipeline.detect_victims("aGVsbG8=")
        assert result is not None
        assert hasattr(result, "confidence")

    @pytest.mark.asyncio
    async def test_singleton(self):
        p1 = get_image_pipeline()
        p2 = get_image_pipeline()
        assert p1 is p2
