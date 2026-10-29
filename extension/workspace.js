// ============================================================
// AI BROWSER MENTOR - WORKSPACE DESKTOP CONTROLLER
// Phase 3: Dedicated Research Workspace View
// ============================================================

let BACKEND_URL = (typeof MentorConfig !== "undefined" && MentorConfig.DEFAULT_BACKEND_URL)
    ? MentorConfig.DEFAULT_BACKEND_URL
    : "https://ai-browser-mentor.onrender.com";

// Dynamically react to storage override changes
if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.onChanged) {
    chrome.storage.onChanged.addListener((changes, areaName) => {
        const key = (typeof MentorConfig !== "undefined" && MentorConfig.STORAGE_KEY)
            ? MentorConfig.STORAGE_KEY
            : "abm_backend_url_override";
        if (areaName === "local" && changes && changes[key]) {
            if (typeof MentorConfig !== "undefined" && typeof MentorConfig.sanitizeBackendUrl === "function") {
                BACKEND_URL = MentorConfig.sanitizeBackendUrl(changes[key].newValue);
            }
        }
    });
}

let currentWorkspace = null;
let allWorkspaces = [];

// DOM Elements
const workspaceSelect = document.getElementById("workspaceSelect");
const btnNewWorkspace = document.getElementById("btnNewWorkspace");
const btnRenameWorkspace = document.getElementById("btnRenameWorkspace");
const btnDeleteWorkspace = document.getElementById("btnDeleteWorkspace");
const wsSourceCountLabel = document.getElementById("wsSourceCountLabel");
const sidebarAlert = document.getElementById("sidebarAlert");

const sourcesListContainer = document.getElementById("sourcesListContainer");
const sourcesEmptyState = document.getElementById("sourcesEmptyState");

const wsQueryInput = document.getElementById("wsQueryInput");
const btnAskSources = document.getElementById("btnAskSources");
const btnCompareSources = document.getElementById("btnCompareSources");
const askBtnSpinner = document.getElementById("askBtnSpinner");
const askBtnText = document.getElementById("askBtnText");

const resultsEmptyState = document.getElementById("resultsEmptyState");
const resultsLoadingState = document.getElementById("resultsLoadingState");
const loadingTitle = document.getElementById("loadingTitle");
const resultContentArea = document.getElementById("resultContentArea");
const resultModeBadge = document.getElementById("resultModeBadge");
const resultProviderBadge = document.getElementById("resultProviderBadge");
const resultAnswerText = document.getElementById("resultAnswerText");
const compareBreakdown = document.getElementById("compareBreakdown");
const agreementsList = document.getElementById("agreementsList");
const disagreementsList = document.getElementById("disagreementsList");
const unverifiedList = document.getElementById("unverifiedList");
const citationsSection = document.getElementById("citationsSection");
const citationsGrid = document.getElementById("citationsGrid");
const resultLimitationsText = document.getElementById("resultLimitationsText");
const btnCopyAnswer = document.getElementById("btnCopyAnswer");

// Init
document.addEventListener("DOMContentLoaded", async () => {
    if (typeof MentorConfig !== "undefined" && typeof MentorConfig.resolveBackendUrl === "function") {
        BACKEND_URL = await MentorConfig.resolveBackendUrl();
    }
    await loadWorkspaces();
    bindEvents();
});

function showAlert(msg, isError = false) {
    if (!sidebarAlert) return;
    sidebarAlert.textContent = msg;
    sidebarAlert.className = "alert-box show " + (isError ? "error" : "info");
    setTimeout(() => {
        sidebarAlert.className = "alert-box";
    }, 4000);
}

async function loadWorkspaces() {
    try {
        allWorkspaces = await WorkspaceStore.getWorkspaces();
        const activeId = await WorkspaceStore.getActiveWorkspaceId();
        currentWorkspace = allWorkspaces.find(w => w.id === activeId) || allWorkspaces[0];

        workspaceSelect.innerHTML = "";
        allWorkspaces.forEach(ws => {
            const opt = document.createElement("option");
            opt.value = ws.id;
            opt.textContent = `${ws.name} (${ws.sources?.length || 0})`;
            if (ws.id === currentWorkspace.id) opt.selected = true;
            workspaceSelect.appendChild(opt);
        });

        renderSources();
    } catch (err) {
        console.error("Failed to load workspaces:", err);
        showAlert("Failed to load research workspaces: " + err.message, true);
    }
}

function renderSources() {
    if (!currentWorkspace) return;

    const sources = currentWorkspace.sources || [];
    wsSourceCountLabel.textContent = `${sources.length} Source${sources.length === 1 ? "" : "s"}`;

    sourcesListContainer.innerHTML = "";

    if (sources.length === 0) {
        sourcesListContainer.appendChild(sourcesEmptyState);
        sourcesEmptyState.style.display = "flex";
        return;
    }

    sourcesEmptyState.style.display = "none";

    sources.forEach(src => {
        const card = document.createElement("div");
        card.className = "source-card";

        const timeStr = src.collected_at ? new Date(src.collected_at).toLocaleDateString() : "Recently";

        card.innerHTML = `
            <div class="source-card-header">
                <div class="source-card-title" title="${escapeHtml(src.title)}">${escapeHtml(src.title)}</div>
            </div>
            <div class="source-card-meta">
                <span>🌐 ${escapeHtml(src.hostname || "Webpage")}</span>
                <span>📅 ${timeStr}</span>
                <span>📝 ${src.text ? src.text.length.toLocaleString() : 0} chars</span>
            </div>
            <div class="source-card-excerpt">${escapeHtml(src.excerpt || "No summary excerpt available.")}</div>
            <div class="source-card-footer">
                <a href="${escapeHtml(src.url)}" target="_blank" rel="noopener noreferrer" class="link-ext">🔗 Visit Page ↗</a>
                <button class="btn-remove-source" data-src-id="${src.id}" title="Remove source">✕ Remove</button>
            </div>
        `;

        const btnRemove = card.querySelector(".btn-remove-source");
        btnRemove.addEventListener("click", async () => {
            await removeSource(src.id, src.title);
        });

        sourcesListContainer.appendChild(card);
    });
}

async function removeSource(sourceId, title) {
    if (!currentWorkspace) return;
    try {
        await WorkspaceStore.removeSource(currentWorkspace.id, sourceId);
        showAlert(`Removed '${title}'`, false);
        await loadWorkspaces();
    } catch (err) {
        showAlert("Failed to remove source: " + err.message, true);
    }
}

function bindEvents() {
    workspaceSelect.addEventListener("change", async (e) => {
        await WorkspaceStore.setActiveWorkspaceId(e.target.value);
        await loadWorkspaces();
    });

    btnNewWorkspace.addEventListener("click", async () => {
        const name = prompt("Enter new workspace name (e.g. 'Competitor Analysis', 'AI Research'):");
        if (!name || !name.trim()) return;
        try {
            const ws = await WorkspaceStore.createWorkspace(name.trim());
            showAlert(`Created workspace '${ws.name}'`, false);
            await loadWorkspaces();
        } catch (err) {
            showAlert("Could not create workspace: " + err.message, true);
        }
    });

    btnRenameWorkspace.addEventListener("click", async () => {
        if (!currentWorkspace) return;
        const newName = prompt("Rename workspace:", currentWorkspace.name);
        if (!newName || !newName.trim()) return;
        try {
            await WorkspaceStore.renameWorkspace(currentWorkspace.id, newName.trim());
            showAlert(`Workspace renamed to '${newName.trim()}'`, false);
            await loadWorkspaces();
        } catch (err) {
            showAlert("Could not rename workspace: " + err.message, true);
        }
    });

    btnDeleteWorkspace.addEventListener("click", async () => {
        if (!currentWorkspace) return;
        if (!confirm(`Are you sure you want to delete workspace '${currentWorkspace.name}' and all its collected sources?`)) {
            return;
        }
        try {
            await WorkspaceStore.deleteWorkspace(currentWorkspace.id);
            showAlert("Workspace deleted.", false);
            await loadWorkspaces();
        } catch (err) {
            showAlert(err.message, true);
        }
    });

    btnAskSources.addEventListener("click", async () => {
        const q = wsQueryInput.value.trim();
        if (!q) {
            alert("Please enter a research question or topic.");
            wsQueryInput.focus();
            return;
        }
        await executeWorkspaceQuery(q);
    });

    wsQueryInput.addEventListener("keydown", async (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            const q = wsQueryInput.value.trim();
            if (q) await executeWorkspaceQuery(q);
        }
    });

    btnCompareSources.addEventListener("click", async () => {
        const focusTopic = wsQueryInput.value.trim();
        await executeWorkspaceCompare(focusTopic);
    });

    btnCopyAnswer.addEventListener("click", () => {
        const text = resultAnswerText.innerText;
        if (text) {
            navigator.clipboard.writeText(text).then(() => {
                btnCopyAnswer.textContent = "✓ Copied!";
                setTimeout(() => { btnCopyAnswer.textContent = "📋 Copy Synthesis"; }, 2000);
            });
        }
    });
}

async function executeWorkspaceQuery(query) {
    if (!currentWorkspace || !currentWorkspace.sources || currentWorkspace.sources.length === 0) {
        alert("Please add at least one saved webpage to this workspace before running a cross-source query.");
        return;
    }

    setLoading(true, "Synthesizing cross-source evidence...", "Extracting relevant passages and citations");

    try {
        const res = await fetch(`${BACKEND_URL}/workspace/query`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                query: query,
                workspace_name: currentWorkspace.name,
                sources: currentWorkspace.sources.map(s => ({
                    id: s.id,
                    title: s.title,
                    url: s.url,
                    hostname: s.hostname,
                    collected_at: s.collected_at,
                    text: s.text,
                    excerpt: s.excerpt
                }))
            })
        });

        if (!res.ok) {
            throw new Error(`Backend error ${res.status}: ${await res.text()}`);
        }

        const data = await res.json();
        renderSynthesisResult(data, "query");
    } catch (err) {
        console.error("Workspace query failed:", err);
        renderErrorResult("Cross-source query failed: " + err.message);
    } finally {
        setLoading(false);
    }
}

async function executeWorkspaceCompare(focusTopic) {
    if (!currentWorkspace || !currentWorkspace.sources || currentWorkspace.sources.length < 2) {
        alert("Source comparison requires at least 2 saved webpages in this workspace. Please add more pages first.");
        return;
    }

    setLoading(true, "Comparing saved sources...", "Extracting agreement, differences, and unverified claims");

    try {
        const res = await fetch(`${BACKEND_URL}/workspace/compare`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                workspace_name: currentWorkspace.name,
                focus_topic: focusTopic,
                sources: currentWorkspace.sources.map(s => ({
                    id: s.id,
                    title: s.title,
                    url: s.url,
                    hostname: s.hostname,
                    collected_at: s.collected_at,
                    text: s.text,
                    excerpt: s.excerpt
                }))
            })
        });

        if (!res.ok) {
            throw new Error(`Backend error ${res.status}: ${await res.text()}`);
        }

        const data = await res.json();
        renderSynthesisResult(data, "compare");
    } catch (err) {
        console.error("Workspace comparison failed:", err);
        renderErrorResult("Cross-source comparison failed: " + err.message);
    } finally {
        setLoading(false);
    }
}

function setLoading(isLoading, title = "", subtitle = "") {
    if (isLoading) {
        resultsEmptyState.style.display = "none";
        resultContentArea.style.display = "none";
        resultsLoadingState.style.display = "flex";
        loadingTitle.textContent = title;
        btnAskSources.disabled = true;
        btnCompareSources.disabled = true;
    } else {
        resultsLoadingState.style.display = "none";
        btnAskSources.disabled = false;
        btnCompareSources.disabled = false;
    }
}

function renderSynthesisResult(data, mode) {
    resultsEmptyState.style.display = "none";
    resultsLoadingState.style.display = "none";
    resultContentArea.style.display = "flex";

    if (mode === "compare") {
        resultModeBadge.textContent = "⚖️ Source Comparison";
        resultProviderBadge.textContent = `Provider: ${data.provider || "Grounded LLM"}`;
        resultAnswerText.textContent = data.comparison_summary || "Comparison completed.";

        // Populate compare sections
        compareBreakdown.style.display = "flex";
        renderListItems(agreementsList, data.agreements, "No specific consensus points detected.");
        renderListItems(disagreementsList, data.disagreements, "No direct contradictions found.");
        renderListItems(unverifiedList, data.unverified_claims, "All key claims have source coverage.");
    } else {
        resultModeBadge.textContent = "🔍 Research Synthesis";
        resultProviderBadge.textContent = `Provider: ${data.provider || "Grounded LLM"}`;
        resultAnswerText.textContent = data.answer || "No response provided.";
        compareBreakdown.style.display = "none";
    }

    // Render citations
    citationsGrid.innerHTML = "";
    const citations = data.citations || [];
    if (citations.length > 0) {
        citationsSection.style.display = "flex";
        citations.forEach(c => {
            const card = document.createElement("div");
            card.className = "citation-card";
            card.innerHTML = `
                <div style="font-weight: 700; color: var(--text);">${escapeHtml(c.source_title || "Source")}</div>
                <div style="font-style: italic; color: var(--text-secondary); line-height: 1.4;">"${escapeHtml(c.quote)}"</div>
                <a href="${escapeHtml(c.url)}" target="_blank" rel="noopener noreferrer" style="color: var(--cyan); text-decoration: none; font-size: 10px; margin-top: 2px;">🔗 Open Original Page ↗</a>
            `;
            citationsGrid.appendChild(card);
        });
    } else {
        citationsSection.style.display = "none";
    }

    resultLimitationsText.textContent = data.limitations || "Evidence grounded in saved source passages.";
}

function renderErrorResult(msg) {
    resultsEmptyState.style.display = "none";
    resultsLoadingState.style.display = "none";
    resultContentArea.style.display = "flex";

    resultModeBadge.textContent = "⚠️ Error";
    resultProviderBadge.textContent = "Local";
    resultAnswerText.textContent = msg;
    compareBreakdown.style.display = "none";
    citationsSection.style.display = "none";
    resultLimitationsText.textContent = `Please check that the backend server is running on ${BACKEND_URL}.`;
}

function renderListItems(container, items, emptyMessage) {
    container.innerHTML = "";
    if (!items || items.length === 0) {
        const item = document.createElement("div");
        item.className = "finding-item";
        item.textContent = emptyMessage;
        container.appendChild(item);
        return;
    }
    items.forEach(text => {
        const item = document.createElement("div");
        item.className = "finding-item";
        item.innerHTML = `<span>&bull;</span><span>${escapeHtml(text)}</span>`;
        container.appendChild(item);
    });
}

function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
