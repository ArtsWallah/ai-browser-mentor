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
// EXTENSION ICON CLICK
// ============================================================

chrome.action.onClicked.addListener(
    async (
        tab
    ) => {

        console.log(
            "BACKGROUND: EXTENSION ICON CLICKED",
            tab?.id
        );


        if (
            !tab?.id
        ) {

            console.warn(
                "BACKGROUND: NO ACTIVE TAB"
            );

            return;
        }


        const url =
            tab.url || "";


        /*
         * Chrome does not allow content scripts
         * on internal browser pages.
         */

        if (

            url.startsWith(
                "chrome://"
            ) ||

            url.startsWith(
                "chrome-extension://"
            ) ||

            url.startsWith(
                "edge://"
            ) ||

            url.startsWith(
                "about:"
            )

        ) {

            console.warn(
                "BACKGROUND: PAGE CANNOT BE CONTROLLED",
                url
            );

            return;
        }


        try {

            await toggleMentor(
                tab.id
            );

        } catch (error) {

            console.error(
                "BACKGROUND: ICON TOGGLE ERROR",
                error
            );

        }

    }
);


// ============================================================
// MESSAGE LISTENER
// ============================================================

chrome.runtime.onMessage.addListener(

    async (
        message,
        sender,
        sendResponse
    ) => {

        console.log(
            "BACKGROUND: MESSAGE RECEIVED",
            message
        );


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