# ============================================================
# AI BROWSER MENTOR - BACKEND
# Clean FastAPI + Groq + Grounded Page Retrieval
# ============================================================
from collections import OrderedDict
import hmac
import json
import os
import re
import threading
import uuid
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.services.embedding_service import embed_texts, embed_text
from app.services.vector_store import create_index, search, init_vector_store_dir, cleanup_temporary_vector_store

# ============================================================
# ENVIRONMENT & SECURITY CONFIGURATION
# ============================================================

load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
DEBUG_ACCESS_TOKEN = os.getenv("DEBUG_ACCESS_TOKEN", "").strip()
DEBUG_LOGS = os.getenv("DEBUG_LOGS", "false").lower() in ("true", "1", "yes")
DISCOVERY_ACCESS_TOKEN = os.getenv("DISCOVERY_ACCESS_TOKEN", "").strip()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Rate Limiting Configuration
# Note: "memory://" provides per-worker rate limiting. For multi-worker deployments,
# set RATE_LIMIT_STORAGE_URL to a Redis instance (e.g. redis://user:pass@host:port/0).
DEFAULT_AI_RATE_LIMIT = os.getenv("AI_RATE_LIMIT", "30/minute")
RATE_LIMIT_STORAGE = os.getenv("RATE_LIMIT_STORAGE_URL", "memory://")

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=RATE_LIMIT_STORAGE,
    default_limits=[]
)

# Request Size Limit Configuration (Default: 2 MB)
MAX_REQUEST_BODY_SIZE = int(os.getenv("MAX_REQUEST_BODY_SIZE", str(2 * 1024 * 1024)))

# Maximum In-Memory Pages to retain before LRU eviction
MAX_IN_MEMORY_PAGES = int(os.getenv("MAX_IN_MEMORY_PAGES", "100"))

# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="AI Browser Mentor API",
    version="1.0.0"
)
app.state.limiter = limiter

# Rate limit exception handler
@app.exception_handler(RateLimitExceeded)
async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "success": False,
            "error": "Rate limit exceeded. Too many requests submitted. Please wait before retrying.",
            "detail": str(exc.detail)
        },
        headers={"Retry-After": "60"}
    )

# ============================================================
# REQUEST SIZE LIMIT MIDDLEWARE (HTTP 413)
# ============================================================

class RequestBodyTooLargeException(Exception):
    pass


class RequestSizeLimitMiddleware:
    """
    Pure ASGI middleware enforcing maximum request body size limit.
    Checks Content-Length header first for instant rejection (HTTP 413),
    and counts streaming chunks incrementally without consuming or exhausting the stream.
    """
    def __init__(self, app, max_body_size: int = MAX_REQUEST_BODY_SIZE):
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 1. Header check
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > self.max_body_size:
                    response = JSONResponse(
                        status_code=413,
                        content={
                            "success": False,
                            "error": f"Request entity too large. Maximum allowed body size is {self.max_body_size} bytes ({self.max_body_size // (1024 * 1024)} MB)."
                        }
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass

        # 2. Streaming chunks check
        bytes_received = 0

        async def custom_receive():
            nonlocal bytes_received
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                bytes_received += len(body)
                if bytes_received > self.max_body_size:
                    raise RequestBodyTooLargeException()
            return message

        try:
            await self.app(scope, custom_receive, send)
        except RequestBodyTooLargeException:
            response = JSONResponse(
                status_code=413,
                content={
                    "success": False,
                    "error": f"Request entity too large. Maximum allowed body size is {self.max_body_size} bytes ({self.max_body_size // (1024 * 1024)} MB)."
                }
            )
            await response(scope, receive, send)

app.add_middleware(RequestSizeLimitMiddleware, max_body_size=MAX_REQUEST_BODY_SIZE)

# ============================================================
# CORS CONFIGURATION
# ============================================================

EXTENSION_ID_PATTERN = re.compile(r"^[a-z]{32}$")


def parse_and_validate_extension_ids(*raw_id_strings: str | None) -> list[str]:
    """Extract and validate 32-character lowercase Chrome extension IDs."""
    valid_ids: list[str] = []
    for raw in raw_id_strings:
        if not raw:
            continue
        for item in raw.split(","):
            cleaned = item.strip().lower()
            if EXTENSION_ID_PATTERN.match(cleaned):
                valid_ids.append(cleaned)
    return list(dict.fromkeys(valid_ids))


def build_allowed_origins(
    allowed_origins_raw: str | None = None,
    extension_id_raw: str | None = None,
    allowed_extension_ids_raw: str | None = None,
    allow_localhost: bool = True,
) -> list[str]:
    """
    Construct explicit allowed origins list safely:
    - Parses comma-separated ALLOWED_ORIGINS
    - Adds localhost origins if allow_localhost is True
    - Adds explicitly validated chrome-extension://<id> origins
    - Ignores malformed extension IDs
    """
    origins: list[str] = []
    if allowed_origins_raw:
        origins.extend([o.strip() for o in allowed_origins_raw.split(",") if o.strip()])

    if allow_localhost:
        origins.extend([
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ])

    valid_ext_ids = parse_and_validate_extension_ids(extension_id_raw, allowed_extension_ids_raw)
    for ext_id in valid_ext_ids:
        origins.append(f"chrome-extension://{ext_id}")

    return list(dict.fromkeys(origins))


def resolve_allow_origin_regex(allow_regex_env: str | bool | None, environment: str) -> str | None:
    """
    Determine if arbitrary extension regex is allowed.
    Strictly disabled by default and NEVER permitted in production mode.
    """
    if environment.lower() == "production":
        return None

    if isinstance(allow_regex_env, bool):
        is_allowed = allow_regex_env
    elif isinstance(allow_regex_env, str):
        is_allowed = allow_regex_env.strip().lower() in ("true", "1", "yes")
    else:
        is_allowed = False

    return r"^chrome-extension://[a-z]{32}$" if is_allowed else None


ALLOWED_ORIGINS_RAW = os.getenv("ALLOWED_ORIGINS", "").strip()
EXTENSION_ID = os.getenv("EXTENSION_ID", "").strip()
ALLOWED_EXTENSION_IDS_RAW = os.getenv("ALLOWED_EXTENSION_IDS", "").strip()
ALLOW_LOCALHOST = os.getenv("ALLOW_LOCALHOST", "true").lower() in ("true", "1", "yes")
# Unrestricted extension regex matching is strictly disabled by default.
ALLOW_EXTENSION_REGEX = os.getenv("ALLOW_EXTENSION_REGEX", "false").lower() in ("true", "1", "yes")

allowed_origins = build_allowed_origins(
    allowed_origins_raw=ALLOWED_ORIGINS_RAW,
    extension_id_raw=EXTENSION_ID,
    allowed_extension_ids_raw=ALLOWED_EXTENSION_IDS_RAW,
    allow_localhost=ALLOW_LOCALHOST,
)

allow_origin_regex = resolve_allow_origin_regex(ALLOW_EXTENSION_REGEX, ENVIRONMENT)
has_wildcard = "*" in allowed_origins or not allowed_origins
allow_credentials = False if has_wildcard else True

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if allowed_origins else ["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_origin_regex=allow_origin_regex,
    allow_credentials=allow_credentials,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ============================================================
# BOUNDED IN-MEMORY PAGE STORE (LRU EVICTION)
# ============================================================

class BoundedPageStore:
    """
    Thread-safe, bounded in-memory LRU store for active tab contexts.
    Strictly prevents memory exhaustion across long-running server sessions.
    """
    def __init__(self, max_size: int = MAX_IN_MEMORY_PAGES):
        self.max_size = max(1, max_size)
        self._data: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return self._data[key]
            return default

    def __getitem__(self, key: str) -> dict[str, Any]:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return self._data[key]
            raise KeyError(key)

    def __setitem__(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self._data[key] = value
            else:
                if len(self._data) >= self.max_size:
                    self._data.popitem(last=False)
                self._data[key] = value

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def items(self):
        with self._lock:
            return list(self._data.items())

    def keys(self):
        with self._lock:
            return list(self._data.keys())

    def values(self):
        with self._lock:
            return list(self._data.values())

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

page_store = BoundedPageStore(max_size=MAX_IN_MEMORY_PAGES)


# ============================================================
# REQUEST MODELS
# ============================================================


class PageIngestRequest(BaseModel):
    page_id: str = ""
    title: str = ""
    url: str = ""
    hostname: str = ""
    description: str = ""

    headings: list[str] = Field(
        default_factory=list
    )

    paragraphs: list[str] = Field(
        default_factory=list
    )

    chunks: list[dict[str, Any]] = Field(
        default_factory=list
    )

    links: list[dict[str, Any]] = Field(
        default_factory=list
    )

    images: list[dict[str, Any]] = Field(
        default_factory=list
    )

    interactiveElements: list[dict[str, Any]] = Field(
        default_factory=list
    )

    content: str = ""

    wordCount: int = 0


class AskRequest(BaseModel):
    question: str
    page_id: str
    top_k: int = 5


class SearchRequest(BaseModel):
    query: str
    page_id: str
    top_k: int = 8


class FindElementRequest(BaseModel):
    query: str

    elements: list[dict[str, Any]] = Field(
        default_factory=list
    )


class ScanLinksRequest(BaseModel):
    page_id: str = ""

    links: list[dict[str, Any]] = Field(
        default_factory=list
    )


class HoverCheckRequest(BaseModel):
    url: str
    page_url: str = ""


# ============================================================
# BASIC HELPERS
# ============================================================


def clean_text(value: Any) -> str:
    """
    Convert arbitrary values to clean text.
    """

    if value is None:
        return ""

    text = str(value)

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def normalize_words(text: str) -> set[str]:
    """
    Convert text into normalized words for lightweight
    deterministic retrieval.
    """

    text = clean_text(text).lower()

    words = re.findall(
        r"[a-zA-Z0-9]{3,}",
        text
    )

    return set(words)


def get_page(page_id: str):
    return page_store.get(page_id)


def build_chunk_text(chunk: dict[str, Any]) -> str:
    heading = clean_text(
        chunk.get("heading", "")
    )

    text = clean_text(
        chunk.get("text", "")
    )

    return f"{heading} {text}".strip()


# ============================================================
# GROQ CALL
# ============================================================


async def call_groq(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 700
) -> str:

    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not configured."
        )

    payload = {
        "model": GROQ_MODEL,

        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],

        "temperature": temperature,
        "max_tokens": max_tokens
    }

    headers = {
        "Authorization":
            f"Bearer {GROQ_API_KEY}",

        "Content-Type":
            "application/json"
    }

    async with httpx.AsyncClient(
        timeout=60.0
    ) as client:

        response = await client.post(
            GROQ_URL,
            headers=headers,
            json=payload
        )

    if response.status_code != 200:

        print(
            "GROQ ERROR:",
            response.status_code,
            response.text
        )

        raise RuntimeError(
            f"Groq API error "
            f"{response.status_code}: "
            f"{response.text}"
        )

    data = response.json()

    choices = data.get(
        "choices",
        []
    )

    if not choices:
        raise RuntimeError(
            "Groq returned no choices."
        )

    message = choices[0].get(
        "message",
        {}
    )

    answer = clean_text(
        message.get(
            "content",
            ""
        )
    )

    if not answer:
        raise RuntimeError(
            "Groq returned an empty response."
        )

    return answer


# ============================================================
# RETRIEVAL
# ============================================================


def retrieve_chunks(
    page: dict[str, Any],
    query: str,
    top_k: int = 8
) -> list[dict[str, Any]]:

    chunks = page.get(
        "chunks",
        []
    )

    if not chunks:
        return []

    # --------------------------------------------------------
    # Normalize query
    # --------------------------------------------------------

    query_words = normalize_words(
        query
    )

    if not query_words:
        return chunks[:top_k]

    query_lower = clean_text(
        query
    ).lower()

    # --------------------------------------------------------
    # Stop words
    # --------------------------------------------------------

    stop_words = {
        "what",
        "where",
        "when",
        "who",
        "why",
        "how",
        "is",
        "are",
        "was",
        "were",
        "the",
        "a",
        "an",
        "of",
        "to",
        "for",
        "on",
        "in",
        "this",
        "that",
        "and",
        "or",
        "can",
        "does",
        "do",
        "i",
        "me",
        "my",
        "tell",
        "about",
        "page"
    }

    meaningful_query_words = (
        query_words - stop_words
    )

    if not meaningful_query_words:
        meaningful_query_words = query_words

    # --------------------------------------------------------
    # Score every chunk
    # --------------------------------------------------------

    scored = []

    for index, chunk in enumerate(chunks):

        chunk_text = build_chunk_text(
            chunk
        )

        if not chunk_text:
            continue

        chunk_lower = chunk_text.lower()

        chunk_words = normalize_words(
            chunk_text
        )

        # ----------------------------------------------------
        # 1. Exact word overlap
        # ----------------------------------------------------

        overlap = (
            meaningful_query_words
            .intersection(chunk_words)
        )

        word_score = (
            len(overlap)
            /
            max(
                len(meaningful_query_words),
                1
            )
        )

        # ----------------------------------------------------
        # 2. Exact phrase match
        # ----------------------------------------------------

        phrase_score = 0.0

        if (
            query_lower
            and query_lower in chunk_lower
        ):
            phrase_score = 1.0

        # ----------------------------------------------------
        # 3. Heading relevance
        # ----------------------------------------------------

        heading = clean_text(
            chunk.get(
                "heading",
                ""
            )
        )

        heading_words = normalize_words(
            heading
        )

        heading_overlap = (
            meaningful_query_words
            .intersection(heading_words)
        )

        heading_score = (
            len(heading_overlap)
            /
            max(
                len(meaningful_query_words),
                1
            )
        )

        # ----------------------------------------------------
        # 4. Partial word matching
        # ----------------------------------------------------

        partial_matches = 0

        for query_word in meaningful_query_words:

            if len(query_word) < 4:
                continue

            for chunk_word in chunk_words:

                if (
                    query_word in chunk_word
                    or
                    chunk_word in query_word
                ):
                    partial_matches += 1
                    break

        partial_score = (
            partial_matches
            /
            max(
                len(meaningful_query_words),
                1
            )
        )

        # ----------------------------------------------------
        # 5. Final weighted score
        # ----------------------------------------------------

        score = (
            word_score * 0.45
            +
            heading_score * 0.25
            +
            partial_score * 0.20
            +
            phrase_score * 0.10
        )

        scored.append(
            {
                "score": score,
                "index": index,
                "chunk": chunk
            }
        )

    # --------------------------------------------------------
    # Sort highest relevance first
    # --------------------------------------------------------

    scored.sort(
        key=lambda item:
            item["score"],
        reverse=True
    )

    # --------------------------------------------------------
    # Return only relevant chunks
    # --------------------------------------------------------

    relevant = [
        item["chunk"]
        for item in scored
        if item["score"] > 0
    ]

    return relevant[:top_k]

# ============================================================
# BUILD GROUNDED CONTEXT
# ============================================================


def build_context(
    chunks: list[dict[str, Any]]
) -> str:

    if not chunks:
        return ""

    parts = []

    for index, chunk in enumerate(
        chunks,
        start=1
    ):

        heading = clean_text(
            chunk.get(
                "heading",
                ""
            )
        )

        text = clean_text(
            chunk.get(
                "text",
                ""
            )
        )

        parts.append(
            "\n".join(
                [
                    f"SOURCE {index}",
                    f"SECTION: {heading}",
                    f"CONTENT: {text}"
                ]
            )
        )

    context = "\n\n".join(
        parts
    )

    # Keep the request safely below Groq's token limit.
    return context[:18000]


# ============================================================
# ROOT
# ============================================================


@app.get("/")
def root():

    return {
        "success": True,
        "message":
            "AI Browser Mentor API is running.",
        "version": "1.0.0"
    }


# ============================================================
# HEALTH
# ============================================================


@app.get("/health")
def health():
    from app.services.security_service import SCAMSHIELD_AVAILABLE

    return {
        "success": True,
        "status": "healthy",
        "groq_configured": bool(GROQ_API_KEY),
        "scamshield_configured": SCAMSHIELD_AVAILABLE,
        "model": GROQ_MODEL,
        "pages": len(page_store),
        "capabilities": [
            "summarize_page",
            "answer_page_question",
            "extract_page_information",
            "analyze_selected_text",
            "analyze_page_security",
            "inspect_links",
            "compare_provided_content",
            "scamshield_fraud_tactics"
        ]
    }


# ============================================================
# PAGE INGEST
# ============================================================


@app.post("/page/ingest")
async def ingest_page(
    request: PageIngestRequest
):

    page_id = clean_text(request.page_id)

    if not page_id:
        page_id = str(uuid.uuid4())

    from app.services.page_intelligence import filter_and_deduplicate_chunks, detect_page_state

    clean_chunks = filter_and_deduplicate_chunks(request.chunks)
    state_info = detect_page_state({
        "title": request.title,
        "url": request.url,
        "content": request.content,
        "chunks": request.chunks
    })

    page_store[page_id] = {
        "page_id": page_id,
        "title": request.title,
        "url": request.url,
        "hostname": request.hostname,
        "description": request.description,
        "headings": request.headings,
        "paragraphs": request.paragraphs,
        "chunks": clean_chunks if clean_chunks else request.chunks,
        "raw_chunks": request.chunks,
        "links": request.links,
        "images": request.images,
        "interactiveElements": request.interactiveElements,
        "content": request.content,
        "wordCount": request.wordCount,
        "page_state": state_info["page_state"],
        "is_loading_or_error": state_info["is_loading_or_error"],
        "state_reason": state_info["reason"]
    }
        # ========================================================
    # RAG: CREATE VECTOR INDEX
    # ========================================================

    try:

        chunk_texts = []
        chunks_to_index = clean_chunks if clean_chunks else request.chunks

        for chunk in chunks_to_index:

            if isinstance(chunk, dict):

                text = build_chunk_text(chunk)

            else:

                text = clean_text(chunk)

            if text:
                chunk_texts.append(text)


        if chunk_texts:

            embeddings = embed_texts(
                chunk_texts
            )

            create_index(
                page_id,
                embeddings,
                chunks_to_index
            )

            if DEBUG_LOGS:
                print(
                    f"RAG INDEX CREATED: "
                    f"{len(chunk_texts)} chunks"
                )

        else:

            if DEBUG_LOGS:
                print(
                    "RAG INDEX: NO CHUNKS"
                )


    except Exception as error:

        if DEBUG_LOGS:
            print(
                "RAG INDEX ERROR:",
                repr(error)
            )

    if DEBUG_LOGS:
        print(f"[ingest_page] Page indexed: id={page_id[:8]}... chunks={len(request.chunks)}")

    return {
        "success": True,
        "message": "Page indexed successfully.",
        "page_id": page_id,
        "page_state": state_info["page_state"],
        "is_loading_or_error": state_info["is_loading_or_error"],
        "state_reason": state_info["reason"],
        "title": request.title,
        "chunkCount": len(request.chunks),
        "linkCount": len(request.links),
        "imageCount": len(request.images),
        "interactiveElementCount": len(request.interactiveElements),
        "wordCount": request.wordCount
    }


# ============================================================
# COMPATIBILITY ENDPOINT
# ============================================================


@app.post("/page")
async def receive_page(
    page: dict[str, Any]
):

    page_id = clean_text(
        page.get("page_id", "")
    )

    if not page_id:

        return {
            "success": False,
            "message":
                "page_id is required."
        }

    page_store[page_id] = page

    if DEBUG_LOGS:
        print(f"[receive_page] Page registered: id={page_id[:8]}...")

    return {

        "success": True,

        "message":
            "Page received successfully.",

        "page_id":
            page_id,

        "title":
            page.get(
                "title",
                ""
            ),

        "url":
            page.get(
                "url",
                ""
            ),

        "word_count":
            page.get(
                "wordCount",
                0
            ),

        "chunk_count":
            len(
                page.get(
                    "chunks",
                    []
                )
            ),

        "link_count":
            len(
                page.get(
                    "links",
                    []
                )
            ),

        "interactive_element_count":
            len(
                page.get(
                    "interactiveElements",
                    []
                )
            )
    }


# ============================================================
# SEARCH PAGE
# ============================================================


@app.post("/search")
@limiter.limit(DEFAULT_AI_RATE_LIMIT)
async def search_page(
    request: Request,
    body: SearchRequest
):

    page = get_page(
        body.page_id
    )

    if not page:

        return {
            "success": False,
            "message":
                "No page found. "
                "Read the current page first.",
            "resultCount": 0,
            "results": []
        }

    chunks = retrieve_chunks(
        page,
        body.query,
        body.top_k
    )

    results = []

    for chunk in chunks:

        results.append(
            {
                "score": 1,
                "document": {

                    "page_id":
                        body.page_id,

                    "title":
                        page.get(
                            "title",
                            ""
                        ),

                    "heading":
                        chunk.get(
                            "heading",
                            ""
                        ),

                    "text":
                        chunk.get(
                            "text",
                            ""
                        )
                }
            }
        )

    return {

        "success": True,

        "resultCount":
            len(results),

        "results":
            results
    }
# ============================================================
# ASK MENTOR
# ============================================================

@app.post("/ask")
@limiter.limit(DEFAULT_AI_RATE_LIMIT)
async def ask_mentor(
    request: Request,
    body: AskRequest
):

    question = clean_text(
        body.question
    )

    if not question:

        return {
            "success": False,
            "message":
                "Please enter a question.",
            "answer": "",
            "sources": []
        }


    page = get_page(
        body.page_id
    )

    if not page:

        return {
            "success": False,
            "message":
                "No page found. "
                "Please read the current page first.",
            "answer": "",
            "sources": []
        }


    chunks = page.get(
        "chunks",
        []
    )


    if not chunks:

        return {
            "success": False,
            "message":
                "No readable page content is available.",
            "answer": "",
            "sources": []
        }


    # --------------------------------------------------------
    # SUMMARY DETECTION
    # --------------------------------------------------------

    q_lower = question.lower()

    summary_patterns = [
        "summarize this page",
        "summarise this page",
        "summarize the page",
        "summarise the page",
        "give me a summary",
        "give me an overview",
        "what is this page about",
        "what's this page about",
        "tell me about this page",
        "main points",
        "key points"
    ]

    is_summary = any(
        pattern in q_lower
        for pattern in summary_patterns
    )


    # --------------------------------------------------------
    # RAG RETRIEVAL
    # --------------------------------------------------------

    if is_summary:

        # For summaries, use representative page chunks.
        relevant_chunks = chunks[:8]

    else:

        try:

            # Convert the user's question into an embedding.
            query_embedding = embed_text(
                question
            )

            # Search the FAISS index belonging
            # ONLY to the current webpage.
            rag_results = search(
                body.page_id,
                query_embedding,
                top_k=body.top_k
            )

            # Convert FAISS results back into the
            # chunk format already used by the rest
            # of the backend.
            relevant_chunks = []

            for result in rag_results:

                chunk = result.get(
                    "chunk"
                )

                if not isinstance(
                    chunk,
                    dict
                ):
                    continue

                text = clean_text(
                    chunk.get(
                        "text",
                        ""
                    )
                )

                if not text:
                    continue

                relevant_chunks.append(
                    chunk
                )

            if DEBUG_LOGS:
                print(f"[ask_mentor] RAG retrieved {len(relevant_chunks)} chunks")

        except Exception as error:

            if DEBUG_LOGS:
                print(
                    "RAG RETRIEVAL ERROR:",
                    repr(error)
                )

            # Safe fallback to your existing
            # deterministic retrieval.
            relevant_chunks = retrieve_chunks(
                page,
                question,
                body.top_k
            )

    if DEBUG_LOGS:
        print(f"[ask_mentor] Evaluated {len(relevant_chunks)} candidate chunks")

    if not relevant_chunks:

        return {
            "success": True,
            "answer":
                "I couldn't find information "
                "relevant to that question on this page.",
            "sources": []
        }

    context = build_context(
        relevant_chunks
    )


    # --------------------------------------------------------
    # GROUNDED SYSTEM PROMPT
    # --------------------------------------------------------

    system_prompt = """
You are AI Browser Mentor.

Your job is to answer questions about the
webpage currently being viewed by the user.

STRICT GROUNDING RULES:

1. Use ONLY the webpage context supplied
   in the user message.

2. Do NOT use your general world knowledge
   to fill missing information.

3. Do NOT invent facts, names, dates,
   numbers, links, instructions, or events.

4. If the webpage context does not contain
   enough information to answer the question,
   say exactly:

   "I couldn't find that information on this page."

5. You may make a very small inference only
   when it is directly and obviously supported
   by the provided webpage text.

6. Never claim that you clicked, opened,
   visited, verified, or interacted with
   something unless the browser explicitly
   reports that action.

7. For navigation questions, explain what
   visible element on the page the user should
   use.

8. Keep answers concise but useful.

9. Do not mention prompts, retrieval,
   context windows, models, APIs, or internal
   implementation.

10. If multiple pieces of webpage evidence
    disagree, say that the page contains
    conflicting information instead of choosing
    one arbitrarily.
"""


    # --------------------------------------------------------
    # TASK
    # --------------------------------------------------------

    if is_summary:

        task = """
Create a concise summary of the current webpage.

Include:
- what the page is about
- the major sections
- the most important information
- useful details a reader should know

Only use information supported by the webpage.
"""

    else:

        task = """
Answer the user's question directly.

If the question asks how to use or navigate
the webpage, explain the relevant visible
controls, sections, links, buttons, or forms
from the supplied page information.

If the requested information is not supported
by the webpage context, say that you could not
find it on this page.
"""


    # --------------------------------------------------------
    # FINAL USER PROMPT
    # --------------------------------------------------------

    user_prompt = f"""
TASK:

{task}

USER QUESTION:

{question}

WEBPAGE TITLE:

{clean_text(page.get("title", ""))}

WEBPAGE URL:

{clean_text(page.get("url", ""))}

WEBPAGE CONTEXT:

{context}
"""


    # --------------------------------------------------------
    # CALL GROQ
    # --------------------------------------------------------

    try:

        answer = await call_groq(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.05,
            max_tokens=700
        )

    except (OSError, ValueError, RuntimeError) as error:

        print(
            "ASK MENTOR ERROR:",
            error
        )

        return {
            "success": False,

            "message":
                "The AI service could not "
                "answer the question.",

            "answer": "",

            "sources": []
        }


    # --------------------------------------------------------
    # SOURCES
    # --------------------------------------------------------

    sources = []

    for chunk in relevant_chunks:

        sources.append(
            {
                "heading":
                    clean_text(
                        chunk.get(
                            "heading",
                            ""
                        )
                    ),

                "text":
                    clean_text(
                        chunk.get(
                            "text",
                            ""
                        )
                    )
            }
        )


    return {

        "success": True,

        "answer":
            answer,

        "provider":
            "groq",

        "sources":
            sources
    }


# ============================================================
# FIND ELEMENT
# ============================================================

@app.post("/find-element")
async def find_element(
    request: FindElementRequest
):

    elements = request.elements

    query = clean_text(
        request.query
    )


    if not query:

        return {
            "success": False,
            "message":
                "Search query is empty.",
            "elementIndex":
                None
        }


    if not elements:

        return {
            "success": False,
            "message":
                "No interactive elements "
                "were found on this page.",
            "elementIndex":
                None
        }


    # --------------------------------------------------------
    # First use deterministic matching.
    #
    # This is intentionally done before the LLM.
    # For simple requests like "login" or
    # "search box", deterministic matching is
    # safer and faster.
    # --------------------------------------------------------

    query_words = normalize_words(
        query
    )


    candidates = []


    for element in elements:

        text_parts = [

            clean_text(
                element.get(
                    "text",
                    ""
                )
            ),

            clean_text(
                element.get(
                    "label",
                    ""
                )
            ),

            clean_text(
                element.get(
                    "ariaLabel",
                    ""
                )
            ),

            clean_text(
                element.get(
                    "placeholder",
                    ""
                )
            ),

            clean_text(
                element.get(
                    "title",
                    ""
                )
            ),

            clean_text(
                element.get(
                    "href",
                    ""
                )
            )
        ]


        searchable = " ".join(
                text_parts
            )


        searchable_words = normalize_words(
                searchable
            )


        overlap = query_words.intersection(
                searchable_words
            )


        score = len(overlap)


        # Exact phrase bonus.
        if (
            query.lower()
            in searchable.lower()
        ):

            score += 5


        # Semantic words.
        if (
            "search" in query_words
            and (
                "search" in
                searchable.lower()
                or
                "query" in
                searchable.lower()
            )
        ):

            score += 3


        if (
            (
                "login" in query_words
                or "signin" in query_words
                or "sign" in query_words
            )
            and any(
                word in
                searchable.lower()
                for word in [
                    "login",
                    "sign in",
                    "signin",
                    "log in"
                ]
            )
        ):

            score += 4


        candidates.append(
            {
                "score":
                    score,

                "element":
                    element
            }
        )


    candidates.sort(
        key=lambda x:
            x["score"],
        reverse=True
    )


    best = candidates[0] if candidates else None


    # --------------------------------------------------------
    # Strong deterministic match
    # --------------------------------------------------------

    if (
        best
        and best["score"] >= 5
    ):

        selected = best["element"]

        return {

            "success":
                True,

            "elementIndex":
                selected.get(
                    "index"
                ),

            "reason":
                "Matched the requested "
                "page element.",

            "element":
                selected
        }


    # --------------------------------------------------------
    # LLM fallback
    #
    # Only the page's actual elements are
    # supplied to the model.
    # --------------------------------------------------------

    compact = []


    for element in elements[:300]:

        compact.append(
            {
                "index":
                    element.get(
                        "index"
                    ),

                "tag":
                    element.get(
                        "tag",
                        element.get(
                            "tagName",
                            ""
                        )
                    ),

                "text":
                    clean_text(
                        element.get(
                            "text",
                            element.get(
                                "label",
                                ""
                            )
                        )
                    ),

                "role":
                    clean_text(
                        element.get(
                            "role",
                            ""
                        )
                    ),

                "ariaLabel":
                    clean_text(
                        element.get(
                            "ariaLabel",
                            ""
                        )
                    ),

                "placeholder":
                    clean_text(
                        element.get(
                            "placeholder",
                            ""
                        )
                    ),

                "href":
                    clean_text(
                        element.get(
                            "href",
                            ""
                        )
                    )
            }
        )


    navigation_prompt = f"""
You are a webpage navigation assistant.

The user wants to find something on the
current webpage.

USER REQUEST:

{query}

AVAILABLE PAGE ELEMENTS:

{json.dumps(
    compact,
    ensure_ascii=False
)}

Return ONLY valid JSON:

{{
  "elementIndex": number or null,
  "reason": "short explanation"
}}

Rules:

1. elementIndex must exactly match an
   element index in the provided list.

2. Never invent an element.

3. Prefer semantic meaning.

4. If no element reasonably matches,
   return null.

5. Do not return markdown.
"""


    try:

        raw = await call_groq(
                system_prompt=(
                    "You identify webpage elements "
                    "using only the supplied list. "
                    "Never invent elements."
                ),

                user_prompt=navigation_prompt,

                temperature=0.0,

                max_tokens=250
            )


        cleaned = raw.strip()


        if cleaned.startswith(
            "```"
        ):

            cleaned = re.sub(
                r"^```(?:json)?",
                "",
                cleaned
            )

            cleaned = re.sub(
                r"```$",
                "",
                cleaned
            )

            cleaned = cleaned.strip()


        result = json.loads(
                cleaned
            )


        selected_index = result.get(
                "elementIndex"
            )


        reason = clean_text(
                result.get(
                    "reason",
                    ""
                )
            )


        valid_indexes = {
            element.get(
                "index"
            )
            for element in elements
        }


        if (
            selected_index is None
            or
            selected_index not in
            valid_indexes
        ):

            return {

                "success":
                    False,

                "message":
                    reason
                    or
                    "No matching element found.",

                "elementIndex":
                    None,

                "reason":
                    reason
            }


        selected = next(
                (
                    e
                    for e in elements
                    if e.get("index")
                    == selected_index
                ),
                None
            )


        return {

            "success":
                True,

            "elementIndex":
                selected_index,

            "reason":
                reason
                or
                "Matching element found.",

            "element":
                selected
        }


    except (OSError, ValueError, RuntimeError) as error:

        print(
            "FIND ELEMENT ERROR:",
            error
        )

        return {

            "success":
                False,

            "message":
                "I could not confidently "
                "identify that element.",

            "elementIndex":
                None
        }


# ============================================================
# LINK RISK ANALYSIS
# ============================================================

TRUSTED_DOMAINS = {

    "wikipedia.org",
    "wikimedia.org",
    "google.com",
    "github.com",
    "microsoft.com",
    "apple.com",
    "amazon.com",
    "openai.com",
    "mozilla.org",
    "python.org",
    "npmjs.com",
    "stackoverflow.com",
    "linkedin.com",
    "youtube.com"
}


SUSPICIOUS_TERMS = [

    "login",
    "signin",
    "verify",
    "verification",
    "password",
    "wallet",
    "payment",
    "billing",
    "recover",
    "unlock",
    "authenticate",
    "credential",
    "gift",
    "prize"
]


def hostname_is_trusted(
    hostname: str
) -> bool:

    hostname = hostname.lower().strip(
            "."
        )

    return any(
        hostname == domain
        or hostname.endswith(
            "." + domain
        )
        for domain in TRUSTED_DOMAINS
    )


def analyze_link(
    url: str,
    text: str = ""
) -> dict[str, Any]:

    from urllib.parse import urlparse

    url = clean_text(url)

    text = clean_text(text)


    result = {

        "url":
            url,

        "text":
            text,

        "risk":
            "Low",

        "score":
            0,

        "reasons":
            []
    }


    if not url:

        result["risk"] = "Unknown"

        result["score"] = 100

        result["reasons"].append(
            "The link does not contain a URL."
        )

        return result


    try:

        parsed = urlparse(url)

    except ValueError:

        result["risk"] = "High"

        result["score"] = 100

        result["reasons"].append(
            "Malformed URL."
        )

        return result


    hostname = (
            parsed.hostname
            or
            ""
        ).lower()


    if not hostname:

        result["risk"] = "Unknown"

        result["score"] = 80

        result["reasons"].append(
            "The URL does not have a recognizable hostname."
        )

        return result


    # --------------------------------------------------------
    # HTTPS
    # --------------------------------------------------------

    if (
        parsed.scheme.lower()
        !=
        "https"
    ):

        result["score"] += 20

        result["reasons"].append(
            "The link does not use HTTPS."
        )


    # --------------------------------------------------------
    # Raw IP
    # --------------------------------------------------------

    if re.fullmatch(
        r"\d{1,3}(?:\.\d{1,3}){3}",
        hostname
    ):

        result["score"] += 25

        result["reasons"].append(
            "The link uses a raw IP address."
        )


    # --------------------------------------------------------
    # Punycode
    # --------------------------------------------------------

    if "xn--" in hostname:

        result["score"] += 30

        result["reasons"].append(
            "The domain uses punycode."
        )


    # --------------------------------------------------------
    # Credential pattern
    # --------------------------------------------------------

    if (
        parsed.username
        or
        parsed.password
        or
        "@" in url
    ):

        result["score"] += 30

        result["reasons"].append(
            "The URL contains a credential-like pattern."
        )


    # --------------------------------------------------------
    # Suspicious path/query words
    # --------------------------------------------------------

    path = (
            parsed.path
            +
            " "
            +
            parsed.query
        ).lower()


    matched_terms = [

        term
        for term in SUSPICIOUS_TERMS
        if term in path
    ]


    if matched_terms:

        result["score"] += 15

        result["reasons"].append(
            "The URL contains security-sensitive terms: "
            +
            ", ".join(
                matched_terms[:5]
            )
        )


    # --------------------------------------------------------
    # Very deep subdomain
    # --------------------------------------------------------

    if (
        len(
            hostname.split(".")
        )
        >=
        5
    ):

        result["score"] += 15

        result["reasons"].append(
            "The hostname contains many subdomains."
        )


    # --------------------------------------------------------
    # Trusted-domain adjustment
    #
    # Important:
    # A trusted domain does NOT automatically
    # make every URL safe.
    # It only lowers heuristic suspicion.
    # --------------------------------------------------------

    if hostname_is_trusted(
        hostname
    ):

        result["score"] = max(
            0,
            result["score"] - 25
        )


        result["reasons"].append(
            "The hostname matches a commonly trusted domain."
        )


    # --------------------------------------------------------
    # Classification
    # --------------------------------------------------------

    if result["score"] >= 60:

        result["risk"] = "High"

    elif result["score"] >= 25:

        result["risk"] = "Medium"

    else:

        result["risk"] = "Low"


    return result


# ============================================================
# SCAN LINKS
# ============================================================

@app.post("/scan-links")
async def scan_links(
    request: ScanLinksRequest
):

    links = request.links


    if not links:

        page = None

        if request.page_id:

            page = get_page(
                    request.page_id
                )


        if page:

            links = page.get(
                    "links",
                    []
                )


    results = []


    low = 0
    medium = 0
    high = 0
    unknown = 0


    for index, link in enumerate(
        links
    ):

        url = clean_text(
                link.get(
                    "href",
                    link.get(
                        "url",
                        ""
                    )
                )
            )


        text = clean_text(
                link.get(
                    "text",
                    link.get(
                        "label",
                        ""
                    )
                )
            )


        result = analyze_link(
                url,
                text
            )


        result["index"] = link.get(
                "index",
                index
            )


        results.append(
            result
        )


        risk = result["risk"]


        if risk == "High":

            high += 1

        elif risk == "Medium":

            medium += 1

        elif risk == "Low":

            low += 1

        else:

            unknown += 1


    return {

        "success":
            True,

        "summary": {

            "total":
                len(results),

            "low":
                low,

            "medium":
                medium,

            "high":
                high,

            "unknown":
                unknown
        },

        "results":
            results
    }


# ============================================================
# HOVER CHECK
# ============================================================

@app.post("/hover-check")
@limiter.limit(DEFAULT_AI_RATE_LIMIT)
async def hover_check(
    request: Request,
    body: HoverCheckRequest
):

    if not clean_text(
        body.url
    ):

        return {

            "success":
                False,

            "message":
                "URL is required."
        }


    result = analyze_link(
            body.url
        )


    return {

        "success":
            True,

        "result":
            result
    }


# ============================================================
# DEBUG PAGE STORE (PROTECTED IN PRODUCTION)
# ============================================================

def _verify_debug_access(x_debug_token: str | None = None):
    """
    Guards internal debug inspection endpoints.
    In production mode, access is strictly forbidden unless authorized via X-Debug-Token header.
    """
    if ENVIRONMENT == "production":
        if not DEBUG_ACCESS_TOKEN or x_debug_token != DEBUG_ACCESS_TOKEN:
            raise HTTPException(
                status_code=403,
                detail="Debug endpoints are disabled in production mode."
            )


@app.get("/debug/pages")
def debug_pages(x_debug_token: str | None = Header(None, alias="X-Debug-Token")):
    _verify_debug_access(x_debug_token)
    pages = []
    for page_id, page in page_store.items():
        pages.append({
            "page_id": page_id,
            "title": page.get("title", ""),
            "url": page.get("url", ""),
            "chunks": len(page.get("chunks", [])),
            "links": len(page.get("links", [])),
            "images": len(page.get("images", [])),
            "interactiveElements": len(page.get("interactiveElements", []))
        })

    return {
        "success": True,
        "pageCount": len(page_store),
        "pages": pages
    }


# ============================================================
# DEBUG SINGLE PAGE (PROTECTED IN PRODUCTION)
# ============================================================

@app.get("/debug/pages/{page_id}")
def debug_page(page_id: str, x_debug_token: str | None = Header(None, alias="X-Debug-Token")):
    _verify_debug_access(x_debug_token)
    page = get_page(page_id)
    if not page:
        return {
            "success": False,
            "message": "Page not found."
        }

    return {
        "success": True,
        "page": page
    }


# ============================================================
# STARTUP & SAFE CLEANUP
# ============================================================

@app.on_event("startup")
async def startup():
    # Safely ensure vector store directory exists
    init_vector_store_dir()

    # Clean up stale temporary vector store files older than retention policy
    retention_hours = int(os.getenv("VECTOR_STORE_RETENTION_HOURS", "24"))
    try:
        purged = cleanup_temporary_vector_store(max_age_hours=retention_hours)
        if purged > 0 and (DEBUG_LOGS or ENVIRONMENT != "production"):
            print(f"[vector_store] Cleaned up {purged} stale temporary vector store files.")
    except Exception as e:
        if DEBUG_LOGS:
            print(f"[vector_store] Startup cleanup note: {e}")

    if DEBUG_LOGS or ENVIRONMENT != "production":
        print("\n==============================================")
        print("AI BROWSER MENTOR BACKEND (HARDENED)")
        print("==============================================")
        print(f"Environment:        {ENVIRONMENT}")
        print(f"Groq Model:         {GROQ_MODEL} (configured: {bool(GROQ_API_KEY)})")
        print(f"AI Rate Limit:      {DEFAULT_AI_RATE_LIMIT} (storage: {RATE_LIMIT_STORAGE})")
        print(f"Max Request Body:   {MAX_REQUEST_BODY_SIZE} bytes")
        print(f"Max In-Memory Pages:{MAX_IN_MEMORY_PAGES}")
        print("==============================================\n")
# ============================================================
# SCAMSHIELD TEXT ANALYSIS
# ============================================================

from app.scamshield_service import analyze_message
from app.schemas import ScamShieldAnalysisResponse


class ScamShieldTextRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)


@app.post("/scamshield/analyze-text", response_model=ScamShieldAnalysisResponse)
@limiter.limit(DEFAULT_AI_RATE_LIMIT)
def scamshield_analyze_text(request: Request, body: ScamShieldTextRequest):
    message = body.message.strip()

    if not message:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Message cannot be blank.")

    try:
        return analyze_message(message)
    except ValueError as error:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=str(error)) from error


# ============================================================
# UNIVERSAL ASSISTANT & ORCHESTRATOR
# ============================================================

from app.services.intent_router import execute_tool_request, execute_command
from app.services.security_service import analyze_security_text, analyze_page_security
from app.schemas import (
    AssistantQueryRequest,
    SecurityTextRequest,
    PageSummaryRequest,
    CommandExecutionRequest,
    CommandExecutionResponse
)


@app.post("/command/execute", response_model=CommandExecutionResponse)
@app.post("/assistant/command", response_model=CommandExecutionResponse)
@limiter.limit(DEFAULT_AI_RATE_LIMIT)
async def command_execute_endpoint(request: Request, body: CommandExecutionRequest):
    """
    Phase 2 & 4 AI Command Center endpoint:
    Accepts natural-language user instruction, gathers page context,
    invokes appropriate registered tool, and returns a verified, structured response
    respecting user privacy settings.
    """
    page = get_page(body.page_id) if body.page_id else None
    return await execute_command(
        instruction=body.instruction,
        page=page,
        selection_text=body.selection_text,
        intent_override=body.intent,
        page_url=body.page_url,
        page_title=body.page_title,
        privacy_mode=body.privacy_mode,
        groq_api_key=GROQ_API_KEY,
        groq_model=GROQ_MODEL
    )


@app.post("/assistant/query")
@limiter.limit(DEFAULT_AI_RATE_LIMIT)
async def assistant_query(request: Request, body: AssistantQueryRequest):
    """
    Central router endpoint for universal queries:
    - Summaries
    - Q&A
    - Security analysis
    - Link inspection
    - Selection explanation
    """
    page = get_page(body.page_id) if body.page_id else None
    return await execute_tool_request(
        query=body.query,
        page=page,
        selection_text=body.selection_text,
        mode=body.mode,
        privacy_mode=body.privacy_mode,
        groq_api_key=GROQ_API_KEY,
        groq_model=GROQ_MODEL
    )


@app.post("/security/analyze-text")
def universal_security_analyze_text(request: SecurityTextRequest):
    """
    General-purpose security analysis for user selections or messages,
    combining ScamShield tactic detection and heuristic indicators.
    """
    from fastapi import HTTPException
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Text cannot be blank.")
    return analyze_security_text(
        text,
        context=request.context,
        disabled_checks=request.disabled_checks
    )


@app.post("/security/analyze-page")
def security_analyze_page_endpoint(request: PageSummaryRequest):
    """
    Complete security audit of an ingested webpage (forms, links, content cues).
    """
    from fastapi import HTTPException
    page = get_page(request.page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found. Please read page first.")
    return analyze_page_security(page, disabled_checks=request.disabled_checks)


@app.post("/page/summary")
@limiter.limit(DEFAULT_AI_RATE_LIMIT)
async def page_summary_endpoint(request: Request, body: PageSummaryRequest):
    """
    Produce structured summary and key points for an ingested webpage.
    """
    from fastapi import HTTPException
    page = get_page(body.page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found. Please read page first.")
    return await execute_tool_request(
        query="Summarize this page with key points",
        page=page,
        mode="summary",
        privacy_mode="hybrid",
        groq_api_key=GROQ_API_KEY,
        groq_model=GROQ_MODEL
    )


# ============================================================
# PHASE 3: RESEARCH WORKSPACE ENDPOINTS
# ============================================================

from app.schemas import (
    WorkspaceQueryRequest,
    WorkspaceQueryResponse,
    WorkspaceCompareRequest,
    WorkspaceCompareResponse
)
from app.services.workspace_service import (
    query_workspace_sources,
    compare_workspace_sources
)


@app.post("/workspace/query", response_model=WorkspaceQueryResponse)
@limiter.limit(DEFAULT_AI_RATE_LIMIT)
async def workspace_query_endpoint(request: Request, body: WorkspaceQueryRequest):
    """
    Phase 3 & 4: Persistent Multi-Tab Research Workspace Query.
    Executes cross-source passage retrieval and synthesizes answers
    with source titles, URLs, and supporting quotes under active privacy policy.
    """
    return await query_workspace_sources(
        request=body,
        groq_api_key=GROQ_API_KEY,
        groq_model=GROQ_MODEL
    )


@app.post("/workspace/compare", response_model=WorkspaceCompareResponse)
@limiter.limit(DEFAULT_AI_RATE_LIMIT)
async def workspace_compare_endpoint(request: Request, body: WorkspaceCompareRequest):
    """
    Phase 3 & 4: Compare saved sources in a research workspace.
    Identifies agreements, disagreements, and unverified claims under active privacy policy.
    """
    return await compare_workspace_sources(
        request=body,
        groq_api_key=GROQ_API_KEY,
        groq_model=GROQ_MODEL
    )


# ============================================================
# PHASE 4: HYBRID AI ENGINE & MODEL REGISTRY ENDPOINTS
# ============================================================

from app.schemas import ModelRegistryResponse
from app.services.hybrid_router import get_active_model_registry


@app.get("/models", response_model=ModelRegistryResponse)
@app.get("/models/status", response_model=ModelRegistryResponse)
async def get_models_endpoint(privacy_mode: str = "hybrid"):
    """
    Phase 4: Inspect active runtime model availability and privacy configuration.
    Returns real, verified local and remote provider statuses without hypothetical listings.
    """
    return await get_active_model_registry(current_privacy_mode=privacy_mode)


# ============================================================
# PHASE 5: EMERGING PATTERN DISCOVERY ENDPOINTS
# ============================================================
# These endpoints are for BATCH RESEARCH USE ONLY.
# They are intentionally separated from the real-time scam analysis
# endpoints so that expensive clustering is NEVER triggered on
# ordinary browser popup requests.
# ============================================================

from app.schemas import (
    DiscoveryRunRequest,
    DiscoveryRunResponse,
    PatternListResponse,
    PatternEntry,
    PatternReviewRequest,
)
_HTTPException = HTTPException

def verify_discovery_access(
    x_discovery_token: str | None = Header(None, alias="X-Discovery-Token"),
    authorization: str | None = Header(None),
):
    """
    Guards batch discovery execution and pattern registry mutation endpoints.
    Requires a valid DISCOVERY_ACCESS_TOKEN via 'X-Discovery-Token' or 'Authorization: Bearer <token>'.
    If DISCOVERY_ACCESS_TOKEN is not configured, endpoints are safely disabled.
    """
    configured_token = os.getenv("DISCOVERY_ACCESS_TOKEN", "").strip() or DISCOVERY_ACCESS_TOKEN
    if not configured_token:
        raise _HTTPException(
            status_code=403,
            detail="Discovery endpoints are disabled because DISCOVERY_ACCESS_TOKEN is not configured.",
        )

    provided_token = x_discovery_token
    if not provided_token and authorization and authorization.startswith("Bearer "):
        provided_token = authorization[7:].strip()

    if not provided_token:
        raise _HTTPException(
            status_code=401,
            detail="Discovery authorization token required.",
        )

    if not hmac.compare_digest(provided_token, configured_token):
        raise _HTTPException(
            status_code=403,
            detail="Invalid discovery authorization token.",
        )


@app.post(
    "/scamshield/discovery/run",
    response_model=DiscoveryRunResponse,
    summary="Run emerging-pattern discovery pipeline (batch research only)",
    tags=["Phase 5 - Discovery"],
    dependencies=[Depends(verify_discovery_access)],
)
@limiter.limit("5/minute")
async def scamshield_discovery_run(request: Request, body: DiscoveryRunRequest):
    """
    Phase 5: Run the emerging social-engineering pattern discovery pipeline.
    For RESEARCH USE ONLY — not triggered on normal browser requests.
    """
    if not body.examples:
        raise _HTTPException(status_code=422, detail="At least one example is required.")

    try:
        from app.services.pattern_discovery import ingest_dicts, run_discovery_pipeline
        from app.services.pattern_registry import PatternRegistry
        from pathlib import Path

        examples = ingest_dicts(body.examples)
        result = run_discovery_pipeline(
            examples,
            min_cluster_size=body.min_cluster_size,
            novelty_threshold=body.novelty_threshold,
            max_rows=body.max_rows,
        )

        result_dict = result.to_dict()
        registry_path = Path(__file__).resolve().parents[1] / "data" / "pattern_registry.json"
        registry = PatternRegistry(registry_path)
        n_imported = registry.import_from_result(result_dict)
        stats = registry.stats()

        return DiscoveryRunResponse(
            success=True,
            n_ingested=result.n_ingested,
            n_deduplicated=result.n_deduplicated,
            n_clusters=len(result.clusters),
            n_noise_points=len(result.noise_points),
            n_high_novelty_candidates=len(result.high_novelty_noise),
            embedding_model=result.embedding_model,
            embedding_available=result.embedding_available,
            algorithm_primary=result.algorithm_primary,
            silhouette_primary=result.silhouette_primary,
            silhouette_baseline=result.silhouette_baseline,
            n_imported_to_registry=n_imported,
            registry_total=stats["total_patterns"],
            limitations=result.limitations,
        )

    except Exception as exc:
        return DiscoveryRunResponse(success=False, limitations=[], error=str(exc))


@app.get(
    "/scamshield/discovery/patterns",
    response_model=PatternListResponse,
    summary="List candidate patterns in the human review registry",
    tags=["Phase 5 - Discovery"],
)
async def scamshield_discovery_list_patterns(
    status: str | None = None,
    sort_by: str = "novelty_score",
):
    """
    Phase 5: List candidate patterns in the pattern registry.
    Optional ?status= filter: pending | known | potentially_novel | benign | inconclusive
    """
    try:
        from app.services.pattern_registry import PatternRegistry
        from pathlib import Path

        registry_path = Path(__file__).resolve().parents[1] / "data" / "pattern_registry.json"
        registry = PatternRegistry(registry_path)
        raw_patterns = registry.list_patterns(status_filter=status, sort_by=sort_by)

        entries = [
            PatternEntry(
                cluster_id=p["cluster_id"],
                n_examples=p["n_examples"],
                novelty_score=p["novelty_score"],
                associated_tactics=p.get("associated_tactics", []),
                tactic_confidence=p.get("tactic_confidence", ""),
                review_status=p.get("review_status", "pending"),
                medoid_message=p.get("medoid", {}).get("message", ""),
                medoid_source=p.get("medoid", {}).get("source", ""),
                shared_ngrams=p.get("shared_ngrams", []),
                limitations=p.get("limitations", []),
                import_timestamp=p.get("import_timestamp", ""),
                source_provenance=p.get("source_provenance", []),
            )
            for p in raw_patterns
        ]

        return PatternListResponse(success=True, total=len(entries), status_filter=status, patterns=entries)

    except Exception as exc:
        raise _HTTPException(status_code=500, detail=str(exc))


@app.post(
    "/scamshield/discovery/review",
    summary="Record a human review decision for a discovered pattern",
    tags=["Phase 5 - Discovery"],
    dependencies=[Depends(verify_discovery_access)],
)
async def scamshield_discovery_review(request: PatternReviewRequest):
    """
    Phase 5: Record a human review decision (no model training is triggered).
    Valid statuses: pending | known | potentially_novel | benign | inconclusive
    """
    from app.services.pattern_registry import PatternRegistry, VALID_STATUSES
    from pathlib import Path

    if request.status not in VALID_STATUSES:
        raise _HTTPException(
            status_code=422,
            detail=f"Invalid status. Must be one of: {sorted(VALID_STATUSES)}",
        )

    registry_path = Path(__file__).resolve().parents[1] / "data" / "pattern_registry.json"
    registry = PatternRegistry(registry_path)

    try:
        updated = registry.review_pattern(
            pattern_id=request.pattern_id,
            status=request.status,
            reviewer=request.reviewer,
            rationale=request.rationale,
        )
        return {
            "success": True,
            "pattern_id": request.pattern_id,
            "new_status": request.status,
            "n_review_history": len(updated.get("review_history", [])),
            "note": "Decision recorded. No model training is triggered by review decisions.",
        }
    except KeyError:
        raise _HTTPException(status_code=404, detail=f"Pattern '{request.pattern_id}' not found.")




