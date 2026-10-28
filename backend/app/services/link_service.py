import re
from typing import Any
from urllib.parse import urlparse, urljoin, unquote


SUSPICIOUS_TLDS = {
    "tk", "ml", "ga", "cf", "gq", "top", "work", "loan", "zip", "mov", "surf", "buzz", "click"
}

POPULAR_DOMAINS = [
    "google.com", "gmail.com", "microsoft.com", "apple.com", "amazon.com",
    "paypal.com", "netflix.com", "facebook.com", "instagram.com", "twitter.com",
    "x.com", "linkedin.com", "github.com", "chase.com", "bankofamerica.com",
    "wellsfargo.com", "citibank.com", "dropbox.com", "slack.com"
]


def normalize_url(url: str, base_url: str = "") -> str:
    """Safely normalize and validate URLs, resolving relative paths."""
    if not url:
        return ""
    clean = url.strip()
    # Resolve relative URLs if base_url is present
    if base_url and (clean.startswith("/") or not clean.startswith(("http://", "https://", "mailto:", "tel:"))):
        try:
            clean = urljoin(base_url, clean)
        except Exception:
            pass
    return clean


def is_ip_address(hostname: str) -> bool:
    return bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", hostname or ""))


def contains_homoglyphs(domain: str) -> bool:
    """Detect punycode or mixed script lookalikes."""
    if domain.startswith("xn--"):
        return True
    # Check for non-ascii characters often used in homoglyph spoofing
    try:
        domain.encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def check_typosquatting(hostname: str) -> str | None:
    """Check if the hostname mimics a popular domain."""
    if not hostname:
        return None
    clean_host = hostname.lower().strip(".")
    for pop in POPULAR_DOMAINS:
        # Authentic domain or legitimate subdomain of the popular domain (e.g. support.google.com)
        if clean_host == pop or clean_host.endswith("." + pop):
            continue

        pop_base = pop.split(".")[0]
        # Deceptive brand name in hyphenated domain (e.g. paypal-security.com, google-verify.net)
        if f"-{pop_base}" in clean_host or f"{pop_base}-" in clean_host:
            return f"Contains brand name '{pop_base}' in hyphenated domain"

        # Character substitutions (e.g. paypa1.com, g00gle.com)
        if any(char in clean_host for char in "01"):
            normalized = clean_host.replace("0", "o").replace("1", "l")
            if normalized == pop or normalized.endswith("." + pop):
                return f"Possible lookalike for '{pop}' (character substitution)"
    return None


def analyze_single_link(url: str, text: str = "", page_url: str = "") -> dict[str, Any]:
    """Inspect a single link for phishing, spoofing, and security risks."""
    norm_url = normalize_url(url, base_url=page_url)
    clean_label = (text or "").strip()

    reasons: list[str] = []
    score = 0  # 0 to 100

    if not norm_url:
        return {
            "url": "",
            "normalized_url": "",
            "text": clean_label,
            "risk": "Unknown",
            "score": 50,
            "reasons": ["Empty or missing link target."],
            "is_external": False
        }

    # Dangerous pseudo-protocols
    lower_url = norm_url.lower()
    if lower_url.startswith("javascript:"):
        return {
            "url": norm_url,
            "normalized_url": norm_url,
            "text": clean_label,
            "risk": "High",
            "score": 95,
            "reasons": ["Dangerous 'javascript:' URI can execute arbitrary script when clicked."],
            "is_external": False
        }

    if lower_url.startswith("data:"):
        return {
            "url": norm_url,
            "normalized_url": norm_url,
            "text": clean_label,
            "risk": "High",
            "score": 85,
            "reasons": ["Data URI link can be used to mask downloads or phishing pages."],
            "is_external": False
        }

    try:
        parsed = urlparse(norm_url)
    except Exception:
        return {
            "url": norm_url,
            "normalized_url": norm_url,
            "text": clean_label,
            "risk": "High",
            "score": 90,
            "reasons": ["Malformed URL structure."],
            "is_external": False
        }

    hostname = (parsed.hostname or "").lower()
    scheme = (parsed.scheme or "").lower()

    if not hostname:
        # Mailto / tel or in-page anchor
        if scheme in ("mailto", "tel"):
            return {
                "url": norm_url,
                "normalized_url": norm_url,
                "text": clean_label,
                "risk": "Low",
                "score": 5,
                "reasons": [f"Direct {scheme} link."],
                "is_external": False
            }
        if norm_url.startswith(("#", "/")) or not norm_url or norm_url == "/":
            return {
                "url": norm_url,
                "normalized_url": norm_url,
                "text": clean_label,
                "risk": "Low",
                "score": 0,
                "reasons": ["Internal page navigation link."],
                "is_external": False
            }
        return {
            "url": norm_url,
            "normalized_url": norm_url,
            "text": clean_label,
            "risk": "Low",
            "score": 0,
            "reasons": ["Relative internal navigation link."],
            "is_external": False
        }

    # 1. Scheme check
    if scheme != "https":
        score += 25
        reasons.append("Unencrypted connection (HTTP instead of HTTPS).")

    # 2. Raw IP address as host
    if is_ip_address(hostname):
        score += 45
        reasons.append("Hostname is a direct IP address, commonly used to bypass domain reputation checks.")

    # 3. Punycode / IDN lookalike
    if contains_homoglyphs(hostname):
        score += 40
        reasons.append(f"Contains Internationalized Domain Name (Punycode: {hostname}), potential homoglyph spoof.")

    # 4. Brand lookalike / typosquatting
    lookalike_warning = check_typosquatting(hostname)
    if lookalike_warning:
        score += 35
        reasons.append(lookalike_warning)

    # 5. Suspicious TLD
    tld = hostname.split(".")[-1] if "." in hostname else ""
    if tld in SUSPICIOUS_TLDS:
        score += 20
        reasons.append(f"Uses unusual or high-abuse top-level domain (.{tld}).")

    # 6. Deceptive anchor text: visible text looks like a URL, but points elsewhere
    if clean_label and ("http://" in clean_label.lower() or "https://" in clean_label.lower() or ".com" in clean_label.lower()):
        try:
            # Extract domain from label
            label_match = re.search(r"https?://([a-zA-Z0-9.-]+)", clean_label)
            if label_match:
                claimed_host = label_match.group(1).lower()
                if claimed_host and claimed_host != hostname:
                    score += 65
                    reasons.append(
                        f"Deceptive link text: Label displays '{claimed_host}' but points to '{hostname}'."
                    )
        except Exception:
            pass

    # 7. Credential / Redirection parameters
    query = unquote(parsed.query).lower()
    if any(param in query for param in ("redirect=", "url=http", "return_to=", "dest=")):
        score += 15
        reasons.append("Open redirect query parameter detected in link target.")

    # Determine risk category
    if score >= 60:
        risk = "High"
    elif score >= 25:
        risk = "Medium"
    else:
        risk = "Low"

    # External check
    page_host = ""
    if page_url:
        try:
            page_host = (urlparse(page_url).hostname or "").lower()
        except Exception:
            pass

    is_external = bool(page_host and hostname and page_host != hostname)

    return {
        "url": norm_url,
        "normalized_url": norm_url,
        "hostname": hostname,
        "text": clean_label,
        "risk": risk,
        "score": score,
        "reasons": reasons if reasons else ["No prominent anomalies detected."],
        "is_external": is_external
    }


def analyze_link_batch(links: list[dict[str, Any]], page_url: str = "") -> dict[str, Any]:
    """Inspect multiple links from a page or request."""
    results = []
    low = 0
    medium = 0
    high = 0
    unknown = 0

    for idx, item in enumerate(links):
        url = item.get("href") or item.get("url") or ""
        text = item.get("text") or item.get("label") or ""
        res = analyze_single_link(url, text, page_url=page_url)
        res["index"] = item.get("index", idx)
        results.append(res)

        r = res["risk"]
        if r == "High":
            high += 1
        elif r == "Medium":
            medium += 1
        elif r == "Low":
            low += 1
        else:
            unknown += 1

    return {
        "success": True,
        "summary": {
            "total": len(results),
            "low": low,
            "medium": medium,
            "high": high,
            "unknown": unknown
        },
        "results": results
    }
