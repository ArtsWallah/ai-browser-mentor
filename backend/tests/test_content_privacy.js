/**
 * Regression Test Suite for AI Browser Mentor - Phase 1A Privacy Fixes
 * 
 * Verifies:
 * 1. Text entered into an input is not included in extracted page content.
 * 2. Text entered into a textarea is not included.
 * 3. Password-field values are never extracted.
 * 4. Safe structural metadata can still be collected.
 * 5. Normal page extraction and existing features continue to work.
 * 6. Full page payloads are not logged to the console.
 */

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

// Read content.js source
const contentJsPath = path.resolve(__dirname, "../../extension/content.js");
const contentJsCode = fs.readFileSync(contentJsPath, "utf-8");

// Mock DOM elements and document environment
class MockElement {
  constructor(tagName, attrs = {}) {
    this.tagName = tagName.toUpperCase();
    this.attributes = { ...attrs };
    this.style = {};
    this.children = [];
    this.parentNode = null;
    this._value = attrs.value || "";
    this._innerText = attrs.innerText || "";
    this._textContent = attrs.textContent || "";
    this.placeholder = attrs.placeholder || "";
    this.title = attrs.title || "";
    this.labels = [];
    this.type = attrs.type || (this.tagName === "INPUT" ? "text" : "");
  }

  get value() {
    return this._value;
  }
  set value(v) {
    this._value = v;
  }

  get innerText() {
    if (this.children.length > 0) {
      return this.children.map(c => c.innerText).filter(Boolean).join(" ");
    }
    return this._innerText;
  }
  set innerText(v) {
    this._innerText = v;
  }

  get textContent() {
    if (this.children.length > 0) {
      return this.children.map(c => c.textContent).filter(Boolean).join(" ");
    }
    return this._textContent;
  }
  set textContent(v) {
    this._textContent = v;
  }

  hasAttribute(name) {
    return this.attributes[name] !== undefined;
  }

  getAttribute(name) {
    return this.attributes[name] !== undefined ? this.attributes[name] : null;
  }

  setAttribute(name, val) {
    this.attributes[name] = String(val);
  }

  removeAttribute(name) {
    delete this.attributes[name];
  }

  getBoundingClientRect() {
    return { left: 10, top: 20, width: 100, height: 30 };
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  remove() {
    if (this.parentNode) {
      const idx = this.parentNode.children.indexOf(this);
      if (idx !== -1) {
        this.parentNode.children.splice(idx, 1);
      }
      this.parentNode = null;
    }
  }

  cloneNode(deep = true) {
    const cloned = new MockElement(this.tagName, { ...this.attributes });
    cloned._value = this._value;
    cloned._innerText = this._innerText;
    cloned._textContent = this._textContent;
    cloned.placeholder = this.placeholder;
    cloned.title = this.title;
    cloned.type = this.type;
    if (deep) {
      for (const ch of this.children) {
        cloned.appendChild(ch.cloneNode(true));
      }
    }
    return cloned;
  }

  querySelectorAll(selector) {
    const results = [];
    const selectors = selector.split(",").map(s => s.trim().toLowerCase());

    const matches = el => {
      const tag = el.tagName.toLowerCase();
      for (const sel of selectors) {
        if (sel === tag) return true;
        if (sel === "[contenteditable]" && el.hasAttribute("contenteditable")) return true;
        if (sel === "[onclick]" && el.hasAttribute("onclick")) return true;
        if (sel === "[tabindex]" && el.hasAttribute("tabindex")) return true;
        if (sel.startsWith("[role=") && sel.endsWith("]")) {
          const role = sel.slice(6, -1).replace(/['"]/g, "");
          if ((el.getAttribute("role") || "").toLowerCase() === role) return true;
        }
        if (sel.startsWith("[contenteditable=") && sel.endsWith("]")) {
          const ce = sel.slice(17, -1).replace(/['"]/g, "");
          if (el.getAttribute("contenteditable") === ce) return true;
        }
        if (sel === "a[href]" && tag === "a" && el.getAttribute("href")) return true;
      }
      return false;
    };

    const traverse = node => {
      for (const ch of node.children) {
        if (matches(ch)) results.push(ch);
        traverse(ch);
      }
    };
    traverse(this);
    return results;
  }
}

// Extract the helper functions and post function from content.js for testing
function buildContentContext() {
  const globalObj = {
    Element: MockElement,
    window: {
      __AI_BROWSER_MENTOR_INJECTED__: false,
      getSelection: () => ({ toString: () => "Selected webpage text" })
    },
    location: { href: "https://example.com/test-page" },
    history: { pushState: () => {}, replaceState: () => {} },
    scrollX: 0,
    scrollY: 0,
    getComputedStyle: () => ({ display: "block", visibility: "visible" }),
    document: {
      title: "Secure Page Example",
      body: new MockElement("body"),
      querySelector: sel => null,
      querySelectorAll: sel => globalObj.document.body.querySelectorAll(sel)
    },
    console: {
      logs: [],
      errors: [],
      warns: [],
      log(...args) { this.logs.push(args); },
      error(...args) { this.errors.push(args); },
      warn(...args) { this.warns.push(args); }
    },
    fetch: async () => ({
      status: 200,
      ok: true,
      json: async () => ({ success: true })
    }),
    chrome: {
      runtime: {
        onMessage: { addListener: () => {} },
        sendMessage: async () => {}
      }
    },
    addEventListener: () => {},
    setTimeout: fn => fn(),
    setInterval: () => {}
  };

  const vm = require("node:vm");
  const ctx = vm.createContext(globalObj);

  // Expose internal functions cleanly before IIFE closing
  const idx = contentJsCode.lastIndexOf("})();");
  const codeToEval = contentJsCode.slice(0, idx) +
    "\n  globalThis.__test_exports = { label, isEditableControl, extract, post, DEBUG };\n})();\n";

  vm.runInContext(codeToEval, ctx);

  return { ctx, globalObj, exports: globalObj.__test_exports };
}

test("Task 1: Text entered into an input is not included in extracted page content", () => {
  const { exports, globalObj } = buildContentContext();
  const body = globalObj.document.body;

  const input = new MockElement("input", {
    type: "text",
    placeholder: "Search query",
    "aria-label": "Search Box"
  });
  input.value = "my_sensitive_credit_card_or_ssn_12345";
  body.appendChild(input);

  const labelResult = exports.label(input);
  assert.strictEqual(labelResult.includes("my_sensitive_credit_card_or_ssn_12345"), false);
  assert.strictEqual(labelResult, "Search Box"); // Safe aria-label used

  const extracted = exports.extract();
  assert.strictEqual(extracted.text.includes("my_sensitive_credit_card_or_ssn_12345"), false);
  for (const chunk of extracted.chunks) {
    assert.strictEqual(chunk.text.includes("my_sensitive_credit_card_or_ssn_12345"), false);
  }
  for (const el of extracted.interactiveElements) {
    assert.strictEqual(el.text.includes("my_sensitive_credit_card_or_ssn_12345"), false);
  }
});

test("Task 1: Text entered into a textarea is not included in extracted content", () => {
  const { exports, globalObj } = buildContentContext();
  const body = globalObj.document.body;

  const textarea = new MockElement("textarea", {
    placeholder: "Enter feedback",
    title: "Feedback Form"
  });
  textarea.value = "Confidential user feedback and private medical history";
  textarea.innerText = "Confidential user feedback and private medical history";
  textarea.textContent = "Confidential user feedback and private medical history";
  body.appendChild(textarea);

  const labelResult = exports.label(textarea);
  assert.strictEqual(labelResult.includes("Confidential user feedback"), false);
  assert.strictEqual(labelResult, "Enter feedback"); // Safe placeholder used

  const extracted = exports.extract();
  assert.strictEqual(extracted.text.includes("Confidential user feedback"), false);
  for (const chunk of extracted.chunks) {
    assert.strictEqual(chunk.text.includes("Confidential user feedback"), false);
  }
  for (const el of extracted.interactiveElements) {
    assert.strictEqual(el.text.includes("Confidential user feedback"), false);
  }
});

test("Task 1: Password-field values are never extracted", () => {
  const { exports, globalObj } = buildContentContext();
  const body = globalObj.document.body;

  const pwd = new MockElement("input", {
    type: "password",
    placeholder: "Enter Password",
    "aria-label": "Account Password"
  });
  pwd.value = "SuperSecretP@ssw0rd!#2026";
  body.appendChild(pwd);

  const labelResult = exports.label(pwd);
  assert.strictEqual(labelResult.includes("SuperSecretP@ssw0rd!#2026"), false);
  assert.strictEqual(labelResult, "Account Password"); // Safe aria-label used

  const extracted = exports.extract();
  assert.strictEqual(extracted.text.includes("SuperSecretP@ssw0rd!#2026"), false);
  for (const el of extracted.interactiveElements) {
    assert.strictEqual(el.text.includes("SuperSecretP@ssw0rd!#2026"), false);
  }
});

test("Task 1: Safe structural metadata can still be collected", () => {
  const { exports, globalObj } = buildContentContext();
  const body = globalObj.document.body;

  const emailInput = new MockElement("input", {
    type: "email",
    placeholder: "user@example.com",
    "aria-label": "User Email",
    title: "Email Address"
  });
  emailInput.value = "actual_user@realdomain.org";

  const submitBtn = new MockElement("input", {
    type: "submit",
    value: "Sign In"
  });

  const pwdInput = new MockElement("input", {
    type: "password",
    placeholder: "Password"
  });
  pwdInput.value = "hidden_password";

  body.appendChild(emailInput);
  body.appendChild(submitBtn);
  body.appendChild(pwdInput);

  const extracted = exports.extract();
  const elements = extracted.interactiveElements;

  // Structural metadata is retained
  assert.strictEqual(elements.length, 3);
  const emailEl = elements.find(e => e.type === "email");
  assert.ok(emailEl);
  assert.strictEqual(emailEl.tag, "input");
  assert.strictEqual(emailEl.ariaLabel, "User Email");
  assert.strictEqual(emailEl.placeholder, "user@example.com");
  assert.strictEqual(emailEl.text, "User Email");
  assert.strictEqual(emailEl.text.includes("actual_user@realdomain.org"), false);

  const submitEl = elements.find(e => e.type === "submit");
  assert.ok(submitEl);
  assert.strictEqual(submitEl.text, "Sign In"); // Button display label preserved

  const pwdEl = elements.find(e => e.type === "password");
  assert.ok(pwdEl);
  assert.strictEqual(pwdEl.placeholder, "Password");
  assert.strictEqual(pwdEl.text, "Password");
  assert.strictEqual(pwdEl.text.includes("hidden_password"), false);
});

test("Task 1 & 4: Normal page extraction and existing features continue to work", () => {
  const { exports, globalObj } = buildContentContext();
  const body = globalObj.document.body;

  const h1 = new MockElement("h1", { innerText: "Cybersecurity Best Practices", textContent: "Cybersecurity Best Practices" });
  const p = new MockElement("p", { innerText: "Always verify website links before clicking.", textContent: "Always verify website links before clicking." });
  const link = new MockElement("a", { href: "https://example.com/learn", innerText: "Learn More", textContent: "Learn More" });

  body.appendChild(h1);
  body.appendChild(p);
  body.appendChild(link);

  const extracted = exports.extract();
  assert.strictEqual(extracted.title, "Secure Page Example");
  assert.ok(extracted.text.includes("Cybersecurity Best Practices"));
  assert.ok(extracted.text.includes("Always verify website links before clicking."));
  assert.strictEqual(extracted.links.length, 1);
  assert.strictEqual(extracted.links[0].url, "https://example.com/learn");
  assert.strictEqual(extracted.links[0].text, "Learn More");
  assert.strictEqual(extracted.chunks.length, 1);
  assert.strictEqual(extracted.chunks[0].heading, "Cybersecurity Best Practices");
});

test("Task 2: Full page payloads are not logged to the console", async () => {
  const { exports, globalObj } = buildContentContext();
  const body = globalObj.document.body;

  const sensitivePayload = {
    url: "https://example.com/login",
    title: "Login Page",
    text: "Extracted full page text with sensitive data",
    headings: ["Account Overview"],
    user_content: "Secret user questions or inputs"
  };

  // Call post()
  await exports.post("/page/ingest", sensitivePayload);

  // Check all logged console outputs
  const logs = globalObj.console.logs;
  for (const logArgs of logs) {
    const logStr = JSON.stringify(logArgs);
    assert.strictEqual(
      logStr.includes("Extracted full page text"),
      false,
      "Payload text must never be logged"
    );
    assert.strictEqual(
      logStr.includes("Secret user questions"),
      false,
      "User content must never be logged"
    );
  }

  // Verify DEBUG is false by default
  assert.strictEqual(exports.DEBUG, false, "Debug logging must be disabled by default");
});

test("Task 2: Source code audit confirms console.log(AI MENTOR: POST, url, payload) is removed", () => {
  assert.strictEqual(
    contentJsCode.includes('"AI MENTOR: POST",\n    url,\n    payload'),
    false,
    "The vulnerable console.log(AI MENTOR: POST, url, payload) must not exist"
  );
  assert.strictEqual(
    contentJsCode.includes('"AI MENTOR: POST", url, payload'),
    false,
    "Inline console.log with payload must not exist"
  );
  assert.strictEqual(
    contentJsCode.includes("e?.value ||"),
    false,
    "Vulnerable e?.value fallback in label() must not exist"
  );
});

test("Phase 1A Regression: contenteditable='plaintext-only' secret marker is never extracted", async () => {
  const { exports, globalObj } = buildContentContext();
  const body = globalObj.document.body;

  const h1 = new MockElement("h1", { innerText: "Editor Section", textContent: "Editor Section" });
  const p = new MockElement("p", { innerText: "Please review the notes.", textContent: "Please review the notes." });

  const ceElement = new MockElement("div", {
    contenteditable: "plaintext-only",
    "aria-label": "Plaintext Notes Editor",
    placeholder: "Type notes here"
  });
  const secretMarker = "SECRET_PLAINTEXT_ONLY_7X9";
  ceElement.innerText = secretMarker;
  ceElement.textContent = secretMarker;

  body.appendChild(h1);
  body.appendChild(p);
  body.appendChild(ceElement);

  // Verify label() does not extract inner secret text
  const lbl = exports.label(ceElement);
  assert.strictEqual(lbl.includes(secretMarker), false);
  assert.strictEqual(lbl, "Plaintext Notes Editor"); // Safe aria-label retained

  // Verify extract() does not extract secret into body, chunks, or interactive elements
  const extracted = exports.extract();
  assert.strictEqual(extracted.text.includes(secretMarker), false);
  for (const chunk of extracted.chunks) {
    assert.strictEqual(chunk.text.includes(secretMarker), false);
    assert.strictEqual(chunk.heading.includes(secretMarker), false);
  }
  for (const el of extracted.interactiveElements) {
    assert.strictEqual(el.text.includes(secretMarker), false);
  }

  // Intercept post payload to verify ingestion payload never has secret marker
  let capturedPayload = null;
  globalObj.fetch = async (url, opts) => {
    capturedPayload = JSON.parse(opts.body);
    return { status: 200, ok: true, json: async () => ({ success: true }) };
  };

  await exports.post("/page/ingest", extracted);
  const payloadStr = JSON.stringify(capturedPayload);
  assert.strictEqual(payloadStr.includes(secretMarker), false, "Ingestion payload must not contain secret marker");

  // Verify safe surrounding text survived
  assert.ok(extracted.text.includes("Editor Section"));
  assert.ok(extracted.text.includes("Please review the notes."));
});

test("Phase 1A Regression: role='textbox' secret marker is never extracted", async () => {
  const { exports, globalObj } = buildContentContext();
  const body = globalObj.document.body;

  const h2 = new MockElement("h2", { innerText: "Customer Support", textContent: "Customer Support" });
  const customTextbox = new MockElement("div", {
    role: "textbox",
    "aria-label": "Support Chat Box",
    placeholder: "Write your message...",
    title: "Support Messaging Input"
  });
  const secretMarker = "SECRET_ROLE_TEXTBOX_4K2";
  customTextbox.innerText = secretMarker;
  customTextbox.textContent = secretMarker;

  body.appendChild(h2);
  body.appendChild(customTextbox);

  // Verify label() uses safe aria-label or placeholder, never the secret inner text
  const lbl = exports.label(customTextbox);
  assert.strictEqual(lbl.includes(secretMarker), false);
  assert.strictEqual(lbl, "Support Chat Box");

  const extracted = exports.extract();
  assert.strictEqual(extracted.text.includes(secretMarker), false);
  for (const chunk of extracted.chunks) {
    assert.strictEqual(chunk.text.includes(secretMarker), false);
  }
  for (const el of extracted.interactiveElements) {
    assert.strictEqual(el.text.includes(secretMarker), false);
    if (el.role === "textbox") {
      assert.strictEqual(el.ariaLabel, "Support Chat Box");
      assert.strictEqual(el.placeholder, "Write your message...");
    }
  }

  // Verify ingestion payload
  let capturedPayload = null;
  globalObj.fetch = async (url, opts) => {
    capturedPayload = JSON.parse(opts.body);
    return { status: 200, ok: true, json: async () => ({ success: true }) };
  };

  await exports.post("/page/ingest", extracted);
  assert.strictEqual(JSON.stringify(capturedPayload).includes(secretMarker), false);
});

test("Phase 1A Regression: role='searchbox' secret marker is never extracted", async () => {
  const { exports, globalObj } = buildContentContext();
  const body = globalObj.document.body;

  const h3 = new MockElement("h3", { innerText: "Search Catalog", textContent: "Search Catalog" });
  const customSearchbox = new MockElement("div", {
    role: "searchbox",
    "aria-label": "Product Search",
    placeholder: "Search items",
    title: "Catalog Search"
  });
  const secretMarker = "SECRET_ROLE_SEARCHBOX_8M3";
  customSearchbox.innerText = secretMarker;
  customSearchbox.textContent = secretMarker;

  body.appendChild(h3);
  body.appendChild(customSearchbox);

  const lbl = exports.label(customSearchbox);
  assert.strictEqual(lbl.includes(secretMarker), false);
  assert.strictEqual(lbl, "Product Search");

  const extracted = exports.extract();
  assert.strictEqual(extracted.text.includes(secretMarker), false);
  for (const chunk of extracted.chunks) {
    assert.strictEqual(chunk.text.includes(secretMarker), false);
  }
  for (const el of extracted.interactiveElements) {
    assert.strictEqual(el.text.includes(secretMarker), false);
    if (el.role === "searchbox") {
      assert.strictEqual(el.ariaLabel, "Product Search");
      assert.strictEqual(el.placeholder, "Search items");
    }
  }

  let capturedPayload = null;
  globalObj.fetch = async (url, opts) => {
    capturedPayload = JSON.parse(opts.body);
    return { status: 200, ok: true, json: async () => ({ success: true }) };
  };

  await exports.post("/page/ingest", extracted);
  assert.strictEqual(JSON.stringify(capturedPayload).includes(secretMarker), false);
});

test("Phase 1A Regression: nested editable elements are removed without breaking surrounding paragraphs", async () => {
  const { exports, globalObj } = buildContentContext();
  const body = globalObj.document.body;

  const p1 = new MockElement("p", { innerText: "Welcome to our portal.", textContent: "Welcome to our portal." });
  const nestedCE = new MockElement("span", {
    contenteditable: "plaintext-only",
    "aria-label": "Inline Editor"
  });
  nestedCE.innerText = "SECRET_PLAINTEXT_ONLY_7X9";
  nestedCE.textContent = "SECRET_PLAINTEXT_ONLY_7X9";
  p1.appendChild(nestedCE);

  const p2 = new MockElement("p", { innerText: "Important notice below:", textContent: "Important notice below:" });
  const nestedTextbox = new MockElement("div", {
    role: "textbox",
    "aria-label": "Inline Input"
  });
  nestedTextbox.innerText = "SECRET_ROLE_TEXTBOX_4K2";
  nestedTextbox.textContent = "SECRET_ROLE_TEXTBOX_4K2";
  p2.appendChild(nestedTextbox);

  const p3 = new MockElement("p", { innerText: "Search here:", textContent: "Search here:" });
  const nestedSearchbox = new MockElement("span", {
    role: "searchbox",
    "aria-label": "Inline Search"
  });
  nestedSearchbox.innerText = "SECRET_ROLE_SEARCHBOX_8M3";
  nestedSearchbox.textContent = "SECRET_ROLE_SEARCHBOX_8M3";
  p3.appendChild(nestedSearchbox);

  body.appendChild(p1);
  body.appendChild(p2);
  body.appendChild(p3);

  const extracted = exports.extract();
  assert.strictEqual(extracted.text.includes("SECRET_PLAINTEXT_ONLY_7X9"), false);
  assert.strictEqual(extracted.text.includes("SECRET_ROLE_TEXTBOX_4K2"), false);
  assert.strictEqual(extracted.text.includes("SECRET_ROLE_SEARCHBOX_8M3"), false);

  // Surrounding text is preserved
  assert.ok(extracted.text.includes("Welcome to our portal."));
  assert.ok(extracted.text.includes("Important notice below:"));
  assert.ok(extracted.text.includes("Search here:"));
  assert.strictEqual(extracted.chunks.length >= 1, true);
  for (const chunk of extracted.chunks) {
    assert.strictEqual(chunk.text.includes("SECRET_"), false);
  }

  // Verify ingestion payload
  let capturedPayload = null;
  globalObj.fetch = async (url, opts) => {
    capturedPayload = JSON.parse(opts.body);
    return { status: 200, ok: true, json: async () => ({ success: true }) };
  };

  await exports.post("/page/ingest", extracted);
  const payloadStr = JSON.stringify(capturedPayload);
  assert.strictEqual(payloadStr.includes("SECRET_PLAINTEXT_ONLY_7X9"), false);
  assert.strictEqual(payloadStr.includes("SECRET_ROLE_TEXTBOX_4K2"), false);
  assert.strictEqual(payloadStr.includes("SECRET_ROLE_SEARCHBOX_8M3"), false);
});
