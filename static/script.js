// =========================================================
// GLOBAL STATE
// =========================================================

let currentThreadId = null;


// =========================================================
// HELPER FUNCTIONS
// =========================================================

function show(id) {

    const element =
        document.getElementById(id);

    if (element) {
        element.classList.remove("hidden");
    }
}


function hide(id) {

    const element =
        document.getElementById(id);

    if (element) {
        element.classList.add("hidden");
    }
}


function setText(id, value) {

    const element =
        document.getElementById(id);

    if (element) {
        element.textContent =
            value ?? "";
    }
}


function formatValue(value) {

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "No information available.";
    }

    if (typeof value === "object") {

        return JSON.stringify(
            value,
            null,
            2
        );
    }

    return String(value);
}


// =========================================================
// MARKDOWN RENDERING
// =========================================================

function renderMarkdown(value) {

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "No information available.";
    }

    const text =
        formatValue(value);


    if (
        typeof marked !== "undefined"
    ) {

        return marked.parse(text);
    }


    return text.replace(
        /\n/g,
        "<br>"
    );
}


// =========================================================
// QUICK PROMPTS
// =========================================================

function setPrompt(text) {

    const input =
        document.getElementById(
            "userInput"
        );

    input.value = text;

    input.focus();
}


// =========================================================
// WORKFLOW DISPLAY
// =========================================================

function updateWorkflow(data) {

    show("workflowSection");


    // -------------------------
    // Guardrail
    // -------------------------

    const badge =
        document.getElementById(
            "guardrailBadge"
        );

    const indicator =
        document.getElementById(
            "guardrailIndicator"
        );


    if (data.guardrail_allowed) {

        setText(
            "guardrailText",
            data.guardrail_reason ||
            "Request passed the input guardrail."
        );

        badge.textContent =
            "✓ Guardrail passed";

        badge.className =
            "guardrail-badge success";

        indicator.textContent =
            "✓";

        indicator.className =
            "workflow-indicator success";

    } else {

        setText(
            "guardrailText",
            data.guardrail_reason ||
            "Request blocked."
        );

        badge.textContent =
            "✕ Guardrail blocked";

        badge.className =
            "guardrail-badge error";

        indicator.textContent =
            "✕";

        indicator.className =
            "workflow-indicator error";
    }


    // -------------------------
    // Supervisor
    // -------------------------

    setText(
        "supervisorText",
        "Supervisor selected the required specialist agents."
    );


    setText(
        "supervisorReasoning",
        data.supervisor_reasoning ||
        "No supervisor reasoning available."
    );


    const supervisorIndicator =
        document.getElementById(
            "supervisorIndicator"
        );

    supervisorIndicator.textContent =
        "✓";

    supervisorIndicator.className =
        "workflow-indicator success";


    // -------------------------
    // Agent Chips
    // -------------------------

    const agentContainer =
        document.getElementById(
            "agentChips"
        );

    agentContainer.innerHTML = "";


    const agents =
        data.selected_agents || [];


    if (agents.length === 0) {

        agentContainer.textContent =
            "No specialist agents selected.";

        return;
    }


    agents.forEach(agent => {

        const chip =
            document.createElement(
                "span"
            );

        chip.className =
            "agent-chip";

        chip.textContent =
            agent;

        agentContainer.appendChild(
            chip
        );

    });
}


// =========================================================
// RESULTS DISPLAY
// =========================================================

function updateResults(data) {

    show("resultSection");


    setText(
        "threadInfo",
        "Thread ID: " +
        (data.thread_id || "-")
    );


    // Render Markdown instead of displaying
    // raw **bold**, ## headings and | tables.

    const flightResults =
        document.getElementById(
            "flightResults"
        );

    if (flightResults) {

        flightResults.innerHTML =
            renderMarkdown(
                data.flight_results
            );
    }


    const hotelResults =
        document.getElementById(
            "hotelResults"
        );

    if (hotelResults) {

        hotelResults.innerHTML =
            renderMarkdown(
                data.hotel_results
            );
    }


    const weatherResults =
        document.getElementById(
            "weatherResults"
        );

    if (weatherResults) {

        weatherResults.innerHTML =
            renderMarkdown(
                data.weather_results
            );
    }


    const budgetResults =
        document.getElementById(
            "budgetResults"
        );

    if (budgetResults) {

        budgetResults.innerHTML =
            renderMarkdown(
                data.budget_results ||
                data.budget
            );
    }


    const itineraryResults =
        document.getElementById(
            "itineraryResults"
        );

    if (itineraryResults) {

        itineraryResults.innerHTML =
            renderMarkdown(
                data.itinerary
            );
    }
}


// =========================================================
// HITL
// =========================================================

function showApproval(data) {

    if (!data.requires_approval) {

        hide("approvalSection");

        return;
    }


    show("approvalSection");


    setText(
        "approvalRequest",
        data.approval_request ||
        "Review the draft itinerary."
    );


    document.getElementById(
        "approvalFeedback"
    ).value = "";


    document.getElementById(
        "approveBtn"
    ).disabled = false;


    document.getElementById(
        "reviseBtn"
    ).disabled = false;
}


// =========================================================
// FINAL RESPONSE
// =========================================================

function showFinal(data) {

    if (!data.answer) {
        return;
    }


    show("finalSection");


    const container =
        document.getElementById(
            "finalResponse"
        );


    if (
        typeof marked !== "undefined"
    ) {

        container.innerHTML =
            marked.parse(
                data.answer
            );

    } else {

        container.textContent =
            data.answer;
    }


    document
        .getElementById(
            "finalSection"
        )
        .scrollIntoView({
            behavior: "smooth"
        });
}


// =========================================================
// ERROR
// =========================================================

function showError(message) {

    const box =
        document.getElementById(
            "errorBox"
        );

    box.textContent =
        message;

    box.classList.remove(
        "hidden"
    );
}


function clearError() {

    const box =
        document.getElementById(
            "errorBox"
        );

    box.textContent = "";

    box.classList.add(
        "hidden"
    );
}


// =========================================================
// SEND TRAVEL REQUEST
// =========================================================

async function sendMessage() {

    const input =
        document.getElementById(
            "userInput"
        );

    const button =
        document.getElementById(
            "sendBtn"
        );

    const buttonText =
        document.getElementById(
            "btnText"
        );

    const loader =
        document.getElementById(
            "btnLoader"
        );


    const message =
        input.value.trim();


    if (!message) {

        input.focus();

        return;
    }


    clearError();


    // Reset old results

    hide("workflowSection");
    hide("resultSection");
    hide("approvalSection");
    hide("finalSection");


    // Loading state

    button.disabled = true;

    buttonText.textContent =
        "Planning...";

    loader.classList.remove(
        "hidden"
    );


    try {

        const response =
            await fetch(
                "/api/travel",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({

                        message:
                            message,

                        thread_id:
                            currentThreadId
                    })
                }
            );


        const data =
            await response.json();


        if (
            !response.ok ||
            !data.success
        ) {

            throw new Error(
                data.error ||
                "Travel planning failed."
            );
        }


        // Save thread

        currentThreadId =
            data.thread_id;


        // Guardrail blocked

        if (
            data.guardrail_allowed === false
        ) {

            updateWorkflow(data);

            showError(
                data.guardrail_reason ||
                "Request blocked by guardrail."
            );

            return;
        }


        // Show workflow

        updateWorkflow(data);


        // Show draft results

        updateResults(data);


        // Show HITL if required

        if (
            data.requires_approval
        ) {

            showApproval(data);

        } else {

            showFinal(data);
        }

    }
    catch (error) {

        console.error(
            "Travel planning error:",
            error
        );

        showError(
            error.message ||
            "Something went wrong."
        );

    }
    finally {

        button.disabled = false;

        buttonText.textContent =
            "Generate Draft";

        loader.classList.add(
            "hidden"
        );
    }
}


// =========================================================
// HUMAN REVIEW
// =========================================================

async function submitApproval(
    approved
) {

    if (!currentThreadId) {

        showError(
            "No active travel planning thread."
        );

        return;
    }


    const feedbackInput =
        document.getElementById(
            "approvalFeedback"
        );


    const feedback =
        feedbackInput.value.trim();


    // Feedback is required for revision

    if (
        !approved &&
        !feedback
    ) {

        feedbackInput.focus();

        showError(
            "Please describe what you want changed."
        );

        return;
    }


    clearError();


    const approveButton =
        document.getElementById(
            "approveBtn"
        );

    const reviseButton =
        document.getElementById(
            "reviseBtn"
        );


    approveButton.disabled = true;

    reviseButton.disabled = true;


    try {

        const response =
            await fetch(
                "/api/travel/review",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({

                        thread_id:
                            currentThreadId,

                        approved:
                            approved,

                        feedback:
                            feedback
                    })
                }
            );


        const data =
            await response.json();


        if (
            !response.ok ||
            !data.success
        ) {

            throw new Error(
                data.error ||
                "Review request failed."
            );
        }


        currentThreadId =
            data.thread_id ||
            currentThreadId;


        // =====================================
        // APPROVED
        // =====================================
        //
        // Once approved, the draft/research
        // stage is finished.
        //
        // Therefore hide:
        //   - Workflow
        //   - Flight/Hotel/Weather/Budget
        //   - Draft itinerary
        //   - HITL review
        //
        // Show ONLY the final plan.
        // =====================================

        if (approved) {

            hide("workflowSection");

            hide("resultSection");

            hide("approvalSection");

            clearError();

            showFinal(data);

            return;
        }


        // =====================================
        // REVISION REQUESTED
        // =====================================
        //
        // Keep the draft workflow visible because
        // the supervisor has to process the feedback
        // and create another draft.
        // =====================================

        updateWorkflow(data);

        updateResults(data);


        if (
            data.requires_approval
        ) {

            showApproval(data);

        } else {

            showFinal(data);
        }

    }
    catch (error) {

        console.error(
            "Review error:",
            error
        );

        showError(
            error.message ||
            "Unable to process review."
        );


        approveButton.disabled =
            false;

        reviseButton.disabled =
            false;
    }
}


// =========================================================
// COPY RESULTS
// =========================================================

async function copyResult() {

    const result =
        document.getElementById(
            "resultSection"
        );


    try {

        await navigator.clipboard.writeText(
            result.innerText
        );


        const button =
            document.querySelector(
                ".copy-button"
            );


        button.textContent =
            "✓ Copied";


        setTimeout(() => {

            button.textContent =
                "📋 Copy Results";

        }, 2000);

    }
    catch (error) {

        console.error(
            "Copy failed:",
            error
        );
    }
}


// =========================================================
// CTRL / CMD + ENTER
// =========================================================

document
    .getElementById("userInput")
    .addEventListener(
        "keydown",
        function(event) {

            if (
                (event.ctrlKey ||
                 event.metaKey) &&
                event.key === "Enter"
            ) {

                sendMessage();
            }

        }
    );