"""
Tests for AI API endpoints.

Tests:
- AI health endpoint
- Model listing
- Report analysis
- Hazard classification
- Prediction routing
- Decision recommendation
- Decision approval/rejection
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(scope="module")
def client():
    """A lifespan-managed TestClient shared by the whole module.

    A bare `TestClient(app)` opens a fresh event loop per request, but the
    application's asyncpg pool outlives each request. The second DB-backed
    request would then check out a connection bound to an already-closed loop
    and fail with "Event loop is closed". Entering the context manager once
    gives every request in the module a single, consistent loop.
    """
    with TestClient(app) as c:
        yield c


class TestAIHealth:
    """Test AI health endpoint."""

    def test_ai_health(self, client):
        response = client.get("/api/ai/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "providers" in data
        assert "models_registered" in data

    def test_ai_providers(self, client):
        response = client.get("/api/ai/providers")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert len(data) > 0


class TestAIModels:
    """Test model registry endpoints."""

    def test_list_models(self, client):
        response = client.get("/api/ai/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert isinstance(data["models"], dict)

    def test_get_model_not_found(self, client):
        response = client.get("/api/ai/models/nonexistent-model-12345")
        assert response.status_code == 404


class TestAIAnalyzeReport:
    """Test report analysis endpoint."""

    def test_analyze_report(self, client):
        response = client.post("/api/ai/analyze-report", json={
            "text": "Severe flooding in Vadodara, water rising fast, people trapped",
        })
        assert response.status_code == 200
        data = response.json()
        assert "original_text" in data
        assert "hazard_type" in data
        assert "explanation" in data

    def test_analyze_report_empty(self, client):
        """Empty text is rejected at validation, not analysed.

        AnalyzeReportRequest declares min_length=1. Returning 200 with
        fallback_used=true for an empty string would tell the caller an
        analysis happened when no text was submitted, so the request is
        refused up front instead.
        """
        response = client.post("/api/ai/analyze-report", json={
            "text": "",
        })
        assert response.status_code == 422

    def test_analyze_report_with_hazard_hint(self, client):
        response = client.post("/api/ai/analyze-report", json={
            "text": "Water everywhere, streets submerged",
            "hazard_hint": "flood",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["original_text"] == "Water everywhere, streets submerged"


class TestAIClassifyHazard:
    """Test hazard classification endpoint."""

    def test_classify_flood(self, client):
        response = client.post("/api/ai/classify-hazard", json={
            "text": "The city is flooded due to heavy rainfall",
        })
        assert response.status_code == 200
        data = response.json()
        assert "prediction" in data
        assert "confidence" in data
        assert "model_id" in data

    def test_classify_earthquake(self, client):
        response = client.post("/api/ai/classify-hazard", json={
            "text": "Earthquake tremors felt across the region",
        })
        assert response.status_code == 200
        data = response.json()
        assert "prediction" in data


class TestAIPredict:
    """Test prediction endpoint."""

    def test_predict_hazard_classification(self, client):
        response = client.post("/api/ai/predict", json={
            "task": "hazard_classification",
            "input_data": "Flood in Vadodara",
            "hazard": "flood",
        })
        assert response.status_code == 200
        data = response.json()
        assert "prediction" in data
        assert "confidence" in data
        assert "model_id" in data

    def test_predict_invalid_task(self, client):
        response = client.post("/api/ai/predict", json={
            "task": "invalid_task",
            "input_data": "test",
        })
        assert response.status_code == 400


class TestAIVerifyReport:
    """Test report verification endpoint."""

    def test_verify_report(self, client):
        response = client.post("/api/ai/verify-report", json={
            "text": "Flooding reported near Vishwamitri river, water level rising",
            "source": "citizen_text",
        })
        assert response.status_code == 200
        data = response.json()
        assert "credibility_score" in data
        assert "explanation" in data


class TestAISummarize:
    """Test summarization endpoint."""

    def test_summarize(self, client):
        response = client.post("/api/ai/summarize", json={
            "text": "Severe flooding has affected multiple areas in Vadodara. "
                    "Water levels are rising rapidly due to heavy rainfall. "
                    "Several people are trapped in their homes. "
                    "Rescue operations are underway.",
        })
        assert response.status_code == 200
        data = response.json()
        assert "prediction" in data
        assert "confidence" in data


class TestDecisionEndpoints:
    """Test decision/approval endpoints."""

    @pytest.fixture(scope="class")
    def incident_id(self):
        """A real incident row.

        actions.incident_id is a foreign key to incidents, so a decision cannot
        reference an ID that was never inserted. This test previously used a
        hard-coded "test-incident-123" and failed on the FK.

        A dedicated engine is used rather than the application's: the app's
        async pool is bound to the TestClient's event loop, and touching it
        from a second loop poisons the pool for the rest of the session.
        """
        import asyncio
        import uuid

        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import get_settings
        from app.models.incident import Incident
        from app.models.zone import Zone

        zone_id = f"test-zone-{uuid.uuid4().hex[:8]}"
        inc_id = f"test-incident-{uuid.uuid4().hex[:8]}"

        async def _create():
            engine = create_async_engine(get_settings().database_url)
            try:
                async with engine.begin() as conn:
                    await conn.execute(
                        Zone.__table__.insert().values(
                            id=zone_id,
                            name=f"Test Zone {uuid.uuid4().hex[:8]}",
                            centroid_lat=22.3072,
                            centroid_lng=73.1812,
                            radius_meters=5000.0,
                        )
                    )
                    await conn.execute(
                        Incident.__table__.insert().values(
                            id=inc_id,
                            zone_id=zone_id,
                            disaster_type="flood",
                            severity_score=70.0,
                            priority_score=70.0,
                        )
                    )
            finally:
                await engine.dispose()

        asyncio.run(_create())
        return inc_id

    def test_recommend(self, client, incident_id):
        response = client.post("/api/decision/recommend", json={
            "incident_id": incident_id,
            "action_type": "dispatch",
            "hazard_type": "flood",
        })
        assert response.status_code == 200
        data = response.json()
        assert "decision_id" in data
        assert data["requires_human_approval"] is True
        assert data["status"] == "pending_approval"

    def test_pending_decisions(self, client, incident_id):
        response = client.get("/api/decision/pending")
        assert response.status_code == 200
        data = response.json()
        assert "pending_count" in data
        assert "decisions" in data

    def test_get_decision_not_found(self, client):
        response = client.get("/api/decision/nonexistent-decision-12345")
        assert response.status_code == 404
