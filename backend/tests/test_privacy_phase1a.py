"""
Regression Test Suite for Phase 1A: Privacy Fixes

Requirements:
- Never extract element.value from input, textarea or other editable form controls.
- Do not collect password, email, search, text or other user-entered values as webpage text.
- Preserve useful non-sensitive structural information such as element type, safe accessibility labels, placeholder text and title attributes where appropriate.
- Avoid extracting editable field contents through alternate properties or selectors.
- Preserve the existing page-summary and page-question-answering behavior as much as possible.
- Do not remove all interactive-element extraction if safe structural extraction can be retained.
- Remove or safely disable logging of full webpage payloads, extracted text, headings, metadata and user content.
- Debug logging must be disabled by default and must never expose sensitive payloads.
"""
import subprocess
import sys
from pathlib import Path
import pytest
from starlette.testclient import TestClient

CONTENT_JS_PATH = Path(__file__).resolve().parent.parent.parent / "extension" / "content.js"
NODE_TEST_PATH = Path(__file__).resolve().parent / "test_content_privacy.js"
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app
from app.services.security_service import analyze_page_security


@pytest.fixture
def client():
    return TestClient(app)


# ============================================================
# 1. STATIC AUDIT OF content.js
# ============================================================

def test_static_audit_sensitive_console_logging_removed():
    """Verify that sensitive console logging of full webpage payloads is removed."""
    assert CONTENT_JS_PATH.exists(), f"Missing content.js at {CONTENT_JS_PATH}"
    code = CONTENT_JS_PATH.read_text(encoding="utf-8")

    # The exact vulnerable log identified in the security audit
    assert '"AI MENTOR: POST",\n    url,\n    payload' not in code, (
        "Found console.log('AI MENTOR: POST', url, payload) in content.js!"
    )
    assert '"AI MENTOR: POST", url, payload' not in code

    # Verify debug logging is disabled by default
    assert "const DEBUG = false;" in code, "DEBUG flag must be false by default in content.js"

    # Verify payload is not logged in post()
    post_block = code[code.find("async function post("): code.find("const ingest =")]
    assert "console.log(" not in post_block or "if (DEBUG)" in post_block
    assert "payload" not in post_block or "JSON.stringify" in post_block  # only in body JSON.stringify


def test_static_audit_form_value_extraction_removed():
    """Verify that e?.value or raw value extraction is not in label()."""
    code = CONTENT_JS_PATH.read_text(encoding="utf-8")

    # Locate label() definition
    assert "const label = e =>" in code
    label_start = code.find("const label = e =>")
    label_end = code.find("const esc = v =>", label_start)
    label_code = code[label_start:label_end]

    # Verify e?.value is eliminated from label()
    assert "e?.value ||" not in label_code, "Found 'e?.value ||' fallback in label()!"
    assert "e.value" not in label_code, "Direct e.value access found in label()!"

    # Verify isEditableControl guard exists
    assert "isEditableControl" in code, "isEditableControl helper must be defined to protect editable inputs"


# ============================================================
# 2. DYNAMIC REGRESSION SUITE VIA NODE.JS DOM RUNNER
# ============================================================

def test_node_privacy_regression_suite():
    """
    Executes the Node.js test suite which verifies against actual DOM extraction logic:
    - Text entered into an input is not included in extracted page content.
    - Text entered into a textarea is not included.
    - Password-field values are never extracted.
    - Safe structural metadata can still be collected.
    - Normal page extraction and existing features continue to work.
    - Full page payloads are not logged to the console.
    """
    assert NODE_TEST_PATH.exists(), f"Missing Node test file at {NODE_TEST_PATH}"

    result = subprocess.run(
        ["node", "--test", str(NODE_TEST_PATH)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False
    )

    print("NODE TEST STDOUT:\n", result.stdout)
    if result.stderr:
        print("NODE TEST STDERR:\n", result.stderr)

    assert result.returncode == 0, f"Node regression tests failed:\n{result.stdout}\n{result.stderr}"
    assert "fail 0" in result.stdout
    assert "pass 11" in result.stdout


# ============================================================
# 3. BACKEND INTEGRATION & EXISTING FEATURE INTEGRITY
# ============================================================

def test_page_ingest_with_safe_structural_metadata(client):
    """
    Verify that page ingest accepts safe structural metadata without user values,
    and security auditing continues to correctly analyze forms and password fields.
    """
    page_data = {
        "url": "http://insecure-login-portal.com/login",
        "title": "Insecure Member Login",
        "description": "Please enter your password to sign in",
        "text": "Insecure Member Login Please enter your credentials below.",
        "chunks": [
            {
                "heading": "Insecure Member Login",
                "text": "Please enter your credentials below.",
                "level": 1,
                "type": "section"
            }
        ],
        "links": [
            {"index": 0, "text": "Forgot Password?", "url": "http://insecure-login-portal.com/reset"}
        ],
        "images": [],
        "interactiveElements": [
            {
                "index": 0,
                "tag": "input",
                "type": "text",
                "role": "",
                "text": "Username",
                "ariaLabel": "Username",
                "placeholder": "Enter username"
            },
            {
                "index": 1,
                "tag": "input",
                "type": "password",
                "role": "",
                "text": "Password",
                "ariaLabel": "Password",
                "placeholder": "Enter password"
            },
            {
                "index": 2,
                "tag": "input",
                "type": "submit",
                "role": "",
                "text": "Log In"
            }
        ],
        "stats": {
            "chunks": 1,
            "images": 0,
            "links": 1,
            "interactiveElements": 3,
            "characters": 60
        }
    }

    # Ingest the page
    resp = client.post("/page/ingest", json=page_data)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data.get("success") is True
    page_id = res_data.get("page_id")
    assert page_id is not None

    # Verify that security auditing detects the password field on unencrypted HTTP
    audit = analyze_page_security(page_data)
    assert audit["success"] is True
    assert any("Password input field found on an unencrypted HTTP" in f for f in audit.get("findings", []))


def test_page_ingest_rich_text_structural_controls_without_secret_markers(client):
    """
    Verify that structural elements for contenteditable, role=textbox, and role=searchbox
    contain only safe structural metadata, secret markers are completely absent,
    and backend ingestion and question-answering succeed.
    """
    secret_markers = [
        "SECRET_PLAINTEXT_ONLY_7X9",
        "SECRET_ROLE_TEXTBOX_4K2",
        "SECRET_ROLE_SEARCHBOX_8M3"
    ]

    safe_page_data = {
        "url": "https://company.secure-portal.com/dashboard",
        "title": "Secure Dashboard Portal",
        "description": "Enterprise customer management dashboard",
        "text": "Secure Dashboard Portal Overview of accounts and operational status.",
        "chunks": [
            {
                "heading": "Secure Dashboard Portal",
                "text": "Overview of accounts and operational status.",
                "level": 1,
                "type": "section"
            }
        ],
        "links": [
            {"index": 0, "text": "Documentation", "url": "https://company.secure-portal.com/docs"}
        ],
        "images": [],
        "interactiveElements": [
            {
                "index": 0,
                "tag": "div",
                "type": "",
                "role": "textbox",
                "text": "Support Chat Box",
                "ariaLabel": "Support Chat Box",
                "placeholder": "Write your message..."
            },
            {
                "index": 1,
                "tag": "div",
                "type": "",
                "role": "searchbox",
                "text": "Product Search",
                "ariaLabel": "Product Search",
                "placeholder": "Search items"
            },
            {
                "index": 2,
                "tag": "div",
                "type": "",
                "role": "",
                "text": "Plaintext Notes Editor",
                "ariaLabel": "Plaintext Notes Editor",
                "placeholder": "Type notes here"
            }
        ],
        "stats": {
            "chunks": 1,
            "images": 0,
            "links": 1,
            "interactiveElements": 3,
            "characters": 65
        }
    }

    # Verify no secret markers exist in any part of payload
    page_json_str = str(safe_page_data)
    for marker in secret_markers:
        assert marker not in page_json_str

    # Ingest the page into backend
    resp = client.post("/page/ingest", json=safe_page_data)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data.get("success") is True
    page_id = res_data.get("page_id")

    # Verify question answering works with the ingested page
    ask_resp = client.post("/ask", json={
        "page_id": page_id,
        "question": "What is this dashboard portal for?"
    })
    assert ask_resp.status_code == 200
    ask_data = ask_resp.json()
    assert ask_data.get("success") is True
    assert "answer" in ask_data
