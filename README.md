# 🧠 AI Browser Mentor

> A RAG-powered Chrome extension that understands the webpage you're currently viewing.

AI Browser Mentor is an AI-powered browser assistant that allows users to ask questions about webpages in natural language.

Instead of sending an entire webpage directly to an LLM, the system extracts and structures webpage content, converts it into embeddings, retrieves the most relevant context using FAISS, and generates a grounded response using Groq.

---

## ✨ Features

- 🧠 Retrieval-Augmented Generation (RAG)
- 🔍 Webpage content extraction
- 📚 Semantic search using FAISS
- ⚡ FastEmbed-based embeddings
- 🤖 Groq-powered LLM responses
- 🖼️ Image extraction and analysis
- 🔗 Link and interactive-element analysis
- 🛡️ Suspicious-link detection
- 📑 Section-aware webpage understanding
- 🌐 Chrome Extension interface
- ☁️ Deployed FastAPI backend

---

## 🎬 Demo

> Add your demo GIF here.

---

## 🏗️ Architecture

```text
                     ┌──────────────────────┐
                     │      Web Browser     │
                     │                      │
                     │  AI Browser Mentor   │
                     └──────────┬───────────┘
                                │
                                │ HTTPS
                                ▼
                     ┌──────────────────────┐
                     │      FastAPI         │
                     │      Backend         │
                     │      Render          │
                     └──────────┬───────────┘
                                │
                    ┌───────────┴───────────┐
                    │                       │
                    ▼                       ▼
             ┌──────────────┐       ┌──────────────┐
             │   FastEmbed  │       │     FAISS    │
             │  Embeddings  │──────▶│ Vector Store │
             └──────────────┘       └───────┬──────┘
                                            │
                                            │ Relevant
                                            │ Context
                                            ▼
                                  ┌──────────────────┐
                                  │     Groq LLM     │
                                  │   GPT-OSS 20B    │
                                  └────────┬─────────┘
                                           │
                                           ▼
                                    Grounded Answer
