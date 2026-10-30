// ============================================================
// AI BROWSER MENTOR - GLOBAL CONFIGURATION
// Single source of truth for extension backend connectivity
// ============================================================

(() => {
  "use strict";

  const DEFAULT_BACKEND_URL = "https://ai-browser-mentor.onrender.com";
  const DEV_BACKEND_URL = "http://127.0.0.1:8000";
  const STORAGE_KEY = "abm_backend_url_override";

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

  const MentorConfig = {
    DEFAULT_BACKEND_URL,
    DEV_BACKEND_URL,
    STORAGE_KEY,
    sanitizeBackendUrl,
    resolveBackendUrl,
    isDefaultBackendOrigin,
    getBackendOriginPattern,
    hasBackendPermission,
    requestBackendPermission,
  };

  if (typeof globalThis !== "undefined") {
    globalThis.MentorConfig = MentorConfig;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = MentorConfig;
  }
})();
