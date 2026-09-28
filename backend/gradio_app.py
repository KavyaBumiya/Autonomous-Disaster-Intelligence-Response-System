"""
AEGIS AI — Gradio Demo Interface (Hugging Face Space)
Self-contained: calls the AI layer directly (no separate backend needed).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import gradio as gr
import spaces
from app.ai.nlp.disaster_nlp import get_disaster_nlp
from app.ai.providers.base import TaskType
from app.ai.router.model_router import get_model_router

_nlp = None
_router = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = get_disaster_nlp()
    return _nlp


def _get_router():
    global _router
    if _router is None:
        _router = get_model_router()
    return _router


async def analyze_report(text: str) -> str:
    try:
        nlp = _get_nlp()
        result = await nlp.analyze(text)
        return f"Hazard: {result.get('hazard_type', 'unknown')}\nConfidence: {result.get('hazard_confidence', 0):.0%}\n{result.get('explanation', '')}"
    except Exception as e:
        return f"Error: {e}"


async def classify_hazard(text: str) -> str:
    try:
        router = _get_router()
        result = await router.route(TaskType.HAZARD_CLASSIFICATION, text)
        return f"Prediction: {result.prediction}\nConfidence: {result.confidence:.0%}\nModel: {result.model_id}"
    except Exception as e:
        return f"Error: {e}"


async def summarize(text: str) -> str:
    try:
        nlp = _get_nlp()
        result = await nlp.summarize(text)
        return result.prediction or "No summary available"
    except Exception as e:
        return f"Error: {e}"


def check_health() -> str:
    try:
        router = _get_router()
        return f"Router ready\nProviders: {len(router._providers)}"
    except Exception as e:
        return f"Error: {e}"


@spaces.GPU
def warmup():
    return "ready"


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
