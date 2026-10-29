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
   * Asynchronously resolve the effective backend URL from chrome.storage.local
   * with fallback to DEFAULT_BACKEND_URL.
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
          return sanitizeBackendUrl(res);
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
  };

  if (typeof globalThis !== "undefined") {
    globalThis.MentorConfig = MentorConfig;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = MentorConfig;
  }
})();
