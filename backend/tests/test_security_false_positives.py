"""
Regression test suite for Security Analysis:
Verifies fix for false positive on ordinary conversations (ChatGPT),
quoted/educational scam discussions, deduplication of overlapping signals,
specific explainable link analysis, and disabled checks support.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.services.security_service import (
    evaluate_heuristics,
    analyze_security_text,
    analyze_page_security
)
from app.services.link_service import analyze_single_link, analyze_link_batch

client = TestClient(app)


def test_regression_benign_chatgpt_conversation():
    """
    Scenario 1:
    A benign ChatGPT conversation mentioning the words 'urgent', 'won', and 'reward'.
    Must NOT trigger High Risk or inflated risk scores.
    """
    chat_text = (
        "User: Hey ChatGPT, I have an urgent question about history: which team won the championship "
        "in 1998, and what was the monetary reward for the winner?\n\n"
        "Assistant: In 1998, France won the FIFA World Cup by defeating Brazil 3-0. "
        "The champion team was awarded prize money from FIFA's tournament pool. "
        "In club football, Real Madrid also won the UEFA Champions League that year."
    )

    # 1. Text analysis
    res_text = analyze_security_text(chat_text, context="chat_conversation")
    assert res_text["success"] is True
    # Verdict must be Low Risk, score < 25
    assert res_text["risk_score"] < 25
    assert res_text["risk_level"] == "Low Risk"

    # 2. Page security on chatgpt.com
    dummy_chatgpt_page = {
        "page_id": "test-chatgpt-page",
        "title": "ChatGPT - 1998 World Cup Discussion",
        "url": "https://chatgpt.com/c/671fd89a-0001",
        "hostname": "chatgpt.com",
        "content": chat_text,
        "links": [
            {"url": "https://chatgpt.com/c/671fd89a-0001", "text": "Current Chat"},
            {"url": "https://help.openai.com/en/articles/6825453-chatgpt-release-notes", "text": "Help Center"},
            {"url": "/c/history-chat", "text": "Previous Chat"}
        ],
        "interactiveElements": [
            {"tag": "textarea", "type": "text", "id": "prompt-textarea"}
        ]
    }

    page_audit = analyze_page_security(dummy_chatgpt_page)
    assert page_audit["success"] is True
    assert page_audit["risk_score"] < 30
    assert page_audit["risk_level"] == "Low Risk"
    assert len(page_audit["flagged_links"]) == 0


def test_regression_quoted_scam_example_in_educational_discussion():
    """
    Scenario 2:
    A quoted scam example inside an educational discussion.
    Should be recognized as a quoted/educational example and contribute 0 threat points to page risk.
    """
    educational_text = (
        "In today's cybersecurity lesson, we analyze an example of a scam email targeting bank customers.\n\n"
        "> URGENT: Your account has been suspended! You have won $1,000,000! "
        "> Action required immediately to claim your reward!\n\n"
        "Notice how the scammer combines artificial urgency with an unrealistic financial lure."
    )

    res_text = analyze_security_text(educational_text, context="educational_article")
    assert res_text["success"] is True
    assert res_text["has_quoted_examples"] is True

    educational_page = {
        "page_id": "test-cybersecurity-lesson",
        "title": "Understanding Social Engineering - Lesson 3",
        "url": "https://academy.security.org/lesson/social-engineering",
        "hostname": "academy.security.org",
        "content": educational_text,
        "links": [
            {"url": "https://academy.security.org/glossary", "text": "Security Glossary"}
        ],
        "interactiveElements": []
    }

    page_audit = analyze_page_security(educational_page)
    assert page_audit["success"] is True
    # Quoted scam examples do not contribute to page risk score
    assert page_audit["risk_score"] < 30
    assert page_audit["risk_level"] == "Low Risk"


def test_regression_genuine_phishing_message_with_otp_and_suspicious_link():
    """
    Scenario 3:
    A genuine phishing message containing an urgent request to disclose an OTP
    and a link with concrete risk indicators (raw IP, unencrypted HTTP).
    Must flag High Risk (score >= 70) with specific link finding identifying the URL and reason.
    """
    phishing_text = (
        "URGENT: Your bank account will be suspended within 24 hours. "
        "Enter your password and OTP immediately to verify your credentials."
    )
    raw_ip_link = "http://192.168.1.100/login"

    phishing_page = {
        "page_id": "test-phishing-page",
        "title": "Account Verification Alert",
        "url": "http://192.168.1.100/login",
        "hostname": "192.168.1.100",
        "content": phishing_text,
        "links": [
            {"url": raw_ip_link, "text": "Click here to login and verify"}
        ],
        "interactiveElements": [
            {"tag": "input", "type": "password", "id": "pwd"}
        ]
    }

    page_audit = analyze_page_security(phishing_page)
    assert page_audit["success"] is True
    assert page_audit["risk_score"] >= 70
    assert page_audit["risk_level"] == "High Risk"

    # Link finding must specify the actual URL and concrete reason
    flagged = page_audit["flagged_links"]
    assert len(flagged) >= 1
    assert any(lk["url"] == raw_ip_link for lk in flagged)

    # Must have an explicit finding with URL and explanation
    link_finding_str = next(f for f in page_audit["findings"] if raw_ip_link in f)
    assert "Unencrypted connection" in link_finding_str or "direct IP address" in link_finding_str


def test_regression_benign_link_vs_suspicious_link_explanation():
    """
    Scenario 4:
    A benign link versus a link with a concrete, explainable risk indicator.
    Benign link is Low risk (0 points), suspicious link is flagged with specific reason.
    """
    benign_res = analyze_single_link("https://support.google.com/accounts", text="Google Support")
    assert benign_res["risk"] == "Low"
    assert benign_res["score"] == 0

    # Suspicious link: plain HTTP + raw IP
    suspicious_url = "http://10.0.0.1/verify-account"
    suspicious_res = analyze_single_link(suspicious_url, text="Verify Account")
    assert suspicious_res["risk"] == "High"
    assert suspicious_res["score"] >= 60
    assert any("direct IP address" in r for r in suspicious_res["reasons"])
    assert any("HTTP instead of HTTPS" in r for r in suspicious_res["reasons"])

    # Batch test ensuring explanation clarity
    batch = analyze_link_batch([
        {"url": "https://support.google.com/accounts", "text": "Google Support"},
        {"url": suspicious_url, "text": "Verify Account"}
    ])
    assert batch["summary"]["low"] == 1
    assert batch["summary"]["high"] == 1


def test_regression_disabled_checks_do_not_affect_score_or_findings():
    """
    Scenario 5:
    Disabled checks must not contribute to the score or appear in active findings.
    """
    text_with_urgency_and_lure = (
        "Action required immediately! You have won a cash prize! "
        "Claim your reward within 24 hours to prevent account closure."
    )

    # Baseline with checks active
    res_baseline = analyze_security_text(text_with_urgency_and_lure)
    assert res_baseline["risk_score"] > 0

    # Test with urgency and reward_lure disabled
    res_disabled = analyze_security_text(
        text_with_urgency_and_lure,
        disabled_checks=["urgency", "reward_lure"]
    )
    assert res_disabled["risk_score"] == 0
    assert res_disabled["risk_level"] == "Low Risk"
    assert len(res_disabled["indicators"]) == 0
    assert len(res_disabled["scamshield_tactics"]) == 0

    # Verify via FastAPI endpoint
    response = client.post(
        "/security/analyze-text",
        json={
            "text": text_with_urgency_and_lure,
            "disabled_checks": ["urgency", "reward_lure"]
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["risk_score"] == 0
    assert data["risk_level"] == "Low Risk"


def test_regression_duplicate_findings_do_not_inflate_score():
    """
    Scenario 6:
    Duplicate signals within the same threat dimension must be deduplicated
    and must not artificially inflate the risk score.
    """
    single_signal_text = "Action required immediately to verify your status."
    res_single = analyze_security_text(single_signal_text)
    score_single = res_single["risk_score"]

    # Text repeating multiple variations of urgency
    repeated_signal_text = (
        "Action required immediately! Your account has been suspended! "
        "Act now to avoid closure! Final warning! Within 24 hours or account will be deleted!"
    )
    res_repeated = analyze_security_text(repeated_signal_text)
    score_repeated = res_repeated["risk_score"]

    # Even with 5 urgent phrases, the single threat dimension ('urgency') is deduplicated
    # and scored once rather than 5 * 20 = 100 points
    assert score_repeated <= 35
    assert res_repeated["risk_level"] in ("Low Risk", "Caution / Suspicious")
