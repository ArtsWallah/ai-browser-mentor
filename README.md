# 🧠 AI Browser Mentor — Universal AI Browser Assistant

> A privacy-conscious, universal browser assistant and security analyst powered by FastAPI, RAG, ScamShield ML, and Groq.

AI Browser Mentor elevates browsing with instant webpage intelligence, grounded Q&A, structured page extraction, selected-text explanations, and multi-layered security analysis (detecting phishing, credential harvesting, manipulative urgency language, and deceptive links).

---

## ✨ Capabilities

- 🧠 **Universal Webpage Intelligence**: Summarize pages, extract key takeaways, generate outline structures, and explain complex jargon in plain language (ELI5).
- 🔍 **Grounded Retrieval-Augmented Generation (RAG)**: FastEmbed text embeddings + resilient vector search (FAISS with automatic NumPy cosine similarity fallback).
- 🛡️ **General-Purpose Security Engine**:
  - Scans user-selected text, email messages, or entire pages.
  - Integrates the trained **ScamShield ML model** for detecting fraud/manipulation tactics (urgency, reward lures, authority impersonation).
  - Detects credential requests, form vulnerabilities, and prompt-injection cues.
  - Transparent risk scoring and evidence explanations.
- 🔗 **Link & Domain Inspector**:
  - Safe URL normalization.
  - Deceptive anchor text mismatch detection (e.g. label says `google.com` but link points to an external lookalike).
  - Flags raw IP hostnames, punycode/homoglyph spoofs, and high-abuse TLDs.
- ⚡ **Agentic Intent Router**:
  - Central dispatcher that routes user queries (`summarize_page`, `answer_page_question`, `analyze_page_security`, `inspect_links`, `explain_selection`, etc.).
  - Deterministic fast-path to save tokens and eliminate unnecessary latency.
  - Strict prompt injection hardening (`<untrusted_webpage_content>` delimiter defense).
- ✉️ **Gmail Fraud Analysis**: Retains a specialized, one-click analysis workflow when viewing individual emails in Gmail.
- 🎨 **Modern Extension UX**: Dark navy, purple, and cyan interface with tabbed navigation, live connection health pill, and selection detection.

---

## 🏗️ Architecture

```text
 ┌────────────────────────────────────────────────────────┐
 │                   Chrome Extension                     │
 │  ┌───────────────┐ ┌────────────────┐ ┌─────────────┐  │
 │  │ Ask AI / RAG  │ │ Security Audit │ │ Link Check  │  │
 │  └───────┬───────┘ └────────┬───────┘ └──────┬──────┘  │
 └──────────┼──────────────────┼────────────────┼─────────┘
            │                  │                │
            ▼                  ▼                ▼
 ┌────────────────────────────────────────────────────────┐
 │                    FastAPI Backend                     │
 │                                                        │
 │             ┌───────────────────────────┐              │
 │             │   Central Intent Router   │              │
 │             └─────────────┬─────────────┘              │
 │        ┌──────────────────┼─────────────────┐          │
 │        ▼                  ▼                 ▼          │
 │ ┌─────────────┐    ┌─────────────┐   ┌─────────────┐   │
 │ │ Page Intel  │    │  Security   │   │ Link Engine │   │
 │ │  & Outlines │    │  & ScamML   │   │  & Auditing │   │
 │ └──────┬──────┘    └──────┬──────┘   └─────────────┘   │
 └────────┼──────────────────┼────────────────────────────┘
          │                  │
          ▼                  ▼
   ┌──────────────┐   ┌──────────────┐
   │ FastEmbed &  │   │  ScamShield  │
   │ Vector Store │   │  ML Tactics  │
   └──────┬───────┘   └──────────────┘
          │
          ▼
   ┌──────────────┐
   │   Groq LLM   │
   │ (Grounded)   │
   └──────────────┘
```

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.10+
- Google Chrome (or Chromium-based browser like Brave or Edge)

### 2. Backend Setup

```bash
cd backend

# Create virtual environment if needed
python -m venv .venv
.\.venv\Scripts\activate   # Windows PowerShell
# source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
```

Edit `backend/.env` with your settings:
```env
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-20b
SCAMSHIELD_MODEL_PATH=C:/path/to/models/tfidf_multilabel_baseline.joblib
```

Start the FastAPI backend:
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Verify backend health at: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

### 3. Load the Chrome Extension

1. Open Chrome and navigate to `chrome://extensions/`.
2. Enable **Developer mode** (toggle in top right).
3. Click **Load unpacked**.
4. Select the `extension/` directory from this repository.
5. Pin **AI Browser Mentor** to your Chrome toolbar.

---

## 🧪 Running Tests

The test suite validates intent routing, link inspection, security heuristics, ScamShield model compatibility, vector search, and API endpoints:

```bash
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_backend.py -v
```

---

## 🔒 Privacy & Security Principles

- **Minimal Transmission**: The extension extracts only the active page content needed for user requests. Selecting text triggers selection-only analysis rather than re-transmitting the whole page.
- **Strict Grounding**: System prompts treat all webpage content as untrusted passive data wrapped in isolation tags, preventing prompt injection.
- **Transparent Evidence**: Risk ratings provide clear, itemized rationales rather than arbitrary scores, with explicit disclaimers regarding automated tools.
