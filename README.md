Prompt Validator (Prototype)

A lightweight API prototype exploring how to structure a guardrail layer for user-generated LLM prompts.
The service evaluates prompts across three risk dimensions:
1. Sensitive information exposure (PII, credentials, private keys)
2. Jailbreak- system override attempts
3. Harmful (illegal + clearly unethical in v1)

The goal of this project is not model accuracy alone, but examining how probabilistic classification interacts with deterministic policy enforcement.

Design Principles

1. Hybrid detection: deterministic heuristics combined with LLM-based classification
2. Structured scoring per risk category
3. Aggregated risk score derived from category signals
4. Deterministic policy decision (allow / rewrite / block)
5. Fail-safe fallback if LLM output is invalid or unavailable
6. Structured logging designed to support offline evaluation and metrics
7. Consideration of additional context and tool access, since risk changes when models can retrieve data or act on behalf of users

High-Level Architecture

Client
→ API (FastAPI)
→ Validators (heuristics + LLM)
→ Scoring Layer
→ Policy Layer
→ Structured Response

The scoring layer produces per-category risk signals.
The policy layer translates those signals into a deterministic enforcement decision.

Example Output (Simplified)

{
"general_risk_score": 78,
"category_scores": {
"sensitive": 10,
"jailbreak": 82,
"harmful": 5
},
"recommendation": "BLOCK_NEEDS_USER_FIX"
}

Evaluation and Calibration

The repository includes a small golden prompt set for offline evaluation.
Structured logs are emitted per validation request, enabling calculation of:
Recommendation distribution (allow / rewrite / block)
Category dominance rates
Parse failure rate
Fallback rate
Latency distribution

Running Locally

python -m venv venv
source venv/bin/activate # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload

Open API docs at:
http://127.0.0.1:8000/docs

Environment Variables

Copy .env.example to .env and configure:
1. LLM provider + API key
2. Model name
3. Optional logging persistence path

Notes

This is a prototype intended for architectural exploration and experimentation.
It is not production-ready.