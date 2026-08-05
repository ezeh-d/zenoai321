# ZENO — Architecture & North-Star Spec

This is ZENO's guiding architecture vision (adapted from the master build
prompt). It is a **north star**, not a checklist that ships in one pass.
The full spec below describes a Hugging-Face-Transformers-scale multimodal
AI *platform* — model registry, training, PEFT, quantization, distributed
serving, ONNX export, and more. That is a multi-team, multi-year build.
This document keeps the vision in one place and, crucially, tells the
truth about what ZENO **already implements today** versus what is
aspirational, so nobody mistakes the map for the territory.

---

## Reality check — what ZENO already has (2026)

The most important architectural principle in the spec is *"do NOT
hard-code around a single model; use a unified model abstraction layer."*
**ZENO already does this.** The core is genuinely modular, and much of the
spec's *philosophy* is live, even though the ML-framework machinery
(training/quantization/etc.) is not.

| Spec area | Status in ZENO today |
|---|---|
| **Model abstraction / swappable models** | ✅ `reyes_agent/provider.py` — one neutral history format + `run_turn()`; Anthropic, xAI, Gemini, Ollama all behind one seam. Swap the model without touching UI/tools/memory. |
| **Orchestrator / agent loop** | ✅ `agent.py::run_agent` — one shared loop; tool rounds capped; used by every front door. |
| **Tool system** | ✅ `tools/` — `@register` decorator, input schemas, gated vs ungated (`requires_confirmation`), ~50 tools. |
| **Agent system w/ approval checkpoints** | ✅ Tier-6 confirmation gate (`confirmation.py`) — dangerous ops need explicit approval. |
| **Memory system (short/long/semantic)** | ✅ SQLite memory (`tools/memory.py`), the Obsidian vault, activity log; injected into the prompt each turn. Partial: no vector store/embeddings yet. |
| **Multimodal — vision** | ✅ `tools/vision.py` — screenshot + webcam described by a vision model; image generation. |
| **Audio (ASR + TTS)** | ✅ Deepgram STT, SAPI/ElevenLabs TTS, browser Web Speech; wake word. |
| **Documents** | ⚠️ Partial — can read files/notes; no full PDF/OCR/RAG pipeline yet. |
| **UI / AI orb w/ states** | ✅ three.js orb with idle/listening/thinking/speaking/error states (toggleable to a static image for weak GPUs). |
| **Safety / permissions** | ✅ Confirmation gate, audit log, kill switch, quiet hours. |
| **Observability / logging** | ✅ `audit.py` JSON-line log of tool runs/errors/approvals. |
| **Serving (local web/desktop)** | ✅ FastAPI + pywebview; LAN-reachable for phone. |
| **Streaming responses** | ✅ SSE token streaming + live activity feed. |
| **Model registry / router** | ⚠️ Partial — provider chosen by config; no auto-router by task/latency/cost yet. |
| **Embeddings / retrieval / RAG** | ❌ Not yet. |
| **Training / fine-tuning / PEFT / LoRA** | ❌ Not built — needs GPU + a real ML stack; out of scope for the current CPU-bound setup. |
| **Quantization / big-model sharding / device_map** | ❌ Not built — belongs to a local-model serving stack (vLLM/llama.cpp), not wired up. |
| **HF Hub / vLLM / SGLang / TGI / MLX integration** | ❌ Not built. |
| **ONNX / mobile export** | ❌ Not built. |
| **Plugin marketplace** | ❌ Not built (tools are extensible in-code, but no marketplace). |

**Honest bottom line:** ZENO is a strong, modular, model-agnostic
*assistant* that already embodies the spec's core philosophy (unified
model seam, tools, agent loop, memory, multimodal, safety, streaming UI).
It is **not** an ML training/serving *framework* — and building that
(training, PEFT, quantization, distributed inference, HF-Hub-scale model
management) is a genuinely enormous, GPU-dependent undertaking that would
be its own project. This doc keeps that ambition visible without
pretending it's done.

**Sensible next increments** (highest value, actually buildable next):
1. Embeddings + a local vector store → real RAG over the vault/documents.
2. A document engine (PDF/OCR → chunk → retrieve).
3. A model *router* (pick small-fast vs strong model by task) on top of
   the existing provider seam.
4. Local model serving via llama.cpp/Ollama for offline mode.

---

## Full north-star spec (aspirational)

> The following is the complete master build prompt, kept verbatim (with
> the name updated to ZENO) as the long-term architectural vision. Treat
> the table above as the source of truth for *current* state.

PROJECT NAME
ZENO — Intelligent Desktop AI / Multimodal AI Assistant

MISSION
Build ZENO as a modular, production-grade AI assistant whose architecture
is inspired by the Hugging Face Transformers ecosystem, supporting
natural-language understanding, text generation, conversational AI, vision
and image analysis, audio and speech, video understanding, multimodal
reasoning, document understanding, retrieval-augmented generation, tool
use, local and cloud models, model switching, fine-tuning, quantization,
GPU/CPU execution, streaming, offline operation, and extensible plugins.

ARCHITECTURAL PRINCIPLE
Do NOT hard-code ZENO around a single model. Use a unified model
abstraction layer (Model Config / Model / Preprocessor as separate but
connected components) so models plug in without rewriting the app.

CORE LAYERS
Orchestrator · Model Registry · Model Loader · Preprocessor Registry ·
Inference Engine · Generation Engine · Memory System · Tool System ·
Agent System · Context Manager · Safety Layer · Conversation Manager ·
Evaluation System · UI/Voice Interface. A model must be replaceable
without changing UI, memory, tools, conversation, permissions, logging, or
orchestration.

MODEL SYSTEM
Transformers-inspired abstraction: MODEL CONFIG (id, architecture, dims,
layers, attention, vocab, context length, modalities, tasks, dtype,
quantization, device, generation defaults); MODEL (load/unload/generate/
forward/embeddings/classify/vision/audio/multimodal/save/export);
PREPROCESSOR (tokenize/decode/process text·image·audio·video·document,
prepare multimodal). Auto-style loaders (AutoModel, AutoModelForCausalLM,
…Vision/Audio/Speech/Multimodal) pick the adapter from id/config/task/
modality.

MODEL REGISTRY
Register models with name, provider, architecture, version, params,
context, modalities, tasks, license, quantization, hardware, location,
availability, metrics, cost, latency, memory. Sources: HF Hub, local,
remote APIs, OpenAI-compatible, vLLM, SGLang, TGI, llama.cpp, MLX, custom.
Ops: install/remove/update/load/unload/switch/benchmark/compare.

PREPROCESSING · INFERENCE · GENERATION · CHAT · MULTIMODAL · VISION ·
AUDIO · VIDEO · DOCUMENT · EMBEDDINGS/RETRIEVAL · MEMORY · TOOLS · AGENTS ·
TRAINING · PEFT · DATA · PERFORMANCE · QUANTIZATION · BIG-MODEL LOADING ·
OPTIMIZATION · SERVING · MODEL ROUTER · EVALUATION · EXPORT · OFFLINE ·
CACHING · PUBLIC API · COMMANDS · SECURITY · OBSERVABILITY · PLUGINS · UI ·
ORB · CONVERSATION FLOW · FAILOVER — each as its own module with
interfaces, implementations, tests, config, error handling, and logging.

MODEL-CENTRIC PHILOSOPHY
1) One unified interface across architectures. 2) Separate model def from
preprocessing. 3) Separate inference from orchestration. 4) Prefer
pretrained over retraining. 5) Easy model switching. 6) Automatic
optimization. 7) Native multimodality. 8) Interchangeable local/remote.
9) Simple developer APIs. 10) Advanced power without forcing complexity.

IMPLEMENTATION PHASES
P1 registry/loader/preprocessor/chat/generation/pipeline/UI ·
P2 vision/audio/documents/embeddings/retrieval/memory/tools ·
P3 router/multimodal/serving/streaming/quantization/GPU ·
P4 training/eval/finetune/PEFT/distributed/export ·
P5 autonomous workflows/plugin marketplace/agent orchestration/adaptive
routing/enterprise security/observability.

FINAL REQUIREMENT
ZENO should feel like a complete AI operating environment, not merely a
chatbot: MODEL → PREPROCESSOR → PIPELINE → INFERENCE → MEMORY → TOOLS →
AGENT → UI as separate modules that evolve independently. Adding a new
model must not require rebuilding the app; adding a modality must not
require rewriting the conversation engine; changing the backend must not
change the UX.
