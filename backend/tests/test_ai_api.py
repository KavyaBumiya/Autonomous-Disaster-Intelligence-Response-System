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


client = TestClient(app)


class TestAIHealth:
    """Test AI health endpoint."""

    def test_ai_health(self):
        response = client.get("/api/ai/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "providers" in data
        assert "models_registered" in data

    def test_ai_providers(self):
        response = client.get("/api/ai/providers")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert len(data) > 0


class TestAIModels:
    """Test model registry endpoints."""

    def test_list_models(self):
        response = client.get("/api/ai/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert isinstance(data["models"], dict)

    def test_get_model_not_found(self):
        response = client.get("/api/ai/models/nonexistent-model-12345")
        assert response.status_code == 404


class TestAIAnalyzeReport:
    """Test report analysis endpoint."""

    def test_analyze_report(self):
        response = client.post("/api/ai/analyze-report", json={
            "text": "Severe flooding in Vadodara, water rising fast, people trapped",
        })
        assert response.status_code == 200
        data = response.json()
        assert "original_text" in data
        assert "hazard_type" in data
        assert "explanation" in data

    def test_analyze_report_empty(self):
        response = client.post("/api/ai/analyze-report", json={
            "text": "",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["fallback_used"] is True

    def test_analyze_report_with_hazard_hint(self):
        response = client.post("/api/ai/analyze-report", json={
            "text": "Water everywhere, streets submerged",
            "hazard_hint": "flood",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["original_text"] == "Water everywhere, streets submerged"


class TestAIClassifyHazard:
    """Test hazard classification endpoint."""

    def test_classify_flood(self):
        response = client.post("/api/ai/classify-hazard", json={
            "text": "The city is flooded due to heavy rainfall",
        })
        assert response.status_code == 200
        data = response.json()
        assert "prediction" in data
        assert "confidence" in data
        assert "model_id" in data

    def test_classify_earthquake(self):
        response = client.post("/api/ai/classify-hazard", json={
            "text": "Earthquake tremors felt across the region",
        })
        assert response.status_code == 200
        data = response.json()
        assert "prediction" in data


class TestAIPredict:
    """Test prediction endpoint."""

    def test_predict_hazard_classification(self):
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

    def test_predict_invalid_task(self):
        response = client.post("/api/ai/predict", json={
            "task": "invalid_task",
            "input_data": "test",
        })
        assert response.status_code == 400


class TestAIVerifyReport:
    """Test report verification endpoint."""

    def test_verify_report(self):
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

    def test_summarize(self):
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

    def test_recommend(self):
        response = client.post("/api/decision/recommend", json={
            "incident_id": "test-incident-123",
            "action_type": "dispatch",
            "hazard_type": "flood",
        })
        assert response.status_code == 200
        data = response.json()
        assert "decision_id" in data
        assert data["requires_human_approval"] is True
        assert data["status"] == "pending_approval"

    def test_pending_decisions(self):
        response = client.get("/api/decision/pending")
        assert response.status_code == 200
        data = response.json()
        assert "pending_count" in data
        assert "decisions" in data

    def test_get_decision_not_found(self):
        response = client.get("/api/decision/nonexistent-decision-12345")
        assert response.status_code == 404
