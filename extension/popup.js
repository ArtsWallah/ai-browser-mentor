// ============================================================
// AI BROWSER MENTOR - UNIVERSAL EXTENSION CONTROLLER
// ============================================================

const BACKEND_URL = "http://127.0.0.1:8000";

// State
let currentTab = null;
let currentPageId = "";
let currentPageData = null;
let currentSelection = "";
let isReadingPage = false;
let isAsking = false;

// DOM Elements
const connectionDot = document.getElementById("connectionDot");
const connectionText = document.getElementById("connectionText");
const activePageTitle = document.getElementById("activePageTitle");
const activePageDomain = document.getElementById("activePageDomain");
const btnReadPage = document.getElementById("btnReadPage");
const readPageSpinner = document.getElementById("readPageSpinner");
const readPageText = document.getElementById("readPageText");

const selectionBanner = document.getElementById("selectionBanner");
const selectionPreview = document.getElementById("selectionPreview");
const btnExplainSelection = document.getElementById("btnExplainSelection");
const btnAuditSelection = document.getElementById("btnAuditSelection");
const globalAlert = document.getElementById("globalAlert");

// Nav tabs
const navTabs = document.querySelectorAll(".nav-tab");
const tabPanels = document.querySelectorAll(".tab-panel");

// Ask AI Panel
const questionInput = document.getElementById("questionInput");
const btnAskMentor = document.getElementById("btnAskMentor");
const askSpinner = document.getElementById("askSpinner");
const askBtnText = document.getElementById("askBtnText");
const answerContainer = document.getElementById("answerContainer");
const answerContent = document.getElementById("answerContent");
const answerProviderBadge = document.getElementById("answerProviderBadge");
const btnCopyAnswer = document.getElementById("btnCopyAnswer");
const sourcesArea = document.getElementById("sourcesArea");
const promptChips = document.querySelectorAll(".prompt-chip");

// Security Panel
const gmailSection = document.getElementById("gmailSection");
const btnScanGmail = document.getElementById("btnScanGmail");
const gmailSpinner = document.getElementById("gmailSpinner");
const gmailBtnText = document.getElementById("gmailBtnText");
const btnAuditPage = document.getElementById("btnAuditPage");
const auditPageSpinner = document.getElementById("auditPageSpinner");
const btnAuditSelectionDirect = document.getElementById("btnAuditSelectionDirect");
const auditSelSpinner = document.getElementById("auditSelSpinner");
const securityVerdictArea = document.getElementById("securityVerdictArea");
const verdictBanner = document.getElementById("verdictBanner");
const verdictTitle = document.getElementById("verdictTitle");
const verdictSubtitle = document.getElementById("verdictSubtitle");
const verdictScore = document.getElementById("verdictScore");
const findingsList = document.getElementById("findingsList");
const scamshieldSection = document.getElementById("scamshieldSection");
const tacticsGrid = document.getElementById("tacticsGrid");
const securityStatusTag = document.getElementById("securityStatusTag");

// Links Panel
const btnRescanLinks = document.getElementById("btnRescanLinks");
const customLinkInput = document.getElementById("customLinkInput");
const btnCheckCustomLink = document.getElementById("btnCheckCustomLink");
const linkTotalCount = document.getElementById("linkTotalCount");
const linkSafeCount = document.getElementById("linkSafeCount");
const linkSuspiciousCount = document.getElementById("linkSuspiciousCount");
const linkRiskyCount = document.getElementById("linkRiskyCount");
const linksListContainer = document.getElementById("linksListContainer");

// Insights Panel
const insightWordCount = document.getElementById("insightWordCount");
const insightReadTime = document.getElementById("insightReadTime");
const insightChunks = document.getElementById("insightChunks");
const insightLinks = document.getElementById("insightLinks");
const headingsOutlineContainer = document.getElementById("headingsOutlineContainer");
const btnSummaryDirect = document.getElementById("btnSummaryDirect");


// ============================================================
// HELPER FUNCTIONS
// ============================================================

function showAlert(message, type = "error") {
    if (!globalAlert) return;
    globalAlert.textContent = message;
    globalAlert.className = `alert-box show ${type}`;
}

function clearAlert() {
    if (!globalAlert) return;
    globalAlert.className = "alert-box";
    globalAlert.textContent = "";
}

function switchTab(targetPanelId) {
    navTabs.forEach(tab => {
        const isActive = tab.getAttribute("data-tab") === targetPanelId;
        tab.classList.toggle("active", isActive);
    });

    tabPanels.forEach(panel => {
        panel.classList.toggle("active", panel.id === targetPanelId);
    });
}

function isRestrictedUrl(url) {
    if (!url) return true;
    return (
        url.startsWith("chrome://") ||
        url.startsWith("chrome-extension://") ||
        url.startsWith("edge://") ||
        url.startsWith("about:") ||
        url.startsWith("view-source:")
    );
}

function escapeHtml(str) {
    if (!str) return "";
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


// ============================================================
// INITIALIZATION
// ============================================================

async function initialize() {
    checkBackendHealth();
    await resolveActiveTab();
    setupEventListeners();
}

async function checkBackendHealth() {
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 2500);

        const res = await fetch(`${BACKEND_URL}/health`, { signal: controller.signal });
        clearTimeout(timeoutId);

        if (res.ok) {
            const data = await res.json();
            connectionDot.className = "connection-dot connected";
            if (data.scamshield_configured) {
                connectionText.textContent = "Connected (ScamShield Active)";
            } else {
                connectionText.textContent = "Connected";
            }
        } else {
            connectionDot.className = "connection-dot error";
            connectionText.textContent = "Degraded";
        }
    } catch {
        connectionDot.className = "connection-dot error";
        connectionText.textContent = "Backend Offline";
    }
}

async function resolveActiveTab() {
    try {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tabs || !tabs[0]) {
            showAlert("Could not access current browser tab.", "error");
            return;
        }

        currentTab = tabs[0];
        const url = currentTab.url || "";

        try {
            const parsed = new URL(url);
            activePageTitle.textContent = currentTab.title || parsed.hostname;
            activePageDomain.textContent = parsed.hostname;

            // Check if Gmail
            if (parsed.hostname.endsWith("mail.google.com")) {
                if (gmailSection) gmailSection.style.display = "flex";
            }
        } catch {
            activePageTitle.textContent = currentTab.title || "Webpage";
            activePageDomain.textContent = url.slice(0, 30);
        }

        if (isRestrictedUrl(url)) {
            showAlert("Chrome restricts assistant extensions on internal pages. Open an ordinary website to read content.", "info");
            btnReadPage.disabled = true;
            return;
        }

        // Try detecting highlighted text on the active page
        detectUserSelection();

    } catch (err) {
        console.warn("Could not query active tab:", err);
    }
}

async function detectUserSelection() {
    if (!currentTab?.id) return;
    try {
        const resp = await chrome.tabs.sendMessage(currentTab.id, { type: "GET_SELECTION" });
        if (resp && resp.has_selection && resp.selection) {
            currentSelection = resp.selection.trim();
            const preview = currentSelection.length > 50 ? `${currentSelection.slice(0, 50)}...` : currentSelection;
            selectionPreview.textContent = `Selection (${currentSelection.length}c): "${preview}"`;
            selectionBanner.style.display = "flex";
        } else {
            selectionBanner.style.display = "none";
        }
    } catch {
        // Content script might not be injected yet or not permitted
        selectionBanner.style.display = "none";
    }
}


// ============================================================
// READ CURRENT WEBPAGE
// ============================================================

async function readCurrentPage() {
    if (!currentTab?.id || isReadingPage) return;

    clearAlert();
    isReadingPage = true;
    btnReadPage.disabled = true;
    readPageSpinner.style.display = "inline-block";
    readPageText.textContent = "Reading...";

    try {
        // 1. Request page extraction from content script
        let pageData = null;
        try {
            pageData = await chrome.tabs.sendMessage(currentTab.id, { type: "GET_PAGE_CONTENT" });
        } catch (scriptErr) {
            // Try injecting if needed
            throw new Error("Could not connect to page. Please refresh the page and try again.");
        }

        if (!pageData || pageData.error) {
            throw new Error(pageData?.error || "Could not extract page text.");
        }

        currentPageData = pageData;
        const pageId = `page_${Date.now()}`;
        currentPageId = pageId;

        // 2. Transmit structured document to backend
        const ingestPayload = {
            page_id: pageId,
            title: pageData.title || currentTab.title || "Webpage",
            url: pageData.url || currentTab.url || "",
            hostname: activePageDomain.textContent || "",
            description: pageData.description || "",
            headings: (pageData.chunks || []).map(c => c.heading).filter(Boolean),
            paragraphs: [],
            chunks: pageData.chunks || [],
            links: pageData.links || [],
            images: pageData.images || [],
            interactiveElements: pageData.interactiveElements || [],
            content: pageData.text || "",
            wordCount: pageData.stats?.characters ? Math.round(pageData.stats.characters / 5) : 0
        };

        const res = await fetch(`${BACKEND_URL}/page/ingest`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(ingestPayload)
        });

        if (!res.ok) {
            throw new Error(`Backend ingest failed (${res.status})`);
        }

        const ingestResult = await res.json();

        // 3. Populate Insights Tab
        updateInsightsTab(ingestPayload);

        // 4. Populate Links Tab
        scanAndRenderLinks(ingestPayload.links, ingestPayload.url);

        readPageText.textContent = "Page Ready";
        showAlert("Page successfully understood and indexed!", "info");
        setTimeout(clearAlert, 2500);

    } catch (err) {
        console.error("Read page error:", err);
        showAlert(err.message || "Failed to read webpage.", "error");
        readPageText.textContent = "Retry Read";
    } finally {
        isReadingPage = false;
        btnReadPage.disabled = false;
        readPageSpinner.style.display = "none";
    }
}

function updateInsightsTab(data) {
    const wordCount = data.wordCount || 0;
    insightWordCount.textContent = wordCount.toLocaleString();
    insightReadTime.textContent = `${Math.max(1, Math.round(wordCount / 200))} min`;
    insightChunks.textContent = (data.chunks || []).length;
    insightLinks.textContent = (data.links || []).length;

    headingsOutlineContainer.innerHTML = "";
    const uniqueHeadings = [...new Set((data.headings || []).filter(Boolean))];

    if (!uniqueHeadings.length) {
        headingsOutlineContainer.innerHTML = '<div style="font-size: 11px; color: var(--muted); text-align: center; padding: 12px;">No headings extracted.</div>';
        return;
    }

    uniqueHeadings.slice(0, 15).forEach((h, idx) => {
        const item = document.createElement("div");
        item.className = "outline-item";
        item.textContent = `${idx + 1}. ${h}`;
        headingsOutlineContainer.appendChild(item);
    });
}


// ============================================================
// ASKING MENTOR & INTELLIGENCE
// ============================================================

async function askMentor(overridePrompt = "", mode = "auto") {
    const query = (overridePrompt || questionInput.value).trim();
    if (!query && !currentSelection) {
        showAlert("Please enter a question or click a prompt chip.", "error");
        return;
    }

    if (isAsking) return;
    clearAlert();
    isAsking = true;
    btnAskMentor.disabled = true;
    askSpinner.style.display = "inline-block";
    askBtnText.textContent = "Thinking...";

    try {
        const payload = {
            query: query,
            page_id: currentPageId || "",
            selection_text: currentSelection || "",
            mode: mode
        };

        const res = await fetch(`${BACKEND_URL}/assistant/query`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            throw new Error(`Assistant query failed (${res.status})`);
        }

        const data = await res.json();
        renderAnswer(data);

    } catch (err) {
        console.error("Ask mentor error:", err);
        showAlert(err.message || "Could not retrieve answer from assistant.", "error");
    } finally {
        isAsking = false;
        btnAskMentor.disabled = false;
        askSpinner.style.display = "none";
        askBtnText.textContent = "Ask Mentor";
    }
}

function renderAnswer(data) {
    answerContainer.style.display = "flex";

    const toolName = (data.tool || "Grounded Q&A").replace(/_/g, " ").toUpperCase();
    const provider = data.provider === "groq" ? "Groq LLM" : "Deterministic Engine";
    answerProviderBadge.textContent = `${toolName} (${provider})`;

    const text = data.text_response || data.answer || "No response provided.";
    answerContent.textContent = text;

    // Render sources if available
    sourcesArea.innerHTML = "";
    const sources = data.sources || [];
    if (sources.length > 0) {
        sourcesArea.style.display = "flex";
        const label = document.createElement("div");
        label.style.fontSize = "10px";
        label.style.fontWeight = "bold";
        label.style.color = "var(--muted)";
        label.textContent = "VERIFIED SOURCES:";
        sourcesArea.appendChild(label);

        sources.slice(0, 3).forEach(s => {
            const pill = document.createElement("div");
            pill.className = "source-pill";
            pill.innerHTML = `<strong>${escapeHtml(s.heading || "Page Section")}</strong>: ${escapeHtml(s.text ? s.text.slice(0, 140) + "..." : "")}`;
            sourcesArea.appendChild(pill);
        });
    } else {
        sourcesArea.style.display = "none";
    }
}


// ============================================================
// SECURITY AUDITING
// ============================================================

async function auditPageSecurity() {
    if (!currentPageId) {
        showAlert("Please read the page first before auditing security.", "info");
        return;
    }

    btnAuditPage.disabled = true;
    auditPageSpinner.style.display = "inline-block";

    try {
        const res = await fetch(`${BACKEND_URL}/security/analyze-page`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ page_id: currentPageId })
        });

        if (!res.ok) {
            throw new Error(`Security audit failed (${res.status})`);
        }

        const data = await res.json();
        renderSecurityVerdict(data);

    } catch (err) {
        showAlert(err.message || "Failed to audit page security.", "error");
    } finally {
        btnAuditPage.disabled = false;
        auditPageSpinner.style.display = "none";
    }
}

async function auditSelectionSecurity(textToAudit = "") {
    const text = (textToAudit || currentSelection).trim();
    if (!text) {
        showAlert("No text selected to audit. Highlight text on the page first.", "error");
        return;
    }

    btnAuditSelectionDirect.disabled = true;
    auditSelSpinner.style.display = "inline-block";

    try {
        const res = await fetch(`${BACKEND_URL}/security/analyze-text`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: text, context: "user_selection" })
        });

        if (!res.ok) {
            throw new Error(`Selection analysis failed (${res.status})`);
        }

        const data = await res.json();
        renderSecurityVerdict({
            risk_level: data.risk_level,
            risk_score: data.risk_score,
            findings: data.reasons,
            text_analysis: data,
            disclaimer: data.disclaimer
        });

    } catch (err) {
        showAlert(err.message || "Failed to audit selected text.", "error");
    } finally {
        btnAuditSelectionDirect.disabled = false;
        auditSelSpinner.style.display = "none";
    }
}

async function scanOpenGmailEmail() {
    if (!currentTab?.id) return;

    btnScanGmail.disabled = true;
    gmailSpinner.style.display = "inline-block";
    gmailBtnText.textContent = "Extracting Email...";

    try {
        const email = await chrome.tabs.sendMessage(currentTab.id, {
            type: "SCAMSHIELD_GET_GMAIL_EMAIL"
        });

        if (!email?.success || !email.message) {
            throw new Error(email?.message || "Please open an individual email in Gmail first.");
        }

        gmailBtnText.textContent = "Analyzing Tactics...";

        // Use the preserved ScamShield endpoint
        const response = await fetch(`${BACKEND_URL}/scamshield/analyze-text`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: email.message })
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || "ScamShield service request failed.");
        }

        const data = await response.json();
        const detected = data.detected_tactics || [];
        const riskLevel = detected.length >= 2 ? "High Risk" : (detected.length === 1 ? "Caution / Suspicious" : "Low Risk");
        const riskScore = Math.min(detected.length * 35, 100);

        renderSecurityVerdict({
            risk_level: riskLevel,
            risk_score: riskScore,
            findings: detected.length > 0
                ? detected.map(t => `Detected manipulation tactic: ${t}`)
                : ["No high-confidence manipulation tactics flagged by the ScamShield baseline model."],
            text_analysis: { scamshield: data },
            disclaimer: data.disclaimer || "Experimental ScamShield tactic analysis only."
        });

    } catch (err) {
        showAlert(err.message || "Failed to analyze Gmail message.", "error");
    } finally {
        btnScanGmail.disabled = false;
        gmailSpinner.style.display = "none";
        gmailBtnText.textContent = "Scan Open Email";
    }
}

function renderSecurityVerdict(audit) {
    securityVerdictArea.style.display = "flex";

    const risk = (audit.risk_level || "Low Risk").toLowerCase();
    verdictBanner.className = "verdict-banner";

    if (risk.includes("high")) {
        verdictBanner.classList.add("high");
        verdictTitle.textContent = "High Risk Detected";
        verdictSubtitle.textContent = "Significant risk indicators found";
        securityStatusTag.className = "badge-risk high";
        securityStatusTag.textContent = "High Risk";
    } else if (risk.includes("caution") || risk.includes("suspicious") || risk.includes("medium")) {
        verdictBanner.classList.add("caution");
        verdictTitle.textContent = "Caution / Suspicious";
        verdictSubtitle.textContent = "Potentially deceptive indicators flagged";
        securityStatusTag.className = "badge-risk medium";
        securityStatusTag.textContent = "Caution";
    } else {
        verdictBanner.classList.add("low");
        verdictTitle.textContent = "Low Risk";
        verdictSubtitle.textContent = "No prominent deceptive patterns identified";
        securityStatusTag.className = "badge-risk low";
        securityStatusTag.textContent = "Low Risk";
    }

    verdictScore.textContent = `${audit.risk_score || 0}/100`;

    // Render findings
    findingsList.innerHTML = "";
    const findings = audit.findings || [];
    findings.forEach(f => {
        const item = document.createElement("div");
        item.className = "finding-item";
        item.innerHTML = `<span class="finding-bullet">&#8226;</span><span>${escapeHtml(f)}</span>`;
        findingsList.appendChild(item);
    });

    // Render ScamShield tactics if available
    const scamshieldData = audit.text_analysis?.scamshield;
    if (scamshieldData && scamshieldData.results) {
        scamshieldSection.style.display = "block";
        tacticsGrid.innerHTML = "";
        scamshieldData.results.forEach(t => {
            const tag = document.createElement("div");
            tag.className = `tactic-tag ${t.detected ? "detected" : ""}`;
            tag.innerHTML = `<span>${escapeHtml(t.tactic)}</span><span>${t.detected ? "&#9888; Yes" : "&#10003; No"}</span>`;
            tacticsGrid.appendChild(tag);
        });
    } else {
        scamshieldSection.style.display = "none";
    }
}


// ============================================================
// LINKS INSPECTION
// ============================================================

async function scanAndRenderLinks(links = [], pageUrl = "") {
    if (!links || !links.length) {
        if (currentPageData?.links) {
            links = currentPageData.links;
            pageUrl = currentPageData.url;
        }
    }

    if (!links || !links.length) {
        linksListContainer.innerHTML = '<div style="font-size: 11px; color: var(--muted); text-align: center; padding: 16px;">No links found on this page.</div>';
        return;
    }

    try {
        const res = await fetch(`${BACKEND_URL}/scan-links`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ links: links.slice(0, 100), page_id: currentPageId })
        });

        if (!res.ok) throw new Error("Link scan request failed");

        const data = await res.json();
        const summary = data.summary || {};

        linkTotalCount.textContent = summary.total || 0;
        linkSafeCount.textContent = summary.low || 0;
        linkSuspiciousCount.textContent = summary.medium || 0;
        linkRiskyCount.textContent = summary.high || 0;

        renderLinksList(data.results || []);

    } catch (err) {
        console.warn("Scan links fallback:", err);
    }
}

function renderLinksList(results) {
    linksListContainer.innerHTML = "";

    if (!results.length) {
        linksListContainer.innerHTML = '<div style="font-size: 11px; color: var(--muted); text-align: center; padding: 16px;">No links to display.</div>';
        return;
    }

    results.slice(0, 40).forEach(link => {
        const row = document.createElement("div");
        row.className = "link-row";

        const riskClass = (link.risk || "low").toLowerCase();
        const top = document.createElement("div");
        top.className = "link-row-top";

        const label = document.createElement("span");
        label.className = "link-label";
        label.textContent = link.text || link.url || "Untitled link";

        const badge = document.createElement("span");
        badge.className = `badge-risk ${riskClass}`;
        badge.textContent = link.risk || "Low";

        top.appendChild(label);
        top.appendChild(badge);
        row.appendChild(top);

        const urlDiv = document.createElement("div");
        urlDiv.className = "link-url";
        urlDiv.textContent = link.url;
        row.appendChild(urlDiv);

        if (link.reasons && link.reasons.length && link.risk !== "Low") {
            const reasonDiv = document.createElement("div");
            reasonDiv.className = "link-reason";
            reasonDiv.textContent = link.reasons[0];
            row.appendChild(reasonDiv);
        }

        linksListContainer.appendChild(row);
    });
}

async function checkCustomUrl() {
    const url = customLinkInput.value.trim();
    if (!url) {
        showAlert("Enter a URL to inspect.", "error");
        return;
    }

    try {
        const res = await fetch(`${BACKEND_URL}/hover-check`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: url, page_url: currentTab?.url || "" })
        });

        if (!res.ok) throw new Error("Hover check failed");

        const data = await res.json();
        const result = data.result || {};

        showAlert(`Link Inspection for ${result.hostname || url}: Risk is ${result.risk}. ${result.reasons ? result.reasons.join(", ") : ""}`, result.risk === "High" ? "error" : "info");

    } catch (err) {
        showAlert("Failed to inspect custom link.", "error");
    }
}


// ============================================================
// EVENT LISTENERS
// ============================================================

function setupEventListeners() {
    // Tab switching
    navTabs.forEach(tab => {
        tab.addEventListener("click", () => {
            const panelId = tab.getAttribute("data-tab");
            switchTab(panelId);
        });
    });

    // Read Page
    btnReadPage?.addEventListener("click", readCurrentPage);

    // Ask Mentor
    btnAskMentor?.addEventListener("click", () => askMentor());

    // Enter key support for textarea
    questionInput?.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            askMentor();
        }
    });

    // Quick Prompt Chips
    promptChips.forEach(chip => {
        chip.addEventListener("click", () => {
            const prompt = chip.getAttribute("data-prompt");
            if (prompt) {
                questionInput.value = prompt;
                askMentor(prompt);
            }
        });
    });

    // Selection Banner Actions
    btnExplainSelection?.addEventListener("click", () => {
        switchTab("panelAsk");
        questionInput.value = `Explain this selection: "${currentSelection.slice(0, 80)}"`;
        askMentor(`Explain this highlighted text in simple plain language: "${currentSelection}"`, "explain");
    });

    btnAuditSelection?.addEventListener("click", () => {
        switchTab("panelSecurity");
        auditSelectionSecurity(currentSelection);
    });

    btnAuditSelectionDirect?.addEventListener("click", () => {
        auditSelectionSecurity();
    });

    // Security Tab Actions
    btnAuditPage?.addEventListener("click", auditPageSecurity);
    btnScanGmail?.addEventListener("click", scanOpenGmailEmail);

    // Links Tab Actions
    btnRescanLinks?.addEventListener("click", () => scanAndRenderLinks());
    btnCheckCustomLink?.addEventListener("click", checkCustomUrl);
    customLinkInput?.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            checkCustomUrl();
        }
    });

    // Insights Direct Summary Action
    btnSummaryDirect?.addEventListener("click", () => {
        switchTab("panelAsk");
        questionInput.value = "Summarize this page";
        askMentor("Summarize this page in 3 concise bullet points", "summary");
    });

    // Copy to clipboard
    btnCopyAnswer?.addEventListener("click", () => {
        const text = answerContent.textContent;
        if (!text) return;
        navigator.clipboard.writeText(text).then(() => {
            const orig = btnCopyAnswer.textContent;
            btnCopyAnswer.textContent = "Copied!";
            setTimeout(() => { btnCopyAnswer.textContent = orig; }, 1500);
        });
    });
}

// Start
document.addEventListener("DOMContentLoaded", initialize);
