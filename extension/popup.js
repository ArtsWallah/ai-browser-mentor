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
let currentPrivacyMode = "hybrid";

// DOM Elements: Header & Status
const connectionDot = document.getElementById("connectionDot");
const connectionText = document.getElementById("connectionText");
const privacyModeSelect = document.getElementById("privacyModeSelect");
const modelStatusNotice = document.getElementById("modelStatusNotice");
const activeProviderBadge = document.getElementById("activeProviderBadge");
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
const btnDismissResult = document.getElementById("btnDismissResult");

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
const resultPageStateBanner = document.getElementById("resultPageStateBanner");
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

    if (targetPanelId === "panelWorkspace") {
        loadAndRenderWorkspace();
    }
}

function isRestrictedUrl(url) {
    if (!url) return true;
    const lower = url.toLowerCase().trim();
    return (
        lower.startsWith("chrome://") ||
        lower.startsWith("chrome-extension://") ||
        lower.startsWith("edge://") ||
        lower.startsWith("about:") ||
        lower.startsWith("view-source:") ||
        lower.startsWith("file://") ||
        lower.startsWith("data:") ||
        lower.startsWith("javascript:") ||
        lower.includes("chromewebstore.google.com") ||
        lower.includes("chrome.google.com/webstore")
    );
}

// ============================================================
// CONTENT SCRIPT COMMUNICATION & RECOVERY STRATEGY
// ============================================================

async function sendTabMessageWithRecovery(tabId, message, timeoutMs = 3500) {
    if (!tabId || tabId < 0) {
        throw new Error("No active browser tab found.");
    }

    const url = currentTab?.url || "";
    if (isRestrictedUrl(url)) {
        throw new Error("Chrome extensions cannot run on internal browser pages or the Chrome Web Store. Please open an ordinary webpage (e.g. https://www.python.org).");
    }

    // 1. Attempt direct message sending first
    try {
        const resp = await Promise.race([
            chrome.tabs.sendMessage(tabId, message),
            new Promise((_, reject) => setTimeout(() => reject(new Error("Direct connection timed out")), 1500))
        ]);
        if (resp !== undefined) {
            return resp;
        }
    } catch (directErr) {
        console.log("Direct tab message failed, attempting recovery injection:", directErr?.message);
    }

    // 2. If direct message failed, inject content.js via scripting API
    if (chrome.scripting && chrome.scripting.executeScript) {
        try {
            await chrome.scripting.executeScript({
                target: { tabId: tabId },
                files: ["content.js"]
            });
            // Brief pause for script evaluation and listener registration
            await new Promise(r => setTimeout(r, 120));
        } catch (injectErr) {
            console.warn("Script injection failed:", injectErr);
            throw new Error(`Cannot run content script on this page: ${injectErr.message || "access denied"}`);
        }

        // 3. Retry sending message after injection
        try {
            const retryResp = await Promise.race([
                chrome.tabs.sendMessage(tabId, message),
                new Promise((_, reject) => setTimeout(() => reject(new Error("Response timed out after script injection")), timeoutMs))
            ]);
            if (retryResp !== undefined) {
                return retryResp;
            }
        } catch (retryErr) {
            console.error("Retry message failed:", retryErr);
            throw new Error(`Content script communication failed: ${retryErr.message || "no response"}`);
        }
    }

    throw new Error("Could not connect to page content script. Please ensure the page is fully loaded.");
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
// INITIALIZATION & PRIVACY MANAGEMENT
// ============================================================

async function initialize() {
    await loadPrivacyMode();
    checkBackendHealth();
    await resolveActiveTab();
    setupEventListeners();
    showCommandEmptyState();
}

async function loadPrivacyMode() {
    try {
        if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
            const data = await chrome.storage.local.get(["ai_mentor_privacy_mode"]);
            if (data && data.ai_mentor_privacy_mode) {
                currentPrivacyMode = data.ai_mentor_privacy_mode;
            }
        }
    } catch (e) {
        console.warn("Storage get privacy mode:", e);
    }
    if (privacyModeSelect) {
        privacyModeSelect.value = currentPrivacyMode;
    }
    updatePrivacyModeUI();
    refreshModelRegistry();
}

async function savePrivacyMode(mode) {
    currentPrivacyMode = mode;
    try {
        if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
            await chrome.storage.local.set({ "ai_mentor_privacy_mode": mode });
        }
    } catch (e) {
        console.warn("Storage set privacy mode:", e);
    }
    updatePrivacyModeUI();
    refreshModelRegistry();
}

function updatePrivacyModeUI() {
    if (!modelStatusNotice) return;
    if (currentPrivacyMode === "local_only") {
        modelStatusNotice.innerHTML = "Privacy: <strong>🔒 Local Only</strong> &bull; Remote LLM calls blocked";
        if (activeProviderBadge) activeProviderBadge.innerHTML = "&#128274; Local Engines Only";
    } else if (currentPrivacyMode === "cloud") {
        modelStatusNotice.innerHTML = "Privacy: <strong>☁️ Cloud</strong> &bull; Remote LLM execution";
        if (activeProviderBadge) activeProviderBadge.innerHTML = "&#9729;&#65039; Cloud Enabled";
    } else {
        modelStatusNotice.innerHTML = "Privacy: <strong>⚡ Hybrid</strong> &bull; Local heuristics + cloud synthesis";
        if (activeProviderBadge) activeProviderBadge.innerHTML = "&#9889; Hybrid Routing";
    }
}

async function refreshModelRegistry() {
    try {
        const res = await fetch(`${BACKEND_URL}/models?privacy_mode=${currentPrivacyMode}`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.models && activeProviderBadge) {
            const readyLocal = data.models.filter(m => m.is_local && m.is_available).length;
            const cloudReady = data.cloud_configured;
            if (currentPrivacyMode === "local_only") {
                activeProviderBadge.innerHTML = `&#128274; ${readyLocal} Local Engine(s) Ready`;
            } else if (currentPrivacyMode === "cloud") {
                activeProviderBadge.innerHTML = cloudReady ? "&#9729;&#65039; Cloud Groq Ready" : "&#9888;&#65039; Cloud Unconfigured";
            } else {
                activeProviderBadge.innerHTML = `&#9889; ${readyLocal} Local + ${cloudReady ? "Cloud" : "Local Fallback"}`;
            }
        }
    } catch (e) {
        // Backend offline
    }
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
            refreshModelRegistry();
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
        const resp = await sendTabMessageWithRecovery(currentTab.id, { type: "GET_SELECTION" }, 1500);
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

    const tabUrl = currentTab.url || "";
    if (isRestrictedUrl(tabUrl)) {
        showAlert("Cannot read internal browser or Chrome Web Store pages. Please open an ordinary webpage.", "error");
        return;
    }

    clearAlert();
    isReadingPage = true;
    btnReadPage.disabled = true;
    readPageSpinner.style.display = "inline-block";
    readPageText.textContent = "Reading...";

    try {
        const pageData = await sendTabMessageWithRecovery(currentTab.id, { type: "GET_PAGE_CONTENT" }, 4500);

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

        const ingestRes = await res.json().catch(() => ({}));

        const chunksCount = (pageData.chunks || []).length;
        if (pageStatusBadge) {
            if (ingestRes.page_state === "loading") {
                pageStatusBadge.textContent = "Loading State";
                pageStatusBadge.className = "badge-status caution";
            } else if (ingestRes.page_state === "offline_error") {
                pageStatusBadge.textContent = "Offline/Error";
                pageStatusBadge.className = "badge-status error";
            } else {
                pageStatusBadge.textContent = `Ready (${chunksCount} chunks)`;
                pageStatusBadge.className = "badge-status ready";
            }
        }

        // Populate Insights Tab
        updateInsightsTab(ingestPayload);

        // Populate Links Tab
        scanAndRenderLinks(ingestPayload.links, ingestPayload.url);

        readPageText.textContent = "Page Ready";
        if (ingestRes.page_state === "loading") {
            showAlert("Notice: Page appears to still be loading. Try reloading if incomplete.", "info");
        } else if (ingestRes.page_state === "offline_error") {
            showAlert("Warning: Page appears offline or displays a connection error.", "error");
        } else {
            showAlert("Page successfully understood and indexed!", "info");
            setTimeout(clearAlert, 2500);
        }

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
            page_title: currentTab?.title || "",
            privacy_mode: currentPrivacyMode
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

    // 1. Tool Title & Provider Badges
    const TOOL_TITLES = {
        "explain_page_content": "Page Explanation",
        "summarize_page": "Page Summary",
        "extract_page_information": "Page Outline",
        "analyze_page_security": "Security Audit",
        "inspect_links": "Link Audit",
        "compare_provided_content": "Content Comparison",
        "answer_page_question": "Grounded Q&A",
        "analyze_selected_text": "Text Security Audit"
    };
    const rawTool = data.tool_name || data.intent || "assistant";
    const toolTitle = TOOL_TITLES[rawTool] || rawTool.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    if (resultToolBadge) {
        resultToolBadge.innerHTML = `&#9889; ${escapeHtml(toolTitle)}`;
    }

    // Provider label formatting
    const rawProvider = data.provider || "System";
    const appliedMode = data.privacy_mode_applied || currentPrivacyMode;
    let providerShort = rawProvider;
    if (rawProvider.includes("groq")) {
        providerShort = "Groq Cloud";
    } else if (rawProvider.includes("ollama")) {
        providerShort = "Ollama Local";
    } else if (rawProvider.includes("deterministic") || rawProvider.includes("engine")) {
        providerShort = "Local NLP";
    } else if (rawProvider.includes("page_state")) {
        providerShort = "State Guard";
    } else if (rawProvider.includes("scamshield")) {
        providerShort = "ScamShield";
    }
    if (resultProviderBadge) {
        resultProviderBadge.textContent = `${providerShort} • ${appliedMode}`;
        resultProviderBadge.title = `Engine: ${rawProvider} | Mode: ${appliedMode}`;
    }

    // 2. Action Summary
    if (resultActionSummary) {
        resultActionSummary.textContent = data.action_summary || "Executed task.";
    }

    // 2.5 Page State Notice (Loading or Error/Offline State)
    if (resultPageStateBanner) {
        const pageState = data.page_state || "";
        if (pageState === "loading") {
            resultPageStateBanner.className = "page-state-banner loading";
            resultPageStateBanner.style.display = "flex";
            resultPageStateBanner.innerHTML = `
                <span style="font-size: 14px; flex-shrink: 0;">&#9203;</span>
                <div>
                    <strong>Page Incomplete or Still Loading</strong>
                    <div style="margin-top: 2px;">The source webpage has not finished rendering. Wait for content to appear or reload (F5), then try again.</div>
                </div>
            `;
        } else if (pageState === "offline_error") {
            resultPageStateBanner.className = "page-state-banner offline_error";
            resultPageStateBanner.style.display = "flex";
            resultPageStateBanner.innerHTML = `
                <span style="font-size: 14px; flex-shrink: 0;">&#9888;</span>
                <div>
                    <strong>Page Offline or Connection Error</strong>
                    <div style="margin-top: 2px;">The source tab encountered a connection error or offline screen. Check your network and reload the page.</div>
                </div>
            `;
        } else {
            resultPageStateBanner.style.display = "none";
        }
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

    // 4. Direct Answer / Explanation (Robust field mapping & honest fallback)
    let answerText = (data.answer || data.text_response || "").trim();
    if (!answerText) {
        if (data.success === false) {
            answerText = data.error || data.action_summary || "Could not generate an explanation for this content.";
        } else {
            answerText = "An explanation could not be generated from the available content. Please verify that the webpage has finished loading or try highlighting a specific paragraph.";
        }
    }
    if (resultAnswer) {
        resultAnswer.textContent = answerText;
    }

    // 5. Key Points (Strictly render when actual non-placeholder points exist)
    if (resultKeyPointsContainer && resultKeyPointsList) {
        const rawPoints = Array.isArray(data.key_points) ? data.key_points : [];
        const genericPlaceholders = new Set([
            "plain-english breakdown generated",
            "key concepts simplified",
            "grounded summary generated from page chunks",
            "verified against top retrieved page sections",
            "grounded in retrieved page sections",
            "grounded summary generated"
        ]);
        const validPoints = rawPoints.filter(p => {
            const str = (p || "").trim();
            return str.length > 5 && !genericPlaceholders.has(str.toLowerCase());
        });

        if (validPoints.length > 0) {
            resultKeyPointsContainer.style.display = "block";
            resultKeyPointsList.innerHTML = "";
            validPoints.forEach(pt => {
                const item = document.createElement("div");
                item.className = "result-key-point-item";
                item.innerHTML = `<span class="result-key-point-bullet">&#9670;</span><span>${escapeHtml(pt)}</span>`;
                resultKeyPointsList.appendChild(item);
            });
        } else {
            resultKeyPointsContainer.style.display = "none";
        }
    }

    // 6. Grounded Evidence Cards (Filter empty headings, UI labels, and loading notices)
    if (resultEvidenceContainer && resultEvidenceCards) {
        const rawEvidence = Array.isArray(data.evidence) ? data.evidence : [];
        const UI_DISALLOWED = new Set([
            "search", "labels", "inbox", "sent", "drafts", "trash", "spam", "all mail",
            "navigation", "menu", "header", "footer", "sidebar", "banner"
        ]);
        const validEvidence = rawEvidence.filter(ev => {
            const quote = (ev.quote || "").trim();
            const heading = (ev.heading || "").trim().toLowerCase();
            if (quote.length < 15) return false;
            // Filter out navigation/interface single-word labels with short text
            if (UI_DISALLOWED.has(heading) && quote.length < 40) return false;
            // Filter out loading indicators from evidence cards
            const quoteLower = quote.toLowerCase();
            if (quoteLower.includes("taking longer than usual") || quoteLower.includes("reloading the page") || quoteLower.includes("gemini is offline")) {
                return false;
            }
            return true;
        });

        if (validEvidence.length > 0) {
            resultEvidenceContainer.style.display = "block";
            resultEvidenceCards.innerHTML = "";
            validEvidence.slice(0, 4).forEach(ev => {
                const card = document.createElement("div");
                card.className = "evidence-card";
                card.innerHTML = `<strong>${escapeHtml(ev.heading || "Source Passage")}</strong><span>${escapeHtml(ev.quote)}</span>`;
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
        const email = await sendTabMessageWithRecovery(currentTab.id, {
            type: "SCAMSHIELD_GET_GMAIL_EMAIL"
        }, 4000);

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

    // Render ScamShield explainable tactics if available
    const scamshieldData = audit.text_analysis?.scamshield;
    if (scamshieldData && scamshieldData.results) {
        scamshieldSection.style.display = "block";
        tacticsGrid.innerHTML = "";

        // Sort detected tactics first, then by score descending
        const sortedResults = [...scamshieldData.results].sort((a, b) => {
            if (a.detected && !b.detected) return -1;
            if (!a.detected && b.detected) return 1;
            return (b.score || 0) - (a.score || 0);
        });

        sortedResults.forEach(t => {
            const card = document.createElement("div");
            card.className = `tactic-explain-card ${t.detected ? "detected" : ""}`;

            let badgeHtml = "";
            if (!t.available) {
                badgeHtml = `<span class="tactic-badge unavailable">Unavailable</span>`;
            } else if (t.detected) {
                badgeHtml = `<span class="tactic-badge detected">&#9888; Flagged (${(t.score * 100).toFixed(0)}%)</span>`;
            } else {
                badgeHtml = `<span class="tactic-badge benign">&#10003; Below Thresh (${(t.score * 100).toFixed(0)}%)</span>`;
            }

            let spansHtml = "";
            const spans = t.evidence_spans || [];
            if (spans.length > 0) {
                spansHtml = `
                    <div class="tactic-spans-container">
                        <span style="font-size: 9px; color: var(--muted); width: 100%; font-weight: 600;">Defensible Evidence Spans (Contribution to Log-Odds):</span>
                        ${spans.map(s => `<span class="tactic-span-pill" title="Feature: ${escapeHtml(s.feature)} (weight: ${s.weight})">"${escapeHtml(s.text)}" (+${s.contribution})</span>`).join("")}
                    </div>
                `;
            }

            card.innerHTML = `
                <div class="tactic-card-header">
                    <span class="tactic-name">${escapeHtml(t.tactic.replace(/_/g, " "))}</span>
                    ${badgeHtml}
                </div>
                <div class="tactic-explanation">${escapeHtml(t.explanation || "No explanation available.")}</div>
                ${spansHtml}
                <div class="tactic-uncertainty">${escapeHtml(t.uncertainty_note || "Experimental model score. Not a calibrated probability of fraud.")}</div>
            `;

            tacticsGrid.appendChild(card);
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
    // Privacy Mode Selector
    privacyModeSelect?.addEventListener("change", (e) => {
        savePrivacyMode(e.target.value);
    });

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
            const labelSpan = btnCopyCommandResult.querySelector("span");
            if (labelSpan) {
                const orig = labelSpan.textContent;
                labelSpan.textContent = "Copied!";
                setTimeout(() => { labelSpan.textContent = orig; }, 1500);
            }
        });
    });

    // Dismiss / Close command result card
    btnDismissResult?.addEventListener("click", () => {
        showCommandEmptyState();
    });

    // ==================== WORKSPACE LISTENERS ====================
    workspaceSelect?.addEventListener("change", async (e) => {
        if (typeof WorkspaceStore !== "undefined") {
            await WorkspaceStore.setActiveWorkspaceId(e.target.value);
            await loadAndRenderWorkspace();
        }
    });

    btnNewWorkspace?.addEventListener("click", async () => {
        const name = prompt("Enter new workspace name (e.g. 'Market Research', 'Security Analysis'):");
        if (!name || !name.trim()) return;
        try {
            const ws = await WorkspaceStore.createWorkspace(name.trim());
            showWorkspaceAlert(`Created workspace '${ws.name}'!`, false);
            await loadAndRenderWorkspace();
        } catch (err) {
            showWorkspaceAlert("Could not create workspace: " + err.message, true);
        }
    });

    btnRenameWorkspace?.addEventListener("click", async () => {
        if (!activeWorkspaceData) return;
        const newName = prompt("Rename workspace:", activeWorkspaceData.name);
        if (!newName || !newName.trim()) return;
        try {
            await WorkspaceStore.renameWorkspace(activeWorkspaceData.id, newName.trim());
            showWorkspaceAlert(`Workspace renamed to '${newName.trim()}'.`, false);
            await loadAndRenderWorkspace();
        } catch (err) {
            showWorkspaceAlert("Could not rename workspace: " + err.message, true);
        }
    });

    btnDeleteWorkspace?.addEventListener("click", async () => {
        if (!activeWorkspaceData) return;
        if (!confirm(`Delete workspace '${activeWorkspaceData.name}' and all its sources?`)) return;
        try {
            await WorkspaceStore.deleteWorkspace(activeWorkspaceData.id);
            showWorkspaceAlert("Workspace deleted.", false);
            await loadAndRenderWorkspace();
        } catch (err) {
            showWorkspaceAlert(err.message, true);
        }
    });

    btnOpenFullWorkspace?.addEventListener("click", () => {
        if (typeof chrome !== "undefined" && chrome.tabs && chrome.runtime) {
            chrome.tabs.create({ url: chrome.runtime.getURL("workspace.html") });
        }
    });

    btnAddPageToWorkspace?.addEventListener("click", addCurrentPageToWorkspace);

    btnWsAskSources?.addEventListener("click", () => {
        const q = wsQueryInput?.value.trim();
        if (!q) {
            showWorkspaceAlert("Please enter a research question or topic.", true);
            wsQueryInput?.focus();
            return;
        }
        executeWorkspaceQuery(q);
    });

    wsQueryInput?.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            const q = wsQueryInput.value.trim();
            if (q) executeWorkspaceQuery(q);
        }
    });

    btnWsCompareSources?.addEventListener("click", () => {
        const focusTopic = wsQueryInput?.value.trim() || "";
        executeWorkspaceCompare(focusTopic);
    });

    btnCopyWsResult?.addEventListener("click", () => {
        const text = wsResultAnswer?.textContent;
        if (!text) return;
        navigator.clipboard.writeText(text).then(() => {
            const orig = btnCopyWsResult.textContent;
            btnCopyWsResult.textContent = "Copied!";
            setTimeout(() => { btnCopyWsResult.textContent = orig; }, 1500);
        });
    });

    // Pre-populate workspace state
    loadAndRenderWorkspace();
}

// ============================================================
// PHASE 3: RESEARCH WORKSPACE CONTROLLER
// ============================================================

let activeWorkspaceData = null;

const workspaceSelect = document.getElementById("workspaceSelect");
const btnNewWorkspace = document.getElementById("btnNewWorkspace");
const btnRenameWorkspace = document.getElementById("btnRenameWorkspace");
const btnDeleteWorkspace = document.getElementById("btnDeleteWorkspace");
const btnOpenFullWorkspace = document.getElementById("btnOpenFullWorkspace");
const wsActiveTabPreview = document.getElementById("wsActiveTabPreview");
const btnAddPageToWorkspace = document.getElementById("btnAddPageToWorkspace");
const addSourceSpinner = document.getElementById("addSourceSpinner");
const addSourceBtnText = document.getElementById("addSourceBtnText");
const workspaceAlert = document.getElementById("workspaceAlert");
const wsSourceCountBadge = document.getElementById("wsSourceCountBadge");
const wsSourcesContainer = document.getElementById("wsSourcesContainer");
const wsSourcesEmptyState = document.getElementById("wsSourcesEmptyState");

const wsQueryInput = document.getElementById("wsQueryInput");
const btnWsAskSources = document.getElementById("btnWsAskSources");
const btnWsCompareSources = document.getElementById("btnWsCompareSources");
const wsQuerySpinner = document.getElementById("wsQuerySpinner");
const wsQueryBtnText = document.getElementById("wsQueryBtnText");
const wsLoadingState = document.getElementById("wsLoadingState");
const wsLoadingTitle = document.getElementById("wsLoadingTitle");
const wsLoadingSubtitle = document.getElementById("wsLoadingSubtitle");
const wsResultCard = document.getElementById("wsResultCard");
const wsResultModeBadge = document.getElementById("wsResultModeBadge");
const wsResultProviderBadge = document.getElementById("wsResultProviderBadge");
const wsResultAnswer = document.getElementById("wsResultAnswer");
const wsCompareBreakdown = document.getElementById("wsCompareBreakdown");
const wsAgreementsList = document.getElementById("wsAgreementsList");
const wsDisagreementsList = document.getElementById("wsDisagreementsList");
const wsUnverifiedList = document.getElementById("wsUnverifiedList");
const wsCitationsContainer = document.getElementById("wsCitationsContainer");
const wsCitationsList = document.getElementById("wsCitationsList");
const wsLimitationsText = document.getElementById("wsLimitationsText");
const btnCopyWsResult = document.getElementById("btnCopyWsResult");

function showWorkspaceAlert(msg, isError = false) {
    if (!workspaceAlert) return;
    workspaceAlert.textContent = msg;
    workspaceAlert.className = "alert-box show " + (isError ? "error" : "info");
    setTimeout(() => {
        workspaceAlert.className = "alert-box";
    }, 4500);
}

async function loadAndRenderWorkspace() {
    if (typeof WorkspaceStore === "undefined") return;

    // Update active tab preview
    if (wsActiveTabPreview) {
        if (currentTab && currentTab.title) {
            let host = "";
            try { host = new URL(currentTab.url).hostname; } catch (_) {}
            wsActiveTabPreview.textContent = `${currentTab.title} (${host})`;
            wsActiveTabPreview.title = currentTab.url || "";
        } else {
            wsActiveTabPreview.textContent = "No active tab selected";
        }
    }

    try {
        const workspaces = await WorkspaceStore.getWorkspaces();
        const activeId = await WorkspaceStore.getActiveWorkspaceId();
        activeWorkspaceData = workspaces.find(w => w.id === activeId) || workspaces[0];

        if (workspaceSelect) {
            workspaceSelect.innerHTML = "";
            workspaces.forEach(ws => {
                const opt = document.createElement("option");
                opt.value = ws.id;
                opt.textContent = `${ws.name} (${ws.sources?.length || 0})`;
                if (ws.id === activeWorkspaceData.id) opt.selected = true;
                workspaceSelect.appendChild(opt);
            });
        }

        renderWorkspaceSources();
    } catch (err) {
        console.error("loadAndRenderWorkspace error:", err);
        showWorkspaceAlert("Failed to load workspace: " + err.message, true);
    }
}

function renderWorkspaceSources() {
    if (!activeWorkspaceData || !wsSourcesContainer) return;

    const sources = activeWorkspaceData.sources || [];
    if (wsSourceCountBadge) {
        wsSourceCountBadge.textContent = `${sources.length} Source${sources.length === 1 ? "" : "s"}`;
    }

    wsSourcesContainer.innerHTML = "";

    if (sources.length === 0) {
        if (wsSourcesEmptyState) {
            wsSourcesContainer.appendChild(wsSourcesEmptyState);
            wsSourcesEmptyState.style.display = "block";
        }
        return;
    }

    if (wsSourcesEmptyState) wsSourcesEmptyState.style.display = "none";

    sources.forEach(src => {
        const card = document.createElement("div");
        card.className = "source-card";
        const timeStr = src.collected_at ? new Date(src.collected_at).toLocaleDateString() : "Saved";

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
            <div class="source-card-actions">
                <a href="${escapeHtml(src.url)}" target="_blank" rel="noopener noreferrer" class="btn-source-link">🔗 Open URL ↗</a>
                <button class="btn-remove-source" data-src-id="${src.id}" title="Remove source">✕ Remove</button>
            </div>
        `;

        card.querySelector(".btn-remove-source")?.addEventListener("click", async () => {
            try {
                await WorkspaceStore.removeSource(activeWorkspaceData.id, src.id);
                showWorkspaceAlert(`Removed '${src.title}' from workspace.`, false);
                await loadAndRenderWorkspace();
            } catch (err) {
                showWorkspaceAlert("Failed to remove source: " + err.message, true);
            }
        });

        wsSourcesContainer.appendChild(card);
    });
}

async function addCurrentPageToWorkspace() {
    if (!currentTab || !currentTab.id) {
        showWorkspaceAlert("No active browser tab found.", true);
        return;
    }

    if (isRestrictedUrl(currentTab.url)) {
        showWorkspaceAlert("Chrome extensions cannot access internal browser pages or the Chrome Web Store. Please open an ordinary webpage.", true);
        return;
    }

    if (!activeWorkspaceData) {
        showWorkspaceAlert("No active workspace selected.", true);
        return;
    }

    addSourceSpinner.style.display = "inline-block";
    addSourceBtnText.textContent = "Extracting...";
    btnAddPageToWorkspace.disabled = true;

    try {
        let pageDataToSave = currentPageData;
        if (!pageDataToSave || pageDataToSave.url !== currentTab.url) {
            // Extract from active tab
            pageDataToSave = await sendTabMessageWithRecovery(currentTab.id, { action: "EXTRACT_PAGE_CONTENT" });
        }

        if (!pageDataToSave || (!pageDataToSave.content && !pageDataToSave.paragraphs?.length && !pageDataToSave.title)) {
            throw new Error("Could not extract meaningful content from this page.");
        }

        const sourceInput = {
            title: pageDataToSave.title || currentTab.title,
            url: pageDataToSave.url || currentTab.url,
            hostname: pageDataToSave.hostname || (currentTab.url ? new URL(currentTab.url).hostname : ""),
            text: pageDataToSave.content || (pageDataToSave.paragraphs || []).join("\n\n"),
            excerpt: pageDataToSave.description || "",
            headings: pageDataToSave.headings || []
        };

        const result = await WorkspaceStore.addSource(activeWorkspaceData.id, sourceInput);
        if (result.isDuplicate) {
            showWorkspaceAlert(`⚠️ Notice: This page is already saved in '${activeWorkspaceData.name}'.`, true);
        } else {
            showWorkspaceAlert(`✓ Added '${result.source.title}' to '${activeWorkspaceData.name}'!`, false);
            await loadAndRenderWorkspace();
        }
    } catch (err) {
        console.error("addCurrentPageToWorkspace error:", err);
        showWorkspaceAlert("Failed to add page: " + err.message, true);
    } finally {
        addSourceSpinner.style.display = "none";
        addSourceBtnText.textContent = "➕ Add Page";
        btnAddPageToWorkspace.disabled = false;
    }
}

async function executeWorkspaceQuery(query) {
    if (!activeWorkspaceData || !activeWorkspaceData.sources || activeWorkspaceData.sources.length === 0) {
        showWorkspaceAlert("Please add at least one page to this workspace before querying.", true);
        return;
    }

    setWsLoading(true, "Synthesizing Across Sources...", "Lexical retrieval and citation extraction");

    try {
        const res = await fetch(`${BACKEND_URL}/workspace/query`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                query: query,
                workspace_name: activeWorkspaceData.name,
                privacy_mode: currentPrivacyMode,
                sources: activeWorkspaceData.sources.map(s => ({
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
            throw new Error(`Server returned error ${res.status}: ${await res.text()}`);
        }

        const data = await res.json();
        renderWorkspaceSynthesis(data, "query");
    } catch (err) {
        renderWorkspaceError("Cross-source query failed: " + err.message);
    } finally {
        setWsLoading(false);
    }
}

async function executeWorkspaceCompare(focusTopic) {
    if (!activeWorkspaceData || !activeWorkspaceData.sources || activeWorkspaceData.sources.length < 2) {
        showWorkspaceAlert("Source comparison requires at least 2 saved pages in this workspace. Please add more pages first.", true);
        return;
    }

    setWsLoading(true, "Comparing Saved Sources...", "Analyzing agreement, differences, and unverified claims");

    try {
        const res = await fetch(`${BACKEND_URL}/workspace/compare`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                workspace_name: activeWorkspaceData.name,
                focus_topic: focusTopic,
                privacy_mode: currentPrivacyMode,
                sources: activeWorkspaceData.sources.map(s => ({
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
            throw new Error(`Server returned error ${res.status}: ${await res.text()}`);
        }

        const data = await res.json();
        renderWorkspaceSynthesis(data, "compare");
    } catch (err) {
        renderWorkspaceError("Source comparison failed: " + err.message);
    } finally {
        setWsLoading(false);
    }
}

function setWsLoading(isLoading, title = "", subtitle = "") {
    if (isLoading) {
        wsResultCard.style.display = "none";
        wsLoadingState.style.display = "flex";
        wsLoadingTitle.textContent = title;
        wsLoadingSubtitle.textContent = subtitle;
        btnWsAskSources.disabled = true;
        btnWsCompareSources.disabled = true;
    } else {
        wsLoadingState.style.display = "none";
        btnWsAskSources.disabled = false;
        btnWsCompareSources.disabled = false;
    }
}

function renderWorkspaceSynthesis(data, mode) {
    wsLoadingState.style.display = "none";
    wsResultCard.style.display = "flex";

    const appliedMode = data.privacy_mode_applied || currentPrivacyMode;
    if (mode === "compare") {
        wsResultModeBadge.textContent = "⚖️ Source Comparison";
        wsResultProviderBadge.textContent = `${data.provider || "Grounded LLM"} • ${appliedMode}`;
        wsResultAnswer.textContent = data.comparison_summary || "Comparison completed.";

        wsCompareBreakdown.style.display = "flex";
        renderList(wsAgreementsList, data.agreements, "No specific consensus points detected.");
        renderList(wsDisagreementsList, data.disagreements, "No direct contradictions found.");
        renderList(wsUnverifiedList, data.unverified_claims, "All key claims have source coverage.");
    } else {
        wsResultModeBadge.textContent = "🔍 Research Synthesis";
        wsResultProviderBadge.textContent = `${data.provider || "Grounded LLM"} • ${appliedMode}`;
        wsResultAnswer.textContent = data.answer || "No response generated.";
        wsCompareBreakdown.style.display = "none";
    }

    // Render citations
    wsCitationsList.innerHTML = "";
    const citations = data.citations || [];
    if (citations.length > 0) {
        wsCitationsContainer.style.display = "flex";
        citations.forEach(c => {
            const card = document.createElement("div");
            card.className = "evidence-citation-card";
            card.innerHTML = `
                <div class="citation-title-row">
                    <span class="citation-title">${escapeHtml(c.source_title || "Source")}</span>
                    <a href="${escapeHtml(c.url)}" target="_blank" rel="noopener noreferrer" style="color: var(--cyan); text-decoration: none; font-size: 10px;">Visit Page ↗</a>
                </div>
                <div class="citation-quote">"${escapeHtml(c.quote)}"</div>
            `;
            wsCitationsList.appendChild(card);
        });
    } else {
        wsCitationsContainer.style.display = "none";
    }

    wsLimitationsText.textContent = data.limitations || "Grounded in bounded excerpts from saved workspace pages.";
}

function renderWorkspaceError(msg) {
    wsLoadingState.style.display = "none";
    wsResultCard.style.display = "flex";
    wsResultModeBadge.textContent = "⚠️ Error";
    wsResultProviderBadge.textContent = "Local";
    wsResultAnswer.textContent = msg;
    wsCompareBreakdown.style.display = "none";
    wsCitationsContainer.style.display = "none";
    wsLimitationsText.textContent = "Verify backend is running on http://127.0.0.1:8000.";
}

function renderList(container, items, emptyMessage) {
    container.innerHTML = "";
    if (!items || items.length === 0) {
        const div = document.createElement("div");
        div.className = "finding-item";
        div.textContent = emptyMessage;
        container.appendChild(div);
        return;
    }
    items.forEach(text => {
        const div = document.createElement("div");
        div.className = "finding-item";
        div.innerHTML = `<span class="finding-bullet">&bull;</span><span>${escapeHtml(text)}</span>`;
        container.appendChild(div);
    });
}

// Start on DOM ready
document.addEventListener("DOMContentLoaded", initialize);

