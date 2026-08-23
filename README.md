# 🧠 AI Browser Mentor

> A RAG-powered Chrome extension that understands the webpage you're currently viewing.

AI Browser Mentor is an AI-powered browser assistant that allows users to ask questions about webpages in natural language.

Instead of sending an entire webpage directly to an LLM, the system extracts and structures webpage content, creates vector embeddings, retrieves the most relevant sections using FAISS, and then sends only relevant context to the LLM.

## 🚀 Live Backend

https://ai-browser-mentor.onrender.com

## ✨ Features

- 🔍 Webpage content extraction
- 🧠 RAG-based question answering
- 📚 Semantic retrieval using FAISS
- ⚡ FastEmbed embeddings
- 🤖 Groq-powered LLM responses
- 🖼️ Image extraction and analysis
- 🔗 Link and interactive-element scanning
- 🛡️ Suspicious-link detection
- 📑 Section-aware webpage understanding
- 🌐 Works with dynamically loaded webpages
- 🔌 Chrome Extension interface
- ☁️ Deployed FastAPI backend

## 🏗️ Architecture

```text
                  ┌─────────────────────┐
                  │    Chrome Browser   │
                  │                     │
                  │  AI Browser Mentor  │
                  └──────────┬──────────┘
                             │
                             │ HTTPS
                             ▼
                  ┌─────────────────────┐
                  │     FastAPI API     │
                  │       Render        │
                  └──────────┬──────────┘
                             │
                 ┌───────────┴───────────┐
                 │                       │
                 ▼                       ▼
          ┌──────────────┐       ┌──────────────┐
          │   FastEmbed  │       │     FAISS    │
          │  Embeddings  │──────▶│ Vector Store │
          └──────────────┘       └───────┬──────┘
                                        │
                                        │ Top-K
                                        │ Context
                                        ▼
                              ┌──────────────────┐
                              │   Groq LLM       │
                              │  GPT-OSS 20B     │
                              └────────┬─────────┘
                                       │
                                       ▼
                                  AI Response
