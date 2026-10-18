// ============================================================
// AI BROWSER MENTOR - POPUP
// ============================================================

console.log(
    "POPUP: AI Browser Mentor loaded"
);


// ============================================================
// CONFIG
// ============================================================

const BACKEND_URL =
    "http://127.0.0.1:8000";


// ============================================================
// DOM
// ============================================================

const readPageButton =
    document.getElementById("readPageButton");

const loadingIndicator =
    document.getElementById("loadingIndicator");

const loadingText =
    document.getElementById("loadingText");

const pageResult =
    document.getElementById("pageResult");

const errorBox =
    document.getElementById("errorBox");

const pageTitle =
    document.getElementById("pageTitle");

const chunkCount =
    document.getElementById("chunkCount");

const imageCount =
    document.getElementById("imageCount");

const linkCount =
    document.getElementById("linkCount");

const elementCount =
    document.getElementById("elementCount");

const questionInput =
    document.getElementById("questionInput");

const askButton =
    document.getElementById("askButton");

const answerArea =
    document.getElementById("answerArea");

const answerText =
    document.getElementById("answerText");

const scanResult =
    document.getElementById("securityResult");

const securityTotal =
    document.getElementById("securityTotal");

const safeCount =
    document.getElementById("safeCount");

const suspiciousCount =
    document.getElementById("suspiciousCount");

const riskyCount =
    document.getElementById("riskyCount");

const connectionDot =
    document.getElementById("connectionDot");

const connectionText =
    document.getElementById("connectionText");


// ============================================================
// STATE
// ============================================================

let currentTab = null;

let pageData = null;

let currentPageId = null;

let pageRead = false;

let mentorEnabled = false;


// ============================================================
// CURRENT TAB
// ============================================================

async function getCurrentTab() {

    const tabs =
        await chrome.tabs.query({

            active: true,

            currentWindow: true
        });


    return tabs[0];
}


// ============================================================
// RESTRICTED PAGE CHECK
// ============================================================

function isRestrictedPage(
    url
) {

    if (!url) {
        return true;
    }


    return (

        url.startsWith("chrome://") ||

        url.startsWith(
            "chrome-extension://"
        ) ||

        url.startsWith("edge://") ||

        url.startsWith("about:") ||

        url.startsWith("devtools:")
    );
}


// ============================================================
// STATUS
// ============================================================

function setStatus(
    active,
    text
) {

    connectionDot?.classList.toggle(
        "active",
        active
    );


    if (connectionText) {

        connectionText.textContent =
            text;
    }
}


// ============================================================
// ERROR
// ============================================================

function showError(
    message
) {

    if (!errorBox) {
        return;
    }


    errorBox.textContent =
        message ||
        "Something went wrong.";


    errorBox.classList.add(
        "show"
    );
}


function clearError() {

    if (!errorBox) {
        return;
    }


    errorBox.textContent =
        "";


    errorBox.classList.remove(
        "show"
    );
}


// ============================================================
// LOADING
// ============================================================

function setLoading(
    enabled,
    message
) {

    loadingIndicator?.classList.toggle(
        "show",
        enabled
    );


    if (loadingText && message) {

        loadingText.textContent =
            message;
    }


    if (readPageButton) {

        readPageButton.disabled =
            enabled;

        readPageButton.classList.toggle(
            "loading",
            enabled
        );
    }
}


// ============================================================
// NUMBER FORMAT
// ============================================================

function formatNumber(
    value
) {

    return Number(
        value || 0
    ).toLocaleString();
}


// ============================================================
// GENERATE PAGE ID
// ============================================================

function generatePageId(
    tab
) {

    if (
        pageData?.page_id
    ) {

        return pageData.page_id;
    }


    if (
        pageData?.pageId
    ) {

        return pageData.pageId;
    }


    return (
        tab?.url ||
        `tab_${tab?.id || Date.now()}`
    );
}


// ============================================================
// NORMALIZE PAGE DATA
// ============================================================

function normalizePageData(
    raw
) {

    const data =
        raw?.page ||
        raw?.data ||
        raw;


    return {

        ...data,

        page_id:
            data?.page_id ||
            data?.pageId ||
            data?.url ||
            `page_${Date.now()}`,

        title:
            data?.title ||
            "Current webpage",

        url:
            data?.url ||
            currentTab?.url ||
            "",

        hostname:
            data?.hostname ||
            (() => {

                try {

                    return new URL(
                        data?.url ||
                        currentTab?.url
                    ).hostname;

                } catch {

                    return "";
                }

            })(),

        headings:
            Array.isArray(
                data?.headings
            )
                ? data.headings
                : [],

        paragraphs:
            Array.isArray(
                data?.paragraphs
            )
                ? data.paragraphs
                : [],

        links:
            Array.isArray(
                data?.links
            )
                ? data.links
                : [],

        chunks:
            Array.isArray(
                data?.chunks
            )
                ? data.chunks
                : [],

        interactiveElements:
            Array.isArray(
                data?.interactiveElements
            )
                ? data.interactiveElements
                : [],

        content:
            data?.content ||
            "",

        wordCount:
            Number(
                data?.wordCount ||
                0
            )
    };
}


// ============================================================
// SEND PAGE TO BACKEND
// ============================================================

async function ingestPage(
    data
) {

    console.log(
        "POPUP: Sending page to /page/ingest"
    );


    const response =
        await fetch(
            `${BACKEND_URL}/page/ingest`,
            {

                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body:
                    JSON.stringify({

                        page_id:
                            data.page_id,

                        title:
                            data.title,

                        url:
                            data.url,

                        hostname:
                            data.hostname,

                        description:
                            data.description ||
                            "",

                        headings:
                            data.headings,

                        paragraphs:
                            data.paragraphs,

                        links:
                            data.links,

                        chunks:
                            data.chunks,

                        content:
                            data.content,

                        interactiveElements:
                            data.interactiveElements,

                        wordCount:
                            data.wordCount
                    })
            }
        );


    if (!response.ok) {

        const text =
            await response.text();

        throw new Error(
            `Backend /page/ingest error ${response.status}: ${text}`
        );
    }


    const result =
        await response.json();


    console.log(
        "POPUP: PAGE INGESTED",
        result
    );


    if (
        result.success === false
    ) {

        throw new Error(
            result.message ||
            "Backend could not store the page."
        );
    }


    return result;
}


// ============================================================
// GET PAGE FROM CONTENT SCRIPT
// ============================================================

async function getPageContent() {

    if (!currentTab?.id) {

        throw new Error(
            "No active browser tab."
        );
    }


    try {

        const response =
            await chrome.tabs.sendMessage(

                currentTab.id,

                {
                    type:
                        "GET_PAGE_CONTENT"
                }
            );


        if (!response) {

            throw new Error(
                "The webpage did not respond."
            );
        }


        if (
            response.success === false
        ) {

            throw new Error(
                response.error ||
                response.message ||
                "Could not read the webpage."
            );
        }


        return response;

    } catch (error) {

        console.error(
            "POPUP: GET_PAGE_CONTENT ERROR",
            error
        );


        throw new Error(
            "Could not read this page. Refresh the webpage and try again."
        );
    }
}


// ============================================================
// ENABLE MENTOR
// ============================================================

async function enableMentor() {

    if (!currentTab?.id) {
        return false;
    }


    try {

        const response =
            await chrome.runtime.sendMessage({

                type:
                    "TOGGLE_MENTOR",

                tabId:
                    currentTab.id
            });


        console.log(
            "POPUP: MENTOR TOGGLE",
            response
        );


        if (
            response?.success
        ) {

            mentorEnabled =
                response.enabled;

            return mentorEnabled;
        }

    } catch (error) {

        console.warn(
            "POPUP: Background Mentor toggle failed",
            error
        );
    }


    // Fallback to content script.

    try {

        const response =
            await chrome.tabs.sendMessage(

                currentTab.id,

                {
                    type:
                        "MENTOR_STATE",

                    enabled:
                        true
                }
            );


        mentorEnabled =
            response?.enabled !== false;


        return mentorEnabled;

    } catch (error) {

        console.error(
            "POPUP: Direct Mentor activation failed",
            error
        );


        return false;
    }
}


// ============================================================
// UPDATE PAGE UI
// ============================================================

function showPageResult(
    data
) {

    pageData =
        data;

    currentPageId =
        data.page_id;

    pageRead =
        true;


    if (pageTitle) {

        pageTitle.textContent =
            data.title;
    }


    if (chunkCount) {

        chunkCount.textContent =
            formatNumber(
                data.chunks.length
            );
    }


    if (imageCount) {

        imageCount.textContent =
            formatNumber(
                data.images?.length ||
                0
            );
    }


    if (linkCount) {

        linkCount.textContent =
            formatNumber(
                data.links.length
            );
    }


    if (elementCount) {

        elementCount.textContent =
            formatNumber(
                data.interactiveElements.length
            );
    }


    pageResult?.classList.add(
        "show"
    );


    if (readPageButton) {

        readPageButton.textContent =
            "Page Read Successfully";

        readPageButton.classList.add(
            "success"
        );
    }
}


// ============================================================
// READ CURRENT PAGE
// ============================================================

async function readCurrentPage() {

    clearError();


    try {

        currentTab =
            await getCurrentTab();


        if (
            !currentTab?.id
        ) {

            throw new Error(
                "No active browser tab."
            );
        }


        if (
            isRestrictedPage(
                currentTab.url
            )
        ) {

            throw new Error(
                "Chrome does not allow the extension to read this page."
            );
        }


        setLoading(
            true,
            "Reading webpage..."
        );


        setStatus(
            false,
            "Reading..."
        );


        // ----------------------------------------------------
        // 1. Extract page locally
        // ----------------------------------------------------

        const rawPage =
            await getPageContent();


        console.log(
            "POPUP: RAW PAGE",
            rawPage
        );


        // ----------------------------------------------------
        // 2. Normalize page
        // ----------------------------------------------------

        const normalized =
            normalizePageData(
                rawPage
            );


        pageData =
            normalized;


        currentPageId =
            generatePageId(
                currentTab
            );


        normalized.page_id =
            currentPageId;


        // ----------------------------------------------------
        // 3. Store page in FastAPI
        // ----------------------------------------------------

        setLoading(
            true,
            "Saving page context..."
        );


        await ingestPage(
            normalized
        );


        // ----------------------------------------------------
        // 4. Show UI
        // ----------------------------------------------------

        showPageResult(
            normalized
        );


        // ----------------------------------------------------
        // 5. Enable all Mentor features
        // ----------------------------------------------------

        setLoading(
            true,
            "Activating Mentor..."
        );


        await enableMentor();


        // ----------------------------------------------------
        // 6. Scan links
        // ----------------------------------------------------

        setLoading(
            true,
            "Scanning page links..."
        );


        await scanPage();


        // ----------------------------------------------------
        // DONE
        // ----------------------------------------------------

        setLoading(
            false
        );


        setStatus(
            true,
            "Active"
        );


        console.log(
            "POPUP: PAGE ACTIVATION COMPLETE"
        );

    } catch (error) {

        console.error(
            "POPUP: READ ERROR",
            error
        );


        setLoading(
            false
        );


        setStatus(
            false,
            "Error"
        );


        showError(
            error?.message ||
            "Could not read the current page."
        );
    }
}


// ============================================================
// SCAN PAGE
// ============================================================

async function scanPage() {

    if (!currentTab?.id) {
        return;
    }


    try {

        const response =
            await chrome.tabs.sendMessage(

                currentTab.id,

                {
                    type:
                        "SCAN_LINKS"
                }
            );


        console.log(
            "POPUP: SCAN RESULT",
            response
        );


        if (
            !response?.success
        ) {

            throw new Error(
                response?.error ||
                response?.message ||
                "Could not scan page links."
            );
        }


        const summary =
            response.summary ||
            {};


        scanResult?.classList.add(
            "show"
        );


        if (securityTotal) {

            securityTotal.textContent =
                `${formatNumber(
                    summary.total
                )} links`;
        }


        if (safeCount) {

            safeCount.textContent =
                formatNumber(
                    summary.low ??
                    summary.safe ??
                    0
                );
        }


        if (suspiciousCount) {

            suspiciousCount.textContent =
                formatNumber(
                    summary.medium ??
                    summary.suspicious ??
                    0
                );
        }


        if (riskyCount) {

            riskyCount.textContent =
                formatNumber(
                    summary.high ??
                    summary.risky ??
                    0
                );
        }


        return response;

    } catch (error) {

        console.error(
            "POPUP: SCAN ERROR",
            error
        );


        showError(
            error?.message ||
            "Could not scan the page."
        );


        return null;
    }
}


// ============================================================
// DETECT NAVIGATION REQUEST
// ============================================================

function looksLikeNavigationRequest(
    question
) {

    const text =
        question
            .toLowerCase()
            .trim();


    const navigationPatterns = [

        "take me to",

        "go to",

        "navigate to",

        "find the",

        "where is the",

        "where can i",

        "show me the",

        "locate the",

        "open the",

        "click the",

        "click on",

        "bring me to",

        "scroll to"
    ];


    return navigationPatterns.some(
        pattern =>
            text.includes(pattern)
    );
}


// ============================================================
// CLEAN NAVIGATION QUERY
// ============================================================

function cleanNavigationQuery(
    question
) {

    let query =
        question
            .trim();


    const patterns = [

        /^take me to\s+/i,

        /^go to\s+/i,

        /^navigate to\s+/i,

        /^find the\s+/i,

        /^where is the\s+/i,

        /^where can i\s+/i,

        /^show me the\s+/i,

        /^locate the\s+/i,

        /^open the\s+/i,

        /^click the\s+/i,

        /^click on\s+/i,

        /^bring me to\s+/i,

        /^scroll to\s+/i
    ];


    for (
        const pattern
        of patterns
    ) {

        query =
            query.replace(
                pattern,
                ""
            );

        break;
    }


    return query.trim();
}


// ============================================================
// HANDLE LOCAL NAVIGATION
// ============================================================

async function handleNavigation(
    question
) {

    if (!currentTab?.id) {
        return false;
    }


    const query =
        cleanNavigationQuery(
            question
        );


    console.log(
        "POPUP: LOCAL NAVIGATION REQUEST:",
        query
    );


    try {

        const response =
            await chrome.tabs.sendMessage(

                currentTab.id,

                {
                    type:
                        "LOCAL_NAVIGATE",

                    query:
                        query,

                    focus:
                        true,

                    activate:
                        false
                }
            );


        console.log(
            "POPUP: NAVIGATION RESULT",
            response
        );


        if (
            response?.success
        ) {

            showAnswer(
                response.message ||
                `I found "${query}" on the page and highlighted it.`
            );


            return true;
        }


        showAnswer(
            response?.message ||
            `I couldn't find "${query}" on this page.`
        );


        return true;

    } catch (error) {

        console.error(
            "POPUP: NAVIGATION ERROR",
            error
        );


        showAnswer(
            `I couldn't navigate to "${query}".`
        );


        return true;
    }
}


// ============================================================
// SHOW ANSWER
// ============================================================

function showAnswer(
    text
) {

    if (!answerArea) {
        return;
    }


    answerText.textContent =
        text || "No answer returned.";


    answerArea.classList.add(
        "show"
    );
}


// ============================================================
// ASK BACKEND
// ============================================================

async function askBackend(
    question
) {

    if (!currentPageId) {

        throw new Error(
            "Please read the page first."
        );
    }


    console.log(
        "POPUP: ASKING BACKEND",
        {
            question,
            page_id:
                currentPageId
        }
    );


    const response =
        await fetch(
            `${BACKEND_URL}/ask`,
            {

                method:
                    "POST",

                headers: {

                    "Content-Type":
                        "application/json"
                },

                body:
                    JSON.stringify({

                        question:
                            question,

                        page_id:
                            currentPageId,

                        top_k:
                            5
                    })
            }
        );


    const result =
        await response.json();


    console.log(
        "POPUP: /ask RESPONSE",
        result
    );


    if (!response.ok) {

        throw new Error(
            result?.message ||
            `Backend returned ${response.status}`
        );
    }


    if (
        result.success === false
    ) {

        throw new Error(
            result.message ||
            "The AI could not answer the question."
        );
    }


    return result;
}


// ============================================================
// ASK MENTOR
// ============================================================

async function askMentor() {

    clearError();


    if (
        !pageRead ||
        !currentPageId
    ) {

        showError(
            "Read the page first."
        );

        return;
    }


    const question =
        questionInput?.value.trim();


    if (!question) {

        showError(
            "Please enter a question."
        );

        questionInput?.focus();

        return;
    }


    if (askButton) {

        askButton.disabled =
            true;

        askButton.textContent =
            "Thinking...";
    }


    showAnswer(
        "Analyzing the page..."
    );


    try {

        // ----------------------------------------------------
        // Navigation request?
        // ----------------------------------------------------

        if (
            looksLikeNavigationRequest(
                question
            )
        ) {

            await handleNavigation(
                question
            );


            return;
        }


        // ----------------------------------------------------
        // Normal AI question
        // ----------------------------------------------------

        const result =
            await askBackend(
                question
            );


        showAnswer(
            result.answer ||
            "I couldn't find an answer on this page."
        );

    } catch (error) {

        console.error(
            "POPUP: ASK ERROR",
            error
        );


        showAnswer(
            "I couldn't answer that right now."
        );


        showError(
            error?.message ||
            "The AI request failed."
        );

    } finally {

        if (askButton) {

            askButton.disabled =
                false;

            askButton.textContent =
                "Ask Mentor";
        }
    }
}


// ============================================================
// INITIALIZE
// ============================================================

async function initialize() {

    try {

        currentTab =
            await getCurrentTab();


        if (!currentTab?.id) {

            setStatus(
                false,
                "No active tab"
            );

            return;
        }


        if (
            isRestrictedPage(
                currentTab.url
            )
        ) {

            setStatus(
                false,
                "Unavailable"
            );


            readPageButton.disabled =
                true;


            readPageButton.textContent =
                "Unavailable on this page";


            return;
        }


        setStatus(
            true,
            "Ready"
        );


        console.log(
            "POPUP: Ready for",
            currentTab.url
        );

    } catch (error) {

        console.error(
            "POPUP: INIT ERROR",
            error
        );


        setStatus(
            false,
            "Error"
        );
    }
}


// ============================================================
// EVENTS
// ============================================================

readPageButton?.addEventListener(
    "click",
    readCurrentPage
);


askButton?.addEventListener(
    "click",
    askMentor
);


// Ctrl + Enter / Cmd + Enter

questionInput?.addEventListener(
    "keydown",
    event => {

        if (
            event.key === "Enter" &&
            (event.ctrlKey ||
             event.metaKey)
        ) {

            event.preventDefault();

            askMentor();
        }
    }
);


// ============================================================
// START
// ============================================================

initialize();
// SCAMSHIELD_EMAIL_ANALYSIS_HANDLER
const scamShieldEmailButton = document.getElementById("scamShieldEmailButton");
const scamShieldEmailStatus = document.getElementById("scamShieldEmailStatus");
const scamShieldEmailResults = document.getElementById("scamShieldEmailResults");

scamShieldEmailButton?.addEventListener("click", async () => {
    scamShieldEmailButton.disabled = true;
    scamShieldEmailStatus.textContent = "Reading the open Gmail message...";
    scamShieldEmailResults.hidden = true;
    scamShieldEmailResults.replaceChildren();

    try {
        const tab = await getCurrentTab();

        if (!tab?.id || !tab.url?.startsWith("https://mail.google.com/")) {
            throw new Error("Open Gmail and select an individual email first.");
        }

        const email = await chrome.tabs.sendMessage(tab.id, {
            type: "SCAMSHIELD_GET_GMAIL_EMAIL"
        });

        if (!email?.success || !email.message) {
            throw new Error(email?.message || "Could not extract the email.");
        }

        scamShieldEmailStatus.textContent = "Analyzing email tactics...";

        const response = await fetch(`${BACKEND_URL}/scamshield/analyze-text`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: email.message })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "The analysis request failed.");
        }

        const heading = document.createElement("h3");
        heading.textContent = `Tactic analysis: ${email.subject || "Opened email"}`;
        scamShieldEmailResults.appendChild(heading);
// Final verdict based on available tactic predictions.
// This is a risk assessment, not proof of fraud or legitimacy.
const availableResults = (data.results || []).filter(
    item => item.available === true && typeof item.detected === "boolean"
);
const detectedResults = availableResults.filter(item => item.detected);
const verdictCard = document.createElement("div");
verdictCard.className = "verdict-card";

const verdictTitle = document.createElement("span");
verdictTitle.className = "verdict-title";

const verdictDetail = document.createElement("span");
verdictDetail.className = "verdict-detail";

if (availableResults.length === 0) {
    verdictTitle.textContent = "Inconclusive";
    verdictTitle.style.color = "#b45309";
    verdictDetail.textContent =
        "No usable tactic predictions are available. Do not rely on this result.";
} else if (detectedResults.length >= 2) {
    verdictTitle.textContent = "Likely Suspicious";
    verdictTitle.style.color = "#b91c1c";
    verdictDetail.textContent =
        `${detectedResults.length} suspicious tactic signal(s) detected. Treat this email cautiously and verify claims independently.`;
} else if (detectedResults.length === 1) {
    verdictTitle.textContent = "Needs Caution";
    verdictTitle.style.color = "#b45309";
    verdictDetail.textContent =
        "A suspicious tactic signal was detected. Review the email and verify the sender before taking action.";
} else if (availableResults.length < (data.results || []).length) {
    verdictTitle.textContent = "Inconclusive";
    verdictTitle.style.color = "#b45309";
    verdictDetail.textContent =
        "No signals were detected by the available checks, but some checks were unavailable. This does not establish that the email is genuine.";
} else {
    verdictTitle.textContent = "No Strong Scam Signals";
    verdictTitle.style.color = "#15803d";
    verdictDetail.textContent =
        "The available tactic checks found no strong signals. This does not guarantee that the email is genuine.";
}

verdictCard.append(verdictTitle, verdictDetail);
scamShieldEmailResults.appendChild(verdictCard);

        for (const item of data.results || []) {
            const row = document.createElement("div");
            row.className = "tactic-row"; row.style.cssText = "padding:8px 0;border-bottom:1px solid #e5e7eb";

            const name = document.createElement("strong");
            name.textContent = String(item.tactic).replaceAll("_", " ");
            row.appendChild(name);

            const detail = document.createElement("div");
            if (item.available === false || item.detected === null) {
                detail.textContent = "Unavailable - this tactic cannot currently be assessed.";
            } else {
                const percent = Number.isFinite(item.score)
                    ? ` (model score: ${(item.score * 100).toFixed(1)}%)`
                    : "";
                detail.textContent = `${item.detected ? "Potential signal detected" : "Not detected"}${percent}`;
            }

            row.appendChild(detail);
            scamShieldEmailResults.appendChild(row);
        }

        const disclaimer = document.createElement("p");
        disclaimer.style.cssText = "font-size:12px;color:#6b7280;margin-top:10px";
        disclaimer.textContent = data.disclaimer || "Experimental model output; not a definitive scam verdict.";
        scamShieldEmailResults.appendChild(disclaimer);

        scamShieldEmailResults.hidden = false;
        scamShieldEmailStatus.textContent = "Analysis complete.";
    } catch (error) {
        scamShieldEmailStatus.textContent = error?.message || "Email analysis failed.";
    } finally {
        scamShieldEmailButton.disabled = false;
    }
});


