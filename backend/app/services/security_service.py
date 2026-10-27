import re
from typing import Any
from app.services.link_service import analyze_single_link, analyze_link_batch

try:
    from app.scamshield_service import analyze_message
    SCAMSHIELD_AVAILABLE = True
except Exception:
    analyze_message = None
    SCAMSHIELD_AVAILABLE = False


# Security indicator patterns
URGENCY_PATTERNS = [
    r"\b(?:immediate(?:ly)?|urgent(?:ly)?|action required|suspended|freeze|disabled|terminate(?:d)?|24 hours|within \d+ hours)\b",
    r"\b(?:final warning|last notice|act now|expir(?:es|ing) soon|critical alert)\b",
    r"\b(?:legal action|law enforcement|arrest warrant|court notice)\b"
]

CREDENTIAL_PATTERNS = [
    r"\b(?:enter (?:your )?(?:password|pin|passcode|secret key|seed phrase))\b",
    r"\b(?:verify (?:your )?(?:identity|account|credentials|social security|ssn))\b",
    r"\b(?:update (?:your )?payment (?:method|information|details))\b",
    r"\b(?:confirm (?:your )?card number|cvv|bank account)\b"
]

FINANCIAL_LURE_PATTERNS = [
    r"\b(?:won|winner|claim your (?:reward|prize|grant|lottery|refund|settlement))\b",
    r"\b(?:exclusive offer|free gift card|crypto payout|bitcoin giveaway)\b",
    r"\b(?:wire transfer|send money via|western union|gift cards? to pay)\b"
]

IMPERSONATION_PATTERNS = [
    r"\b(?:security team|fraud department|customer support|help desk|account team)\b",
    r"\b(?:official notice from|authorized representative|it administrator)\b"
]

INJECTION_PATTERNS = [
    r"(?:ignore (?:all )?previous instructions|system prompt|bypass filter)",
    r"(?:treat the above as|new persona|developer mode enabled)",
    r"(?:send (?:all|the) (?:passwords|data|cookies|tokens) to)"
]


def evaluate_heuristics(text: str) -> list[dict[str, Any]]:
    """Scan text against known phishing, fraud, and manipulation cues."""
    indicators = []
    text_clean = text.lower()

    # Urgency check
    for pat in URGENCY_PATTERNS:
        match = re.search(pat, text_clean)
        if match:
            indicators.append({
                "type": "urgency",
                "severity": "Medium",
                "label": "High-Pressure / Urgency Language",
                "explanation": f"Found urgent call-to-action ('{match.group(0)}'), often used to rush victims into compliance.",
                "matched": match.group(0)
            })
            break

    # Credential check
    for pat in CREDENTIAL_PATTERNS:
        match = re.search(pat, text_clean)
        if match:
            indicators.append({
                "type": "credential_request",
                "severity": "High",
                "label": "Suspicious Request for Credentials or Sensitive Data",
                "explanation": f"Text requests sensitive credentials ('{match.group(0)}'). Legitimate services rarely ask for credentials via ordinary messages or untrusted pages.",
                "matched": match.group(0)
            })
            break

    # Financial lure check
    for pat in FINANCIAL_LURE_PATTERNS:
        match = re.search(pat, text_clean)
        if match:
            indicators.append({
                "type": "reward_lure",
                "severity": "Medium",
                "label": "Reward or Financial Lure",
                "explanation": f"Text contains an unexpected offer or prize lure ('{match.group(0)}').",
                "matched": match.group(0)
            })
            break

    # Impersonation check
    for pat in IMPERSONATION_PATTERNS:
        match = re.search(pat, text_clean)
        if match:
            indicators.append({
                "type": "authority_impersonation",
                "severity": "Low",
                "label": "Authority / Support Framing",
                "explanation": f"Uses formal support/security authority cues ('{match.group(0)}').",
                "matched": match.group(0)
            })
            break

    # Prompt injection check
    for pat in INJECTION_PATTERNS:
        match = re.search(pat, text_clean)
        if match:
            indicators.append({
                "type": "prompt_injection",
                "severity": "High",
                "label": "Prompt Manipulation / Override Cue",
                "explanation": "Content attempts to override assistant behavior or manipulate instructions.",
                "matched": match.group(0)
            })
            break

    return indicators


def analyze_security_text(text: str, context: str = "selection") -> dict[str, Any]:
    """
    Perform multi-layered security analysis on arbitrary text.
    Combines the trained ScamShield ML model with deterministic heuristic checks.
    """
    clean_text = (text or "").strip()
    if not clean_text:
        return {
            "success": False,
            "message": "No text provided for security analysis.",
            "risk_level": "Unknown",
            "risk_score": 0,
            "indicators": [],
            "scamshield": None,
            "disclaimer": "No text was submitted."
        }

    # 1. ScamShield ML analysis
    scamshield_data = None
    scamshield_tactics = []
    if SCAMSHIELD_AVAILABLE and analyze_message:
        try:
            # Model accepts up to 10000 chars
            scamshield_data = analyze_message(clean_text[:10000])
            if isinstance(scamshield_data, dict):
                scamshield_tactics = scamshield_data.get("detected_tactics", [])
        except Exception as error:
            scamshield_data = {
                "available": False,
                "error": str(error),
                "experimental": True,
                "disclaimer": "ScamShield ML model is currently unavailable."
            }
    else:
        scamshield_data = {
            "available": False,
            "reason": "ScamShield model service is not configured or loaded.",
            "experimental": True,
            "disclaimer": "Heuristic detection active as fallback."
        }

    # 2. Heuristic indicators
    heuristics = evaluate_heuristics(clean_text)

    # 3. Score synthesis
    risk_score = 0
    reasons = []

    # Factor ScamShield ML tactics
    if scamshield_tactics:
        risk_score += min(len(scamshield_tactics) * 25, 60)
        reasons.append(f"ScamShield ML detected {len(scamshield_tactics)} manipulation tactic(s): {', '.join(scamshield_tactics)}.")

    # Factor heuristics
    for ind in heuristics:
        sev = ind.get("severity")
        if sev == "High":
            risk_score += 35
        elif sev == "Medium":
            risk_score += 20
        else:
            risk_score += 10
        reasons.append(f"[{ind.get('label')}] {ind.get('explanation')}")

    risk_score = min(risk_score, 100)

    if risk_score >= 60:
        risk_level = "High Risk"
    elif risk_score >= 25:
        risk_level = "Caution / Suspicious"
    else:
        risk_level = "Low Risk"

    return {
        "success": True,
        "context": context,
        "risk_level": risk_level,
        "risk_score": risk_score,
        "reasons": reasons if reasons else ["No high-confidence phishing or manipulation tactics detected."],
        "indicators": heuristics,
        "scamshield": scamshield_data,
        "disclaimer": (
            "Automated security assessment only. Scores and tactics do not guarantee safety or prove intent. "
            "Never open suspicious links or provide credentials without independent verification."
        )
    }


def analyze_page_security(page: dict[str, Any]) -> dict[str, Any]:
    """Comprehensive security audit of a loaded webpage (content, forms, and links)."""
    if not page:
        return {
            "success": False,
            "message": "No webpage data available to analyze.",
            "risk_level": "Unknown",
            "findings": []
        }

    url = page.get("url", "")
    hostname = page.get("hostname", "")
    content = page.get("content", "")
    links = page.get("links", [])
    interactive = page.get("interactiveElements", [])

    # Text audit
    text_analysis = analyze_security_text(content[:10000], context="page_content")

    # Links audit
    link_analysis = analyze_link_batch(links, page_url=url)
    link_summary = link_analysis.get("summary", {})

    findings = list(text_analysis.get("reasons", []))

    # Form / interactive element checks
    has_password_field = False
    has_unsecured_form = False

    for el in interactive:
        tag = el.get("tag", "").lower()
        itype = el.get("type", "").lower()
        if itype == "password":
            has_password_field = True
            if url.startswith("http://"):
                has_unsecured_form = True

    if has_unsecured_form:
        findings.append("CRITICAL: Password input field found on an unencrypted HTTP connection!")

    if link_summary.get("high", 0) > 0:
        findings.append(f"Found {link_summary['high']} high-risk link(s) on this page.")
    if link_summary.get("medium", 0) > 0:
        findings.append(f"Found {link_summary['medium']} suspicious / medium-risk link(s).")

    # Overall risk calculation
    overall_score = text_analysis.get("risk_score", 0)
    if has_unsecured_form:
        overall_score = max(overall_score, 90)
    if link_summary.get("high", 0) > 0:
        overall_score = max(overall_score, 70)
    elif link_summary.get("medium", 0) > 0:
        overall_score = max(overall_score, 40)

    overall_score = min(overall_score, 100)

    if overall_score >= 60:
        risk_level = "High Risk"
    elif overall_score >= 25:
        risk_level = "Caution / Suspicious"
    else:
        risk_level = "Low Risk"

    return {
        "success": True,
        "page_id": page.get("page_id", ""),
        "title": page.get("title", ""),
        "hostname": hostname,
        "url": url,
        "risk_level": risk_level,
        "risk_score": overall_score,
        "findings": findings if findings else ["Page appears typical; no prominent deceptive elements flagged."],
        "text_analysis": text_analysis,
        "links_summary": link_summary,
        "has_password_field": has_password_field,
        "disclaimer": (
            "Safety assessments reflect heuristic and pattern-matching indicators. "
            "A 'Low Risk' rating is not a guarantee that a website is benign."
        )
    }
