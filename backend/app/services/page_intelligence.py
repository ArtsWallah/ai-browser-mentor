import re
from typing import Any


def extract_page_outline(page: dict[str, Any]) -> dict[str, Any]:
    """Extract a clean structured representation of the webpage."""
    if not page:
        return {
            "title": "Unavailable",
            "url": "",
            "hostname": "",
            "description": "",
            "reading_time_mins": 0,
            "headings_tree": [],
            "stats": {}
        }

    title = page.get("title", "")
    url = page.get("url", "")
    hostname = page.get("hostname", "")
    description = page.get("description", "")
    word_count = page.get("wordCount", 0) or 0
    headings = page.get("headings", [])
    chunks = page.get("chunks", [])
    links = page.get("links", [])
    images = page.get("images", [])
    interactive = page.get("interactiveElements", [])

    reading_time = max(1, round(word_count / 200)) if word_count else 1

    # Extract distinct sections
    sections = []
    for chunk in chunks:
        h = chunk.get("heading")
        if h and h not in sections:
            sections.append(h)

    return {
        "title": title,
        "url": url,
        "hostname": hostname,
        "description": description,
        "word_count": word_count,
        "reading_time_mins": reading_time,
        "sections": sections[:12],
        "headings": headings[:20],
        "stats": {
            "chunks": len(chunks),
            "links": len(links),
            "images": len(images),
            "interactive_elements": len(interactive)
        }
    }


def deterministic_summary(page: dict[str, Any], max_points: int = 5) -> dict[str, Any]:
    """
    Generate an instant, reliable extractive summary and key points
    without requiring external LLM network calls.
    """
    if not page or not page.get("chunks"):
        return {
            "summary": "No readable content was extracted from this page.",
            "key_points": [],
            "source": "deterministic_fallback"
        }

    title = page.get("title", "this page")
    description = page.get("description", "")
    chunks = page.get("chunks", [])

    # Gather top informative sentences across chunks
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

        # Split into sentences
        sentences = re.split(r"(?<=[.!?])\s+", text)
        for s in sentences:
            s_clean = s.strip()
            if len(s_clean) > 40 and len(s_clean) < 250:
                s_lower = s_clean.lower()
                if s_lower not in seen:
                    seen.add(s_lower)
                    prefix = f"**{heading}**: " if heading and heading.lower() not in s_lower else ""
                    points.append(f"{prefix}{s_clean}")
                    if len(points) >= max_points:
                        break
        if len(points) >= max_points:
            break

    # Construct lead overview
    lead_summary = f"Overview of {title}."
    if description:
        lead_summary = f"{title}: {description}"
    elif points:
        lead_summary = points[0]

    return {
        "summary": lead_summary,
        "key_points": points[:max_points],
        "source": "deterministic_extractive"
    }


def build_safe_context(chunks: list[dict[str, Any]], max_chars: int = 6000) -> str:
    """
    Format retrieved chunks safely inside untrusted delimiters
    to prevent prompt injection.
    """
    context_lines = []
    total = 0

    for idx, c in enumerate(chunks, 1):
        heading = c.get("heading", "")
        text = c.get("text", "")
        formatted = f"--- [Section {idx}: {heading}] ---\n{text}\n"
        if total + len(formatted) > max_chars:
            break
        context_lines.append(formatted)
        total += len(formatted)

    joined = "\n".join(context_lines)
    return f"<untrusted_webpage_content>\n{joined}\n</untrusted_webpage_content>"
