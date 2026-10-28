import re
from typing import Any

from app.schemas import EvidenceItem

# ============================================================
# PAGE STATE PATTERNS (LOADING, OFFLINE, CONNECTION ERRORS)
# ============================================================

LOADING_INDICATOR_PATTERNS = [
    r"this is taking longer than usual",
    r"try reloading the page",
    r"gemini is offline",
    r"loading gmail",
    r"still loading\b",
    r"loading\.\.\.",
    r"please wait while (?:we|the page|it) loads?",
    r"standard view \| load basic html",
    r"redirecting\.\.\.",
    r"working\.\.\.",
    r"hold tight, loading",
    r"please wait\.\.\.",
]

OFFLINE_ERROR_PATTERNS = [
    r"you(?:'re| are) offline\b",
    r"no internet connection\b",
    r"check your (?:network )?connection and try again",
    r"please check your (?:internet|network) connection",
    r"connect to the internet",
    r"err_internet_disconnected",
    r"err_connection_timed_out",
    r"err_name_not_resolved",
    r"temporary error \(500\)",
    r"502 bad gateway",
    r"503 service (?:temporarily )?unavailable",
    r"something went wrong\.? please try again",
    r"an unexpected error occurred",
    r"the server encountered a temporary error and could not complete",
    r"page not responding",
    r"application error: a client-side exception",
]


def detect_page_state(page: dict[str, Any]) -> dict[str, Any]:
    """
    Detect whether the page content primarily consists of loading messages,
    connection errors, offline notices, or retry instructions.

    Returns:
        dict with keys:
            is_loading_or_error: bool
            page_state: "ready" | "loading" | "offline_error"
            reason: str
            detected_phrases: list[str]
            suggestion: str
    """
    if not page:
        return {
            "is_loading_or_error": False,
            "page_state": "ready",
            "reason": "",
            "detected_phrases": [],
            "suggestion": ""
        }

    title = (page.get("title") or "").strip().lower()
    url = (page.get("url") or "").strip().lower()
    text = (page.get("content") or "").strip()
    raw_chunks = page.get("chunks") or []

    # Combine chunk texts if content string was not provided
    if not text and raw_chunks:
        text = " ".join(
            (c.get("text") or "") for c in raw_chunks if isinstance(c, dict)
        ).strip()

    text_lower = text.lower()
    total_len = len(text_lower)

    # 1. Search for indicator matches
    loading_matches: list[str] = []
    for pattern in LOADING_INDICATOR_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            loading_matches.append(match.group(0))

    offline_matches: list[str] = []
    for pattern in OFFLINE_ERROR_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            offline_matches.append(match.group(0))

    # Also inspect title cues
    title_is_loading = any(p in title for p in ["loading", "still loading", "opening...", "redirecting"])
    title_is_offline = any(p in title for p in ["offline", "error", "connection problem", "unavailable"])

    # Filter to substantive chunks
    substantive_chunks = [
        c for c in raw_chunks
        if isinstance(c, dict) and (c.get("text") or "").strip()
    ]
    num_substantive_chunks = len(substantive_chunks)

    is_loading = False
    is_offline = False
    detected_phrases: list[str] = []

    # High-confidence indicators (unambiguous loading / offline screens)
    high_confidence_loading = any(
        phrase in text_lower
        for phrase in [
            "this is taking longer than usual",
            "try reloading the page",
            "gemini is offline",
            "loading gmail",
            "still loading"
        ]
    )

    high_confidence_offline = any(
        phrase in text_lower
        for phrase in [
            "you are offline",
            "you're offline",
            "no internet connection",
            "check your connection and try again",
            "err_internet_disconnected",
            "server unreachable",
            "something went wrong"
        ]
    )

    # Condition A: High-confidence phrase present and page has sparse body text or Gmail URL
    if high_confidence_loading and (total_len < 1200 or num_substantive_chunks <= 3 or "mail.google.com" in url or "gmail" in title):
        is_loading = True
        detected_phrases.extend(loading_matches or ["This is taking longer than usual. Try reloading the page"])

    elif high_confidence_offline and (total_len < 1200 or num_substantive_chunks <= 3 or title_is_offline):
        is_offline = True
        detected_phrases.extend(offline_matches or ["You are offline"])

    # Condition B: Title indicates loading/offline and total text is brief
    elif title_is_loading and (loading_matches or total_len < 600):
        is_loading = True
        detected_phrases.extend(loading_matches or ["Loading..."])

    elif title_is_offline and (offline_matches or total_len < 600):
        is_offline = True
        detected_phrases.extend(offline_matches or ["Offline / Error"])

    # Condition C: Generic indicator matches where text is very short (< 400 chars)
    elif loading_matches and (total_len < 400 or num_substantive_chunks <= 2):
        is_loading = True
        detected_phrases.extend(loading_matches)

    elif offline_matches and (total_len < 400 or num_substantive_chunks <= 2):
        is_offline = True
        detected_phrases.extend(offline_matches)

    # Deduplicate detected phrases
    clean_detected: list[str] = []
    seen_phr: set[str] = set()
    for phr in detected_phrases:
        p_str = phr.strip().capitalize()
        if p_str.lower() not in seen_phr:
            seen_phr.add(p_str.lower())
            clean_detected.append(p_str)

    if is_loading:
        return {
            "is_loading_or_error": True,
            "page_state": "loading",
            "reason": f"Page appears to still be loading ({', '.join(clean_detected[:2])}).",
            "detected_phrases": clean_detected,
            "suggestion": "Reload the page (press F5 or Ctrl+R) and wait for content to finish rendering, then retry extraction."
        }

    if is_offline:
        return {
            "is_loading_or_error": True,
            "page_state": "offline_error",
            "reason": f"Page is offline or encountered a connection error ({', '.join(clean_detected[:2])}).",
            "detected_phrases": clean_detected,
            "suggestion": "Check your internet connection and reload the webpage."
        }

    return {
        "is_loading_or_error": False,
        "page_state": "ready",
        "reason": "Page content is substantive and ready.",
        "detected_phrases": [],
        "suggestion": ""
    }


# ============================================================
# CHUNK FILTERING & DEDUPLICATION
# ============================================================

def filter_and_deduplicate_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Clean chunks by:
    - Filtering out empty headings or sections with no meaningful supporting text.
    - Removing duplicate headings and redundant evidence chunks.
    - Preserving useful headings and their associated text.
    - Preserving legitimate short content (not removing solely because it is short).
    """
    cleaned: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for c in chunks:
        if not isinstance(c, dict):
            continue

        heading = (c.get("heading") or "").strip()
        text = (c.get("text") or "").strip()

        # Filter empty headings and sections with no meaningful supporting text
        if not text:
            continue

        # Redundancy check: deduplicate based on normalized heading + quote snippet
        norm_heading = re.sub(r"\s+", " ", heading.lower())
        norm_text_snippet = re.sub(r"\s+", " ", text[:120].lower())
        dedup_key = f"{norm_heading}:::{norm_text_snippet}"

        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        cleaned.append({
            "heading": heading or "Page Section",
            "text": text,
            "level": c.get("level", 0),
            "type": c.get("type", "section")
        })

    return cleaned


def extract_grounded_evidence(
    chunks: list[dict[str, Any]],
    max_items: int = 4,
    max_quote_len: int = 250
) -> list[EvidenceItem]:
    """
    Produce clean, grounded EvidenceItems from page chunks:
    - Filters empty or meaningless text.
    - Deduplicates identical or near-identical quotes.
    - Preserves short legitimate passages.
    """
    clean_chunks = filter_and_deduplicate_chunks(chunks)
    evidence: list[EvidenceItem] = []
    seen_quotes: set[str] = set()

    for c in clean_chunks:
        text = c["text"]
        quote = text[:max_quote_len].strip()
        if not quote:
            continue

        quote_key = re.sub(r"\s+", " ", quote.lower())
        if quote_key in seen_quotes:
            continue
        seen_quotes.add(quote_key)

        evidence.append(EvidenceItem(
            heading=c["heading"],
            quote=quote,
            relevance_score=0.95
        ))
        if len(evidence) >= max_items:
            break

    return evidence


# ============================================================
# PAGE OUTLINE & DETERMINISTIC SUMMARY
# ============================================================

def extract_page_outline(page: dict[str, Any]) -> dict[str, Any]:
    """Extract a clean structured representation of the webpage."""
    if not page:
        return {
            "title": "Unavailable",
            "url": "",
            "hostname": "",
            "description": "",
            "reading_time_mins": 0,
            "sections": [],
            "headings": [],
            "stats": {}
        }

    title = page.get("title", "")
    url = page.get("url", "")
    hostname = page.get("hostname", "")
    description = page.get("description", "")
    word_count = page.get("wordCount", 0) or 0
    raw_headings = page.get("headings", [])
    raw_chunks = page.get("chunks", [])
    links = page.get("links", [])
    images = page.get("images", [])
    interactive = page.get("interactiveElements", [])

    reading_time = max(1, round(word_count / 200)) if word_count else 1

    # Filter out empty chunks with no text
    valid_chunks = filter_and_deduplicate_chunks(raw_chunks)

    # Extract distinct sections with actual text
    sections = []
    seen_sec = set()
    for chunk in valid_chunks:
        h = chunk.get("heading", "").strip()
        if h and h.lower() not in seen_sec:
            seen_sec.add(h.lower())
            sections.append(h)

    # Clean headings: preserve unique non-empty headings
    clean_headings = []
    seen_head = set()
    for h in raw_headings:
        if isinstance(h, str) and h.strip():
            h_clean = h.strip()
            if h_clean.lower() not in seen_head:
                seen_head.add(h_clean.lower())
                clean_headings.append(h_clean)

    return {
        "title": title,
        "url": url,
        "hostname": hostname,
        "description": description,
        "word_count": word_count,
        "reading_time_mins": reading_time,
        "sections": sections[:12],
        "headings": clean_headings[:20] if clean_headings else sections[:20],
        "stats": {
            "chunks": len(valid_chunks),
            "links": len(links),
            "images": len(images),
            "interactive_elements": len(interactive)
        }
    }


def deterministic_summary(page: dict[str, Any], max_points: int = 5) -> dict[str, Any]:
    """
    Generate an instant, reliable extractive summary and key points
    without requiring external LLM network calls.
    Gracefully handles loading/error states and empty headings.
    """
    if not page:
        return {
            "summary": "No readable content was extracted from this page.",
            "key_points": [],
            "page_state": "empty",
            "source": "deterministic_fallback"
        }

    # First check loading/error state
    state = detect_page_state(page)
    if state["is_loading_or_error"]:
        detected_str = ", ".join(state["detected_phrases"][:2])
        return {
            "summary": f"This page appears to be loading or temporarily unavailable ({detected_str}). Actual content is not yet available to summarize.",
            "key_points": [
                "Page content has not finished loading or is offline.",
                state.get("suggestion", "Reload the page and try again.")
            ],
            "page_state": state["page_state"],
            "source": "page_state_detector"
        }

    raw_chunks = page.get("chunks", [])
    chunks = filter_and_deduplicate_chunks(raw_chunks)
    if not chunks:
        return {
            "summary": "No substantive readable content was found on this page.",
            "key_points": [],
            "page_state": "empty",
            "source": "deterministic_fallback"
        }

    title = page.get("title", "this page")
    description = page.get("description", "")

    # Gather top informative sentences across valid chunks
    points = []
    seen = set()

    if description and len(description) > 30:
        clean_desc = description.strip()
        points.append(clean_desc)
        seen.add(clean_desc.lower())

    for chunk in chunks:
        text = chunk.get("text", "").strip()
        heading = chunk.get("heading", "").strip()
        if not text:
            continue

        sentences = re.split(r"(?<=[.!?])\s+", text)
        for s in sentences:
            s_clean = s.strip()
            # Allow legitimate short sentences (from 15 chars) up to 250 chars
            if 15 <= len(s_clean) < 250:
                s_lower = s_clean.lower()
                if s_lower not in seen:
                    seen.add(s_lower)
                    prefix = f"**{heading}**: " if heading and heading.lower() not in s_lower else ""
                    points.append(f"{prefix}{s_clean}")
                    if len(points) >= max_points:
                        break
        if len(points) >= max_points:
            break

    # If sentence splitting yielded nothing (e.g. short texts without terminal punctuation), use chunk texts directly
    if not points:
        for chunk in chunks[:max_points]:
            t = chunk.get("text", "").strip()
            if t:
                h = chunk.get("heading", "")
                prefix = f"**{h}**: " if h and h.lower() not in t.lower() else ""
                points.append(f"{prefix}{t[:200]}")

    lead_summary = f"Overview of {title}."
    if description:
        lead_summary = f"{title}: {description}"
    elif points:
        lead_summary = points[0]

    return {
        "summary": lead_summary,
        "key_points": points[:max_points],
        "page_state": "ready",
        "source": "deterministic_extractive"
    }


def build_safe_context(chunks: list[dict[str, Any]], max_chars: int = 6000) -> str:
    """
    Format retrieved chunks safely inside untrusted delimiters
    to prevent prompt injection. Filters empty chunks.
    """
    clean_chunks = filter_and_deduplicate_chunks(chunks)
    context_lines = []
    total = 0

    for idx, c in enumerate(clean_chunks, 1):
        heading = c.get("heading", "")
        text = c.get("text", "")
        formatted = f"--- [Section {idx}: {heading}] ---\n{text}\n"
        if total + len(formatted) > max_chars:
            break
        context_lines.append(formatted)
        total += len(formatted)

    joined = "\n".join(context_lines)
    return f"<untrusted_webpage_content>\n{joined}\n</untrusted_webpage_content>"
