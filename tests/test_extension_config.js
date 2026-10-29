/**
 * Phase 1H Verification Test Suite: Extension Backend URL Centralization
 *
 * Verifies:
 * 1. MentorConfig exports and default production URL (https://ai-browser-mentor.onrender.com).
 * 2. Valid localhost HTTP and HTTPS overrides with trailing slash sanitization.
 * 3. Insecure remote HTTP and malformed override rejection with fallback to production default.
 * 4. Safe chrome.storage.local resolution with error handling.
 * 5. Extension manifest content_scripts ordering (config.js before content.js).
 * 6. Extension HTML script tag ordering (config.js before popup.js and workspace.js).
 * 7. Extension recovery injection ordering and active URL interpolation in error messages.
 */

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const rootDir = path.resolve(__dirname, "..");
const configPath = path.join(rootDir, "extension", "config.js");
const manifestPath = path.join(rootDir, "extension", "manifest.json");
const popupHtmlPath = path.join(rootDir, "extension", "popup.html");
const workspaceHtmlPath = path.join(rootDir, "extension", "workspace.html");
const popupJsPath = path.join(rootDir, "extension", "popup.js");
const workspaceJsPath = path.join(rootDir, "extension", "workspace.js");
const contentJsPath = path.join(rootDir, "extension", "content.js");

const MentorConfig = require(configPath);

test("1. Production default URL and storage key", () => {
  assert.strictEqual(
    MentorConfig.DEFAULT_BACKEND_URL,
    "https://ai-browser-mentor.onrender.com",
    "Default backend URL must be https://ai-browser-mentor.onrender.com"
  );
  assert.strictEqual(
    MentorConfig.STORAGE_KEY,
    "abm_backend_url_override",
    "Storage key must be abm_backend_url_override"
  );
  assert.strictEqual(
    MentorConfig.DEV_BACKEND_URL,
    "http://127.0.0.1:8000",
    "Dev backend URL must be http://127.0.0.1:8000"
  );
});

test("2. Valid localhost HTTP and HTTPS override sanitization", () => {
  const sanitize = MentorConfig.sanitizeBackendUrl;

  // Localhost variants
  assert.strictEqual(sanitize("http://127.0.0.1:8000"), "http://127.0.0.1:8000");
  assert.strictEqual(sanitize("http://127.0.0.1:8000/"), "http://127.0.0.1:8000");
  assert.strictEqual(sanitize("http://127.0.0.1:8000///"), "http://127.0.0.1:8000");
  assert.strictEqual(sanitize("http://localhost:8000"), "http://localhost:8000");
  assert.strictEqual(sanitize("http://localhost:3000/api/"), "http://localhost:3000/api");
  assert.strictEqual(sanitize("http://app.localhost:8080"), "http://app.localhost:8080");
  assert.strictEqual(sanitize("http://[::1]:8000"), "http://[::1]:8000");

  // Valid HTTPS override
  assert.strictEqual(sanitize("https://custom-deploy.example.com/"), "https://custom-deploy.example.com");
  assert.strictEqual(sanitize("https://ai-browser-mentor.onrender.com"), "https://ai-browser-mentor.onrender.com");
});

test("3. Insecure remote HTTP and malformed override rejection", () => {
  const sanitize = MentorConfig.sanitizeBackendUrl;
  const expectedDefault = "https://ai-browser-mentor.onrender.com";

  // Insecure remote HTTP (must reject)
  assert.strictEqual(sanitize("http://insecure-remote.com"), expectedDefault);
  assert.strictEqual(sanitize("http://192.168.1.100:8000"), expectedDefault);
  assert.strictEqual(sanitize("http://10.0.0.1:8000"), expectedDefault);
  assert.strictEqual(sanitize("http://evil.attacker.com"), expectedDefault);

  // Embedded credentials (must reject)
  assert.strictEqual(sanitize("http://attacker.com:80@localhost"), expectedDefault);
  assert.strictEqual(sanitize("http://user:pass@127.0.0.1:8000"), expectedDefault);
  assert.strictEqual(sanitize("https://user:pass@example.com"), expectedDefault);
  assert.strictEqual(sanitize("http://user@localhost:8000"), expectedDefault);
  assert.strictEqual(sanitize("http://localhost:8000@attacker.com"), expectedDefault);

  // Query strings and fragments (must reject)
  assert.strictEqual(sanitize("http://localhost:8000?query=1"), expectedDefault);
  assert.strictEqual(sanitize("http://localhost:8000/#fragment"), expectedDefault);
  assert.strictEqual(sanitize("https://example.com/api?token=secret"), expectedDefault);
  assert.strictEqual(sanitize("https://example.com/api#anchor"), expectedDefault);
  assert.strictEqual(sanitize("http://127.0.0.1:8000/?"), expectedDefault);
  assert.strictEqual(sanitize("http://127.0.0.1:8000/#"), expectedDefault);

  // Invalid / Malformed inputs
  assert.strictEqual(sanitize(""), expectedDefault);
  assert.strictEqual(sanitize("   "), expectedDefault);
  assert.strictEqual(sanitize(null), expectedDefault);
  assert.strictEqual(sanitize(undefined), expectedDefault);
  assert.strictEqual(sanitize(12345), expectedDefault);
  assert.strictEqual(sanitize("not-a-valid-url"), expectedDefault);
  assert.strictEqual(sanitize("javascript:alert(1)"), expectedDefault);
  assert.strictEqual(sanitize("ftp://localhost:8000"), expectedDefault);
  assert.strictEqual(sanitize("//localhost:8000"), expectedDefault);
});

test("4. chrome.storage.local resolution with fallback and mock environments", async () => {
  // Save original global chrome
  const originalChrome = global.chrome;

  try {
    // 4a. When chrome is undefined
    delete global.chrome;
    const urlWithoutChrome = await MentorConfig.resolveBackendUrl();
    assert.strictEqual(urlWithoutChrome, MentorConfig.DEFAULT_BACKEND_URL);

    // 4b. When chrome.storage.local returns empty
    global.chrome = {
      storage: {
        local: {
          get: (keys, cb) => cb({})
        }
      }
    };
    const urlEmptyStorage = await MentorConfig.resolveBackendUrl();
    assert.strictEqual(urlEmptyStorage, MentorConfig.DEFAULT_BACKEND_URL);

    // 4c. When chrome.storage.local returns valid localhost override
    global.chrome = {
      storage: {
        local: {
          get: (keys, cb) => cb({ abm_backend_url_override: "http://127.0.0.1:8000/" })
        }
      }
    };
    const urlValidOverride = await MentorConfig.resolveBackendUrl();
    assert.strictEqual(urlValidOverride, "http://127.0.0.1:8000");

    // 4d. When chrome.storage.local returns insecure remote override
    global.chrome = {
      storage: {
        local: {
          get: (keys, cb) => cb({ abm_backend_url_override: "http://malicious.org" })
        }
      }
    };
    const urlRejectedOverride = await MentorConfig.resolveBackendUrl();
    assert.strictEqual(urlRejectedOverride, MentorConfig.DEFAULT_BACKEND_URL);

    // 4e. When chrome.runtime.lastError occurs
    global.chrome = {
      runtime: { lastError: new Error("Quota exceeded") },
      storage: {
        local: {
          get: (keys, cb) => cb(null)
        }
      }
    };
    const urlErrorFallback = await MentorConfig.resolveBackendUrl();
    assert.strictEqual(urlErrorFallback, MentorConfig.DEFAULT_BACKEND_URL);
  } finally {
    global.chrome = originalChrome;
  }
});

test("5. Manifest.json structure and content_scripts ordering", () => {
  const manifestRaw = fs.readFileSync(manifestPath, "utf-8");
  const manifest = JSON.parse(manifestRaw);

  assert.strictEqual(manifest.manifest_version, 3);
  assert.ok(Array.isArray(manifest.content_scripts), "content_scripts must be an array");
  assert.ok(manifest.content_scripts.length > 0, "content_scripts must not be empty");

  const cs = manifest.content_scripts[0];
  assert.deepStrictEqual(cs.js, ["config.js", "content.js"], "config.js must precede content.js in manifest content_scripts");

  // Ensure permissions were not broadened
  assert.deepStrictEqual(
    manifest.permissions,
    ["storage", "tabs", "scripting", "activeTab"],
    "Permissions must match expected set exactly"
  );
  assert.deepStrictEqual(
    manifest.host_permissions,
    ["http://*/*", "https://*/*"],
    "Host permissions must match expected set exactly"
  );
});

test("6. HTML script tags load config.js before application scripts", () => {
  const popupHtml = fs.readFileSync(popupHtmlPath, "utf-8");
  const workspaceHtml = fs.readFileSync(workspaceHtmlPath, "utf-8");

  // popup.html
  const configPopupIdx = popupHtml.indexOf('<script src="config.js"></script>');
  const popupJsIdx = popupHtml.indexOf('<script src="popup.js"></script>');
  assert.ok(configPopupIdx !== -1, "popup.html must load config.js");
  assert.ok(popupJsIdx !== -1, "popup.html must load popup.js");
  assert.ok(configPopupIdx < popupJsIdx, "popup.html must load config.js before popup.js");

  // workspace.html
  const configWsIdx = workspaceHtml.indexOf('<script src="config.js"></script>');
  const wsJsIdx = workspaceHtml.indexOf('<script src="workspace.js"></script>');
  assert.ok(configWsIdx !== -1, "workspace.html must load config.js");
  assert.ok(wsJsIdx !== -1, "workspace.html must load workspace.js");
  assert.ok(configWsIdx < wsJsIdx, "workspace.html must load config.js before workspace.js");
});

test("7. Script recovery and dynamic error messaging in popup.js, workspace.js, and content.js", () => {
  const popupJs = fs.readFileSync(popupJsPath, "utf-8");
  const workspaceJs = fs.readFileSync(workspaceJsPath, "utf-8");
  const contentJs = fs.readFileSync(contentJsPath, "utf-8");

  // Recovery injection in popup.js must inject config.js before content.js
  assert.ok(
    popupJs.includes('files: ["config.js", "content.js"]'),
    "popup.js recovery injection must include config.js before content.js"
  );

  // Dynamic error messages
  assert.ok(
    popupJs.includes("Verify backend is running on ${BACKEND_URL}."),
    "popup.js renderWorkspaceError must reference dynamic ${BACKEND_URL}"
  );
  assert.ok(
    workspaceJs.includes("Please check that the backend server is running on ${BACKEND_URL}."),
    "workspace.js renderErrorResult must reference dynamic ${BACKEND_URL}"
  );

  // content.js awaits getEffectiveApiBaseUrl()
  assert.ok(
    contentJs.includes("const baseUrl = await getEffectiveApiBaseUrl();"),
    "content.js post() must await getEffectiveApiBaseUrl() before issuing fetch"
  );

  // Safe MentorConfig guards in all three scripts
  assert.ok(popupJs.includes("typeof MentorConfig"), "popup.js must guard MentorConfig usage");
  assert.ok(workspaceJs.includes("typeof MentorConfig"), "workspace.js must guard MentorConfig usage");
  assert.ok(contentJs.includes("typeof MentorConfig"), "content.js must guard MentorConfig usage");
});

test("8. Delayed initial URL resolution does not clobber storage-change override in content.js", async () => {
  const vm = require("node:vm");

  let delayedResolve;
  const delayedPromise = new Promise((resolve) => {
    delayedResolve = resolve;
  });

  const mockMentorConfig = {
    DEFAULT_BACKEND_URL: "https://ai-browser-mentor.onrender.com",
    STORAGE_KEY: "abm_backend_url_override",
    sanitizeBackendUrl: MentorConfig.sanitizeBackendUrl,
    resolveBackendUrl: () => delayedPromise,
  };

  let storageChangedListener = null;

  const sandbox = {
    console: { warn: () => {}, log: () => {}, error: () => {} },
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    setInterval: setInterval,
    clearInterval: clearInterval,
    URL: URL,
    addEventListener: () => {},
    removeEventListener: () => {},
    history: { pushState: () => {}, replaceState: () => {} },
    location: { href: "https://example.com" },
    document: {
      querySelectorAll: () => [],
      getElementById: () => null,
      createElement: () => ({ style: {}, appendChild: () => {}, setAttribute: () => {} }),
      body: { appendChild: () => {} },
      head: { appendChild: () => {} }
    },
    window: {},
    globalThis: {},
    MentorConfig: mockMentorConfig,
    chrome: {
      runtime: { onMessage: { addListener: () => {} } },
      storage: {
        local: { get: (keys, cb) => cb({}) },
        onChanged: {
          addListener: (fn) => { storageChangedListener = fn; }
        }
      }
    }
  };
  sandbox.window = sandbox.globalThis;
  sandbox.globalThis = sandbox;

  const contentCode = fs.readFileSync(contentJsPath, "utf-8");
  vm.createContext(sandbox);
  vm.runInContext(contentCode, sandbox);

  // Storage change arrives BEFORE delayed initial resolveBackendUrl finishes
  assert.ok(storageChangedListener, "Storage listener must be registered");
  storageChangedListener(
    { abm_backend_url_override: { newValue: "http://localhost:9000" } },
    "local"
  );

  // Now settle the delayed initial resolution with an older value
  delayedResolve("http://127.0.0.1:8000");
  await delayedPromise;

  // Wait a tick for microtasks
  await new Promise((r) => setTimeout(r, 10));

  // Verify effective URL inside content.js sandbox remains http://localhost:9000
  const effectiveUrl = await vm.runInContext("getEffectiveApiBaseUrl()", sandbox);
  assert.strictEqual(
    effectiveUrl,
    "http://localhost:9000",
    "Effective URL must be http://localhost:9000 and not overwritten by older delayed resolution"
  );
});
