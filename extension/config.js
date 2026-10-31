// ============================================================
// AI BROWSER MENTOR - GLOBAL CONFIGURATION
// Single source of truth for extension backend connectivity
// ============================================================

(() => {
  "use strict";

  const DEFAULT_BACKEND_URL = "https://ai-browser-mentor.onrender.com";
  const DEV_BACKEND_URL = "http://127.0.0.1:8000";
  const STORAGE_KEY = "abm_backend_url_override";
  const SESSION_STORAGE_KEY = "abm_session_token";
  const SESSION_TOKEN_PREFIX = "abm_s_";
  const SESSION_TOKEN_REGEX = /^[A-Za-z0-9_-]{24,256}$/;

  let cachedSessionToken = null;
  let initSessionPromise = null;

  /**
   * Check whether a given URL is covered by the static host_permissions in manifest.json:
   * - https://ai-browser-mentor.onrender.com/*
   * - http://localhost/* (any port)
   * - http://127.0.0.1/* (any port)
   *
   * Note:
   * - https://localhost and https://127.0.0.1 are NOT statically permitted.
   * - http://[::1] is NOT statically permitted.
   * - Subdomains like http://app.localhost are NOT statically permitted.
   */
  function isDefaultBackendOrigin(rawUrl) {
    if (!rawUrl || typeof rawUrl !== "string") {
      return false;
    }
    try {
      const parsed = new URL(rawUrl.trim());
      const hostname = parsed.hostname.toLowerCase();
      const protocol = parsed.protocol.toLowerCase();

      // Exactly matches https://ai-browser-mentor.onrender.com
      if (protocol === "https:" && hostname === "ai-browser-mentor.onrender.com") {
        return true;
      }

      // Exactly matches http://localhost and http://127.0.0.1 (with any valid port)
      if (protocol === "http:" && (hostname === "localhost" || hostname === "127.0.0.1")) {
        return true;
      }

      return false;
    } catch {
      return false;
    }
  }

  /**
   * Derive Chrome match-pattern origin from a URL string for permissions API.
   * Chrome match patterns for host permissions follow:
   *   <scheme>://<host>/<path>
   * Where:
   * - Scheme must be "https" for remote custom backends.
   * - Host cannot include port numbers (e.g. :8443 is invalid in Chrome match patterns).
   * - Wildcard host (e.g. "*" or subdomains) is prohibited to prevent accidental broad grants.
   *
   * Example: "https://custom.example.com:8443/api" -> "https://custom.example.com/*"
   */
  function getBackendOriginPattern(rawUrl) {
    if (!rawUrl || typeof rawUrl !== "string") {
      return null;
    }
    try {
      const parsed = new URL(rawUrl.trim());
      const protocol = parsed.protocol.toLowerCase();
      const hostname = parsed.hostname.toLowerCase();

      // Only allow https: for custom host permission requests
      if (protocol !== "https:") {
        return null;
      }

      // Reject empty, wildcard, or invalid hostnames to prevent granting broad permissions
      if (!hostname || hostname === "*" || hostname.includes("*")) {
        return null;
      }

      // Chrome match patterns require hostname without port and path "/*"
      return `https://${hostname}/*`;
    } catch {
      return null;
    }
  }

  /**
   * Validate and sanitize a backend URL string.
   * Security rules:
   * - Allows any valid https:// URL.
   * - Allows http:// strictly for local development (localhost, 127.0.0.1, ::1, *.localhost).
   * - Rejects remote insecure http:// URLs.
   * - Strips trailing slashes.
   * - Falls back safely to DEFAULT_BACKEND_URL on invalid input.
   */
  function sanitizeBackendUrl(rawUrl) {
    if (!rawUrl || typeof rawUrl !== "string") {
      return DEFAULT_BACKEND_URL;
    }

    const trimmed = rawUrl.trim().replace(/\/+$/, "");
    if (!trimmed) {
      return DEFAULT_BACKEND_URL;
    }

    try {
      const parsed = new URL(trimmed);
      const protocol = parsed.protocol.toLowerCase();
      const hostname = parsed.hostname.toLowerCase();

      // Reject embedded username / password credentials
      if (parsed.username || parsed.password || trimmed.includes("@")) {
        console.warn("AI Browser Mentor: URL credentials rejected in backend URL override:", trimmed);
        return DEFAULT_BACKEND_URL;
      }

      // Reject query strings and fragments in base URLs
      if (parsed.search || parsed.hash || trimmed.includes("?") || trimmed.includes("#")) {
        console.warn("AI Browser Mentor: Query strings and fragments rejected in backend URL override:", trimmed);
        return DEFAULT_BACKEND_URL;
      }

      // Allow production HTTPS
      if (protocol === "https:") {
        return trimmed;
      }

      // Allow HTTP strictly for local development
      if (protocol === "http:") {
        const isLocalhost = (
          hostname === "localhost" ||
          hostname === "127.0.0.1" ||
          hostname === "::1" ||
          hostname === "[::1]" ||
          hostname.endsWith(".localhost")
        );
        if (isLocalhost) {
          return trimmed;
        }
      }

      console.warn("AI Browser Mentor: Insecure remote HTTP backend URL override rejected:", trimmed);
      return DEFAULT_BACKEND_URL;
    } catch {
      console.warn("AI Browser Mentor: Malformed backend URL override rejected:", trimmed);
      return DEFAULT_BACKEND_URL;
    }
  }

  /**
   * Check whether permission has been granted for the given backend URL.
   * Default origins and local development hosts statically declared in manifest always return true.
   * Remote custom origins check chrome.permissions.contains.
   * Fails closed (returns false) if chrome.permissions API is unavailable.
   */
  async function hasBackendPermission(rawUrl) {
    if (!rawUrl || typeof rawUrl !== "string") {
      return false;
    }
    if (isDefaultBackendOrigin(rawUrl)) {
      return true;
    }

    const pattern = getBackendOriginPattern(rawUrl);
    if (!pattern) {
      return false;
    }

    if (
      typeof chrome !== "undefined" &&
      chrome.permissions &&
      typeof chrome.permissions.contains === "function"
    ) {
      return new Promise((resolve) => {
        try {
          chrome.permissions.contains({ origins: [pattern] }, (result) => {
            if (chrome.runtime && chrome.runtime.lastError) {
              resolve(false);
            } else {
              resolve(Boolean(result));
            }
          });
        } catch {
          resolve(false);
        }
      });
    }

    // Fail closed if chrome.permissions API is unavailable
    return false;
  }

  /**
   * Validate and request optional host permission for a custom backend URL.
   * Invokes chrome.permissions.request() synchronously within the user gesture call stack
   * without preceding asynchronous contains() checks to preserve Chrome user activation.
   * Ensures HTTPS for remote backends, handles permission denial gracefully,
   * fails closed if the permissions API is unavailable, and never prompts for default or localhost origins.
   *
   * @param {string} rawUrl - Proposed backend URL
   * @returns {Promise<{success: boolean, url: string, reason?: string}>}
   */
  function requestBackendPermission(rawUrl) {
    if (!rawUrl || typeof rawUrl !== "string" || !rawUrl.trim()) {
      return Promise.resolve({
        success: true,
        url: DEFAULT_BACKEND_URL,
      });
    }

    const trimmed = rawUrl.trim();
    const sanitized = sanitizeBackendUrl(trimmed);

    // If sanitizeBackendUrl returned DEFAULT_BACKEND_URL while rawUrl wasn't pointing to it,
    // the input was rejected (e.g. insecure remote HTTP, credentials, invalid syntax).
    const parsedRaw = (() => {
      try { return new URL(trimmed); } catch { return null; }
    })();
    if (parsedRaw && parsedRaw.protocol === "http:" && !isDefaultBackendOrigin(trimmed)) {
      return Promise.resolve({
        success: false,
        url: DEFAULT_BACKEND_URL,
        reason: "Insecure remote HTTP is not permitted. Custom backends must use HTTPS or run locally (localhost/127.0.0.1).",
      });
    }
    if (sanitized === DEFAULT_BACKEND_URL && !trimmed.includes("ai-browser-mentor.onrender.com")) {
      return Promise.resolve({
        success: false,
        url: DEFAULT_BACKEND_URL,
        reason: "Malformed or invalid backend URL. Base URLs cannot contain credentials, query strings, or fragments.",
      });
    }

    // Default origins and local development hosts are covered by host_permissions
    if (isDefaultBackendOrigin(sanitized)) {
      return Promise.resolve({
        success: true,
        url: sanitized,
      });
    }

    const pattern = getBackendOriginPattern(sanitized);
    if (!pattern) {
      return Promise.resolve({
        success: false,
        url: DEFAULT_BACKEND_URL,
        reason: "Could not determine origin pattern for permission request.",
      });
    }

    // Fail closed if permissions API is unavailable
    if (
      typeof chrome === "undefined" ||
      !chrome.permissions ||
      typeof chrome.permissions.request !== "function"
    ) {
      return Promise.resolve({
        success: false,
        url: DEFAULT_BACKEND_URL,
        reason: "Chrome permissions API is unavailable. Cannot grant host permission.",
      });
    }

    // Request permission synchronously within the current user gesture call stack.
    // Chrome does not re-prompt if the origin is already granted.
    return new Promise((resolve) => {
      try {
        chrome.permissions.request({ origins: [pattern] }, (granted) => {
          if (chrome.runtime && chrome.runtime.lastError) {
            resolve({
              success: false,
              url: DEFAULT_BACKEND_URL,
              reason: `Permission request failed: ${chrome.runtime.lastError.message}`,
            });
          } else if (granted) {
            resolve({
              success: true,
              url: sanitized,
            });
          } else {
            resolve({
              success: false,
              url: DEFAULT_BACKEND_URL,
              reason: `Host permission was denied for ${pattern}. Cannot connect to custom backend without permission.`,
            });
          }
        });
      } catch (err) {
        resolve({
          success: false,
          url: DEFAULT_BACKEND_URL,
          reason: `Permission request error: ${err.message || err}`,
        });
      }
    });
  }

  /**
   * Asynchronously resolve the effective backend URL from chrome.storage.local
   * with fallback to DEFAULT_BACKEND_URL.
   * If a custom remote URL is stored, verifies that host permission is present.
   */
  async function resolveBackendUrl() {
    if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
      try {
        const res = await new Promise((resolve) => {
          chrome.storage.local.get([STORAGE_KEY], (items) => {
            if (chrome.runtime && chrome.runtime.lastError) {
              resolve(null);
            } else {
              resolve(items ? items[STORAGE_KEY] : null);
            }
          });
        });
        if (res) {
          const sanitized = sanitizeBackendUrl(res);
          if (sanitized !== DEFAULT_BACKEND_URL && !isDefaultBackendOrigin(sanitized)) {
            const hasPerm = await hasBackendPermission(sanitized);
            if (!hasPerm) {
              console.warn(
                "AI Browser Mentor: Custom backend URL lacks host permission, falling back to default:",
                sanitized
              );
              return DEFAULT_BACKEND_URL;
            }
          }
          return sanitized;
        }
      } catch (err) {
        console.warn("AI Browser Mentor: Failed to read backend URL from storage:", err);
      }
    }
    return DEFAULT_BACKEND_URL;
  }

  /**
   * Validate that a session token adheres to length and character-set requirements.
   * Only base64url characters [A-Za-z0-9_-] with length 24-256 are permitted.
   */
  function isValidSessionToken(token) {
    if (!token || typeof token !== "string") {
      return false;
    }
    const trimmed = token.trim();
    if (trimmed.length < 24 || trimmed.length > 256) {
      return false;
    }
    return SESSION_TOKEN_REGEX.test(trimmed);
  }

  /**
   * Read stored session token from chrome.storage.local with safe messaging fallback
   * for sandboxed or content-script environments where direct storage is unavailable.
   */
  function readStoredToken() {
    return new Promise((resolve) => {
      // 1. Direct chrome.storage.local access
      if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
        try {
          chrome.storage.local.get([SESSION_STORAGE_KEY], (items) => {
            if (chrome.runtime && chrome.runtime.lastError) {
              resolve(null);
            } else {
              const val = items ? items[SESSION_STORAGE_KEY] : null;
              resolve(typeof val === "string" ? val : null);
            }
          });
          return;
        } catch {
          // Fall through to messaging fallback
        }
      }

      // 2. Safe messaging fallback if direct storage is unavailable
      if (typeof chrome !== "undefined" && chrome.runtime && typeof chrome.runtime.sendMessage === "function") {
        try {
          chrome.runtime.sendMessage({ type: "ABM_GET_SESSION_TOKEN" }, (response) => {
            if (chrome.runtime && chrome.runtime.lastError) {
              resolve(null);
            } else if (response && response.success && response.sessionToken) {
              resolve(response.sessionToken);
            } else {
              resolve(null);
            }
          });
          return;
        } catch {
          resolve(null);
        }
      }

      // 3. In-memory fallback
      resolve(cachedSessionToken || null);
    });
  }

  /**
   * Write session token to storage with safe messaging fallback.
   * Never persists invalid, empty, or corrupt tokens.
   */
  function writeStoredToken(token) {
    if (!isValidSessionToken(token)) {
      return Promise.resolve(false);
    }
    cachedSessionToken = token;

    return new Promise((resolve) => {
      if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
        try {
          chrome.storage.local.set({ [SESSION_STORAGE_KEY]: token }, () => {
            resolve(!Boolean(chrome.runtime && chrome.runtime.lastError));
          });
          return;
        } catch {
          // Fall through to messaging fallback
        }
      }

      if (typeof chrome !== "undefined" && chrome.runtime && typeof chrome.runtime.sendMessage === "function") {
        try {
          chrome.runtime.sendMessage({ type: "ABM_SET_SESSION_TOKEN", token }, (response) => {
            resolve(Boolean(response && response.success));
          });
          return;
        } catch {
          resolve(false);
        }
      }

      resolve(true);
    });
  }

  /**
   * Remove stored session token from persistent storage and memory.
   */
  function removeStoredToken() {
    cachedSessionToken = null;

    return new Promise((resolve) => {
      if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
        try {
          chrome.storage.local.remove([SESSION_STORAGE_KEY], () => {
            resolve(!Boolean(chrome.runtime && chrome.runtime.lastError));
          });
          return;
        } catch {
          // Fall through
        }
      }

      if (typeof chrome !== "undefined" && chrome.runtime && typeof chrome.runtime.sendMessage === "function") {
        try {
          chrome.runtime.sendMessage({ type: "ABM_CLEAR_SESSION_TOKEN" }, (response) => {
            resolve(Boolean(response && response.success));
          });
          return;
        } catch {
          resolve(false);
        }
      }

      resolve(true);
    });
  }

  /**
   * Request a fresh session token from the backend /session/init endpoint.
   * In-flight deduplication ensures concurrent calls share a single network request.
   * Never logs raw tokens. Does not save corrupt state on failure.
   */
  async function initSession() {
    if (initSessionPromise) {
      return initSessionPromise;
    }

    initSessionPromise = (async () => {
      try {
        const backendUrl = await resolveBackendUrl();
        const initUrl = `${backendUrl}/session/init`;

        const response = await fetch(initUrl, {
          method: "POST",
          headers: {
            "Accept": "application/json",
          },
        });

        if (!response.ok) {
          console.warn("AI Browser Mentor: Failed to initialize session (status: " + response.status + ")");
          return null;
        }

        const data = await response.json();
        if (data && data.success && isValidSessionToken(data.session_token)) {
          await writeStoredToken(data.session_token);
          return data.session_token;
        }

        console.warn("AI Browser Mentor: Server returned invalid session token structure");
        return null;
      } catch (err) {
        console.warn("AI Browser Mentor: Network error during session initialization");
        return null;
      } finally {
        initSessionPromise = null;
      }
    })();

    return initSessionPromise;
  }

  /**
   * Retrieve the active session token.
   * - If cached or in storage, returns the existing token (reusing it).
   * - If missing or forceRefresh is true, requests a new token via initSession().
   * - Returns null if the backend is unreachable or initialization fails.
   */
  async function getSessionToken(forceRefresh = false) {
    if (!forceRefresh) {
      if (isValidSessionToken(cachedSessionToken)) {
        return cachedSessionToken;
      }

      const stored = await readStoredToken();
      if (isValidSessionToken(stored)) {
        cachedSessionToken = stored;
        return stored;
      }
    }

    return await initSession();
  }

  /**
   * Clear active session token from cache and persistent storage.
   */
  async function clearSessionToken() {
    return await removeStoredToken();
  }

  /**
   * Helper that resolves standard authentication headers for backend API requests.
   * Fails closed (throws an Error) if session initialization failed.
   */
  async function getAuthHeaders(extraHeaders = {}) {
    const token = await getSessionToken();
    if (!token) {
      throw new Error("Could not obtain secure session token from backend.");
    }
    return {
      "Content-Type": "application/json",
      "X-Session-ID": token,
      ...extraHeaders,
    };
  }

  const MentorConfig = {
    DEFAULT_BACKEND_URL,
    DEV_BACKEND_URL,
    STORAGE_KEY,
    SESSION_STORAGE_KEY,
    SESSION_TOKEN_PREFIX,
    isValidSessionToken,
    sanitizeBackendUrl,
    resolveBackendUrl,
    isDefaultBackendOrigin,
    getBackendOriginPattern,
    hasBackendPermission,
    requestBackendPermission,
    getSessionToken,
    initSession,
    clearSessionToken,
    getAuthHeaders,
  };

  if (typeof globalThis !== "undefined") {
    globalThis.MentorConfig = MentorConfig;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = MentorConfig;
  }
})();
