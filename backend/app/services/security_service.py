import re
from typing import Any
from app.services.link_service import analyze_single_link, analyze_link_batch

try:
    from app.scamshield_service import analyze_message
    SCAMSHIELD_AVAILABLE = True
except Exception:
    analyze_message = None
    SCAMSHIELD_AVAILABLE = False


# Security indicator patterns (phishing, social engineering, coercion)
URGENCY_PATTERNS = [
    r"\b(?:account (?:is |has been |was )?(?:suspended|disabled|frozen|locked|terminated|closed|compromised|breached|hacked))\b",
    r"\b(?:immediate(?:ly)?|urgent(?:ly)?)\s*(?::|\s+(?:action required|verify|update|confirm|click|review|pay|act))\b",
    r"\b(?:action required immediately|act now to avoid|act within \d+ (?:minutes|hours|days) to (?:prevent|avoid))\b",
    r"\b(?:final warning|last notice before (?:suspension|termination|closure|legal action))\b",
    r"\b(?:legal action will be taken|law enforcement notice|arrest warrant issued)\b",
    r"\b(?:within (?:24|\d+)\s*(?:minutes|hours|days) (?:or (?:lose access|your account will be (?:deleted|closed|suspended|locked))))\b"
]

CREDENTIAL_PATTERNS = [
    r"\b(?:enter|provide|send|submit|share|verify|confirm)\s+(?:your\s+)?(?:password|pin|passcode|secret key|seed phrase|otp|one[- ]time password)\b",
    r"\b(?:verify|confirm)\s+(?:your\s+)?(?:credentials|social security(?: number)?|ssn|banking login|secret key)\b",
    r"\b(?:update\s+(?:your\s+)?payment\s+(?:method|details)\s+to\s+restore\s+access)\b",
    r"\b(?:confirm\s+(?:your\s+)?(?:card number|cvv|bank account details)\s+immediately)\b"
]

FINANCIAL_LURE_PATTERNS = [
    r"\b(?:you(?:'ve| have)?\s+won|you are (?:the|a)\s+winner|selected as (?:the|a)\s+lucky winner)\b",
    r"\b(?:claim (?:your\s+)?(?:reward|prize|grant|lottery payout|cash prize|refund|settlement))\b",
    r"\b(?:free gift card giveaway|crypto payout bonus|bitcoin giveaway|exclusive cash prize)\b",
    r"\b(?:wire transfer immediately|send money via western union|pay with (?:apple|google|steam|amazon)?\s*gift cards?)\b"
]

IMPERSONATION_PATTERNS = [
    r"\b(?:official notice from\s+(?:the\s+)?(?:security team|fraud department|it administrator|account team))\b",
    r"\b(?:authorized representative of\s+(?:your\s+)?bank)\b",
    r"\b(?:urgent message from\s+(?:it support|system administrator|helpdesk))\b"
]

INJECTION_PATTERNS = [
    r"(?:ignore (?:all )?previous instructions|system prompt|bypass filter)",
    r"(?:treat the above as|new persona|developer mode enabled)",
    r"(?:send (?:all|the) (?:passwords|data|cookies|tokens) to)"
]


def normalize_check_name(name: str) -> str:
    """Normalize check / tactic names for consistent matching against disabled_checks."""
    n = (name or "").lower().strip().replace(" ", "_").replace("-", "_")
    mapping = {
        "urgency": "urgency",
        "urgent": "urgency",
        "high_pressure": "urgency",
        "reward_lure": "reward_lure",
        "reward": "reward_lure",
        "financial_lure": "reward_lure",
        "lure": "reward_lure",
        "credential_request": "credential_request",
        "credential": "credential_request",
        "credentials": "credential_request",
        "password": "credential_request",
        "authority_impersonation": "authority_impersonation",
        "impersonation": "authority_impersonation",
        "authority": "authority_impersonation",
        "prompt_injection": "prompt_injection",
        "injection": "prompt_injection",
        "links": "links",
        "link": "links",
        "link_analysis": "links"
    }
    return mapping.get(n, n)


def is_quoted_or_example_context(text: str, start: int, end: int) -> bool:
    """
    Check if a matched span appears inside a blockquote, quotation marks, code block,
    or is explicitly framed as an educational/discussion example of a scam.
    """
    if not text:
        return False

    # 1. Blockquote check (line starts with '>')
    line_start = text.rfind('\n', 0, start)
    line_start = 0 if line_start == -1 else line_start + 1
    line_end = text.find('\n', end)
    line_end = len(text) if line_end == -1 else line_end
    line = text[line_start:line_end].strip()
    if line.startswith(">"):
        return True

    # 2. Markdown code fences (``` or `)
    prefix = text[:start]
    if prefix.count("```") % 2 == 1:
        return True

    # 3. Enclosed in quotes
    window_before = text[max(0, start - 200):start]
    window_after = text[end:min(len(text), end + 200)]
    if ('"' in window_before and '"' in window_after) or \
       ("“" in window_before and "”" in window_after) or \
       ("‘" in window_before and "’" in window_after):
        return True

    # 4. Educational or discussion context in surrounding text
    surrounding_context = (text[max(0, start - 300):start] + " " + text[end:min(len(text), end + 300)]).lower()
    educational_patterns = [
        r"\b(?:example|sample|instance) of (?:a |an )?(?:scam|phishing|fraud|fake|malicious|suspicious)\b",
        r"\b(?:is this|looks like|received (?:this|a)|got this|someone sent (?:me )?this)\b",
        r"\b(?:scam email|phishing email|fake text|fraudulent message|spam message)(?:\s*(?:looks like|reads|says|below|:))\b",
        r"\b(?:educational|demonstration|analyzing|investigating|discussion about scams?)\b",
        r"\b(?:such as:|for example:?|here is what they sent:?|here is a sample:?)\b"
    ]
    for ep in educational_patterns:
        if re.search(ep, surrounding_context):
            return True

    return False


def evaluate_heuristics(text: str, disabled_checks: list[str] | None = None) -> list[dict[str, Any]]:
    """Scan text against known phishing, fraud, and manipulation cues with context verification."""
    indicators = []
    text_clean = text.lower()
    disabled_set = {normalize_check_name(c) for c in (disabled_checks or []) if c}

    # Urgency check
    if "urgency" not in disabled_set:
        for pat in URGENCY_PATTERNS:
            match = re.search(pat, text_clean)
            if match:
                is_quoted = is_quoted_or_example_context(text, match.start(), match.end())
                indicators.append({
                    "type": "urgency",
                    "severity": "Medium",
                    "label": "High-Pressure / Urgency Language",
                    "explanation": f"Found urgent call-to-action ('{match.group(0)}'), often used to rush victims into compliance.",
                    "matched": match.group(0),
                    "is_quoted_example": is_quoted
                })
                break

    # Credential check
    if "credential_request" not in disabled_set:
        for pat in CREDENTIAL_PATTERNS:
            match = re.search(pat, text_clean)
            if match:
                is_quoted = is_quoted_or_example_context(text, match.start(), match.end())
                indicators.append({
                    "type": "credential_request",
                    "severity": "High",
                    "label": "Suspicious Request for Credentials or Sensitive Data",
                    "explanation": f"Text requests sensitive credentials ('{match.group(0)}'). Legitimate services rarely ask for credentials via ordinary messages or untrusted pages.",
                    "matched": match.group(0),
                    "is_quoted_example": is_quoted
                })
                break

    # Financial lure check
    if "reward_lure" not in disabled_set:
        for pat in FINANCIAL_LURE_PATTERNS:
            match = re.search(pat, text_clean)
            if match:
                is_quoted = is_quoted_or_example_context(text, match.start(), match.end())
                indicators.append({
                    "type": "reward_lure",
                    "severity": "Medium",
                    "label": "Reward or Financial Lure",
                    "explanation": f"Text contains an unexpected offer or prize lure ('{match.group(0)}').",
                    "matched": match.group(0),
                    "is_quoted_example": is_quoted
                })
                break

    # Impersonation check
    if "authority_impersonation" not in disabled_set:
        for pat in IMPERSONATION_PATTERNS:
            match = re.search(pat, text_clean)
            if match:
                is_quoted = is_quoted_or_example_context(text, match.start(), match.end())
                indicators.append({
                    "type": "authority_impersonation",
                    "severity": "Low",
                    "label": "Authority / Support Framing",
                    "explanation": f"Uses formal support/security authority cues ('{match.group(0)}').",
                    "matched": match.group(0),
                    "is_quoted_example": is_quoted
                })
                break

    # Prompt injection check
    if "prompt_injection" not in disabled_set:
        for pat in INJECTION_PATTERNS:
            match = re.search(pat, text_clean)
            if match:
                is_quoted = is_quoted_or_example_context(text, match.start(), match.end())
                indicators.append({
                    "type": "prompt_injection",
                    "severity": "High",
                    "label": "Prompt Manipulation / Override Cue",
                    "explanation": "Content attempts to override assistant behavior or manipulate instructions.",
                    "matched": match.group(0),
                    "is_quoted_example": is_quoted
                })
                break

    return indicators


def analyze_security_text(
    text: str,
    context: str = "selection",
    disabled_checks: list[str] | None = None
) -> dict[str, Any]:
    """
    Perform multi-layered security analysis on arbitrary text.
    Combines the trained ScamShield ML model with deterministic heuristic checks.
    Deduplicates overlapping signals and separates manipulative language detection
    from webpage maliciousness.
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
            "scamshield_tactics": [],
            "has_quoted_examples": False,
            "is_all_quoted": False,
            "reasons": [],
            "disclaimer": "No text was submitted."
        }

    disabled_set = {normalize_check_name(c) for c in (disabled_checks or []) if c}

    # 1. ScamShield ML analysis
    scamshield_data = None
    scamshield_tactics = []
    if SCAMSHIELD_AVAILABLE and analyze_message:
        try:
            raw_scamshield = analyze_message(clean_text[:10000])
            if isinstance(raw_scamshield, dict):
                raw_tactics = raw_scamshield.get("detected_tactics", [])
                scamshield_tactics = [t for t in raw_tactics if normalize_check_name(t) not in disabled_set]
                filtered_results = [
                    res for res in raw_scamshield.get("results", [])
                    if normalize_check_name(res.get("tactic", "")) not in disabled_set
                ]
                scamshield_data = dict(raw_scamshield)
                scamshield_data["detected_tactics"] = scamshield_tactics
                scamshield_data["results"] = filtered_results
                scamshield_data["tactic_findings"] = filtered_results
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

    # 2. Deterministic heuristic checks
    heuristics = evaluate_heuristics(clean_text, disabled_checks=disabled_checks)

    # 3. Deduplication and Corroboration across threat dimensions
    dimension_map: dict[str, dict[str, Any]] = {}

    for ind in heuristics:
        dim = ind["type"]
        if dim not in dimension_map:
            dimension_map[dim] = {
                "heuristic": ind,
                "ml": False,
                "is_quoted": ind.get("is_quoted_example", False)
            }
        else:
            if ind.get("is_quoted_example"):
                dimension_map[dim]["is_quoted"] = True

    for tactic in scamshield_tactics:
        norm_tactic = normalize_check_name(tactic)
        if norm_tactic in dimension_map:
            dimension_map[norm_tactic]["ml"] = True
        else:
            dimension_map[norm_tactic] = {
                "heuristic": None,
                "ml": True,
                "is_quoted": False
            }

    # 4. Multi-Signal Score Calculation
    risk_score = 0
    reasons = []
    has_quoted_examples = False
    all_quoted = len(dimension_map) > 0
    uncorroborated_ml_count = 0

    for dim, info in dimension_map.items():
        heur = info["heuristic"]
        ml_hit = info["ml"]
        is_quoted = info["is_quoted"]

        if is_quoted:
            has_quoted_examples = True
            reasons.append(
                f"[Quoted/Discussion Example] Detected sample '{dim.replace('_', ' ')}' within quoted or educational context (non-actionable)."
            )
            continue  # Quoted examples do NOT add risk points

        all_quoted = False

        if ml_hit and heur:
            # Corroborated: both ML model and explicit heuristics detect this dimension
            if dim in ("credential_request", "prompt_injection"):
                risk_score += 35
            else:
                risk_score += 25
            reasons.append(
                f"[Corroborated {heur.get('label')}] Both ScamShield model and linguistic cues detected: {heur.get('explanation')}"
            )
        elif heur:
            # Heuristic only
            sev = heur.get("severity")
            if sev == "High":
                risk_score += 25
            elif sev == "Medium":
                risk_score += 15
            else:
                risk_score += 10
            reasons.append(f"[{heur.get('label')}] {heur.get('explanation')}")
        elif ml_hit:
            # ML only (uncalibrated linguistic correlation without actionable heuristic proof)
            # Bound uncorroborated ML contributions to prevent false positives from generic words
            if uncorroborated_ml_count < 2:
                risk_score += 5
                uncorroborated_ml_count += 1
            reasons.append(
                f"[ScamShield ML Tactic] Model detected linguistic pattern associated with '{dim.replace('_', ' ')}' (uncalibrated text correlation)."
            )

    risk_score = min(risk_score, 100)

    # Risk level classification
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
        "indicators": [ind for ind in heuristics if not ind.get("is_quoted_example")],
        "scamshield": scamshield_data,
        "scamshield_tactics": scamshield_tactics,
        "has_quoted_examples": has_quoted_examples,
        "is_all_quoted": all_quoted and len(dimension_map) > 0,
        "disclaimer": (
            "Automated security assessment only. Scores and tactics evaluate linguistic manipulation "
            "and do not constitute definitive proof that a website or domain is malicious. "
            "Never open suspicious links or provide credentials without independent verification."
        )
    }


def analyze_page_security(page: dict[str, Any], disabled_checks: list[str] | None = None) -> dict[str, Any]:
    """
    Comprehensive security audit of a loaded webpage (content, forms, and links).
    Clearly distinguishes content manipulation language from infrastructure maliciousness.
    Does not inflate score based on generic words, duplicate signals, or quoted examples.
    """
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

    disabled_set = {normalize_check_name(c) for c in (disabled_checks or []) if c}

    # 1. Text audit
    text_analysis = analyze_security_text(
        content[:10000],
        context="page_content",
        disabled_checks=disabled_checks
    )

    # 2. Links audit
    check_links = "links" not in disabled_set
    if check_links:
        link_analysis = analyze_link_batch(links, page_url=url)
        link_summary = link_analysis.get("summary", {})
        link_results = link_analysis.get("results", [])
    else:
        link_analysis = {"results": [], "summary": {"total": 0, "low": 0, "medium": 0, "high": 0, "unknown": 0}}
        link_summary = link_analysis["summary"]
        link_results = []

    findings = []

    # Include text reasons (filter empty or placeholder reasons)
    for r in text_analysis.get("reasons", []):
        if r and "No high-confidence" not in r:
            findings.append(r)

    # 3. Form / interactive element checks
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

    # 4. Detailed link findings with exact URL and specific explanation
    suspicious_links = []
    if check_links:
        for lk in link_results:
            if lk.get("risk") in ("High", "Medium"):
                suspicious_links.append(lk)
                lk_url = lk.get("url", "")
                reasons_str = "; ".join(lk.get("reasons", []))
                findings.append(f"[{lk['risk']} Risk Link] {lk_url}: {reasons_str}")

    # 5. Transparent, Non-Inflating Risk Score Synthesis
    # Distinguish language on page from website maliciousness
    is_all_quoted = text_analysis.get("is_all_quoted", False)
    text_score = text_analysis.get("risk_score", 0)

    # If the text was entirely quoted/educational scam discussion, text threat is 0
    if is_all_quoted:
        effective_text_score = 0
    else:
        # Manipulation language alone on a legitimate/secure webpage CANNOT push a site to High Risk
        # Cap text contribution to page score at 25 points ("Review recommended" max)
        effective_text_score = min(text_score, 25)

    # Base overall score from effective text score
    overall_score = effective_text_score

    # Factor infrastructure threats:
    # A. Unsecured HTTP password form: major infrastructure threat (+60)
    if has_unsecured_form:
        overall_score = max(overall_score + 60, 85)

    # B. High risk links (e.g. raw IP address, javascript: URI, homoglyphs):
    high_risk_links = [lk for lk in suspicious_links if lk.get("risk") == "High"]
    medium_risk_links = [lk for lk in suspicious_links if lk.get("risk") == "Medium"]

    if high_risk_links:
        # Each unique high-risk link adds concrete threat
        link_penalty = 50 + min((len(high_risk_links) - 1) * 10, 30)
        overall_score = max(overall_score, link_penalty)
    elif medium_risk_links:
        # Medium risk links add moderate caution
        link_penalty = 30 + min((len(medium_risk_links) - 1) * 5, 15)
        overall_score = max(overall_score, link_penalty)

    overall_score = min(overall_score, 100)

    # 6. Verdict calibration
    if overall_score >= 70:
        risk_level = "High Risk"
    elif overall_score >= 30:
        risk_level = "Review recommended"
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
        "findings": findings if findings else ["Page appears typical; no deceptive elements or malicious links flagged."],
        "text_analysis": text_analysis,
        "links_summary": link_summary,
        "flagged_links": suspicious_links,
        "has_password_field": has_password_field,
        "disclaimer": (
            "Safety assessments evaluate heuristic security indicators and link properties. "
            "A 'Low Risk' rating is not a guarantee of safety, and detected text tactics "
            "do not prove a website is malicious without corroborating infrastructure evidence."
        )
    }
