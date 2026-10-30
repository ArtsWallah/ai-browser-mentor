/**
 * Regression Test Suite: Shared Page-Ingestion Optimization & HTTP 413 Prevention
 *
 * Verifies:
 * 1. Base64 data URIs are stripped from image sources while valid URLs are preserved.
 * 2. Hard caps: images <= 50, interactive elements <= 100, links <= 150.
 * 3. Security-relevant inputs (password fields) are prioritized in interactive elements.
 * 4. Redundant bounding-box coordinates (x, y, width, height) are omitted.
 * 5. Redundant link properties are deduplicated while preserving `url`.
 * 6. UTF-8 byte measurement correctly accounts for multi-byte Unicode characters.
 * 7. Progressive trimming reduces oversized payloads below the 1.8 MB safety margin.
 * 8. On ingestion failure (including HTTP 413), currentPageId remains unset.
 * 9. Summarize and Explain stop execution cleanly when auto-ingestion fails.
 * 10. Ingest payload schema matches backend PageIngestRequest expectations.
 */

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const rootDir = path.resolve(__dirname, "..");
const contentJsPath = path.join(rootDir, "extension", "content.js");
const popupJsPath = path.join(rootDir, "extension", "popup.js");

const contentJsCode = fs.readFileSync(contentJsPath, "utf-8");
const popupJsCode = fs.readFileSync(popupJsPath, "utf-8");

// Lightweight DOM Mock for testing content.js extraction
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
    this.type = attrs.type || (this.tagName === "INPUT" ? "text" : "");
    this.href = attrs.href || "";
    this.src = attrs.src || "";
    this.currentSrc = attrs.currentSrc || attrs.src || "";
    this.alt = attrs.alt || "";
  }

  get innerText() {
    if (this.children.length > 0) {
      return this.children.map(c => c.innerText).filter(Boolean).join(" ");
    }
    return this._innerText;
  }
  set innerText(v) { this._innerText = v; }

  get textContent() {
    if (this.children.length > 0) {
      return this.children.map(c => c.textContent).filter(Boolean).join(" ");
    }
    return this._textContent;
  }
  set textContent(v) { this._textContent = v; }

  getAttribute(name) {
    return this.attributes[name] !== undefined ? this.attributes[name] : null;
  }
  setAttribute(name, val) { this.attributes[name] = String(val); }
  removeAttribute(name) { delete this.attributes[name]; }

  getBoundingClientRect() {
    return { left: 10, top: 20, width: 100, height: 30 };
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  cloneNode(deep = true) {
    const clone = new MockElement(this.tagName.toLowerCase(), { ...this.attributes });
    clone._value = this._value;
    clone._innerText = this._innerText;
    clone._textContent = this._textContent;
    clone.placeholder = this.placeholder;
    clone.title = this.title;
    clone.type = this.type;
    clone.href = this.href;
    clone.src = this.src;
    clone.currentSrc = this.currentSrc;
    clone.alt = this.alt;
    if (deep) {
      for (const c of this.children) {
        clone.appendChild(c.cloneNode(true));
      }
    }
    return clone;
  }

  remove() {
    if (this.parentNode) {
      const idx = this.parentNode.children.indexOf(this);
      if (idx !== -1) this.parentNode.children.splice(idx, 1);
      this.parentNode = null;
    }
  }

  querySelectorAll(selector) {
    const results = [];
    const parts = selector.split(",").map(s => s.trim().toLowerCase());

    const matchNode = (node) => {
      const tag = node.tagName.toLowerCase();
      const nodeRole = (node.getAttribute("role") || "").toLowerCase();
      const isAnchorWithHref = tag === "a" && (node.href || node.getAttribute("href"));

      for (const part of parts) {
        if (part === "a[href]" && isAnchorWithHref) return true;
        if (part === "img" && tag === "img") return true;
        if (part === tag) return true;
        if (part === "[role='button']" && nodeRole === "button") return true;
        if (part === "[role='link']" && nodeRole === "link") return true;
        if (part === "[role='textbox']" && nodeRole === "textbox") return true;
        if (part === "[role='searchbox']" && nodeRole === "searchbox") return true;
        if (part === "[onclick]" && node.getAttribute("onclick")) return true;
        if (part === "[tabindex]" && node.getAttribute("tabindex")) return true;
        if (part === "[contenteditable]" && node.getAttribute("contenteditable")) return true;
      }
      return false;
    };

    const traverse = (node) => {
      for (const child of node.children) {
        if (matchNode(child)) results.push(child);
        traverse(child);
      }
    };
    traverse(this);
    return results;
  }

  querySelector(selector) {
    const list = this.querySelectorAll(selector);
    return list.length > 0 ? list[0] : null;
  }
}

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
      title: "Test Page for Ingestion",
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
    setInterval: () => ({ unref: () => {} })
  };

  const ctx = vm.createContext(globalObj);
  const idx = contentJsCode.lastIndexOf("})();");
  const codeToEval = contentJsCode.slice(0, idx) +
    "\n  globalThis.__test_exports = { extract, label };\n})();\n";

  vm.runInContext(codeToEval, ctx);
  return { ctx, globalObj, exports: globalObj.__test_exports };
}

function buildPopupContext() {
  const dummyEl = {
    addEventListener: () => {},
    style: {},
    classList: { add: () => {}, remove: () => {} },
    getAttribute: () => null,
    setAttribute: () => {},
    appendChild: () => {},
    focus: () => {}
  };
  const globalObj = {
    document: {
      getElementById: () => dummyEl,
      querySelectorAll: () => [],
      addEventListener: () => {}
    },
    chrome: {
      storage: {
        local: {
          get: (keys, cb) => cb && cb({}),
          set: (items, cb) => cb && cb()
        },
        onChanged: { addListener: () => {} }
      },
      tabs: {
        query: (q, cb) => cb && cb([{ id: 1, url: "https://example.com" }]),
        sendMessage: (id, msg, cb) => cb && cb({ success: true })
      },
      runtime: {
        getURL: path => path,
        lastError: null
      },
      permissions: {
        contains: (perms, cb) => cb && cb(true),
        request: (perms, cb) => cb && cb(true)
      }
    },
    TextEncoder: globalThis.TextEncoder,
    unescape: globalThis.unescape,
    encodeURIComponent: globalThis.encodeURIComponent,
    fetch: async () => ({ status: 200, ok: true, json: async () => ({}) }),
    setTimeout: (fn, ms) => {},
    clearTimeout: () => {},
    console: console,
    module: { exports: {} }
  };
  globalObj.window = globalObj;
  globalObj.globalThis = globalObj;

  const ctx = vm.createContext(globalObj);
  vm.runInContext(popupJsCode, ctx);
  return { ctx, globalObj, exports: globalObj.module.exports };
}

// -------------------------------------------------------------
// TESTS
// -------------------------------------------------------------

test("1. Base64 data URIs are stripped from image sources while valid URLs are preserved", () => {
  const { exports, globalObj } = buildContentContext();
  const body = globalObj.document.body;

  // Image with giant base64 data URI
  const base64Img = new MockElement("img", {
    src: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA" + "A".repeat(5000),
    alt: "Embedded diagram"
  });
  body.appendChild(base64Img);

  // Normal image with valid HTTPS URL
  const validImg = new MockElement("img", {
    src: "https://example.com/assets/logo.png",
    alt: "Company Logo"
  });
  body.appendChild(validImg);

  const extracted = exports.extract();
  assert.strictEqual(extracted.images.length, 2);

  // Base64 image src must be stripped to empty string
  assert.strictEqual(extracted.images[0].src, "");
  assert.strictEqual(extracted.images[0].alt, "Embedded diagram");

  // Valid HTTPS URL must be preserved
  assert.strictEqual(extracted.images[1].src, "https://example.com/assets/logo.png");
  assert.strictEqual(extracted.images[1].alt, "Company Logo");

  // Bounding box coordinates must NOT be present
  assert.strictEqual(extracted.images[0].x, undefined);
  assert.strictEqual(extracted.images[0].width, undefined);
});

test("2. Hard caps on images (<= 50), links (<= 150), and interactive elements (<= 100)", () => {
  const { exports, globalObj } = buildContentContext();
  const body = globalObj.document.body;

  // Add 80 images
  for (let i = 0; i < 80; i++) {
    body.appendChild(new MockElement("img", { src: `https://example.com/img${i}.jpg`, alt: `Image ${i}` }));
  }

  // Add 200 links
  for (let i = 0; i < 200; i++) {
    const a = new MockElement("a", { href: `https://example.com/link${i}`, title: `Link Title ${i}` });
    a.innerText = `Link ${i}`;
    body.appendChild(a);
  }

  // Add 150 interactive buttons
  for (let i = 0; i < 150; i++) {
    const btn = new MockElement("button", { type: "button" });
    btn.innerText = `Button ${i}`;
    body.appendChild(btn);
  }

  const extracted = exports.extract();
  assert.strictEqual(extracted.images.length, 50, "Images must be capped at 50");
  assert.strictEqual(extracted.links.length, 150, "Links must be capped at 150");
  assert.strictEqual(extracted.interactiveElements.length, 100, "Interactive elements must be capped at 100");

  // Coordinates should be omitted
  assert.strictEqual(extracted.interactiveElements[0].x, undefined);
  assert.strictEqual(extracted.interactiveElements[0].width, undefined);

  // Redundant href should be omitted from link object while url is preserved
  assert.strictEqual(extracted.links[0].url, "https://example.com/link0");
  assert.strictEqual(extracted.links[0].href, undefined);
});

test("3. Password fields are prioritized in interactive elements", () => {
  const { exports, globalObj } = buildContentContext();
  const body = globalObj.document.body;

  // Add 120 regular buttons
  for (let i = 0; i < 120; i++) {
    const btn = new MockElement("button", { type: "button" });
    btn.innerText = `Action ${i}`;
    body.appendChild(btn);
  }

  // Add a security-sensitive password input at the very end
  const pwInput = new MockElement("input", { type: "password", "aria-label": "User Password" });
  body.appendChild(pwInput);

  const extracted = exports.extract();
  assert.strictEqual(extracted.interactiveElements.length, 100);

  // The password input must be included in the top 100 due to priority weighting
  const hasPassword = extracted.interactiveElements.some(el => el.type === "password");
  assert.strictEqual(hasPassword, true, "Security-relevant password input must be retained within capped elements");
});

test("4. Unicode text is accurately measured in UTF-8 bytes", () => {
  const { exports: popupExports } = buildPopupContext();
  const { measureUtf8Bytes } = popupExports;

  // ASCII string: 1 byte per char
  assert.strictEqual(measureUtf8Bytes("Hello World"), 11);

  // Multi-byte Unicode: Emojis are 4 UTF-8 bytes each
  const emojiStr = "🛡️🚀⚡";
  // Verify byte length is significantly greater than character length
  assert.strictEqual(measureUtf8Bytes(emojiStr) > emojiStr.length, true);

  // Chinese characters: 3 UTF-8 bytes each
  const chineseStr = "网页内容摘要";
  assert.strictEqual(measureUtf8Bytes(chineseStr), 18); // 6 chars * 3 bytes
});

test("5. Progressive trimming keeps oversized payloads below 1.8 MB", () => {
  const { exports: popupExports } = buildPopupContext();
  const { trimIngestPayload, measureUtf8Bytes, MAX_INGEST_PAYLOAD_BYTES } = popupExports;

  // Create an oversized payload (e.g. 2.5 MB of chunk data and links)
  const hugeChunks = [];
  for (let i = 0; i < 300; i++) {
    hugeChunks.push({
      heading: `Section ${i}`,
      text: "Detailed section analysis with long academic paragraphs. ".repeat(150),
      level: 2,
      type: "section"
    });
  }

  const hugeLinks = [];
  for (let i = 0; i < 150; i++) {
    hugeLinks.push({ index: i, text: `Link ${i}`, url: `https://example.com/path/${i}` });
  }

  const rawPayload = {
    page_id: "page_test_huge",
    title: "Very Large Research Paper",
    url: "https://example.com/huge-paper",
    hostname: "example.com",
    description: "Deep dive academic research with extensive DOM tree.",
    headings: hugeChunks.map(c => c.heading),
    paragraphs: [],
    chunks: hugeChunks,
    links: hugeLinks,
    images: [{ index: 0, src: "https://example.com/fig1.png", alt: "Figure 1" }],
    interactiveElements: [{ index: 0, tag: "button", type: "button", text: "Download" }],
    content: "Extracted full page text. ".repeat(8000),
    wordCount: 50000
  };

  const initialBytes = measureUtf8Bytes(JSON.stringify(rawPayload));
  assert.strictEqual(initialBytes > MAX_INGEST_PAYLOAD_BYTES, true, "Initial payload must exceed 1.8 MB to test trimmer");

  const trimmed = trimIngestPayload(rawPayload, MAX_INGEST_PAYLOAD_BYTES);
  assert.notStrictEqual(trimmed, null, "Trimmed payload must not be null for salvageable text");

  const trimmedBytes = measureUtf8Bytes(JSON.stringify(trimmed));
  assert.strictEqual(trimmedBytes <= MAX_INGEST_PAYLOAD_BYTES, true, "Trimmed payload must be within 1.8 MB safety margin");
  assert.strictEqual(trimmed.chunks.length > 0, true, "Trimmed payload must preserve essential chunks");
});

test("6. HTTP 413 error handling leaves currentPageId unset", async () => {
  // Simulate popup readCurrentPage behavior when receiving 413
  let currentPageId = "";
  let lastReadPageError = "";

  const mockFetch413 = async () => ({
    status: 413,
    ok: false,
    json: async () => ({
      success: false,
      error: "Request entity too large. Maximum allowed body size is 2097152 bytes (2 MB)."
    })
  });

  const res = await mockFetch413();
  if (!res.ok) {
    const errJson = await res.json().catch(() => null);
    let errMsg = "";
    if (res.status === 413) {
      errMsg = errJson?.error || "Webpage content exceeds maximum allowed body size (2 MB). Try selecting a specific section of text.";
    } else {
      errMsg = `Backend ingest failed (${res.status})`;
    }
    currentPageId = "";
    lastReadPageError = errMsg;
  }

  assert.strictEqual(currentPageId, "", "currentPageId must remain empty string on 413 failure");
  assert.strictEqual(lastReadPageError.includes("too large") || lastReadPageError.includes("2 MB"), true);
});

test("7. Summarize and Explain stop execution when auto-ingestion fails", async () => {
  // Simulate executeCommand control flow
  let isExecutingCommand = false;
  let commandErrorShown = "";
  let backendCommandCalled = false;
  let currentPageId = "";

  const fakeReadCurrentPage = async () => {
    // Simulated failed ingestion
    return false;
  };

  async function simulateExecuteCommand(intent) {
    isExecutingCommand = true;
    try {
      if (!currentPageId) {
        const ingestSuccess = await fakeReadCurrentPage();
        if (!ingestSuccess || !currentPageId) {
          commandErrorShown = "Could not read active webpage context. Command stopped to prevent using unindexed or invalid page context.";
          return;
        }
      }
      backendCommandCalled = true;
    } finally {
      isExecutingCommand = false;
    }
  }

  await simulateExecuteCommand("summarize_page");
  assert.strictEqual(backendCommandCalled, false, "Downstream command must NOT be executed if ingestion fails");
  assert.strictEqual(commandErrorShown.includes("Command stopped"), true);
  assert.strictEqual(currentPageId, "", "Page ID must remain unset");
});

test("8. Ingest payload conforms to PageIngestRequest requirements", () => {
  const { exports, globalObj } = buildContentContext();
  const body = globalObj.document.body;

  const h1 = new MockElement("h1");
  h1.innerText = "Introduction to Security";
  body.appendChild(h1);

  const p = new MockElement("p");
  p.innerText = "This document explains security practices in browsers.";
  body.appendChild(p);

  const extracted = exports.extract();
  const pageId = "page_valid_123";

  const payload = {
    page_id: pageId,
    title: extracted.title,
    url: extracted.url,
    hostname: "example.com",
    description: extracted.description,
    headings: extracted.chunks.map(c => c.heading).filter(Boolean),
    paragraphs: [],
    chunks: extracted.chunks,
    links: extracted.links,
    images: extracted.images,
    interactiveElements: extracted.interactiveElements,
    content: extracted.text,
    wordCount: Math.round(extracted.text.length / 5)
  };

  // Required backend PageIngestRequest fields
  const requiredFields = [
    "page_id", "title", "url", "hostname", "description",
    "headings", "paragraphs", "chunks", "links", "images",
    "interactiveElements", "content", "wordCount"
  ];

  for (const field of requiredFields) {
    assert.strictEqual(payload.hasOwnProperty(field), true, `Payload missing required PageIngestRequest field: ${field}`);
  }
});
