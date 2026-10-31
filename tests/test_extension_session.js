/**
 * Extension Session Lifecycle Verification Tests (Phase 2D - Stage 2)
 *
 * Verifies:
 * 1. MentorConfig session constants (SESSION_STORAGE_KEY, SESSION_TOKEN_PREFIX).
 * 2. Token format validation (isValidSessionToken).
 * 3. Token initialization via /session/init and storage in chrome.storage.local.
 * 4. Token reuse across calls without duplicate network requests.
 * 5. Concurrent in-flight call deduplication.
 * 6. Graceful failure handling on network errors without state corruption.
 * 7. Force refresh behavior.
 * 8. Safe messaging fallback when direct storage is unavailable.
 * 9. Token clearing (clearSessionToken).
 * 10. Background service worker message listener and sensitive log suppression.
 */

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const rootDir = path.resolve(__dirname, "..");
const configPath = path.join(rootDir, "extension", "config.js");
const backgroundJsPath = path.join(rootDir, "extension", "background.js");
const MentorConfig = require(configPath);

test("1. Session constants exported on MentorConfig", () => {
  assert.strictEqual(
    MentorConfig.SESSION_STORAGE_KEY,
    "abm_session_token",
    "Session storage key must be 'abm_session_token'"
  );
  assert.strictEqual(
    MentorConfig.SESSION_TOKEN_PREFIX,
    "abm_s_",
    "Session token prefix must be 'abm_s_'"
  );
  assert.strictEqual(
    typeof MentorConfig.isValidSessionToken,
    "function",
    "isValidSessionToken must be a function"
  );
  assert.strictEqual(
    typeof MentorConfig.getSessionToken,
    "function",
    "getSessionToken must be a function"
  );
  assert.strictEqual(
    typeof MentorConfig.initSession,
    "function",
    "initSession must be a function"
  );
  assert.strictEqual(
    typeof MentorConfig.clearSessionToken,
    "function",
    "clearSessionToken must be a function"
  );
});

test("2. isValidSessionToken validates token format strictly", () => {
  const { isValidSessionToken } = MentorConfig;

  // Valid tokens
  assert.strictEqual(isValidSessionToken("abm_s_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"), true);
  assert.strictEqual(isValidSessionToken("abm_s_" + "a".repeat(43)), true);
  assert.strictEqual(isValidSessionToken("token_with_valid_characters_1234567890"), true);

  // Invalid tokens
  assert.strictEqual(isValidSessionToken(""), false);
  assert.strictEqual(isValidSessionToken(null), false);
  assert.strictEqual(isValidSessionToken(undefined), false);
  assert.strictEqual(isValidSessionToken(12345), false);
  assert.strictEqual(isValidSessionToken({}), false);
  assert.strictEqual(isValidSessionToken("short"), false); // Under 24 chars
  assert.strictEqual(isValidSessionToken("abm_s_has spaces in token"), false);
  assert.strictEqual(isValidSessionToken("abm_s_has$special*characters!"), false);
  assert.strictEqual(isValidSessionToken("<script>alert(1)</script>"), false);
  assert.strictEqual(isValidSessionToken("a".repeat(300)), false); // Exceeds 256 chars
});

test("3. initSession acquires token via POST /session/init and writes to storage", async () => {
  await MentorConfig.clearSessionToken();
  const mockStorage = {};
  let fetchCalled = false;
  let fetchUrl = "";
  let fetchMethod = "";

  const fakeToken = "abm_s_" + "x".repeat(43);

  // Mock chrome.storage.local
  global.chrome = {
    storage: {
      local: {
        get: (keys, cb) => cb({ [keys[0]]: mockStorage[keys[0]] }),
        set: (obj, cb) => {
          Object.assign(mockStorage, obj);
          if (cb) cb();
        },
        remove: (keys, cb) => {
          keys.forEach((k) => delete mockStorage[k]);
          if (cb) cb();
        },
      },
    },
    runtime: { lastError: null },
  };

  // Mock global fetch
  const originalFetch = global.fetch;
  global.fetch = async (url, options) => {
    fetchCalled = true;
    fetchUrl = url;
    fetchMethod = options.method;
    return {
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        session_token: fakeToken,
      }),
    };
  };

  try {
    const token = await MentorConfig.initSession();

    assert.strictEqual(fetchCalled, true, "fetch must be called");
    assert.strictEqual(fetchUrl.endsWith("/session/init"), true, "Endpoint must be /session/init");
    assert.strictEqual(fetchMethod, "POST", "Method must be POST");
    assert.strictEqual(token, fakeToken, "Returned token must match server response");
    assert.strictEqual(
      mockStorage[MentorConfig.SESSION_STORAGE_KEY],
      fakeToken,
      "Token must be persisted in chrome.storage.local"
    );
  } finally {
    global.fetch = originalFetch;
    delete global.chrome;
    await MentorConfig.clearSessionToken();
  }
});

test("4. getSessionToken reuses existing token without network requests", async () => {
  await MentorConfig.clearSessionToken();
  const existingToken = "abm_s_" + "existing_token_stored_in_cache_999";
  const mockStorage = {
    [MentorConfig.SESSION_STORAGE_KEY]: existingToken,
  };

  let fetchCalled = false;
  global.chrome = {
    storage: {
      local: {
        get: (keys, cb) => cb({ [keys[0]]: mockStorage[keys[0]] }),
        set: (obj, cb) => {
          Object.assign(mockStorage, obj);
          if (cb) cb();
        },
        remove: (keys, cb) => {
          keys.forEach((k) => delete mockStorage[k]);
          if (cb) cb();
        },
      },
    },
    runtime: { lastError: null },
  };

  const originalFetch = global.fetch;
  global.fetch = async () => {
    fetchCalled = true;
    throw new Error("fetch should not be called when token is present");
  };

  try {
    const token = await MentorConfig.getSessionToken();
    assert.strictEqual(token, existingToken, "Existing token must be returned");
    assert.strictEqual(fetchCalled, false, "Network request must not occur when token is stored");
  } finally {
    global.fetch = originalFetch;
    delete global.chrome;
    await MentorConfig.clearSessionToken();
  }
});

test("5. initSession deduplicates concurrent in-flight requests", async () => {
  await MentorConfig.clearSessionToken();
  let fetchCount = 0;
  const mockStorage = {};
  const fakeToken = "abm_s_" + "dedup_token_test_1234567890123456";

  global.chrome = {
    storage: {
      local: {
        get: (keys, cb) => cb({ [keys[0]]: mockStorage[keys[0]] }),
        set: (obj, cb) => {
          Object.assign(mockStorage, obj);
          if (cb) cb();
        },
        remove: (keys, cb) => {
          keys.forEach((k) => delete mockStorage[k]);
          if (cb) cb();
        },
      },
    },
    runtime: { lastError: null },
  };

  const originalFetch = global.fetch;
  global.fetch = async () => {
    fetchCount++;
    // Simulate network delay
    await new Promise((r) => setTimeout(r, 20));
    return {
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        session_token: fakeToken,
      }),
    };
  };

  try {
    // Launch 3 simultaneous initSession calls
    const [t1, t2, t3] = await Promise.all([
      MentorConfig.initSession(),
      MentorConfig.initSession(),
      MentorConfig.initSession(),
    ]);

    assert.strictEqual(fetchCount, 1, "Only 1 network request must be made for concurrent init calls");
    assert.strictEqual(t1, fakeToken);
    assert.strictEqual(t2, fakeToken);
    assert.strictEqual(t3, fakeToken);
  } finally {
    global.fetch = originalFetch;
    delete global.chrome;
    await MentorConfig.clearSessionToken();
  }
});

test("6. Graceful failure on backend/network error without state corruption", async () => {
  await MentorConfig.clearSessionToken();
  const existingGoodToken = "abm_s_" + "good_token_before_failure_12345";
  const mockStorage = {
    [MentorConfig.SESSION_STORAGE_KEY]: existingGoodToken,
  };

  global.chrome = {
    storage: {
      local: {
        get: (keys, cb) => cb({ [keys[0]]: mockStorage[keys[0]] }),
        set: (obj, cb) => {
          Object.assign(mockStorage, obj);
          if (cb) cb();
        },
        remove: (keys, cb) => {
          keys.forEach((k) => delete mockStorage[k]);
          if (cb) cb();
        },
      },
    },
    runtime: { lastError: null },
  };

  const originalFetch = global.fetch;
  global.fetch = async () => {
    return {
      ok: false,
      status: 503,
      json: async () => ({ error: "Service Unavailable" }),
    };
  };

  try {
    const res = await MentorConfig.initSession();
    assert.strictEqual(res, null, "Failed init must return null");
    // Ensure the failure did not overwrite storage with null or undefined
    assert.strictEqual(
      mockStorage[MentorConfig.SESSION_STORAGE_KEY],
      existingGoodToken,
      "Storage must not be corrupted on failed initialization"
    );
  } finally {
    global.fetch = originalFetch;
    delete global.chrome;
    await MentorConfig.clearSessionToken();
  }
});

test("7. Force refresh requests a fresh token and updates storage", async () => {
  await MentorConfig.clearSessionToken();
  const oldToken = "abm_s_" + "old_token_before_refresh_1234567";
  const newToken = "abm_s_" + "new_refreshed_token_value_987654";
  const mockStorage = {
    [MentorConfig.SESSION_STORAGE_KEY]: oldToken,
  };

  global.chrome = {
    storage: {
      local: {
        get: (keys, cb) => cb({ [keys[0]]: mockStorage[keys[0]] }),
        set: (obj, cb) => {
          Object.assign(mockStorage, obj);
          if (cb) cb();
        },
        remove: (keys, cb) => {
          keys.forEach((k) => delete mockStorage[k]);
          if (cb) cb();
        },
      },
    },
    runtime: { lastError: null },
  };

  const originalFetch = global.fetch;
  global.fetch = async () => {
    return {
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        session_token: newToken,
      }),
    };
  };

  try {
    const refreshed = await MentorConfig.getSessionToken(true);
    assert.strictEqual(refreshed, newToken, "Refreshed token must be returned");
    assert.strictEqual(
      mockStorage[MentorConfig.SESSION_STORAGE_KEY],
      newToken,
      "Storage must be updated with the fresh token"
    );
  } finally {
    global.fetch = originalFetch;
    delete global.chrome;
    await MentorConfig.clearSessionToken();
  }
});

test("8. clearSessionToken removes token from storage and memory", async () => {
  const mockStorage = {
    [MentorConfig.SESSION_STORAGE_KEY]: "abm_s_" + "token_to_be_cleared_1234567",
  };

  global.chrome = {
    storage: {
      local: {
        get: (keys, cb) => cb({ [keys[0]]: mockStorage[keys[0]] }),
        set: (obj, cb) => {
          Object.assign(mockStorage, obj);
          if (cb) cb();
        },
        remove: (keys, cb) => {
          keys.forEach((k) => delete mockStorage[k]);
          if (cb) cb();
        },
      },
    },
    runtime: { lastError: null },
  };

  try {
    await MentorConfig.clearSessionToken();
    assert.strictEqual(
      mockStorage[MentorConfig.SESSION_STORAGE_KEY],
      undefined,
      "Token must be deleted from storage"
    );
  } finally {
    delete global.chrome;
  }
});

test("9. Messaging fallback when direct chrome.storage is unavailable", async () => {
  const fallbackToken = "abm_s_" + "fallback_token_via_messaging_12345";
  let messageSent = null;

  // chrome.storage is undefined; only chrome.runtime.sendMessage is available
  global.chrome = {
    runtime: {
      lastError: null,
      sendMessage: (msg, cb) => {
        messageSent = msg;
        if (msg.type === "ABM_GET_SESSION_TOKEN") {
          cb({ success: true, sessionToken: fallbackToken });
        } else if (msg.type === "ABM_CLEAR_SESSION_TOKEN") {
          cb({ success: true });
        } else if (msg.type === "ABM_SET_SESSION_TOKEN") {
          cb({ success: true });
        } else {
          cb({ success: false });
        }
      },
    },
  };

  // Clear in-memory token to force storage/messaging read
  await MentorConfig.clearSessionToken();

  try {
    const token = await MentorConfig.getSessionToken();
    assert.strictEqual(messageSent?.type, "ABM_GET_SESSION_TOKEN", "Fallback must send runtime message");
    assert.strictEqual(token, fallbackToken, "Token must be retrieved via runtime messaging");
  } finally {
    delete global.chrome;
    await MentorConfig.clearSessionToken();
  }
});

test("10. Background service worker handles session messages and suppresses credential logging", () => {
  const backgroundContent = fs.readFileSync(backgroundJsPath, "utf-8");

  assert.strictEqual(
    backgroundContent.includes("ABM_GET_SESSION_TOKEN"),
    true,
    "background.js must handle ABM_GET_SESSION_TOKEN message"
  );
  assert.strictEqual(
    backgroundContent.includes("ABM_SET_SESSION_TOKEN"),
    true,
    "background.js must handle ABM_SET_SESSION_TOKEN message"
  );
  assert.strictEqual(
    backgroundContent.includes("ABM_CLEAR_SESSION_TOKEN"),
    true,
    "background.js must handle ABM_CLEAR_SESSION_TOKEN message"
  );

  // Verify that ABM_ messages are not logged to console
  assert.strictEqual(
    backgroundContent.includes('!message?.type?.startsWith("ABM_")'),
    true,
    "background.js must suppress console logging for ABM_ session messages"
  );

  // Verify that external senders are rejected
  assert.strictEqual(
    backgroundContent.includes("sender.id !== chrome.runtime.id"),
    true,
    "background.js must reject messages with foreign sender ID"
  );
});

test("11. getAuthHeaders resolves X-Session-ID and fails closed on unauthenticated sessions", async () => {
  await MentorConfig.clearSessionToken();

  const validToken = "abm_s_" + "auth_header_valid_token_test_1234567";
  const mockStorage = {
    [MentorConfig.SESSION_STORAGE_KEY]: validToken,
  };

  global.chrome = {
    storage: {
      local: {
        get: (keys, cb) => cb({ [keys[0]]: mockStorage[keys[0]] }),
        set: (obj, cb) => {
          Object.assign(mockStorage, obj);
          if (cb) cb();
        },
        remove: (keys, cb) => {
          keys.forEach((k) => delete mockStorage[k]);
          if (cb) cb();
        },
      },
    },
    runtime: { lastError: null },
  };

  try {
    const headers = await MentorConfig.getAuthHeaders({ "Custom-Header": "foo" });
    assert.strictEqual(headers["Content-Type"], "application/json");
    assert.strictEqual(headers["X-Session-ID"], validToken);
    assert.strictEqual(headers["Custom-Header"], "foo");
  } finally {
    delete global.chrome;
    await MentorConfig.clearSessionToken();
  }

  // When token cannot be obtained (e.g. backend offline), must fail closed
  await MentorConfig.clearSessionToken();
  global.chrome = {
    storage: {
      local: {
        get: (keys, cb) => cb({}),
        set: (obj, cb) => cb && cb(),
        remove: (keys, cb) => cb && cb(),
      },
    },
    runtime: { lastError: null },
  };
  const originalFetch = global.fetch;
  global.fetch = async () => ({ ok: false, status: 503 });

  try {
    await assert.rejects(
      async () => await MentorConfig.getAuthHeaders(),
      /Could not obtain secure session token/,
      "getAuthHeaders must fail closed when session cannot be established"
    );
  } finally {
    global.fetch = originalFetch;
    delete global.chrome;
    await MentorConfig.clearSessionToken();
  }
});

test("12. popup.js uses crypto.randomUUID for pageId and authenticates API requests", () => {
  const popupJsPath = path.join(rootDir, "extension", "popup.js");
  const popupContent = fs.readFileSync(popupJsPath, "utf-8");

  assert.strictEqual(
    popupContent.includes("crypto.randomUUID()"),
    true,
    "popup.js must generate page IDs using crypto.randomUUID()"
  );

  assert.strictEqual(
    popupContent.includes("getAuthHeaders()"),
    true,
    "popup.js must use getAuthHeaders() for outgoing requests"
  );
});

test("13. content.js authenticates POST requests with X-Session-ID", () => {
  const contentJsPath = path.join(rootDir, "extension", "content.js");
  const contentCode = fs.readFileSync(contentJsPath, "utf-8");

  assert.strictEqual(
    contentCode.includes('requestHeaders["X-Session-ID"]'),
    true,
    "content.js must attach X-Session-ID to outgoing requests"
  );
});
