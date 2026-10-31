// ============================================================
// AI BROWSER MENTOR - BACKGROUND SERVICE WORKER
// ============================================================

console.log(
    "BACKGROUND: AI Browser Mentor started"
);


// ============================================================
// GET MENTOR STATE
// ============================================================

async function getMentorState(tabId) {

    try {

        const key =
            `mentor_${tabId}`;

        const result =
            await chrome.storage.session.get(
                [key]
            );

        return result[key] === true;

    } catch (error) {

        console.error(
            "BACKGROUND: GET STATE ERROR",
            error
        );

        return false;
    }
}


// ============================================================
// SEND STATE TO CONTENT SCRIPT
// ============================================================

async function sendStateToTab(tabId) {

    try {

        const enabled =
            await getMentorState(
                tabId
            );

        console.log(
            "BACKGROUND: SEND STATE",
            {
                tabId,
                enabled
            }
        );

        await chrome.tabs.sendMessage(
            tabId,
            {
                type:
                    "MENTOR_STATE",

                enabled:
                    enabled
            }
        );

    } catch (error) {

        /*
         * This is normal on pages where content scripts
         * cannot run, such as chrome:// pages.
         */

        console.log(
            "BACKGROUND: CONTENT SCRIPT NOT AVAILABLE",
            tabId
        );
    }
}


// ============================================================
// TOGGLE MENTOR FOR TAB
// ============================================================

async function toggleMentor(tabId) {

    const key =
        `mentor_${tabId}`;


    const current =
        await getMentorState(
            tabId
        );


    const newState =
        !current;


    await chrome.storage.session.set({

        [key]:
            newState

    });


    console.log(
        "BACKGROUND: MENTOR TOGGLED",
        {
            tabId,
            enabled:
                newState
        }
    );


    await sendStateToTab(
        tabId
    );


    return newState;
}


// ============================================================
// MESSAGE LISTENER
// ============================================================

chrome.runtime.onMessage.addListener(

    async (
        message,
        sender,
        sendResponse
    ) => {

        if (!message?.type?.startsWith("ABM_")) {
            console.log(
                "BACKGROUND: MESSAGE RECEIVED",
                message
            );
        } else {
            // Verify message originated strictly from this extension
            if (sender.id && typeof chrome !== "undefined" && chrome.runtime && sender.id !== chrome.runtime.id) {
                sendResponse({ success: false, error: "Unauthorized sender" });
                return true;
            }
        }

        // ====================================================
        // SESSION TOKEN MESSAGING FALLBACK
        // ====================================================

        if (message?.type === "ABM_GET_SESSION_TOKEN") {
            try {
                chrome.storage.local.get(["abm_session_token"], (items) => {
                    if (chrome.runtime && chrome.runtime.lastError) {
                        sendResponse({ success: false, sessionToken: null });
                    } else {
                        sendResponse({
                            success: true,
                            sessionToken: items ? items["abm_session_token"] || null : null,
                        });
                    }
                });
            } catch {
                sendResponse({ success: false, sessionToken: null });
            }
            return true;
        }

        if (message?.type === "ABM_SET_SESSION_TOKEN") {
            const token = message?.token;
            if (typeof token === "string" && /^[A-Za-z0-9_-]{24,256}$/.test(token.trim())) {
                try {
                    chrome.storage.local.set({ abm_session_token: token.trim() }, () => {
                        sendResponse({ success: !Boolean(chrome.runtime && chrome.runtime.lastError) });
                    });
                } catch {
                    sendResponse({ success: false });
                }
            } else {
                sendResponse({ success: false });
            }
            return true;
        }

        if (message?.type === "ABM_CLEAR_SESSION_TOKEN") {
            try {
                chrome.storage.local.remove(["abm_session_token"], () => {
                    sendResponse({ success: !Boolean(chrome.runtime && chrome.runtime.lastError) });
                });
            } catch {
                sendResponse({ success: false });
            }
            return true;
        }


        // ====================================================
        // CONTENT SCRIPT READY
        // ====================================================

        if (
            message?.type ===
            "CONTENT_READY"
        ) {

            if (
                !sender.tab?.id
            ) {

                return;
            }


            await sendStateToTab(
                sender.tab.id
            );


            return;
        }


        // ====================================================
        // LEGACY TOGGLE MESSAGE
        //
        // Kept for compatibility with the old popup.
        // The popup is no longer used.
        // ====================================================

        if (
            message?.type ===
            "TOGGLE_MENTOR"
        ) {

            const tabId =
                message.tabId ||
                sender.tab?.id;


            if (
                !tabId
            ) {

                sendResponse({

                    success:
                        false,

                    message:
                        "No tab ID."

                });

                return;
            }


            try {

                const enabled =
                    await toggleMentor(
                        tabId
                    );


                sendResponse({

                    success:
                        true,

                    enabled:
                        enabled

                });

            } catch (error) {

                console.error(
                    "BACKGROUND: LEGACY TOGGLE ERROR",
                    error
                );


                sendResponse({

                    success:
                        false,

                    message:
                        error.message ||
                        "Could not toggle Mentor."

                });

            }


            return true;
        }

    }

);


// ============================================================
// TAB ACTIVATED
// ============================================================

chrome.tabs.onActivated.addListener(

    async (
        activeInfo
    ) => {

        console.log(
            "BACKGROUND: TAB ACTIVATED",
            activeInfo.tabId
        );


        await sendStateToTab(
            activeInfo.tabId
        );

    }

);


// ============================================================
// TAB UPDATED
// ============================================================

chrome.tabs.onUpdated.addListener(

    async (
        tabId,
        changeInfo
    ) => {

        /*
         * When a page finishes loading, make sure
         * the content script receives the current
         * Mentor state.
         */

        if (
            changeInfo.status !==
            "complete"
        ) {

            return;
        }


        console.log(
            "BACKGROUND: TAB LOADED",
            tabId
        );


        await sendStateToTab(
            tabId
        );

    }

);


// ============================================================
// TAB CLOSED
// ============================================================

chrome.tabs.onRemoved.addListener(

    async (
        tabId
    ) => {

        try {

            await chrome.storage.session.remove(
                `mentor_${tabId}`
            );


            console.log(
                "BACKGROUND: TAB STATE REMOVED",
                tabId
            );

        } catch (error) {

            console.warn(
                "BACKGROUND: CLEANUP ERROR",
                error
            );

        }

    }

);