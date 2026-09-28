"""
AEGIS AI — Gradio Demo Interface (Hugging Face Space)
Thin UI layer — all logic lives in the FastAPI backend.
"""
import httpx
import gradio as gr

API_BASE = "http://localhost:8000"


def analyze_report(text: str) -> str:
    try:
        resp = httpx.post(f"{API_BASE}/api/ai/analyze-report", json={"text": text}, timeout=30)
        data = resp.json()
        return f"Hazard: {data.get('hazard_type', 'unknown')}\nConfidence: {data.get('hazard_confidence', 0):.0%}\n{data.get('explanation', '')}"
    except Exception as e:
        return f"Error: {e}"


def classify_hazard(text: str) -> str:
    try:
        resp = httpx.post(f"{API_BASE}/api/ai/classify-hazard", json={"text": text}, timeout=30)
        data = resp.json()
        return f"Prediction: {data.get('prediction', 'unknown')}\nConfidence: {data.get('confidence', 0):.0%}\nModel: {data.get('model_id', 'unknown')}"
    except Exception as e:
        return f"Error: {e}"


def summarize(text: str) -> str:
    try:
        resp = httpx.post(f"{API_BASE}/api/ai/summarize", json={"text": text}, timeout=30)
        data = resp.json()
        return data.get("prediction", "No summary available")
    except Exception as e:
        return f"Error: {e}"


def check_health() -> str:
    try:
        resp = httpx.get(f"{API_BASE}/api/ai/health", timeout=10)
        data = resp.json()
        return f"Status: {data.get('status', 'unknown')}\nModels: {data.get('models_registered', 0)}"
    except Exception as e:
        return f"Backend unreachable: {e}"


with gr.Blocks(title="AEGIS AI — Disaster Intelligence") as demo:
    gr.Markdown("# AEGIS AI — Autonomous Disaster Intelligence\n*One AI. Every disaster. Every decision.*")

    with gr.Tab("Health"):
        gr.Button("Check Health").click(check_health, outputs=gr.Textbox(label="Status"))

    with gr.Tab("Analyze Report"):
        report_input = gr.Textbox(lines=5, label="Emergency Report Text")
        report_output = gr.Textbox(label="Analysis Result")
        gr.Button("Analyze").click(analyze_report, inputs=report_input, outputs=report_output)

    with gr.Tab("Classify Hazard"):
        classify_input = gr.Textbox(lines=3, label="Report Text")
        classify_output = gr.Textbox(label="Classification")
        gr.Button("Classify").click(classify_hazard, inputs=classify_input, outputs=classify_output)

    with gr.Tab("Summarize"):
        summary_input = gr.Textbox(lines=8, label="Long Report")
        summary_output = gr.Textbox(label="Summary")
        gr.Button("Summarize").click(summarize, inputs=summary_input, outputs=summary_output)

if __name__ == "__main__":
    demo.launch()
