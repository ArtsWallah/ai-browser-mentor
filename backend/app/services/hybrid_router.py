# ============================================================
# AI BROWSER MENTOR - HYBRID AI ENGINE & PRIVACY ROUTER
# Phase 4: Model Registry, Privacy Enforcement & Multi-Provider Routing
# ============================================================

import os
from typing import Any, Callable
import httpx
from dotenv import load_dotenv

from app.schemas import ModelCapabilityInfo, ModelRegistryResponse

load_dotenv()

# Privacy Modes
PRIVACY_HYBRID = "hybrid"
PRIVACY_LOCAL_ONLY = "local_only"
PRIVACY_CLOUD = "cloud"
VALID_PRIVACY_MODES = {PRIVACY_HYBRID, PRIVACY_LOCAL_ONLY, PRIVACY_CLOUD}

# Environment Configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11434")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "llama3")


def normalize_privacy_mode(mode: str | None) -> str:
    """Normalize user-requested privacy mode with safe fallback to hybrid."""
    if not mode:
        return PRIVACY_HYBRID
    m = mode.strip().lower()
    if m in ("local", "local_only", "local-only", "offline"):
        return PRIVACY_LOCAL_ONLY
    if m in ("cloud", "remote"):
        return PRIVACY_CLOUD
    if m in ("hybrid", "auto"):
        return PRIVACY_HYBRID
    return PRIVACY_HYBRID


async def probe_local_llm(base_url: str = LOCAL_LLM_URL, timeout: float = 0.6) -> tuple[bool, str, list[str]]:
    """
    Probes whether a local LLM server (e.g. Ollama or local OpenAI-compatible endpoint)
    is actively running. Returns (is_available, status_message, list_of_models).
    """
    clean_url = base_url.rstrip("/")
    # 1. Try Ollama tags endpoint
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{clean_url}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
                return True, f"Ollama is running with {len(models)} model(s) installed.", models
    except Exception:
        pass

    # 2. Try OpenAI-compatible /v1/models endpoint (LM Studio, LocalAI, Jan, etc.)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            v1_url = clean_url if clean_url.endswith("/v1") else f"{clean_url}/v1"
            resp = await client.get(f"{v1_url}/models")
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
                return True, f"Local OpenAI-compatible server active with {len(models)} model(s).", models
    except Exception:
        pass

    return False, f"Local LLM service offline at {clean_url}. Start Ollama or LM Studio for full local generative models.", []


async def get_active_model_registry(current_privacy_mode: str = PRIVACY_HYBRID) -> ModelRegistryResponse:
    """
    Inspects actual runtime model availability and builds a verified registry.
    Never advertises unavailable or unconfigured models as ready.
    """
    pm = normalize_privacy_mode(current_privacy_mode)
    models: list[ModelCapabilityInfo] = []

    # 1. Local Deterministic NLP Engine
    models.append(ModelCapabilityInfo(
        id="local-deterministic-nlp",
        name="Deterministic Extractive NLP Engine",
        provider="local_deterministic",
        is_local=True,
        supported_tasks=[
            "summarize_page",
            "extract_page_information",
            "inspect_links",
            "answer_page_question",
            "explain_page_content",
            "compare_provided_content",
            "workspace_query",
            "workspace_compare"
        ],
        is_configured=True,
        is_available=True,
        status_message="Ready (runs in-process, zero cloud network latency, 100% private)",
        max_context_chars=50000,
        privacy_level="local_only"
    ))

    # 2. Local ScamShield Tactic Classifier
    from app.services.security_service import SCAMSHIELD_AVAILABLE
    models.append(ModelCapabilityInfo(
        id="local-scamshield-classifier",
        name="ScamShield AI Tactic Classifier (Scikit-Learn Ensemble)",
        provider="local_scamshield",
        is_local=True,
        supported_tasks=["analyze_selected_text", "scam_classification"],
        is_configured=SCAMSHIELD_AVAILABLE,
        is_available=SCAMSHIELD_AVAILABLE,
        status_message="Ready (local ML models for fraud tactic detection)" if SCAMSHIELD_AVAILABLE else "Model file missing or unconfigured.",
        max_context_chars=15000,
        privacy_level="local_only"
    ))

    # 3. Local FastEmbed ONNX Embeddings
    models.append(ModelCapabilityInfo(
        id="local-fastembed-minilm",
        name="FastEmbed ONNX (all-MiniLM-L6-v2)",
        provider="local_fastembed",
        is_local=True,
        supported_tasks=["embeddings", "semantic_search", "vector_indexing"],
        is_configured=True,
        is_available=True,
        status_message="Ready (local vector embeddings without external API calls)",
        max_context_chars=512,
        privacy_level="local_only"
    ))

    # 4. Local LLM Service (Ollama / LocalAI / LM Studio)
    local_llm_up, local_msg, installed_models = await probe_local_llm(LOCAL_LLM_URL)
    active_local_model = installed_models[0] if installed_models else LOCAL_LLM_MODEL
    models.append(ModelCapabilityInfo(
        id="local-llm-service",
        name=f"Local LLM ({active_local_model})" if local_llm_up else "Local LLM Service (Ollama / LM Studio)",
        provider="local_llm",
        is_local=True,
        supported_tasks=["summarize_page", "answer_page_question", "explain_page_content", "workspace_query", "workspace_compare"],
        is_configured=True,
        is_available=local_llm_up,
        status_message=local_msg,
        max_context_chars=8192,
        privacy_level="local_only"
    ))

    # 5. Cloud Groq LLM
    has_groq = bool(GROQ_API_KEY and len(GROQ_API_KEY.strip()) > 8)
    models.append(ModelCapabilityInfo(
        id="groq-cloud-llm",
        name=f"Groq Cloud ({GROQ_MODEL})",
        provider="groq",
        is_local=False,
        supported_tasks=["summarize_page", "answer_page_question", "explain_page_content", "workspace_query", "workspace_compare"],
        is_configured=has_groq,
        is_available=has_groq,
        status_message="Ready (Cloud API, fast Groq LPUs)" if has_groq else "GROQ_API_KEY not configured.",
        max_context_chars=32768,
        privacy_level="cloud"
    ))

    return ModelRegistryResponse(
        success=True,
        active_privacy_modes=["hybrid", "local_only", "cloud"],
        default_privacy_mode=PRIVACY_HYBRID,
        current_privacy_mode=pm,
        models=models,
        local_llm_detected=local_llm_up,
        local_llm_url=LOCAL_LLM_URL,
        cloud_configured=has_groq
    )


async def call_groq_api(
    system_prompt: str,
    user_prompt: str,
    api_key: str = GROQ_API_KEY,
    model: str = GROQ_MODEL,
    temperature: float = 0.1,
    max_tokens: int = 800
) -> str:
    """Call Groq API with robust timeout and validation."""
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    async with httpx.AsyncClient(timeout=35.0) as client:
        resp = await client.post(GROQ_URL, headers=headers, json=payload)

    if resp.status_code != 200:
        raise RuntimeError(f"Groq API error ({resp.status_code}): {resp.text}")

    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("Groq returned empty choices.")

    content = choices[0].get("message", {}).get("content", "")
    content = content.strip() if content else ""
    if not content:
        raise RuntimeError("Groq returned an empty response.")
    return content


async def call_local_llm_api(
    system_prompt: str,
    user_prompt: str,
    base_url: str = LOCAL_LLM_URL,
    model: str = LOCAL_LLM_MODEL,
    temperature: float = 0.1,
    max_tokens: int = 800
) -> str:
    """Call a local Ollama or OpenAI-compatible endpoint."""
    clean_url = base_url.rstrip("/")

    # Try Ollama native generate API
    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.post(
                f"{clean_url}/api/generate",
                json={
                    "model": model,
                    "prompt": f"{system_prompt}\n\nUser: {user_prompt}",
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens}
                }
            )
            if resp.status_code == 200:
                res_json = resp.json()
                return res_json.get("response", "").strip()
    except Exception:
        pass

    # Try OpenAI-compatible chat completions
    v1_url = clean_url if clean_url.endswith("/v1") else f"{clean_url}/v1"
    async with httpx.AsyncClient(timeout=40.0) as client:
        resp = await client.post(
            f"{v1_url}/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": temperature,
                "max_tokens": max_tokens
            }
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Local LLM error ({resp.status_code}): {resp.text}")

    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


async def route_llm_request(
    system_prompt: str,
    user_prompt: str,
    privacy_mode: str = PRIVACY_HYBRID,
    fallback_local_fn: Callable[[], str] | None = None,
    temperature: float = 0.1,
    max_tokens: int = 800
) -> tuple[str, str]:
    """
    Routes an LLM generation request according to the user's privacy mode:
    
    1. 'local_only':
       - STRICT PROHIBITION: Never sends data to cloud / remote APIs.
       - Tries local LLM if online.
       - If no local LLM, calls fallback_local_fn (deterministic local engine).
       - Returns (result_text, provider_label).
       
    2. 'hybrid':
       - Security & classification run locally.
       - Generative tasks use Cloud LLM when configured.
       - Automatically falls back to local LLM or deterministic fallback if cloud fails or offline.
       
    3. 'cloud':
       - Uses Cloud LLM according to remote consent.
       - Fails with explanation if cloud provider is not configured.
    """
    mode = normalize_privacy_mode(privacy_mode)

    # ----------------------------------------------------
    # LOCAL ONLY MODE: Strict Cloud Blocking
    # ----------------------------------------------------
    if mode == PRIVACY_LOCAL_ONLY:
        # Check if a local LLM is running
        local_up, _, installed_models = await probe_local_llm(LOCAL_LLM_URL, timeout=0.4)
        if local_up:
            target_model = installed_models[0] if installed_models else LOCAL_LLM_MODEL
            try:
                ans = await call_local_llm_api(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    base_url=LOCAL_LLM_URL,
                    model=target_model,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                if ans:
                    return ans, f"local (ollama: {target_model})"
            except Exception as e:
                print("Local LLM failed, using deterministic local engine:", repr(e))

        # Use deterministic local in-process fallback
        if fallback_local_fn:
            return fallback_local_fn(), "local (deterministic)"
        
        return (
            "Local-only mode active: Cloud model processing is blocked by your privacy policy. "
            "Start an optional local model (e.g. Ollama) for full generative answers without cloud requests.",
            "local (policy_enforced)"
        )

    # ----------------------------------------------------
    # CLOUD MODE: Cloud Execution Required
    # ----------------------------------------------------
    if mode == PRIVACY_CLOUD:
        if not GROQ_API_KEY:
            raise RuntimeError(
                "Cloud privacy mode was selected, but GROQ_API_KEY is not configured on the backend. "
                "Please configure an API key or switch to 'Hybrid' or 'Local only' mode."
            )
        ans = await call_groq_api(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=GROQ_API_KEY,
            model=GROQ_MODEL,
            temperature=temperature,
            max_tokens=max_tokens
        )
        if not ans or not ans.strip():
            raise RuntimeError("Cloud model returned an empty response.")
        return ans.strip(), f"cloud (groq: {GROQ_MODEL})"

    # ----------------------------------------------------
    # HYBRID MODE: Balanced Intelligent Execution
    # ----------------------------------------------------
    # Try cloud first if configured
    if GROQ_API_KEY:
        try:
            ans = await call_groq_api(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=GROQ_API_KEY,
                model=GROQ_MODEL,
                temperature=temperature,
                max_tokens=max_tokens
            )
            if ans and ans.strip():
                return ans.strip(), f"cloud (groq: {GROQ_MODEL})"
            print("Groq returned empty response in hybrid mode, falling back to local.")
        except Exception as groq_err:
            print("Groq cloud call failed in hybrid mode, falling back to local:", repr(groq_err))

    # Fallback to local LLM if running
    local_up, _, installed_models = await probe_local_llm(LOCAL_LLM_URL, timeout=0.3)
    if local_up:
        target_model = installed_models[0] if installed_models else LOCAL_LLM_MODEL
        try:
            ans = await call_local_llm_api(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                base_url=LOCAL_LLM_URL,
                model=target_model,
                temperature=temperature,
                max_tokens=max_tokens
            )
            if ans and ans.strip():
                return ans.strip(), f"local (ollama: {target_model})"
        except Exception as local_err:
            print("Local LLM failed in hybrid mode, using deterministic engine:", repr(local_err))

    # Ultimate fallback: local deterministic engine
    if fallback_local_fn:
        res = fallback_local_fn()
        if res and res.strip():
            return res.strip(), "local (deterministic)"

    return (
        "An explanation could not be generated from the available content. Please verify that the webpage has finished loading or try selecting a specific paragraph.",
        "fallback (no_model_output)"
    )
