// ============================================================
// AI BROWSER MENTOR - UNIVERSAL EXTENSION CONTROLLER
// Phase 2: AI Command Center Orchestration
// ============================================================

const BACKEND_URL = "http://127.0.0.1:8000";

// State
let currentTab = null;
let currentPageId = "";
let currentPageData = null;
let currentSelection = "";
let isReadingPage = false;
let isExecutingCommand = false;
let allScannedLinks = [];
let currentLinkFilter = "all";

// DOM Elements: Header & Status
const connectionDot = document.getElementById("connectionDot");
const connectionText = document.getElementById("connectionText");
const activePageTitle = document.getElementById("activePageTitle");
const activePageDomain = document.getElementById("activePageDomain");
const pageStatusBadge = document.getElementById("pageStatusBadge");
const btnReadPage = document.getElementById("btnReadPage");
const readPageSpinner = document.getElementById("readPageSpinner");
const readPageText = document.getElementById("readPageText");

// Selection Banner
const selectionBanner = document.getElementById("selectionBanner");
const selectionPreview = document.getElementById("selectionPreview");
const btnExplainSelection = document.getElementById("btnExplainSelection");
const btnAuditSelection = document.getElementById("btnAuditSelection");
const globalAlert = document.getElementById("globalAlert");

// Navigation Tabs
const navTabs = document.querySelectorAll(".nav-tab");
const tabPanels = document.querySelectorAll(".tab-panel");

// Command Center Elements
const commandChips = document.querySelectorAll(".command-chip");
const contextPageName = document.getElementById("contextPageName");
const contextSelectionText = document.getElementById("contextSelectionText");
const commandInput = document.getElementById("commandInput");
const btnRunCommand = document.getElementById("btnRunCommand");
const commandSpinner = document.getElementById("commandSpinner");
const commandBtnText = document.getElementById("commandBtnText");
const btnClearCommand = document.getElementById("btnClearCommand");
const btnNewTask = document.getElementById("btnNewTask");
const btnCopyCommandResult = document.getElementById("btnCopyCommandResult");

// Command States & Result Cards
const commandEmptyState = document.getElementById("commandEmptyState");
const commandLoadingState = document.getElementById("commandLoadingState");
const commandLoadingSubtitle = document.getElementById("commandLoadingSubtitle");
const commandErrorBox = document.getElementById("commandErrorBox");
const commandErrorMsg = document.getElementById("commandErrorMsg");
const commandResultCard = document.getElementById("commandResultCard");

const resultToolBadge = document.getElementById("resultToolBadge");
const resultProviderBadge = document.getElementById("resultProviderBadge");
const resultActionSummary = document.getElementById("resultActionSummary");
const resultRiskBanner = document.getElementById("resultRiskBanner");
const resultRiskTitle = document.getElementById("resultRiskTitle");
const resultRiskSubtitle = document.getElementById("resultRiskSubtitle");
const resultRiskScore = document.getElementById("resultRiskScore");
const resultAnswer = document.getElementById("resultAnswer");
const resultKeyPointsContainer = document.getElementById("resultKeyPointsContainer");
const resultKeyPointsList = document.getElementById("resultKeyPointsList");
const resultEvidenceContainer = document.getElementById("resultEvidenceContainer");
const resultEvidenceCards = document.getElementById("resultEvidenceCards");
const resultLimitations = document.getElementById("resultLimitations");
const resultLimitationsText = document.getElementById("resultLimitationsText");

// Security Panel Elements
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

// Links Panel Elements
const btnRescanLinks = document.getElementById("btnRescanLinks");
const customLinkInput = document.getElementById("customLinkInput");
const btnCheckCustomLink = document.getElementById("btnCheckCustomLink");
const linkTotalCount = document.getElementById("linkTotalCount");
const linkSafeCount = document.getElementById("linkSafeCount");
const linkSuspiciousCount = document.getElementById("linkSuspiciousCount");
const linkRiskyCount = document.getElementById("linkRiskyCount");
const linksListContainer = document.getElementById("linksListContainer");

// Insights Panel Elements
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
    const lower = url.toLowerCase();
    return (
        lower.startsWith("chrome://") ||
        lower.startsWith("chrome-extension://") ||
        lower.startsWith("edge://") ||
        lower.startsWith("about:") ||
        lower.startsWith("view-source:") ||
        lower.startsWith("file://") ||
        lower.includes("chromewebstore.google.com") ||
        lower.includes("chrome.google.com/webstore")
    );
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


// ============================================================
// INITIALIZATION
// ============================================================

async function initialize() {
    checkBackendHealth();
    await resolveActiveTab();
    setupEventListeners();
    showCommandEmptyState();
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
        const title = currentTab.title || "Active Webpage";

        try {
            const parsed = new URL(url);
            activePageTitle.textContent = title;
            activePageDomain.textContent = parsed.hostname;
            if (contextPageName) contextPageName.textContent = title.slice(0, 36) + (title.length > 36 ? "..." : "");

            // Check if Gmail
            if (parsed.hostname.endsWith("mail.google.com")) {
                if (gmailSection) gmailSection.style.display = "flex";
            }
        } catch {
            activePageTitle.textContent = title;
            activePageDomain.textContent = url.slice(0, 30);
            if (contextPageName) contextPageName.textContent = title.slice(0, 36);
        }

        if (isRestrictedUrl(url)) {
            if (pageStatusBadge) {
                pageStatusBadge.textContent = "Restricted";
                pageStatusBadge.className = "badge-status restricted";
            }
            showAlert("Chrome restricts assistant extensions on internal and web store pages.", "info");
            btnReadPage.disabled = true;
            return;
        }

        if (pageStatusBadge) {
            pageStatusBadge.textContent = "Not Read";
            pageStatusBadge.className = "badge-status";
        }

        // Detect highlighted text on the active page
        detectUserSelection();

    } catch (err) {
        console.warn("Could not query active tab:", err);
    }
}

async function detectUserSelection() {
    if (!currentTab?.id || isRestrictedUrl(currentTab.url)) return;
    try {
        const resp = await chrome.tabs.sendMessage(currentTab.id, { type: "GET_SELECTION" });
        if (resp && resp.has_selection && resp.selection) {
            currentSelection = resp.selection.trim();
            const preview = currentSelection.length > 50 ? `${currentSelection.slice(0, 50)}...` : currentSelection;
            selectionPreview.textContent = `Selection (${currentSelection.length}c): "${preview}"`;
            selectionBanner.style.display = "flex";

            if (contextSelectionText) {
                contextSelectionText.textContent = `${currentSelection.length} chars selected`;
            }
        } else {
            currentSelection = "";
            selectionBanner.style.display = "none";
            if (contextSelectionText) {
                contextSelectionText.textContent = "No selection";
            }
        }
    } catch {
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
        let pageData = null;
        try {
            pageData = await chrome.tabs.sendMessage(currentTab.id, { type: "GET_PAGE_CONTENT" });
        } catch (scriptErr) {
            throw new Error("Could not connect to page content script. Please refresh the page and try again.");
        }

        if (!pageData || pageData.error) {
            throw new Error(pageData?.error || "Could not extract page text.");
        }

        currentPageData = pageData;
        const pageId = `page_${Date.now()}`;
        currentPageId = pageId;

        // Transmit structured document to backend
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

        const chunksCount = (pageData.chunks || []).length;
        if (pageStatusBadge) {
            pageStatusBadge.textContent = `Ready (${chunksCount} chunks)`;
            pageStatusBadge.className = "badge-status ready";
        }

        // Populate Insights Tab
        updateInsightsTab(ingestPayload);

        // Populate Links Tab
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
// PHASE 2: AI COMMAND CENTER ORCHESTRATION
// ============================================================

function hideCommandStates() {
    if (commandEmptyState) commandEmptyState.style.display = "none";
    if (commandLoadingState) commandLoadingState.style.display = "none";
    if (commandErrorBox) commandErrorBox.style.display = "none";
    if (commandResultCard) commandResultCard.style.display = "none";
}

function showCommandEmptyState() {
    hideCommandStates();
    if (commandEmptyState) commandEmptyState.style.display = "flex";
}

function showCommandLoading(subtitle = "Gathering page context and orchestrating registered tool...") {
    hideCommandStates();
    if (commandLoadingState) {
        commandLoadingState.style.display = "flex";
        if (commandLoadingSubtitle) commandLoadingSubtitle.textContent = subtitle;
    }
}

function showCommandError(errorMessage) {
    hideCommandStates();
    if (commandErrorBox) {
        commandErrorBox.style.display = "flex";
        if (commandErrorMsg) commandErrorMsg.textContent = errorMessage;
    }
}

function clearCommandInputAndResults() {
    if (commandInput) {
        commandInput.value = "";
        commandInput.focus();
    }
    showCommandEmptyState();
}

async function executeCommand(overrideInstruction = "", intentOverride = "auto") {
    // Re-check selection
    await detectUserSelection();

    const rawInstruction = (overrideInstruction || commandInput?.value || "").trim();
    if (!rawInstruction && !currentSelection) {
        showCommandError("Please enter a command or select a suggested task chip.");
        return;
    }

    if (isExecutingCommand) return;
    isExecutingCommand = true;

    // Transition UI to loading state
    showCommandLoading("Analyzing request & routing to registered tool...");
    if (btnRunCommand) btnRunCommand.disabled = true;
    if (commandSpinner) commandSpinner.style.display = "inline-block";
    if (commandBtnText) commandBtnText.textContent = "Running...";

    try {
        // If page has not been ingested yet and we are on an accessible tab, ingest first
        if (!currentPageId && currentTab?.id && !isRestrictedUrl(currentTab.url)) {
            showCommandLoading("Reading active webpage for context...");
            try {
                await readCurrentPage();
            } catch (ingestErr) {
                console.warn("Auto-read page warning:", ingestErr);
            }
        }

        showCommandLoading("Executing tool & grounding response...");

        const instructionToSend = rawInstruction || (currentSelection ? "Analyze this selected text" : "Summarize this page");

        const payload = {
            instruction: instructionToSend,
            intent: intentOverride || "auto",
            page_id: currentPageId || "",
            selection_text: currentSelection || "",
            page_url: currentTab?.url || "",
            page_title: currentTab?.title || ""
        };

        const res = await fetch(`${BACKEND_URL}/command/execute`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || `Command execution failed (${res.status})`);
        }

        const data = await res.json();
        renderCommandResult(data);

    } catch (err) {
        console.error("Execute command error:", err);
        showCommandError(err.message || "Could not execute command. Please verify backend server.");
    } finally {
        isExecutingCommand = false;
        if (btnRunCommand) btnRunCommand.disabled = false;
        if (commandSpinner) commandSpinner.style.display = "none";
        if (commandBtnText) commandBtnText.innerHTML = "&#9889; Run";
    }
}

function renderCommandResult(data) {
    hideCommandStates();
    if (commandResultCard) commandResultCard.style.display = "flex";

    // 1. Tool and Provider Badges
    const toolName = (data.tool_name || data.intent || "assistant").replace(/_/g, " ").toUpperCase();
    if (resultToolBadge) resultToolBadge.innerHTML = `&#9889; ${escapeHtml(toolName)}`;
    if (resultProviderBadge) resultProviderBadge.textContent = data.provider || "System";

    // 2. Action Summary
    if (resultActionSummary) {
        resultActionSummary.textContent = data.action_summary || "Executed task.";
    }

    // 3. Risk Assessment Banner (if security/link audit ran)
    if (data.risk_assessment && resultRiskBanner) {
        const risk = data.risk_assessment;
        resultRiskBanner.style.display = "flex";
        const levelLower = (risk.risk_level || "low").toLowerCase();
        resultRiskBanner.className = `verdict-banner ${levelLower.includes("high") ? "high" : levelLower.includes("caution") || levelLower.includes("suspicious") || levelLower.includes("medium") ? "caution" : "low"}`;
        if (resultRiskTitle) resultRiskTitle.textContent = risk.risk_level || "Risk Audit";
        if (resultRiskSubtitle) resultRiskSubtitle.textContent = risk.findings && risk.findings[0] ? risk.findings[0] : "Assessment complete";
        if (resultRiskScore) resultRiskScore.textContent = `${risk.risk_score || 0}/100`;
    } else if (resultRiskBanner) {
        resultRiskBanner.style.display = "none";
    }

    // 4. Direct Answer
    if (resultAnswer) {
        resultAnswer.textContent = data.answer || "No output provided.";
    }

    // 5. Key Points
    if (resultKeyPointsContainer && resultKeyPointsList) {
        const points = data.key_points || [];
        if (points.length > 0) {
            resultKeyPointsContainer.style.display = "block";
            resultKeyPointsList.innerHTML = "";
            points.forEach(pt => {
                const item = document.createElement("div");
                item.className = "result-key-point-item";
                item.innerHTML = `<span class="result-key-point-bullet">&#9670;</span><span>${escapeHtml(pt)}</span>`;
                resultKeyPointsList.appendChild(item);
            });
        } else {
            resultKeyPointsContainer.style.display = "none";
        }
    }

    // 6. Grounded Evidence Cards
    if (resultEvidenceContainer && resultEvidenceCards) {
        const evidence = data.evidence || [];
        if (evidence.length > 0) {
            resultEvidenceContainer.style.display = "block";
            resultEvidenceCards.innerHTML = "";
            evidence.slice(0, 4).forEach(ev => {
                const card = document.createElement("div");
                card.className = "evidence-card";
                card.innerHTML = `<strong>${escapeHtml(ev.heading || "Page Context")}</strong><span>${escapeHtml(ev.quote || "")}</span>`;
                resultEvidenceCards.appendChild(card);
            });
        } else {
            resultEvidenceContainer.style.display = "none";
        }
    }

    // 7. Limitations Notice
    if (resultLimitations && resultLimitationsText) {
        resultLimitationsText.textContent = data.limitations || "Grounded strictly on visible webpage context.";
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

        allScannedLinks = data.results || [];
        renderLinksList();

    } catch (err) {
        console.warn("Scan links fallback:", err);
    }
}

function renderLinksList(results = null) {
    linksListContainer.innerHTML = "";
    const sourceList = results !== null ? results : allScannedLinks;

    let filtered = sourceList;
    if (currentLinkFilter === "risky") {
        filtered = sourceList.filter(l => l.risk === "High" || l.risk === "Medium");
    } else if (currentLinkFilter === "safe") {
        filtered = sourceList.filter(l => l.risk === "Low");
    }

    if (!filtered.length) {
        linksListContainer.innerHTML = '<div style="font-size: 11px; color: var(--muted); text-align: center; padding: 16px;">No links match current filter.</div>';
        return;
    }

    filtered.forEach(link => {
        const row = document.createElement("div");
        row.className = "link-row";

        const riskClass = (link.risk || "Low").toLowerCase();
        const reasonsHtml = (link.reasons || []).map(r => `<div class="link-reason">&#9888; ${escapeHtml(r)}</div>`).join("");

        row.innerHTML = `
            <div class="link-row-top">
                <div class="link-label" title="${escapeHtml(link.text || 'Link')}">${escapeHtml(link.text || 'Link')}</div>
                <span class="badge-risk ${riskClass}">${escapeHtml(link.risk || "Low")}</span>
            </div>
            <div class="link-url" title="${escapeHtml(link.url)}">${escapeHtml(link.url)}</div>
            ${reasonsHtml}
        `;
        linksListContainer.appendChild(row);
    });
}

async function checkCustomUrl() {
    const url = (customLinkInput?.value || "").trim();
    if (!url) {
        showAlert("Please enter a URL to check.", "error");
        return;
    }

    try {
        const res = await fetch(`${BACKEND_URL}/hover-check`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: url, page_url: currentTab?.url || "" })
        });

        if (!res.ok) throw new Error("Custom link check failed");

        const data = await res.json();
        if (data.success && data.analysis) {
            renderLinksList([data.analysis]);
        }
    } catch {
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

    // Read Page Button
    btnReadPage?.addEventListener("click", readCurrentPage);

    // Command Center Run Button
    btnRunCommand?.addEventListener("click", () => executeCommand());

    // Enter key support for command input
    commandInput?.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            executeCommand();
        }
    });

    // Clear command input & reset to empty state
    btnClearCommand?.addEventListener("click", clearCommandInputAndResults);
    btnNewTask?.addEventListener("click", clearCommandInputAndResults);

    // Suggested Task Chips
    commandChips.forEach(chip => {
        chip.addEventListener("click", () => {
            const prompt = chip.getAttribute("data-prompt") || "";
            const task = chip.getAttribute("data-task") || "auto";
            if (commandInput) commandInput.value = prompt;
            executeCommand(prompt, task);
        });
    });

    // Selection Banner Actions
    btnExplainSelection?.addEventListener("click", () => {
        switchTab("panelCommand");
        const prompt = `Explain this selection: "${currentSelection.slice(0, 80)}"`;
        if (commandInput) commandInput.value = prompt;
        executeCommand("Explain this highlighted text in simple plain language", "explain_page_content");
    });

    btnAuditSelection?.addEventListener("click", () => {
        switchTab("panelCommand");
        const prompt = `Audit selection for security: "${currentSelection.slice(0, 80)}"`;
        if (commandInput) commandInput.value = prompt;
        executeCommand("Analyze this selected text for security and scam risks", "analyze_selected_text");
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

    // Link Filter Chips
    document.getElementById("filterLinksAll")?.addEventListener("click", () => {
        currentLinkFilter = "all";
        renderLinksList();
    });
    document.getElementById("filterLinksRisky")?.addEventListener("click", () => {
        currentLinkFilter = "risky";
        renderLinksList();
    });
    document.getElementById("filterLinksSafe")?.addEventListener("click", () => {
        currentLinkFilter = "safe";
        renderLinksList();
    });

    // Insights Direct Summary Action
    btnSummaryDirect?.addEventListener("click", () => {
        switchTab("panelCommand");
        if (commandInput) commandInput.value = "Summarize this page";
        executeCommand("Summarize this page with core takeaways", "summarize_page");
    });

    // Copy command result
    btnCopyCommandResult?.addEventListener("click", () => {
        const text = resultAnswer?.textContent;
        if (!text) return;
        navigator.clipboard.writeText(text).then(() => {
            const orig = btnCopyCommandResult.textContent;
            btnCopyCommandResult.textContent = "Copied!";
            setTimeout(() => { btnCopyCommandResult.textContent = orig; }, 1500);
        });
    });
}

// Start on DOM ready
document.addEventListener("DOMContentLoaded", initialize);
