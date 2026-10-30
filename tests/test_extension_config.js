/**
 * Phase 1H & Phase 1I Verification Test Suite: Extension Backend URL Centralization & Permission Hardening
 *
 * Verifies:
 * 1. MentorConfig exports and default production URL (https://ai-browser-mentor.onrender.com).
 * 2. Valid localhost HTTP and HTTPS overrides with trailing slash sanitization.
 * 3. Insecure remote HTTP and malformed override rejection with fallback to production default.
 * 4. Safe chrome.storage.local resolution with error handling.
 * 5. Extension manifest permission hardening:
 *    - tabs permission is removed.
 *    - permissions contains only storage, scripting, activeTab.
 *    - host_permissions contains only approved backend origins.
 *    - optional_host_permissions declared for custom backend HTTPS.
 *    - content_scripts ordering and matches remain intact.
 * 6. Extension HTML script tag ordering (config.js before popup.js and workspace.js).
 * 7. Extension recovery injection ordering and active URL interpolation in error messages.
 * 8. Delayed initial URL resolution does not clobber storage-change override in content.js.
 * 9. Custom backend permission validation, request handling, and resolution guards.
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

test("5. Manifest.json permission hardening and content_scripts ordering", () => {
  const manifestRaw = fs.readFileSync(manifestPath, "utf-8");
  const manifest = JSON.parse(manifestRaw);

  assert.strictEqual(manifest.manifest_version, 3);
  assert.ok(Array.isArray(manifest.content_scripts), "content_scripts must be an array");
  assert.ok(manifest.content_scripts.length > 0, "content_scripts must not be empty");

  const cs = manifest.content_scripts[0];
  assert.deepStrictEqual(cs.js, ["config.js", "content.js"], "config.js must precede content.js in manifest content_scripts");

  // Content script matches must remain unchanged
  assert.deepStrictEqual(
    cs.matches,
    ["http://*/*", "https://*/*"],
    "Content script matches must remain http://*/* and https://*/*"
  );

  // Broad tabs permission must be removed
  assert.strictEqual(
    manifest.permissions.includes("tabs"),
    false,
    "The broad 'tabs' permission must be removed from manifest.json"
  );

  // Exact minimal permissions
  assert.deepStrictEqual(
    manifest.permissions,
    ["storage", "scripting", "activeTab"],
    "Permissions must match hardened minimal set exactly"
  );

  // Host permissions restricted to approved backend origins
  assert.deepStrictEqual(
    manifest.host_permissions,
    [
      "https://ai-browser-mentor.onrender.com/*",
      "http://localhost/*",
      "http://127.0.0.1/*"
    ],
    "Host permissions must match approved backend origins exactly"
  );

  // Optional host permissions declared for user-configured custom backends
  assert.deepStrictEqual(
    manifest.optional_host_permissions,
    ["https://*/*"],
    "Optional host permissions must support HTTPS patterns for custom backends"
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
    setInterval: (fn, ms) => {
      const timer = setInterval(fn, ms);
      if (timer && typeof timer.unref === "function") timer.unref();
      return timer;
    },
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

test("9. Custom backend permission validation, request handling, and resolution guards", async () => {
  const originalChrome = global.chrome;

  try {
    // 9a. Default origin checks matching static manifest host_permissions exactly
    assert.strictEqual(
      MentorConfig.isDefaultBackendOrigin("https://ai-browser-mentor.onrender.com"),
      true,
      "Official production domain must be recognized as default origin"
    );
    assert.strictEqual(
      MentorConfig.isDefaultBackendOrigin("http://localhost"),
      true,
      "Localhost HTTP without port must be recognized as default origin"
    );
    assert.strictEqual(
      MentorConfig.isDefaultBackendOrigin("http://localhost:8000"),
      true,
      "Localhost HTTP with port must be recognized as default origin"
    );
    assert.strictEqual(
      MentorConfig.isDefaultBackendOrigin("http://localhost:3000/api"),
      true,
      "Localhost HTTP with path must be recognized as default origin"
    );
    assert.strictEqual(
      MentorConfig.isDefaultBackendOrigin("http://127.0.0.1"),
      true,
      "127.0.0.1 HTTP without port must be recognized as default origin"
    );
    assert.strictEqual(
      MentorConfig.isDefaultBackendOrigin("http://127.0.0.1:8000"),
      true,
      "127.0.0.1 HTTP with port must be recognized as default origin"
    );

    // Explicit non-defaults: HTTPS localhost, IPv6 [::1], and .localhost subdomains
    assert.strictEqual(
      MentorConfig.isDefaultBackendOrigin("https://localhost"),
      false,
      "HTTPS localhost is not covered by static host_permissions"
    );
    assert.strictEqual(
      MentorConfig.isDefaultBackendOrigin("https://localhost:8000"),
      false,
      "HTTPS localhost with port is not covered by static host_permissions"
    );
    assert.strictEqual(
      MentorConfig.isDefaultBackendOrigin("https://127.0.0.1"),
      false,
      "HTTPS 127.0.0.1 is not covered by static host_permissions"
    );
    assert.strictEqual(
      MentorConfig.isDefaultBackendOrigin("https://127.0.0.1:8000"),
      false,
      "HTTPS 127.0.0.1 with port is not covered by static host_permissions"
    );
    assert.strictEqual(
      MentorConfig.isDefaultBackendOrigin("http://[::1]"),
      false,
      "IPv6 http://[::1] is not covered by static host_permissions"
    );
    assert.strictEqual(
      MentorConfig.isDefaultBackendOrigin("http://[::1]:8000"),
      false,
      "IPv6 http://[::1]:8000 is not covered by static host_permissions"
    );
    assert.strictEqual(
      MentorConfig.isDefaultBackendOrigin("http://app.localhost:8080"),
      false,
      "Subdomain .localhost is not covered by static host_permissions"
    );
    assert.strictEqual(
      MentorConfig.isDefaultBackendOrigin("https://custom-cloud.example.com"),
      false,
      "Remote custom domain must not be recognized as default origin"
    );

    // 9b. Origin pattern generation (Chrome match-pattern rules: no port numbers, no wildcards)
    assert.strictEqual(
      MentorConfig.getBackendOriginPattern("https://custom.example.com:8443/api/v1"),
      "https://custom.example.com/*",
      "Origin pattern must strip ports and paths to create valid Chrome match pattern"
    );
    assert.strictEqual(
      MentorConfig.getBackendOriginPattern("https://custom.example.com/deep/path/"),
      "https://custom.example.com/*",
      "Origin pattern must normalize paths to /*"
    );
    assert.strictEqual(
      MentorConfig.getBackendOriginPattern("https://custom.example.com:443/api?key=value#frag"),
      "https://custom.example.com/*",
      "Origin pattern must strip ports, query strings, and fragments"
    );
    assert.strictEqual(
      MentorConfig.getBackendOriginPattern("http://remote.example.com"),
      null,
      "HTTP remote origins must return null (only HTTPS allowed for custom host patterns)"
    );
    assert.strictEqual(
      MentorConfig.getBackendOriginPattern("https://*"),
      null,
      "Wildcard host https://* must be rejected to prevent accidental broad grant"
    );
    assert.strictEqual(
      MentorConfig.getBackendOriginPattern("https://*/*"),
      null,
      "Wildcard host https://*/* must be rejected"
    );
    assert.strictEqual(
      MentorConfig.getBackendOriginPattern("https://*.example.com"),
      null,
      "Subdomain wildcard must be rejected"
    );
    assert.strictEqual(
      MentorConfig.getBackendOriginPattern("invalid-url"),
      null,
      "Malformed URL must return null"
    );
    assert.strictEqual(
      MentorConfig.getBackendOriginPattern(""),
      null,
      "Empty URL must return null"
    );
    assert.strictEqual(
      MentorConfig.getBackendOriginPattern(null),
      null,
      "Null URL must return null"
    );

    // 9c. Fail closed when Chrome permissions API is unavailable
    delete global.chrome;
    const hasPermWithoutApi = await MentorConfig.hasBackendPermission("https://custom.example.com");
    assert.strictEqual(
      hasPermWithoutApi,
      false,
      "hasBackendPermission must fail closed (return false) when chrome.permissions is unavailable"
    );
    const reqPermWithoutApi = await MentorConfig.requestBackendPermission("https://custom.example.com");
    assert.strictEqual(
      reqPermWithoutApi.success,
      false,
      "requestBackendPermission must fail closed when chrome.permissions is unavailable"
    );
    assert.strictEqual(
      reqPermWithoutApi.url,
      MentorConfig.DEFAULT_BACKEND_URL
    );

    // But default origins and localhost always succeed without permissions API
    const hasDefaultPerm = await MentorConfig.hasBackendPermission("https://ai-browser-mentor.onrender.com");
    assert.strictEqual(hasDefaultPerm, true, "Default origin has static permission");
    const hasLocalhostPerm = await MentorConfig.hasBackendPermission("http://localhost:8000");
    assert.strictEqual(hasLocalhostPerm, true, "Localhost HTTP has static permission");
    const hasIpPerm = await MentorConfig.hasBackendPermission("http://127.0.0.1:8000");
    assert.strictEqual(hasIpPerm, true, "127.0.0.1 HTTP has static permission");

    // 9d. Explicit Chrome permissions mock
    let promptCalled = false;
    global.chrome = {
      permissions: {
        contains: (opts, cb) => cb(false),
        request: (opts, cb) => {
          promptCalled = true;
          cb(true);
        }
      }
    };

    // Default origins never trigger prompt
    const resDefault = await MentorConfig.requestBackendPermission("https://ai-browser-mentor.onrender.com");
    assert.strictEqual(resDefault.success, true);
    assert.strictEqual(promptCalled, false, "Default origin must never prompt for optional permissions");

    const resLocal = await MentorConfig.requestBackendPermission("http://localhost:8000");
    assert.strictEqual(resLocal.success, true);
    assert.strictEqual(promptCalled, false, "Localhost origin must never prompt for optional permissions");

    // 9e. Insecure remote HTTP backend is rejected without prompt
    const resInsecure = await MentorConfig.requestBackendPermission("http://insecure-remote.example.com");
    assert.strictEqual(resInsecure.success, false);
    assert.strictEqual(promptCalled, false, "Insecure remote HTTP must be rejected without prompt");
    assert.ok(resInsecure.reason.includes("HTTPS"), "Rejection reason must mention HTTPS requirement");

    // 9f. Custom HTTPS backend prompts for permission synchronously without prior contains() check
    let requestInvokedSynchronously = false;
    let containsCalled = false;
    global.chrome.permissions.contains = (opts, cb) => {
      containsCalled = true;
      cb(false);
    };
    global.chrome.permissions.request = (opts, cb) => {
      requestInvokedSynchronously = true;
      cb(true);
    };

    const reqPromise = MentorConfig.requestBackendPermission("https://custom-model-server.org:8443/api");

    // Assert synchronously before awaiting promise resolution
    assert.strictEqual(
      requestInvokedSynchronously,
      true,
      "chrome.permissions.request must be invoked synchronously within the call stack to preserve user gesture"
    );
    assert.strictEqual(
      containsCalled,
      false,
      "requestBackendPermission must not invoke contains() prior to requesting permission"
    );

    const resGranted = await reqPromise;
    assert.strictEqual(resGranted.success, true);
    assert.strictEqual(resGranted.url, "https://custom-model-server.org:8443/api");

    // 9g. Custom HTTPS backend handles user denial gracefully
    global.chrome.permissions.request = (opts, cb) => cb(false);
    const resDenied = await MentorConfig.requestBackendPermission("https://untrusted-host.example.com");
    assert.strictEqual(resDenied.success, false);
    assert.strictEqual(resDenied.url, MentorConfig.DEFAULT_BACKEND_URL);
    assert.ok(resDenied.reason.includes("denied"), "Failure reason must state that permission was denied");

    // 9h. resolveBackendUrl falls back to default if custom remote origin lacks permission
    global.chrome.permissions.contains = (opts, cb) => cb(false);
    global.chrome.storage = {
      local: {
        get: (keys, cb) => cb({ abm_backend_url_override: "https://unapproved-backend.com" })
      }
    };
    const resolvedDenied = await MentorConfig.resolveBackendUrl();
    assert.strictEqual(
      resolvedDenied,
      MentorConfig.DEFAULT_BACKEND_URL,
      "resolveBackendUrl must fall back to default when stored remote URL lacks host permission"
    );

    // 9i. resolveBackendUrl succeeds if custom remote origin has permission
    global.chrome.permissions.contains = (opts, cb) => cb(true);
    const resolvedApproved = await MentorConfig.resolveBackendUrl();
    assert.strictEqual(
      resolvedApproved,
      "https://unapproved-backend.com",
      "resolveBackendUrl must return custom URL when host permission is present"
    );
  } finally {
    global.chrome = originalChrome;
  }
});

test("10. Inline backend configuration UI structure and absence of window.prompt", () => {
  const popupHtml = fs.readFileSync(popupHtmlPath, "utf-8");
  const popupJs = fs.readFileSync(popupJsPath, "utf-8");

  // Verify inline configuration section and controls in popup.html
  assert.ok(popupHtml.includes('id="backendConfigSection"'), "popup.html must include backendConfigSection");
  assert.ok(popupHtml.includes('id="backendUrlInput"'), "popup.html must include backendUrlInput");
  assert.ok(popupHtml.includes('id="btnGrantSaveBackend"'), "popup.html must include btnGrantSaveBackend");
  assert.ok(popupHtml.includes('id="btnResetBackend"'), "popup.html must include btnResetBackend");
  assert.ok(popupHtml.includes('id="backendConfigStatus"'), "popup.html must include backendConfigStatus");

  // Verify absence of window.prompt in popup.js
  assert.strictEqual(
    popupJs.includes("window.prompt"),
    false,
    "popup.js must not contain any window.prompt calls"
  );

  // Verify direct synchronous permission request inside btnGrantSaveBackend listener
  assert.ok(
    popupJs.includes("btnGrantSaveBackend.addEventListener"),
    "popup.js must attach event listener directly to btnGrantSaveBackend"
  );
  assert.ok(
    popupJs.includes("chrome.permissions.request({ origins: [pattern] }"),
    "popup.js must invoke chrome.permissions.request directly inside the button click listener"
  );
});
