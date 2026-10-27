// ============================================================
// AI BROWSER MENTOR - WORKSPACE STORAGE MANAGER
// Phase 3: Persistent Multi-Tab Research Storage
// Uses chrome.storage.local with storage limit guards
// ============================================================

const WORKSPACE_STORAGE_KEY = "abm_workspaces_v1";
const ACTIVE_WORKSPACE_KEY = "abm_active_workspace_id";
const MAX_SOURCE_TEXT_CHARS = 25000; // Safeguard against chrome.storage quota limits

/**
 * Storage adapter supporting chrome.storage.local and localStorage fallback.
 */
const StorageAdapter = {
    async get(key) {
        if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
            return new Promise((resolve) => {
                chrome.storage.local.get([key], (result) => {
                    if (chrome.runtime.lastError) {
                        console.warn("StorageAdapter get error:", chrome.runtime.lastError.message);
                        resolve(null);
                    } else {
                        resolve(result[key]);
                    }
                });
            });
        }
        try {
            const raw = localStorage.getItem(key);
            return raw ? JSON.parse(raw) : null;
        } catch (e) {
            console.warn("localStorage fallback get error:", e);
            return null;
        }
    },

    async set(key, value) {
        if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
            return new Promise((resolve, reject) => {
                const payload = {};
                payload[key] = value;
                chrome.storage.local.set(payload, () => {
                    if (chrome.runtime.lastError) {
                        reject(new Error(chrome.runtime.lastError.message));
                    } else {
                        resolve();
                    }
                });
            });
        }
        try {
            localStorage.setItem(key, JSON.stringify(value));
            return Promise.resolve();
        } catch (e) {
            return Promise.reject(e);
        }
    }
};

/**
 * Normalize URLs for duplicate detection (removes tracking params and hash).
 */
function normalizeSourceUrl(rawUrl) {
    if (!rawUrl) return "";
    try {
        const u = new URL(rawUrl.trim());
        // Remove tracking query parameters
        const trackingParams = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"];
        trackingParams.forEach(p => u.searchParams.delete(p));
        u.hash = ""; // strip anchor
        return u.toString().replace(/\/$/, ""); // strip trailing slash
    } catch (_) {
        return rawUrl.trim().toLowerCase().replace(/\/$/, "");
    }
}

/**
 * Workspace Store API
 */
const WorkspaceStore = {
    /**
     * Get all workspaces. Creates a default workspace if empty.
     */
    async getWorkspaces() {
        let list = await StorageAdapter.get(WORKSPACE_STORAGE_KEY);
        if (!Array.isArray(list) || list.length === 0) {
            const defaultWs = {
                id: "ws_default",
                name: "General Research",
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                sources: [],
                findings: []
            };
            list = [defaultWs];
            await StorageAdapter.set(WORKSPACE_STORAGE_KEY, list);
            await StorageAdapter.set(ACTIVE_WORKSPACE_KEY, defaultWs.id);
        }
        return list;
    },

    /**
     * Get the active workspace ID.
     */
    async getActiveWorkspaceId() {
        const activeId = await StorageAdapter.get(ACTIVE_WORKSPACE_KEY);
        if (activeId) return activeId;
        const workspaces = await this.getWorkspaces();
        return workspaces[0]?.id || "ws_default";
    },

    /**
     * Set the active workspace ID.
     */
    async setActiveWorkspaceId(workspaceId) {
        await StorageAdapter.set(ACTIVE_WORKSPACE_KEY, workspaceId);
    },

    /**
     * Get the full active workspace object.
     */
    async getActiveWorkspace() {
        const workspaces = await this.getWorkspaces();
        const activeId = await this.getActiveWorkspaceId();
        let ws = workspaces.find(w => w.id === activeId);
        if (!ws) {
            ws = workspaces[0];
            if (ws) await this.setActiveWorkspaceId(ws.id);
        }
        return ws;
    },

    /**
     * Create a new workspace.
     */
    async createWorkspace(name) {
        const cleanName = (name || "").trim() || "Untitled Workspace";
        const workspaces = await this.getWorkspaces();
        const newWs = {
            id: "ws_" + Date.now() + "_" + Math.random().toString(36).substring(2, 7),
            name: cleanName,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            sources: [],
            findings: []
        };
        workspaces.push(newWs);
        await StorageAdapter.set(WORKSPACE_STORAGE_KEY, workspaces);
        await this.setActiveWorkspaceId(newWs.id);
        return newWs;
    },

    /**
     * Rename an existing workspace.
     */
    async renameWorkspace(workspaceId, newName) {
        const cleanName = (newName || "").trim();
        if (!cleanName) throw new Error("Workspace name cannot be empty.");
        const workspaces = await this.getWorkspaces();
        const ws = workspaces.find(w => w.id === workspaceId);
        if (!ws) throw new Error("Workspace not found.");
        ws.name = cleanName;
        ws.updated_at = new Date().toISOString();
        await StorageAdapter.set(WORKSPACE_STORAGE_KEY, workspaces);
        return ws;
    },

    /**
     * Delete a workspace.
     */
    async deleteWorkspace(workspaceId) {
        let workspaces = await this.getWorkspaces();
        if (workspaces.length <= 1) {
            throw new Error("Cannot delete the only research workspace. Create another workspace first.");
        }
        workspaces = workspaces.filter(w => w.id !== workspaceId);
        await StorageAdapter.set(WORKSPACE_STORAGE_KEY, workspaces);

        const currentActive = await this.getActiveWorkspaceId();
        if (currentActive === workspaceId) {
            await this.setActiveWorkspaceId(workspaces[0].id);
        }
        return workspaces;
    },

    /**
     * Add a source to a workspace.
     * Prevents duplicate URLs, sanitizes text, limits size.
     */
    async addSource(workspaceId, sourceInput) {
        if (!sourceInput || !sourceInput.url) {
            throw new Error("Cannot add source without a valid URL.");
        }

        const normalizedUrl = normalizeSourceUrl(sourceInput.url);
        const workspaces = await this.getWorkspaces();
        const ws = workspaces.find(w => w.id === workspaceId);
        if (!ws) throw new Error("Workspace not found.");

        // Check for duplicate URL in this workspace
        const existing = ws.sources.find(s => normalizeSourceUrl(s.url) === normalizedUrl);
        if (existing) {
            return {
                success: false,
                isDuplicate: true,
                message: `This page is already saved in '${ws.name}'.`,
                source: existing
            };
        }

        // Bounded text content (prevents storage quota explosion)
        const rawText = (sourceInput.text || sourceInput.content || "").trim();
        const boundedText = rawText.slice(0, MAX_SOURCE_TEXT_CHARS);

        // Pre-generate clean excerpt
        let excerpt = (sourceInput.description || "").trim();
        if (!excerpt && boundedText) {
            excerpt = boundedText.slice(0, 240).replace(/\s+/g, " ") + (boundedText.length > 240 ? "..." : "");
        }

        // Hostname parsing
        let hostname = sourceInput.hostname || "";
        if (!hostname) {
            try {
                hostname = new URL(sourceInput.url).hostname;
            } catch (_) {
                hostname = "webpage";
            }
        }

        const newSource = {
            id: "src_" + Date.now() + "_" + Math.random().toString(36).substring(2, 7),
            title: (sourceInput.title || hostname || "Untitled Webpage").trim(),
            url: sourceInput.url.trim(),
            hostname: hostname,
            collected_at: new Date().toISOString(),
            text: boundedText,
            excerpt: excerpt,
            headings: Array.isArray(sourceInput.headings) ? sourceInput.headings.slice(0, 15) : []
        };

        ws.sources.unshift(newSource);
        ws.updated_at = new Date().toISOString();

        try {
            await StorageAdapter.set(WORKSPACE_STORAGE_KEY, workspaces);
        } catch (storageErr) {
            // Handle storage quota error: trim text and retry
            console.warn("Storage quota warning on save, compressing source text:", storageErr.message);
            newSource.text = newSource.text.slice(0, 8000);
            await StorageAdapter.set(WORKSPACE_STORAGE_KEY, workspaces);
        }

        return {
            success: true,
            isDuplicate: false,
            message: `Added '${newSource.title}' to '${ws.name}'.`,
            source: newSource
        };
    },

    /**
     * Remove a single source from a workspace.
     */
    async removeSource(workspaceId, sourceId) {
        const workspaces = await this.getWorkspaces();
        const ws = workspaces.find(w => w.id === workspaceId);
        if (!ws) throw new Error("Workspace not found.");

        const initialCount = ws.sources.length;
        ws.sources = ws.sources.filter(s => s.id !== sourceId);
        if (ws.sources.length !== initialCount) {
            ws.updated_at = new Date().toISOString();
            await StorageAdapter.set(WORKSPACE_STORAGE_KEY, workspaces);
        }
        return ws;
    },

    /**
     * Save research synthesis finding into workspace.
     */
    async saveFinding(workspaceId, findingData) {
        const workspaces = await this.getWorkspaces();
        const ws = workspaces.find(w => w.id === workspaceId);
        if (!ws) throw new Error("Workspace not found.");

        if (!ws.findings) ws.findings = [];

        const finding = {
            id: "find_" + Date.now() + "_" + Math.random().toString(36).substring(2, 7),
            query: findingData.query || "Research Synthesis",
            answer: findingData.answer || "",
            citations: findingData.citations || [],
            created_at: new Date().toISOString()
        };

        ws.findings.unshift(finding);
        // Keep max 20 findings per workspace
        if (ws.findings.length > 20) ws.findings = ws.findings.slice(0, 20);

        ws.updated_at = new Date().toISOString();
        await StorageAdapter.set(WORKSPACE_STORAGE_KEY, workspaces);
        return finding;
    },

    /**
     * Remove a research finding.
     */
    async removeFinding(workspaceId, findingId) {
        const workspaces = await this.getWorkspaces();
        const ws = workspaces.find(w => w.id === workspaceId);
        if (!ws || !ws.findings) return;

        ws.findings = ws.findings.filter(f => f.id !== findingId);
        ws.updated_at = new Date().toISOString();
        await StorageAdapter.set(WORKSPACE_STORAGE_KEY, workspaces);
        return ws;
    }
};

// Export for extension scripts
if (typeof window !== "undefined") {
    window.WorkspaceStore = WorkspaceStore;
}
if (typeof module !== "undefined" && module.exports) {
    module.exports = { WorkspaceStore, StorageAdapter, normalizeSourceUrl };
}
