"""
AEGIS AI — AI/ML Layer
=====================
Provider-agnostic AI/ML abstraction for the AEGIS platform.

Architecture:
    AIModelProvider (base)
    ├── HuggingFaceProvider  — HF Hub models (NLP, vision, speech, embeddings)
    ├── LocalModelProvider    — Locally-hosted models (whisper, distilbert)
    └── OpenAIProvider       — OpenAI-compatible APIs (NVIDIA NIM, OpenAI)

The rest of AEGIS calls the abstraction — never a specific provider.
"""
