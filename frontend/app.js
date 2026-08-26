document.addEventListener('DOMContentLoaded', () => {
    // Initialize Lucide icons
    if (window.lucide) {
        lucide.createIcons();
    }

    // Navigation Logic
    const navItems = document.querySelectorAll('.nav-item');
    const views = document.querySelectorAll('.view');

    navItems.forEach(item => {
        item.addEventListener('click', async () => {
            // Remove active class from all nav items
            navItems.forEach(nav => nav.classList.remove('active'));
            // Add active class to clicked item
            item.classList.add('active');

            // Hide all views
            views.forEach(view => view.classList.remove('active'));

            // Show the corresponding view
            const viewId = `view-${item.dataset.view}`;
            document.getElementById(viewId).classList.add('active');

            const isChatView = item.dataset.view === 'chat';
            toggleConversationHistory(isChatView);
            if (isChatView) {
                await loadConversationHistory();
            }

            // Re-fetch balances/transactions whenever the dashboard is opened,
            // so money received while the user was on another tab shows up
            // without needing a full page reload.
            if (item.dataset.view === 'dashboard') {
                refreshDashboard();
            }
            if (item.dataset.view === 'transactions') {
                loadAllTransactions();
            }
        });
    });

    document.getElementById('view-all-transactions-btn')?.addEventListener('click', () => {
        document.querySelector('.nav-item[data-view="transactions"]')?.click();
    });

    // Chat Logic
    const chatInput = document.getElementById('chat-input');

    // Add event listener for Enter key in chat input
    if (chatInput) {
        chatInput.addEventListener('keypress', function (e) {
            if (e.key === 'Enter') {
                sendMessage();
            }
        });
    }

    const newConversationBtn = document.getElementById('new-conversation-btn');
    if (newConversationBtn) {
        newConversationBtn.addEventListener('click', startNewConversation);
    }

    wireStepUpModal();
    wireAdminDocSignModal();
    wireStatementModal();
    wireChatAttach();
    wireDocumentAttach();
    wireChatMic();
    initDashboard();

    window.addEventListener('languagechange', () => {
        const messages = document.getElementById('chat-messages');
        const hasOnlyWelcome = messages?.querySelectorAll('.message').length === 1;
        if (hasOnlyWelcome) {
            const welcome = messages.querySelector('.message.ai .bubble');
            if (welcome) welcome.textContent = chatWelcomeText();
        }
        if (!document.getElementById('view-chat')?.classList.contains('hidden')) {
            void loadConversationHistory();
        }
        if (document.getElementById('view-cards')?.classList.contains('active')) {
            renderCardsList(loadedCards);
        }
        const countryInput = document.getElementById('card-order-country');
        if (countryInput?.dataset.defaultCountry === 'true' && countryInput.value === countryInput.dataset.currentDefault) {
            countryInput.value = t('card_modal.default_country', 'Romania');
            countryInput.dataset.currentDefault = countryInput.value;
        }
        document.querySelectorAll('#new-card-account option:disabled, #card-order-account option:disabled').forEach((option) => {
            option.textContent = t('card_modal.create_account_first', 'Create an account first');
        });
        if (document.getElementById('view-dashboard')?.classList.contains('active')) {
            renderSavingsAccountsList();
            void loadTransactions();
            void loadSpendingByCategory();
            void loadScheduledTransfers();
        }
        if (document.getElementById('view-analytics')?.classList.contains('active')) {
            renderSavingsAccountsList();
            void loadSpendingByCategory();
            void loadScheduledTransfers();
            void loadAccountProducts();
        }
        if (document.getElementById('view-transactions')?.classList.contains('active')) {
            void loadAllTransactions();
        }
        if (document.getElementById('view-payments')?.classList.contains('active')) {
            void loadBeneficiaries();
            void loadPayments();
        }
        if (document.getElementById('view-face-login')?.classList.contains('active') && faceStatusEnrolled !== null) {
            renderFaceStatus(faceStatusEnrolled);
        }
        window.refreshTranslations?.();
    });
});

/** Lets the user attach a photo/PDF (e.g. "extras de cont") to the chat to
 * supply an IBAN, instead of typing it - reuses the same /iban-ocr/extract
 * endpoint as the Payments form's scan button (see wirePaymentsForm). On a
 * good read, sends the IBAN as the next chat message so the assistant picks
 * it up in context like any other user-provided IBAN; on a bad read, tells
 * the user to type it manually instead of guessing. */
function wireChatAttach() {
    const attachBtn = document.getElementById('chat-attach-btn');
    const attachInput = document.getElementById('chat-attach-input');
    const statusEl = document.getElementById('chat-attach-status');
    if (!attachBtn || !attachInput) return;

    attachBtn.addEventListener('click', () => attachInput.click());

    attachInput.addEventListener('change', async () => {
        const file = attachInput.files[0];
        if (!file) return;

        statusEl.hidden = false;
        statusEl.className = 'field-hint';
        statusEl.textContent = t('common.reading_file', 'Se citește fișierul...');

        const formData = new FormData();
        formData.append('file', file);
        try {
            const res = await fetch(`${API_BASE_URL}/iban-ocr/extract`, {
                method: 'POST',
                credentials: 'include',
                body: formData,
            });
            if (!res.ok) {
                const body = await res.json().catch(() => ({}));
                throw new Error(body?.error?.message || `Request failed (${res.status})`);
            }
            const result = await res.json();

            if (result.iban && !result.low_confidence) {
                statusEl.hidden = true;
                const chatInput = document.getElementById('chat-input');
                chatInput.value = t('chat.iban_read_from_file', 'IBAN citit din fișierul atașat: {iban}', { iban: result.iban });
                await sendMessage();
            } else {
                statusEl.className = 'field-hint ocr-warning';
                statusEl.textContent = t('chat.iban_not_found_in_file', 'Nu am găsit un IBAN clar în fișier - te rog scrie-l manual.');
            }
        } catch (err) {
            statusEl.hidden = false;
            statusEl.className = 'field-hint ocr-warning';
            statusEl.textContent = err.message;
        } finally {
            attachInput.value = '';
        }
    });
}

/** Lets the user attach a PDF to the chat so DocumentAgent can answer
 * questions about it - separate from wireChatAttach above, which reads an
 * IBAN out of a scanned statement and is unrelated to this feature. Posts to
 * POST /documents/upload; the returned document_id is remembered in
 * currentDocumentId and sent along with every chat message until detached
 * or the conversation changes (see clearActiveDocument, sendMessage). */
function wireDocumentAttach() {
    const attachBtn = document.getElementById('document-attach-btn');
    const attachInput = document.getElementById('document-attach-input');
    const statusEl = document.getElementById('document-attach-status');
    if (!attachBtn || !attachInput) return;

    const MAX_DOCUMENT_SIZE_BYTES = 5 * 1024 * 1024;

    attachBtn.addEventListener('click', () => attachInput.click());

    attachInput.addEventListener('change', async () => {
        const file = attachInput.files[0];
        if (!file) return;

        if (file.size > MAX_DOCUMENT_SIZE_BYTES) {
            statusEl.hidden = false;
            statusEl.className = 'field-hint ocr-warning';
            statusEl.textContent = t('chat.document_too_large', 'Fișierul depășește 5 MB.');
            attachInput.value = '';
            return;
        }

        statusEl.hidden = false;
        statusEl.className = 'field-hint';
        statusEl.textContent = t('chat.document_uploading', 'Se încarcă documentul...');

        const formData = new FormData();
        formData.append('file', file);
        if (currentConversationId) {
            formData.append('conversation_id', currentConversationId);
        }

        try {
            const res = await fetch(`${API_BASE_URL}/documents/upload`, {
                method: 'POST',
                credentials: 'include',
                body: formData,
            });
            if (!res.ok) {
                const body = await res.json().catch(() => ({}));
                throw new Error(body?.error?.message || `Request failed (${res.status})`);
            }
            const result = await res.json();

            statusEl.hidden = true;
            setCurrentConversationId(result.conversation_id);
            renderDocumentChip(result.document);
            showToast(t('chat.document_attached', 'Document atașat. Poți pune întrebări despre el.'));
        } catch (err) {
            statusEl.hidden = false;
            statusEl.className = 'field-hint ocr-warning';
            statusEl.textContent = err.message;
        } finally {
            attachInput.value = '';
        }
    });
}

/** Maps the app's short language code (language.js sets document.documentElement.lang
 * to one of these) to the BCP-47 locale the SpeechRecognition API expects. */
const SPEECH_RECOGNITION_LOCALES = {
    ro: 'ro-RO', en: 'en-US', uk: 'uk-UA', hu: 'hu-HU', tr: 'tr-TR',
    it: 'it-IT', es: 'es-ES', fr: 'fr-FR', de: 'de-DE',
};

/** Lets the user dictate into the chat input using the browser's native
 * SpeechRecognition API - no server round trip, no external service. The
 * mic button toggles listening on/off; the recognized text replaces
 * whatever was already in the box on start, and updates live (including
 * interim results) until the user stops it or the browser detects silence.
 * Recognition language follows the app's active language (see language.js),
 * so switching languages changes what the mic expects to hear. Hides the
 * button entirely on browsers that don't implement the API (e.g. Firefox). */
function wireChatMic() {
    const micBtn = document.getElementById('chat-mic-btn');
    const chatInput = document.getElementById('chat-input');
    if (!micBtn || !chatInput) return;

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        micBtn.hidden = true;
        return;
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;

    let listening = false;
    let baseText = '';

    const stopListening = () => {
        listening = false;
        micBtn.classList.remove('listening');
        micBtn.setAttribute('aria-pressed', 'false');
    };

    recognition.addEventListener('start', () => {
        listening = true;
        micBtn.classList.add('listening');
        micBtn.setAttribute('aria-pressed', 'true');
        baseText = chatInput.value.trim() ? `${chatInput.value.trim()} ` : '';
    });

    recognition.addEventListener('result', (event) => {
        let transcript = '';
        for (let i = 0; i < event.results.length; i++) {
            transcript += event.results[i][0].transcript;
        }
        chatInput.value = baseText + transcript;
    });

    recognition.addEventListener('error', (event) => {
        stopListening();
        if (event.error === 'no-speech' || event.error === 'aborted') return;
        showToast(t('chat.voice_input_error', 'Voice input failed. Please try again or type your message.'));
    });

    recognition.addEventListener('end', stopListening);

    micBtn.addEventListener('click', () => {
        if (listening) {
            recognition.stop();
            return;
        }
        recognition.lang = SPEECH_RECOGNITION_LOCALES[document.documentElement.lang] || 'en-US';
        try {
            recognition.start();
        } catch {
            /* start() throws if recognition is already running; nothing to do. */
        }
    });
}

let currentDocumentId = null;

/** Shows the small "N pag. · nume.pdf · ✕" pill above the chat input and
 * remembers the document so sendMessage can include it on the next turn. */
function renderDocumentChip(document_) {
    currentDocumentId = document_.id;

    const chip = document.getElementById('document-chip');
    if (!chip) return;
    chip.innerHTML = '';

    const label = document.createElement('span');
    label.textContent = `${document_.page_count} pag. · ${document_.filename}`;
    chip.appendChild(label);

    const signBtn = document.createElement('button');
    signBtn.type = 'button';
    signBtn.className = 'document-chip-sign';
    signBtn.textContent = 'Semnează electronic';
    signBtn.addEventListener('click', () => handleSignDocument(document_, signBtn));
    chip.appendChild(signBtn);

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'document-chip-close';
    closeBtn.setAttribute('aria-label', t('chat.detach_document', 'Detașează documentul'));
    closeBtn.textContent = '✕';
    closeBtn.addEventListener('click', () => {
        clearActiveDocument();
        showToast(t('chat.document_detached', 'Document detașat.'));
    });
    chip.appendChild(closeBtn);

    chip.hidden = false;
}

/** Detaches the active document from the chat, without touching the stored
 * conversation - the document itself stays in the conversation's history in
 * the database, this only clears what the client sends on future turns. */
function clearActiveDocument() {
    currentDocumentId = null;
    const chip = document.getElementById('document-chip');
    if (chip) {
        chip.hidden = true;
        chip.innerHTML = '';
    }
    const signContainer = document.getElementById('document-sign-card-container');
    if (signContainer) signContainer.innerHTML = '';
}

/** "Semnează electronic" on the attached document's chip. Deliberately a
 * direct REST call (POST /esign/documents/{id}/sign-requests), not a chat
 * message - the AI's DocumentAgent has no write tools at all (see
 * backend app/ai/tools/document_tools.py), so a real sign action has to
 * come from an explicit user click, never from asking the chatbot to do it.
 *
 * The call only creates a PENDING proposal - it renders through the exact
 * same confirm/reject card and Face ID/password step-up modal as any other
 * AI-proposed action (see renderProposalCard/openStepUpModal above), because
 * the backend returns the same ProposalRead shape. */
async function handleSignDocument(document_, triggerBtn) {
    const container = document.getElementById('document-sign-card-container');
    if (!container) return;

    triggerBtn.disabled = true;
    try {
        const proposal = await apiFetch(`/esign/documents/${document_.id}/sign-requests`, {
            method: 'POST',
            body: JSON.stringify({
                intent: `Am citit și sunt de acord cu conținutul documentului „${document_.filename}”.`,
            }),
        });
        container.innerHTML = '';
        renderProposalCard(proposal, container);
        triggerBtn.hidden = true;
    } catch (err) {
        showToast(err.message || 'Eroare la crearea cererii de semnătură.');
        triggerBtn.disabled = false;
    }
}

/* -------------------------------------------------------------------------
 * AI chat - talks to POST /chat (see backend app/modules/chat/router.py).
 * History now lives server-side (conversations/messages tables) - the client
 * only holds the id of the conversation in progress, so it survives a reload.
 * ------------------------------------------------------------------------- */

let currentConversationId = null;
let conversationHistory = [];

const CHAT_ERRORS = {
    unavailable: ['chat.errors.unavailable', 'Asistentul AI nu este disponibil momentan. Încearcă din nou.'],
    invalid: ['chat.errors.invalid', 'Mesajul nu poate fi trimis. Verifică ce ai scris.'],
    generic: ['errors.generic', 'A apărut o problemă. Încearcă din nou.'],
};

function chatWelcomeText() {
    return t('chat.welcome', 'Salut! Sunt asistentul tău bancar. Pot să îți verific soldul conturilor și să răspund la întrebări despre bancă. Cu ce te pot ajuta?');
}

// Romanian labels for the routing tag - keys match RoutingDecision.agent_name
// (see backend app/ai/orchestrator.py). Anything not listed falls back to a
// capitalized version of the raw agent name.
const AGENT_TAG_LABELS = {
    banking: 'Bancar',
    insights: 'Analiză',
    planning: 'Planificare',
    documents: 'Documente',
    docs: 'Ajutor',
};

function agentTagLabel(agentName) {
    if (AGENT_TAG_LABELS[agentName]) return AGENT_TAG_LABELS[agentName];
    return agentName.charAt(0).toUpperCase() + agentName.slice(1);
}

/** One "Label: value" row in the agent tag's tooltip. Built with
 * createElement/textContent, not innerHTML, so `value` (which may echo
 * server-controlled text like routing.reason) is never parsed as markup. */
function agentTagTooltipRow(label, value) {
    const row = document.createElement('div');
    const strong = document.createElement('strong');
    strong.textContent = `${label}:`;
    row.appendChild(strong);
    row.appendChild(document.createTextNode(` ${value}`));
    return row;
}

/** Small metadata pill naming which agent produced a reply. LEGACY, kept as
 * the fallback for anything with no chain semantics: rows stored before Step
 * 15, and any caller still passing a single RoutingDecision. New code goes
 * through renderAgentChain, which renders a one-element chain identically. */
function renderAgentTag(routing, container) {
    renderAgentChain([routing], container);
}

/** The agent chain that produced a reply (see ChatResponse.routing_chain).
 * One hop renders "→ Bancar"; a mid-turn handoff renders
 * "→ Analiză → Bancar". Appended to `container` before the bubble is added,
 * so it renders above it, not inside it. Hover/focus reveals a custom tooltip
 * (see .agent-tag-tooltip) listing every hop, instead of the OS-styled `title`
 * attribute tooltip.
 *
 * XSS: built with createElement/textContent throughout, never innerHTML - the
 * tooltip echoes server-side text (routing.reason, matched_rule) and must
 * never be parsed as markup. */
function renderAgentChain(routingChain, container) {
    const chain = (routingChain || []).filter(Boolean);
    if (!chain.length) return;

    const tag = document.createElement('div');
    tag.className = chain.length > 1 ? 'agent-tag agent-tag-chain' : 'agent-tag';
    tag.tabIndex = 0;
    tag.appendChild(document.createTextNode(
        chain.map(hop => `→ ${agentTagLabel(hop.agent_name)}`).join(' ')
    ));

    const tooltip = document.createElement('div');
    tooltip.className = 'agent-tag-tooltip';
    chain.forEach((hop, index) => {
        // A multi-hop chain needs its rows grouped per agent, otherwise three
        // "Motiv:" lines in a row say nothing about which agent each belongs to.
        if (chain.length > 1) {
            const heading = document.createElement('div');
            heading.className = 'agent-tag-tooltip-hop';
            heading.textContent = `${index + 1}. ${agentTagLabel(hop.agent_name)}`;
            tooltip.appendChild(heading);
        }
        tooltip.appendChild(agentTagTooltipRow('Agent', hop.agent_name));
        tooltip.appendChild(agentTagTooltipRow('Motiv', hop.reason));
        tooltip.appendChild(agentTagTooltipRow('Regulă', hop.matched_rule ?? '—'));
        // Keyword rules always match at confidence=1.0 - showing it there is
        // just noise. Only LLM-fallback routing (confidence < 1.0) is worth
        // surfacing. A handoff hop is always 1.0, so it never shows either.
        if (hop.confidence !== undefined && hop.confidence < 1.0) {
            const pct = Math.round(hop.confidence * 100);
            tooltip.appendChild(agentTagTooltipRow('Încredere', `${pct}%`));
        }
    });
    tag.appendChild(tooltip);

    container.appendChild(tag);
}

/** Rebuild each turn's agent chain from stored history rows.
 *
 * Live replies carry `routing_chain` on the response; replayed ones don't -
 * the server stores one row per hop, each with its own routing_metadata, and
 * the chain is implied by ORDER (see _persist_turn in chat/router.py). This
 * walks the assistant rows in order and groups a row onto the run in progress
 * when its `handoff_from` names the previous row's agent - which is exactly
 * what a handoff wrote there.
 *
 * Returns a Map keyed by the message object, holding the chain to draw on it.
 * Only the LAST row of each run gets an entry: it is the hop that produced the
 * visible reply, and the earlier hops of a chain usually have empty content
 * (the source agent handed off before saying anything) and draw no bubble at
 * all. Rows predating Step 15 have no handoff_from anywhere, so every one of
 * them is its own single-element chain - the old behaviour, unchanged. */
function agentChainsByMessage(messages) {
    const chains = new Map();
    let run = [];

    const flush = () => {
        if (!run.length) return;
        chains.set(run[run.length - 1].message, run.map(entry => entry.routing));
        run = [];
    };

    messages.forEach(message => {
        // A user turn is the only thing that definitely ends a chain - one
        // turn is one user message, however many agents answered it.
        if (message.role === 'user') {
            flush();
            return;
        }
        const routing = message.role === 'assistant' ? message.routing : null;
        // Trace rows (tool calls and their results) carry no decision. They sit
        // BETWEEN a chain's hops, so skipping them is not the same as ending
        // the chain - treating them as a break would split every two-hop turn
        // back into two unrelated single-agent tags.
        if (!routing) return;
        const previous = run.length ? run[run.length - 1].routing : null;
        if (previous && routing.handoff_from !== previous.agent_name) flush();
        run.push({ message, routing });
    });
    flush();

    return chains;
}

/** Builds a chat bubble matching the existing markup and appends it.
 * `options.routingChain`, when present on an 'ai' message, renders the agent
 * chain (see renderAgentChain) above the bubble. `options.routing` is the
 * single-decision legacy form of the same thing. */
function appendChatBubble(role, text, options = {}) {
    const chatMessages = document.getElementById('chat-messages');

    const wrapper = document.createElement('div');
    wrapper.className = `message ${role}`;

    if (role === 'ai') {
        const avatar = document.createElement('div');
        avatar.className = 'avatar';
        avatar.innerHTML = '<i data-lucide="sparkles"></i>';
        wrapper.appendChild(avatar);
    }

    // Column wrapper so the agent tag stacks above the bubble instead of
    // sitting beside it in .message's horizontal flex row.
    const content = document.createElement('div');
    content.className = 'message-content';

    if (role === 'ai' && options.routingChain) {
        renderAgentChain(options.routingChain, content);
    } else if (role === 'ai' && options.routing) {
        renderAgentTag(options.routing, content);
    }

    const bubble = document.createElement('div');
    bubble.className = options.bubbleClass ? `bubble ${options.bubbleClass}` : 'bubble';
    if (options.html) {
        bubble.innerHTML = options.html;
    } else {
        // textContent, not innerHTML: the reply is model-authored text and must
        // never be interpreted as markup.
        bubble.textContent = text;
    }
    content.appendChild(bubble);
    wrapper.appendChild(content);

    chatMessages.appendChild(wrapper);
    if (window.lucide) lucide.createIcons();
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return wrapper;
}

function chatErrorMessage(err) {
    // No status at all means the request never reached the API (backend down,
    // DNS, CORS) - to the user that is the same thing as "AI unavailable".
    if (!err.status || err.status === 502 || err.status === 503) {
        return t(...CHAT_ERRORS.unavailable);
    }
    if (err.status === 422) return t(...CHAT_ERRORS.invalid);
    return t(...CHAT_ERRORS.generic);
}

// Function to send a message in the AI Chat view
async function sendMessage() {
    const input = document.getElementById('chat-input');
    const sendButton = document.querySelector('.btn-send');
    const message = input.value.trim();

    // Silent no-op: an accidental Enter on an empty box shouldn't do anything.
    if (!message) return;

    appendChatBubble('user', message);
    input.value = '';

    // A real model call takes a few seconds; the label makes that wait read as
    // deliberate rather than as the UI having stalled.
    const typingBubble = appendChatBubble('ai', '', {
        bubbleClass: 'typing',
        html:
            `<div class="typing-label">${escapeHTML(t('chat.typing', 'Asistentul gândește...'))}</div>` +
            '<div class="typing-dots">' +
            '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>' +
            '</div>',
    });
    if (sendButton) sendButton.disabled = true;

    try {
        // apiFetch already prefixes /api/v1 and sends the session cookie.
        const response = await apiFetch('/chat', {
            method: 'POST',
            body: JSON.stringify({
                message,
                conversation_id: currentConversationId,
                document_id: currentDocumentId,
            }),
        });

        typingBubble.remove();
        const aiBubble = appendChatBubble('ai', response.reply, {
            // routing_chain since Step 15: several agents can answer one turn.
            // `routing` is the server's backward-compatible last-hop duplicate,
            // used only if an older backend omits the chain entirely.
            routingChain: response.routing_chain?.length ? response.routing_chain : undefined,
            routing: response.routing || undefined,
        });
        if (response.proposal) {
            supersedeLivePendingProposalCards();
            livePendingProposalCards.push(renderProposalCard(response.proposal, aiBubble));
        }
        setCurrentConversationId(response.conversation_id);
        void loadConversationHistory();
        // The agent can freeze/unfreeze a card, change a limit, or touch
        // beneficiaries/scheduled transfers directly - refresh those views so
        // an already-open panel doesn't show stale state until a manual reload.
        void loadCards();
        void loadAccounts();
        void loadBeneficiaries();
        void loadScheduledTransfers();
    } catch (err) {
        typingBubble.remove();

        if (err.status === 401) {
            // Session expired mid-conversation - same redirect the rest of the
            // app uses (see requireSession in api.js).
            window.location.href = 'login.html';
            return;
        }

        appendChatBubble('ai', chatErrorMessage(err), { bubbleClass: 'error' });
    } finally {
        if (sendButton) sendButton.disabled = false;
    }
}

/** Clears the chat panel back to the empty-state welcome bubble and detaches
 * from the current conversation - the next message starts a new one. */
function startNewConversation() {
    setCurrentConversationId(null);
    clearActiveDocument();
    livePendingProposalCards = [];
    const chatMessages = document.getElementById('chat-messages');
    chatMessages.innerHTML = '';
    appendChatBubble('ai', chatWelcomeText());
    renderConversationHistory();
}

function setCurrentConversationId(conversationId) {
    currentConversationId = conversationId || null;
    if (currentConversationId) {
        sessionStorage.setItem('bank.currentConversationId', currentConversationId);
    } else {
        sessionStorage.removeItem('bank.currentConversationId');
    }
}

function toggleConversationHistory(isVisible) {
    const history = document.getElementById('conversation-history');
    if (history) history.hidden = !isVisible;
}

function truncateConversationPreview(value) {
    const normalized = String(value || '').replace(/\s+/g, ' ').trim();
    return normalized.length > 58 ? `${normalized.slice(0, 58).trim()}...` : normalized;
}

function formatRelativeConversationTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';

    const elapsedMinutes = Math.floor((Date.now() - date.getTime()) / 60000);
    const locale = document.documentElement.lang || 'ro';
    const relativeTime = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
    if (elapsedMinutes < 1) return relativeTime.format(0, 'second');
    if (elapsedMinutes < 60) return relativeTime.format(-elapsedMinutes, 'minute');
    if (elapsedMinutes < 24 * 60) return relativeTime.format(-Math.floor(elapsedMinutes / 60), 'hour');

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const conversationDay = new Date(date);
    conversationDay.setHours(0, 0, 0, 0);
    const dayDifference = Math.floor((today - conversationDay) / 86400000);
    if (dayDifference < 7) return relativeTime.format(-dayDifference, 'day');
    return date.toLocaleDateString(locale, { day: 'numeric', month: 'short' });
}

function showConversationHistoryError(message = '') {
    const error = document.getElementById('conversation-history-error');
    if (!error) return;
    error.textContent = message;
    error.hidden = !message;
}

async function loadConversationHistory() {
    const list = document.getElementById('conversation-history-list');
    if (!list) return;

    showConversationHistoryError();
    list.innerHTML = `<p class="conversation-history-empty">${escapeHTML(t('common.loading', 'Se încarcă...'))}</p>`;

    try {
        const conversations = await apiFetch('/chat/conversations');
        conversationHistory = await Promise.all(conversations.map(async conversation => {
            let preview = conversation.title;
            if (!preview) {
                try {
                    const messages = await apiFetch(`/chat/conversations/${conversation.id}/messages`);
                    const firstMessage = messages.find(message =>
                        (message.role === 'user' || message.role === 'assistant') && message.content
                    );
                    preview = firstMessage?.content;
                } catch {
                    preview = null;
                }
            }
            return { ...conversation, preview: preview || t('dashboard.Conversație nouă', 'Conversație nouă') };
        }));

        renderConversationHistory();

        const rememberedId = sessionStorage.getItem('bank.currentConversationId');
        if (!currentConversationId && rememberedId && conversationHistory.some(item => item.id === rememberedId)) {
            await openConversation(rememberedId);
        }
    } catch (err) {
        list.innerHTML = '';
        showConversationHistoryError(t('chat.history.load_error', 'Istoricul conversațiilor nu a putut fi încărcat. Încearcă din nou.'));
    }
}

function renderConversationHistory() {
    const list = document.getElementById('conversation-history-list');
    if (!list) return;
    list.innerHTML = '';

    if (!conversationHistory.length) {
        list.innerHTML = `<p class="conversation-history-empty">${escapeHTML(t('chat.history.empty', 'Nu ai conversații salvate.'))}</p>`;
        return;
    }

    conversationHistory.forEach(conversation => {
        const item = document.createElement('div');
        item.className = 'conversation-history-item';
        if (conversation.id === currentConversationId) item.classList.add('active');

        const selectButton = document.createElement('button');
        selectButton.type = 'button';
        selectButton.className = 'conversation-history-select';
        selectButton.addEventListener('click', () => openConversation(conversation.id));

        const preview = document.createElement('span');
        preview.className = 'conversation-history-preview';
        preview.textContent = truncateConversationPreview(conversation.preview);

        const timestamp = document.createElement('span');
        timestamp.className = 'conversation-history-time';
        timestamp.textContent = formatRelativeConversationTime(conversation.created_at);
        selectButton.append(preview, timestamp);

        const actions = document.createElement('div');
        actions.className = 'conversation-history-actions';

        const renameButton = document.createElement('button');
        renameButton.type = 'button';
        renameButton.className = 'conversation-history-action';
        renameButton.title = t('chat.history.rename_title', 'Redenumește conversația');
        renameButton.setAttribute('aria-label', t('chat.history.rename_title', 'Redenumește conversația'));
        renameButton.innerHTML = '<i data-lucide="pencil"></i>';
        renameButton.addEventListener('click', () => beginConversationRename(item, conversation));

        const deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'conversation-history-action';
        deleteButton.title = t('chat.history.delete_title', 'Șterge conversația');
        deleteButton.setAttribute('aria-label', t('chat.history.delete_title', 'Șterge conversația'));
        deleteButton.innerHTML = '<i data-lucide="trash-2"></i>';
        deleteButton.addEventListener('click', () => deleteConversation(conversation));

        actions.append(renameButton, deleteButton);
        item.append(selectButton, actions);
        list.appendChild(item);
    });

    if (window.lucide) lucide.createIcons();
}

async function openConversation(conversationId) {
    setCurrentConversationId(conversationId);
    clearActiveDocument();
    livePendingProposalCards = [];
    renderConversationHistory();
    showConversationHistoryError();

    try {
        const messages = await apiFetch(`/chat/conversations/${conversationId}/messages`);
        const chatMessages = document.getElementById('chat-messages');
        chatMessages.innerHTML = '';
        // Chains are reconstructed from ALL rows, before the empty-content
        // filter below: a hop that handed off has no text of its own, but it
        // is still the first half of the chain drawn on the reply that follows.
        const chains = agentChainsByMessage(messages);
        const dialogue = messages.filter(message =>
            (message.role === 'user' || message.role === 'assistant') && message.content
        );
        if (dialogue.length) {
            dialogue.forEach(message => appendChatBubble(
                message.role === 'user' ? 'user' : 'ai',
                message.content,
                {
                    routingChain: chains.get(message),
                    routing: message.routing || undefined,
                }
            ));
        } else {
            appendChatBubble('ai', chatWelcomeText());
        }
    } catch (err) {
        showConversationHistoryError(t('chat.history.open_error', 'Conversația nu a putut fi încărcată. Încearcă din nou.'));
    }
}

function beginConversationRename(item, conversation) {
    const selectButton = item.querySelector('.conversation-history-select');
    const actions = item.querySelector('.conversation-history-actions');
    if (!selectButton || !actions) return;

    item.classList.add('editing');
    // The input goes in as a SIBLING of selectButton, never a child of it -
    // selectButton is a real <button>, and nesting a focusable <input>
    // inside a <button> is invalid HTML (interactive content inside
    // interactive content). Browsers don't auto-correct that when the DOM
    // is built via createElement/appendChild (only HTML-parsed markup gets
    // that fix-up), so the live, invalid structure stuck around - every
    // Space keystroke in the input register as activating the enclosing
    // button, which called openConversation() and blew away edit mode.
    selectButton.hidden = true;
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'conversation-history-rename-input';
    input.value = conversation.title || conversation.preview;
    input.maxLength = 120;
    input.setAttribute('aria-label', t('chat.history.rename_input_label', 'Nume conversație'));
    input.addEventListener('click', event => event.stopPropagation());
    input.addEventListener('keydown', event => {
        event.stopPropagation();
        if (event.key === 'Enter') saveConversationRename(conversation, input.value);
        if (event.key === 'Escape') renderConversationHistory();
    });
    item.insertBefore(input, selectButton);

    actions.replaceChildren();
    const saveButton = document.createElement('button');
    saveButton.type = 'button';
    saveButton.className = 'conversation-history-action';
    saveButton.title = t('chat.history.save_name', 'Salvează numele');
    saveButton.setAttribute('aria-label', t('chat.history.save_name', 'Salvează numele'));
    saveButton.innerHTML = '<i data-lucide="check"></i>';
    saveButton.addEventListener('click', () => saveConversationRename(conversation, input.value));

    const cancelButton = document.createElement('button');
    cancelButton.type = 'button';
    cancelButton.className = 'conversation-history-action';
    cancelButton.title = t('chat.history.cancel_rename', 'Renunță');
    cancelButton.setAttribute('aria-label', t('chat.history.cancel_rename', 'Renunță'));
    cancelButton.innerHTML = '<i data-lucide="x"></i>';
    cancelButton.addEventListener('click', renderConversationHistory);
    actions.append(saveButton, cancelButton);
    input.focus();
    input.select();
    if (window.lucide) lucide.createIcons();
}

async function saveConversationRename(conversation, nextTitle) {
    const title = nextTitle.trim();
    if (!title) {
        showConversationHistoryError(t('chat.history.name_empty', 'Numele conversației nu poate fi gol.'));
        return;
    }

    try {
        await apiFetch(`/chat/conversations/${conversation.id}`, {
            method: 'PATCH',
            body: JSON.stringify({ title }),
        });
        conversation.title = title;
        conversation.preview = title;
        renderConversationHistory();
    } catch (err) {
        showConversationHistoryError(t('chat.history.rename_error', 'Conversația nu a putut fi redenumită. Încearcă din nou.'));
    }
}

async function deleteConversation(conversation) {
    const approved = window.confirm(t('chat.history.delete_confirm', 'Sigur vrei să ștergi conversația „{title}”?', { title: truncateConversationPreview(conversation.preview) }));
    if (!approved) return;

    try {
        await apiFetch(`/chat/conversations/${conversation.id}`, { method: 'DELETE' });
        conversationHistory = conversationHistory.filter(item => item.id !== conversation.id);
        if (currentConversationId === conversation.id) startNewConversation();
        renderConversationHistory();
    } catch (err) {
        showConversationHistoryError(t('chat.history.delete_error', 'Conversația nu a putut fi ștearsă. Încearcă din nou.'));
    }
}

// Security function to escape HTML
function escapeHTML(str) {
    return str.replace(/[&<>'"]/g,
        tag => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            "'": '&#39;',
            '"': '&quot;'
        }[tag] || tag)
    );
}

/* -------------------------------------------------------------------------
 * AI Human-in-the-Loop Actions (Step 11) - a propose_* tool (see backend
 * app/ai/tools/propose_tools.py) never executes anything itself; it only
 * creates a pending row in `proposals`. This renders that as a card with
 * Confirmă/Anulează, and drives the two endpoints
 * (POST /chat/proposals/{id}/confirm and .../reject) that turn a pending
 * proposal into a real, executed action - confirm only after step-up auth
 * (Face ID or password), verified server-side.
 * ------------------------------------------------------------------------- */

// Every still-live proposal card rendered THIS page load, in order. When a
// new one arrives, the backend has already rejected every other pending
// proposal in this conversation (see proposals_service.create_proposal) -
// this just reflects that in the UI instead of leaving a stale card with
// live Confirm/Reject buttons sitting in the chat ("de fapt, trimite 500
// RON" after a 50 RON proposal used to leave both cards clickable).
let livePendingProposalCards = [];

function supersedeLivePendingProposalCards() {
    livePendingProposalCards.forEach(card => {
        if (card.isConnected && !card.classList.contains('proposal-confirmed')
            && !card.classList.contains('proposal-rejected')) {
            markProposalCardResolved(card, 'rejected');
        }
    });
    livePendingProposalCards = [];
}

/** Simple toast for background feedback that doesn't belong in the chat
 * transcript itself (a proposal being confirmed/rejected). Auto-dismisses. */
function showToast(message) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3500);
}

/** Appends a confirm/reject card for an AI-proposed action inside the chat
 * bubble that carried it (see sendMessage's use of response.proposal). */
function renderProposalCard(proposal, container) {
    const card = document.createElement('div');
    card.className = 'human-in-the-loop-card';
    card.dataset.proposalId = proposal.id;

    const body = document.createElement('div');
    body.className = 'action-proposal';
    body.innerHTML = `<strong>${escapeHTML(t('chat.proposal.heading', 'Propunere de acțiune'))}</strong><p>${escapeHTML(proposal.summary)}</p>`;
    card.appendChild(body);

    const actions = document.createElement('div');
    actions.className = 'hitl-actions';

    const confirmBtn = document.createElement('button');
    confirmBtn.type = 'button';
    confirmBtn.className = 'btn btn-primary';
    confirmBtn.textContent = t('common.Confirmă', 'Confirmă');
    confirmBtn.addEventListener('click', () => openStepUpModal(proposal.id, card));

    const rejectBtn = document.createElement('button');
    rejectBtn.type = 'button';
    rejectBtn.className = 'btn btn-secondary';
    rejectBtn.textContent = t('common.Anulează', 'Anulează');
    rejectBtn.addEventListener('click', () => handleRejectProposal(proposal.id, card));

    actions.appendChild(confirmBtn);
    actions.appendChild(rejectBtn);
    card.appendChild(actions);

    container.appendChild(card);
    if (window.lucide) lucide.createIcons();
    return card;
}

/** Replaces a proposal card's buttons with a static status label - same
 * shape for both terminal states, only the class/icon/text differ. */
function markProposalCardResolved(card, state) {
    card.classList.add(state === 'confirmed' ? 'proposal-confirmed' : 'proposal-rejected');
    const actions = card.querySelector('.hitl-actions');
    if (!actions) return;
    const label = document.createElement('div');
    label.className = `proposal-status-label ${state}`;
    label.innerHTML = state === 'confirmed'
        ? `<i data-lucide="check-circle"></i> ${escapeHTML(t('chat.proposal.confirmed', 'Confirmată'))}`
        : `<i data-lucide="x-circle"></i> ${escapeHTML(t('chat.proposal.rejected', 'Anulată'))}`;
    actions.replaceWith(label);
    if (window.lucide) lucide.createIcons();
}

async function handleRejectProposal(proposalId, card) {
    const buttons = card.querySelectorAll('button');
    buttons.forEach(btn => { btn.disabled = true; });
    try {
        await apiFetch(`/chat/proposals/${proposalId}/reject`, { method: 'POST' });
        markProposalCardResolved(card, 'rejected');
        showToast(t('chat.proposal.reject_success', 'Propunerea a fost anulată.'));
    } catch (err) {
        buttons.forEach(btn => { btn.disabled = false; });
        showToast(t('chat.proposal.reject_error', 'Eroare la anulare.'));
    }
}

// Set by openStepUpModal, read by the modal's Face ID/password handlers -
// there is only ever one step-up confirmation in flight at a time (the
// modal is fully modal: nothing else on the page is reachable while open).
let stepUpProposalId = null;
let stepUpCard = null;

function openStepUpModal(proposalId, card) {
    stepUpProposalId = proposalId;
    stepUpCard = card;

    const modal = document.getElementById('step-up-auth-modal');
    const errorEl = document.getElementById('step-up-error');
    const passwordInput = document.getElementById('step-up-password-input');
    errorEl.hidden = true;
    passwordInput.value = '';
    modal.hidden = false;
}

function closeStepUpModal() {
    document.getElementById('step-up-auth-modal').hidden = true;
    stepUpProposalId = null;
    stepUpCard = null;
}

function showStepUpError(message) {
    const errorEl = document.getElementById('step-up-error');
    errorEl.textContent = message;
    errorEl.hidden = false;
}

async function confirmWithCredential(proposalId, authMethod, credential, card) {
    try {
        const proposal = await apiFetch(`/chat/proposals/${proposalId}/confirm`, {
            method: 'POST',
            body: JSON.stringify({ auth_method: authMethod, credential }),
        });
        closeStepUpModal();
        markProposalCardResolved(card, 'confirmed');
        showToast(t('chat.proposal.confirm_success', 'Acțiunea a fost confirmată și executată cu succes!'));
        return proposal;
    } catch (err) {
        if (err.status === 409) {
            // Already confirmed/rejected/expired elsewhere (e.g. a second
            // tab) - the card's own buttons are stale, so just reflect it.
            closeStepUpModal();
            markProposalCardResolved(card, err.code === 'proposal_expired' ? 'rejected' : 'confirmed');
            showToast(err.message);
            return null;
        }
        showStepUpError(err.message || t('chat.proposal.auth_failed', 'Autentificare eșuată.'));
        return null;
    }
}

function wireStepUpModal() {
    const modal = document.getElementById('step-up-auth-modal');
    if (!modal) return;

    document.getElementById('close-step-up-modal').addEventListener('click', closeStepUpModal);

    document.getElementById('step-up-face-btn').addEventListener('click', async () => {
        if (!stepUpProposalId) return;
        const proposalId = stepUpProposalId;
        const card = stepUpCard;

        // requestFaceConfirmationToken() (reused as-is) drives its own modal
        // (#face-confirm-modal) - hide this one while that's on top, and
        // bring it back if the user cancels the camera instead of finishing.
        modal.hidden = true;
        const token = await requestFaceConfirmationToken();
        if (!token) {
            modal.hidden = false;
            return;
        }
        await confirmWithCredential(proposalId, 'face', token, card);
    });

    document.getElementById('step-up-password-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        if (!stepUpProposalId) return;
        const passwordInput = document.getElementById('step-up-password-input');
        const password = passwordInput.value;
        if (!password) return;
        await confirmWithCredential(stepUpProposalId, 'password', password, stepUpCard);
    });
}

/* -------------------------------------------------------------------------
 * "Documente de semnat" - documents an admin generated and sent (see
 * backend app/modules/admin/service.py::generate_and_send_document),
 * listed from GET /documents/to-sign. Signing one goes through the
 * STRONGER OTP+Face confirm path (esign_service.confirm_admin_document),
 * not the ordinary Face-or-password step-up modal above - see
 * wireAdminDocSignModal/handleSignAdminDocument below.
 * ------------------------------------------------------------------------- */

async function loadDocumentsToSign() {
    const list = document.getElementById('documents-to-sign-list');
    if (!list) return;
    list.innerHTML = '<p class="field-hint">Se încarcă...</p>';

    let documents;
    try {
        documents = await apiFetch('/documents/to-sign');
    } catch (err) {
        list.innerHTML = `<p class="field-hint ocr-warning">${escapeHTML(err.message)}</p>`;
        return;
    }

    if (!documents.length) {
        list.innerHTML = '<p class="field-hint">Nu ai documente de semnat momentan.</p>';
        return;
    }

    list.innerHTML = '';
    documents.forEach((doc) => {
        const card = document.createElement('div');
        card.className = 'document-to-sign-card';

        const info = document.createElement('div');
        info.innerHTML = `<strong>${escapeHTML(doc.filename)}</strong>` +
            `<p class="field-hint">${escapeHTML(formatDateTime(doc.created_at))} · ${doc.page_count} pag.</p>`;
        card.appendChild(info);

        const actions = document.createElement('div');
        actions.className = 'document-to-sign-actions';

        const previewBtn = document.createElement('button');
        previewBtn.type = 'button';
        previewBtn.className = 'btn btn-secondary';
        previewBtn.textContent = 'Previzualizează';
        previewBtn.addEventListener('click', () => previewDocumentPdf(`/documents/${doc.id}/pdf`));
        actions.appendChild(previewBtn);

        if (doc.signed) {
            const badge = document.createElement('span');
            badge.className = 'document-to-sign-status signed';
            badge.innerHTML = '<i data-lucide="check-circle"></i> Semnat';
            actions.appendChild(badge);
        } else {
            const signBtn = document.createElement('button');
            signBtn.type = 'button';
            signBtn.className = 'btn btn-primary';
            signBtn.textContent = 'Semnează';
            signBtn.addEventListener('click', () => handleSignAdminDocument(doc, signBtn));
            actions.appendChild(signBtn);
        }
        card.appendChild(actions);

        list.appendChild(card);
    });
    if (window.lucide) lucide.createIcons();
}

/** Opens a document's actual PDF in a new tab. A plain `<a href>` to the
 * API won't work: the API is a different origin from this page (see
 * API_BASE_URL), so the browser wouldn't send the session cookie on a
 * fresh navigation reliably across browsers/SameSite settings. Fetching as
 * a blob with credentials included sidesteps that - same reasoning as
 * every other authenticated call in this file, just with `res.blob()`
 * instead of JSON. */
async function previewDocumentPdf(path) {
    try {
        const res = await fetch(`${API_BASE_URL}${path}`, { credentials: 'include' });
        if (!res.ok) throw new Error('Previzualizarea documentului a eșuat.');
        const blob = await res.blob();
        window.open(URL.createObjectURL(blob), '_blank');
    } catch (err) {
        showToast(err.message || 'Previzualizarea documentului a eșuat.');
    }
}

/** Creates the sign-request proposal (same endpoint the self-uploaded-
 * document "Semnează electronic" chip button uses - see handleSignDocument)
 * then opens the OTP+Face modal for it, instead of the generic proposal
 * card + step-up modal - an admin-issued document never goes through
 * POST /chat/proposals/{id}/confirm. */
async function handleSignAdminDocument(doc, triggerBtn) {
    triggerBtn.disabled = true;
    try {
        const proposal = await apiFetch(`/esign/documents/${doc.id}/sign-requests`, {
            method: 'POST',
            body: JSON.stringify({
                intent: `Am citit și sunt de acord cu conținutul documentului oficial „${doc.filename}”.`,
            }),
        });
        await openAdminDocSignModal(proposal.id, doc.filename);
    } catch (err) {
        showToast(err.message || 'Eroare la crearea cererii de semnătură.');
    } finally {
        triggerBtn.disabled = false;
    }
}

let adminDocSignProposalId = null;
let adminDocSignFilename = null;

function showAdminDocSignError(message) {
    const errorEl = document.getElementById('admin-doc-sign-error');
    errorEl.textContent = message;
    errorEl.hidden = false;
}

/** Requests a fresh OTP (POST .../signing-code, 204, delivered out-of-band
 * via Teams - same convention as password-reset codes) and shows the modal
 * for entering it. Re-callable as "Retrimite codul" without closing the
 * modal. */
async function requestAdminDocSignCode() {
    const statusEl = document.getElementById('admin-doc-sign-status');
    const errorEl = document.getElementById('admin-doc-sign-error');
    errorEl.hidden = true;
    statusEl.textContent = 'Se trimite codul de semnare...';
    try {
        await apiFetch(`/esign/proposals/${adminDocSignProposalId}/signing-code`, { method: 'POST' });
        statusEl.textContent = `Cod trimis pentru „${adminDocSignFilename}”. Verifică Teams.`;
    } catch (err) {
        statusEl.textContent = '';
        showAdminDocSignError(err.message || 'Codul nu a putut fi trimis.');
    }
}

async function openAdminDocSignModal(proposalId, filename) {
    adminDocSignProposalId = proposalId;
    adminDocSignFilename = filename;

    const modal = document.getElementById('admin-doc-sign-modal');
    const errorEl = document.getElementById('admin-doc-sign-error');
    const otpInput = document.getElementById('admin-doc-sign-otp-input');
    errorEl.hidden = true;
    otpInput.value = '';
    modal.hidden = false;

    await requestAdminDocSignCode();
}

function closeAdminDocSignModal() {
    document.getElementById('admin-doc-sign-modal').hidden = true;
    adminDocSignProposalId = null;
    adminDocSignFilename = null;
}

function wireAdminDocSignModal() {
    const modal = document.getElementById('admin-doc-sign-modal');
    if (!modal) return;

    document.getElementById('close-admin-doc-sign-modal').addEventListener('click', closeAdminDocSignModal);
    document.getElementById('admin-doc-sign-resend-btn').addEventListener('click', requestAdminDocSignCode);

    document.getElementById('admin-doc-sign-otp-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const proposalId = adminDocSignProposalId;
        if (!proposalId) return;

        const otpCode = document.getElementById('admin-doc-sign-otp-input').value.trim();
        if (otpCode.length !== 6) return;

        // Second factor: reuses the SAME camera-capture flow the ordinary
        // step-up modal uses for Face ID - hide this modal while it's on
        // top, bring it back if the user cancels the camera instead of
        // finishing.
        modal.hidden = true;
        const faceToken = await requestFaceConfirmationToken(
            'Semnare document oficial - identificare prin Face ID'
        );
        if (!faceToken) {
            modal.hidden = false;
            return;
        }

        try {
            await apiFetch(`/esign/proposals/${proposalId}/confirm-admin-document`, {
                method: 'POST',
                body: JSON.stringify({ otp_code: otpCode, face_token: faceToken }),
            });
            closeAdminDocSignModal();
            showToast('Documentul a fost semnat cu succes!');
            await loadDocumentsToSign();
        } catch (err) {
            modal.hidden = false;
            // The OTP is already consumed (or was never valid) at this
            // point either way - a retry needs a fresh one, not another
            // attempt with the same value.
            document.getElementById('admin-doc-sign-otp-input').value = '';
            showAdminDocSignError(err.message || 'Semnarea a eșuat.');
        }
    });
}

/* =========================================================================
 * Live backend wiring (accounts, transactions, transfers). Everything above
 * this line is the original static prototype's demo-only logic (nav, chat
 * simulation) - see api.js for the fetch wrapper this uses.
 * ========================================================================= */

let currentAccounts = [];
let currentCards = [];

const CURRENCY_ICONS = { RON: 'coins', EUR: 'euro', USD: 'dollar-sign' };

/* --- Balance count-up/down animation ---
 * Every balance display (headline total, account cards, savings pots) is
 * rebuilt from scratch via innerHTML on each refresh, so there's no DOM node
 * to tween across renders. Instead we remember the last value we displayed
 * for each element's key (see previousBalances below) and, right after the
 * new markup is inserted, replay a short count from that old value up to the
 * true new one on the freshly created element - the final state is always
 * correct even if the animation is skipped or interrupted. */

/** accountId (or a fixed key like 'headline') -> last balance_minor shown,
 * so the next render knows what to count FROM. Persisted to sessionStorage
 * (not just an in-memory Map) so the count survives an actual browser
 * reload, not only a same-tab refreshDashboard() call: without this, F5
 * right after a transfer would show the new balance appearing already-final
 * with no animation, since a reload wipes all in-memory JS state and there'd
 * be nothing to count FROM. sessionStorage (not localStorage) so a stale
 * balance from a previous session/device never leaks in as a bogus "from"
 * value - it's scoped to this tab and cleared when the tab closes. */
const BALANCE_STORAGE_KEY = 'bank_previous_balances';

function loadPreviousBalances() {
    try {
        const raw = sessionStorage.getItem(BALANCE_STORAGE_KEY);
        return raw ? new Map(Object.entries(JSON.parse(raw))) : new Map();
    } catch {
        return new Map(); // Corrupt/unavailable storage - just start fresh.
    }
}

function savePreviousBalances() {
    try {
        sessionStorage.setItem(BALANCE_STORAGE_KEY, JSON.stringify(Object.fromEntries(previousBalances)));
    } catch { /* Storage is optional - worst case a reload skips one animation. */ }
}

const previousBalances = loadPreviousBalances();

/** el -> in-flight requestAnimationFrame id, so re-rendering mid-animation
 * (e.g. two refreshes in quick succession) cancels the stale tween instead
 * of racing it. */
const balanceAnimations = new WeakMap();

/** Counts `el`'s text from `fromMinor` to `toMinor` over `duration`ms,
 * formatting each frame with `format` (defaults to plain formatMoney).
 * Briefly tints the text green/red while it moves, fading back to normal.
 * Jumps straight to the final value with no animation when there's nothing
 * to animate, or when the user prefers reduced motion. */
function animateBalance(el, fromMinor, toMinor, currency, { duration = 700, format } = {}) {
    if (!el) return;
    const formatFn = format || ((amount) => formatMoney(amount, currency));

    const pending = balanceAnimations.get(el);
    if (pending) cancelAnimationFrame(pending);

    if (fromMinor === toMinor || !Number.isFinite(fromMinor) || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        el.textContent = formatFn(toMinor);
        el.classList.remove('balance-flash-up', 'balance-flash-down');
        return;
    }

    // The element's text was just set to the FINAL value a moment ago (e.g.
    // by the innerHTML template that created it) - jump it back to the
    // starting value synchronously, before the browser gets a chance to
    // paint, so what's on screen the instant this runs is the count's start,
    // not a flash of the answer followed by a rewind down to where it
    // "should" have started.
    el.textContent = formatFn(fromMinor);

    // Restart the flash even if it's already mid-fade from a previous change.
    el.classList.remove('balance-flash-up', 'balance-flash-down');
    void el.offsetWidth;
    el.classList.add(toMinor > fromMinor ? 'balance-flash-up' : 'balance-flash-down');

    const easeOutCubic = (x) => 1 - (1 - x) ** 3;
    const start = performance.now();

    const tick = (now) => {
        const progress = Math.min((now - start) / duration, 1);
        const current = Math.round(fromMinor + (toMinor - fromMinor) * easeOutCubic(progress));
        el.textContent = formatFn(current);
        if (progress < 1) {
            balanceAnimations.set(el, requestAnimationFrame(tick));
        } else {
            balanceAnimations.delete(el);
            el.classList.remove('balance-flash-up', 'balance-flash-down');
        }
    };
    balanceAnimations.set(el, requestAnimationFrame(tick));
}

/** Looks up the previous value for `key`, animates `el` from there to
 * `toMinor`, then remembers `toMinor` as the new baseline for next time. */
function animateBalanceFor(key, el, toMinor, currency, options) {
    const fromMinor = previousBalances.has(key) ? previousBalances.get(key) : toMinor;
    animateBalance(el, fromMinor, toMinor, currency, options);
    previousBalances.set(key, toMinor);
    savePreviousBalances();
}

/** A term deposit can receive money anytime but can't be the SOURCE of a
 * transfer/payment until maturity_date - matches the backend's
 * assert_not_locked_for_debit, kept here too so the UI never offers a
 * choice that would just come back as a 409. */
function isSpendable(acc) {
    if (acc.status !== 'active') return false;
    if (acc.product_type === 'term_deposit' && acc.maturity_date) {
        return new Date(acc.maturity_date) <= new Date();
    }
    return true;
}

/** Shows or hides the admin-panel link to match whoever is CURRENTLY
 * signed in.
 *
 * Asks the server (GET /admin/me) rather than reading a role off the user
 * object: the role is not part of UserRead, and a client-side flag would be
 * cosmetic anyway - the real gate is require_admin on every /admin route,
 * so this link is only ever a convenience, never the actual security
 * boundary. Explicitly sets `hidden` BOTH ways (not just true->false) and
 * gets re-run on tab focus (see wireAdminLinkRefresh) - the session cookie
 * is shared per-browser, not per-tab, so logging into a different account
 * in another tab silently changes who this tab is authenticated as too;
 * without re-checking on focus, an admin's link would stay visible (and a
 * newly-promoted admin's would stay hidden) until the next full reload. */
async function revealAdminLinkIfAdmin() {
    const link = document.getElementById('admin-panel-link');
    if (!link) return;
    try {
        await apiFetch('/admin/me');
        link.hidden = false;
    } catch {
        link.hidden = true;
    }
}

/** Re-checks admin status whenever this tab regains focus/visibility - see
 * revealAdminLinkIfAdmin's doc comment for why that's necessary. */
function wireAdminLinkRefresh() {
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') void revealAdminLinkIfAdmin();
    });
    window.addEventListener('focus', () => void revealAdminLinkIfAdmin());
}

async function initDashboard() {
    const user = await requireSession();
    if (!user) return; // requireSession already redirected to login.html

    document.getElementById('user-name').textContent = `${user.first_name} ${user.last_name}`;
    applyAvatar(user);
    void revealAdminLinkIfAdmin();
    wireAdminLinkRefresh();

    document.getElementById('logout-btn').addEventListener('click', async () => {
        try {
            await apiFetch('/auth/logout', { method: 'POST' });
        } finally {
            window.location.href = 'login.html';
        }
    });

    wireNewAccountModal();
    wireSavingsModal();
    wireTransferModal();
    wireNewCardModal();
    wireCardOrderModal();
    wirePaymentsForm();
    wireProfilePanel(user);
    wireNotificationsPanel();
    wireAddBeneficiaryForm();
    wireScheduledTransfersModal();

    await loadAccountProducts();
    await refreshDashboard();
}

async function refreshDashboard() {
    await loadAccounts();
    await loadTransactions();
    await loadCards();
    await loadBeneficiaries();
    await loadPayments();
    await loadSpendingByCategory();
    await loadScheduledTransfers();
}

//: Fixed hue order, validated (CVD-safe under protan/deuteranopia simulation,
//: normal-vision floor, contrast on this app's --bg-surface #1A2235 - see
//: dataviz skill's palette.md/color-formula.md) - never cycled, never
//: generated. Assigned to real categories only, in order of first
//: appearance; "Altele" always gets SPENDING_OTHER_COLOR instead, win or
//: lose, so a residual/mixed bucket never impersonates a real category's hue.
const SPENDING_CATEGORY_PALETTE = [
    '#3987e5', // blue
    '#d95926', // orange
    '#199e70', // aqua
    '#c98500', // yellow
    '#d55181', // magenta
    '#008300', // green
];
const SPENDING_OTHER_CATEGORY_NAME = 'Altele';
const SPENDING_OTHER_COLOR = '#898781';

function localizeTransactionDescription(description) {
    const transfer = description?.match(/^Transfer: (.+) → (.+)$/);
    if (transfer) return t('dynamic.transaction_transfer', 'Transfer: {from} → {to}', { from: transfer[1], to: transfer[2] });
    const payment = description?.match(/^Plată către (.+)$/);
    if (payment) return t('dynamic.transaction_payment', 'Payment to {name}', { name: payment[1] });
    return description;
}

//: Maps the backend's fixed, Romanian-only category names (see
//: CATEGORY_KEYWORDS in categorize_transactions.py) to i18n keys - the
//: backend has no locale concept, it always returns e.g. "Facturi &
//: Utilități", so every category (not just "Altele") needs a lookup here
//: or it stays hardcoded in Romanian regardless of the selected language.
const SPENDING_CATEGORY_KEYS = {
    'Facturi & Utilități': 'dynamic.category_bills_utilities',
    'Telecomunicații': 'dynamic.category_telecom',
    'Divertisment': 'dynamic.category_entertainment',
    'Mâncare & Băutură': 'dynamic.category_food_drink',
    'Cumpărături alimentare': 'dynamic.category_groceries',
    'Transport / Combustibil': 'dynamic.category_transport',
    'Sănătate': 'dynamic.category_health',
    'Electronice': 'dynamic.category_electronics',
    'Îmbrăcăminte': 'dynamic.category_clothing',
    'Educație': 'dynamic.category_education',
    'Locuință & Amenajări': 'dynamic.category_home',
    'Asigurări': 'dynamic.category_insurance',
    'Transferuri': 'dynamic.category_transfers',
};

function localizeCategoryName(name) {
    if (name === SPENDING_OTHER_CATEGORY_NAME) return t('dynamic.category_other', 'Other');
    const key = SPENDING_CATEGORY_KEYS[name];
    return key ? t(key, name) : name;
}

//: Donut/pie is only honest "at a glance" up to ~6 slices (see dataviz
//: skill's anti-patterns.md) - past that, distinct hues run out and slivers
//: blur together. Anything past the cap folds into one trailing "Altele",
//: merged with the backend's own "Altele" if it sent one.
const SPENDING_MAX_DIRECT_CATEGORIES = 6;

/** Caps at SPENDING_MAX_DIRECT_CATEGORIES real (non-"Altele") categories,
 * folding the backend's own "Altele" plus any overflow past the cap into one
 * trailing bucket - always last, regardless of its size, so a residual/mixed
 * category is never mistaken for a single coherent one that happens to rank
 * high. Categories arrive pre-sorted descending by amount (see
 * categorize_transactions.py), so `.slice` alone preserves rank order. */
function foldSpendingCategories(categories) {
    const real = categories.filter(c => c.name !== SPENDING_OTHER_CATEGORY_NAME);
    const backendOther = categories.find(c => c.name === SPENDING_OTHER_CATEGORY_NAME);

    const kept = real.slice(0, SPENDING_MAX_DIRECT_CATEGORIES);
    const overflow = real.slice(SPENDING_MAX_DIRECT_CATEGORIES);

    let otherTotalMinor = backendOther ? backendOther.total_minor : 0;
    let otherPercentage = backendOther ? backendOther.percentage : 0;
    overflow.forEach(c => {
        otherTotalMinor += c.total_minor;
        otherPercentage += c.percentage;
    });

    const result = kept.map(c => ({ ...c, color: null }));
    result.forEach((c, i) => { c.color = SPENDING_CATEGORY_PALETTE[i % SPENDING_CATEGORY_PALETTE.length]; });

    if (otherTotalMinor > 0) {
        result.push({
            name: SPENDING_OTHER_CATEGORY_NAME,
            total_minor: otherTotalMinor,
            percentage: otherPercentage,
            color: SPENDING_OTHER_COLOR,
        });
    }
    return result;
}

//: Geometry shared between the SVG markup and the hover math below -
//: viewBox is square, ring sits centered, with enough margin past the
//: stroke for the hover "pop out" translate and drop-shadow to never clip.
const SPENDING_DONUT_SIZE = 200;
const SPENDING_DONUT_CENTER = SPENDING_DONUT_SIZE / 2;
const SPENDING_DONUT_RADIUS = 68;
const SPENDING_DONUT_STROKE = 26;
const SPENDING_DONUT_GAP_PX = 3;
const SPENDING_DONUT_HOVER_OFFSET = 8;
const SPENDING_DONUT_CIRCUMFERENCE = 2 * Math.PI * SPENDING_DONUT_RADIUS;

/** Outward (dx, dy) for a slice whose visual midpoint sits at `midAngleDeg`
 * (0 = 12 o'clock, clockwise) - the direction a hovered slice "explodes"
 * toward, and the direction its drop-shadow leans. */
function angleToOffset(midAngleDeg, distance) {
    const rad = (midAngleDeg * Math.PI) / 180;
    return { dx: Math.sin(rad) * distance, dy: -Math.cos(rad) * distance };
}

/** Builds the ring's SVG markup: two <circle>s per category, sharing the
 * same arc (stroke-dasharray only paints that one slice, with a small gap
 * on either side instead of a border - see dataviz skill's anti-patterns.md
 * on borders between marks).
 *
 * They're split in two because pointer-events hit-test an SVG shape's
 * CURRENT painted geometry, transform included: a single circle that both
 * received hover events AND translated outward on hover would move out from
 * under a cursor sitting near its outer edge, fire pointerleave, snap back
 * under the cursor, fire pointerenter, and repeat - a self-triggering flicker
 * users see as the slice "flying" right where they're pointing. So
 * `.spending-segment-hit` (transparent, never transformed by hover state)
 * is the only thing hit-tested, and `.spending-segment-fill` (the visible
 * color, `pointer-events: none`) is free to pop outward on hover without
 * ever being able to move itself out from under the pointer that triggered
 * it.
 *
 * Positioning, the mount animation, and the hover pop-out on the fill circle
 * are ALL one CSS `transform` chain (`translate() rotate() scale()`,
 * right-to-left composition) driven by --rot/--hx/--hy/--scale custom
 * properties - deliberately NOT split across an SVG `rotate` attribute on a
 * wrapping <g> plus a separate CSS transform on the child, which would nest
 * the child's translate inside the parent's rotation and swing the hover
 * offset off in the wrong direction. The hit circle shares --rot (so its
 * hit area still tracks the slice's position) but never --hx/--hy/--scale. */
function buildSpendingDonutSegments(categories) {
    let cumulativePercent = 0;
    return categories.map((cat, i) => {
        const startPercent = cumulativePercent;
        cumulativePercent += cat.percentage;
        const segLen = (cat.percentage / 100) * SPENDING_DONUT_CIRCUMFERENCE;
        const visibleLen = Math.max(segLen - SPENDING_DONUT_GAP_PX, 1);
        const startAngleDeg = (startPercent / 100) * 360;
        const midAngleDeg = startAngleDeg + ((cat.percentage / 100) * 360) / 2;
        const { dx, dy } = angleToOffset(midAngleDeg, SPENDING_DONUT_HOVER_OFFSET);

        return `
            <g class="spending-segment" data-index="${i}" tabindex="0"
               role="img" aria-label="${escapeHTML(localizeCategoryName(cat.name))}"
               style="--rot: ${(startAngleDeg - 90).toFixed(3)}deg; --hx-active: ${dx.toFixed(2)}px; --hy-active: ${dy.toFixed(2)}px; --seg-delay: ${i * 70}ms;">
                <circle class="spending-segment-hit"
                    cx="${SPENDING_DONUT_CENTER}" cy="${SPENDING_DONUT_CENTER}" r="${SPENDING_DONUT_RADIUS}"
                    fill="none" stroke="transparent" stroke-width="${SPENDING_DONUT_STROKE}"
                    stroke-linecap="round"
                    stroke-dasharray="0 ${SPENDING_DONUT_GAP_PX / 2} ${visibleLen} ${SPENDING_DONUT_CIRCUMFERENCE}"
                ></circle>
                <circle class="spending-segment-fill"
                    cx="${SPENDING_DONUT_CENTER}" cy="${SPENDING_DONUT_CENTER}" r="${SPENDING_DONUT_RADIUS}"
                    fill="none" stroke="${cat.color}" stroke-width="${SPENDING_DONUT_STROKE}"
                    stroke-linecap="round"
                    stroke-dasharray="0 ${SPENDING_DONUT_GAP_PX / 2} ${visibleLen} ${SPENDING_DONUT_CIRCUMFERENCE}"
                ></circle>
            </g>
        `;
    }).join('');
}

/** Renders the SVG donut + center total into `#spending-category-donut`
 * (a plain wrapper div, not itself an SVG - built fresh each load since the
 * category set can change). */
function renderSpendingDonut(donutWrap, categories, primaryCurrency) {
    const totalMinor = categories.reduce((sum, c) => sum + c.total_minor, 0);
    donutWrap.innerHTML = `
        <svg class="spending-donut" viewBox="0 0 ${SPENDING_DONUT_SIZE} ${SPENDING_DONUT_SIZE}" role="group" aria-label="${escapeHTML(t('dynamic.spending_by_category', 'Spending by category'))}">
            ${buildSpendingDonutSegments(categories)}
        </svg>
        <div class="spending-donut-center">
            <span class="spending-donut-total-label">${escapeHTML(t('dynamic.total', 'Total'))}</span>
            <span class="spending-donut-total-value">${formatMoney(totalMinor, primaryCurrency)}</span>
        </div>
        <div class="spending-donut-tooltip" id="spending-donut-tooltip" hidden></div>
    `;
    // Segments mount at scale 0 (see CSS) and grow in, staggered - the
    // "animated" entrance. Two rAFs so the browser commits the 0-scale
    // frame before the transition-triggering class lands (one is flaky).
    requestAnimationFrame(() => requestAnimationFrame(() => {
        donutWrap.classList.add('is-mounting');
        // Swap to the fast, undelayed transition once every staggered
        // entrance has finished, so a later slice's hover response doesn't
        // inherit its mount stagger and feel laggy (see the CSS comment).
        const mountDurationMs = categories.length * 70 + 550;
        setTimeout(() => {
            donutWrap.classList.remove('is-mounting');
            donutWrap.classList.add('is-mounted');
        }, mountDurationMs);
    }));
}

/** Cross-highlights a category across the donut and the legend: hovering or
 * focusing either one highlights that category's slice + row and dims every
 * other one, so a colorblind user can confirm "this slice = this row" by
 * position/highlight rather than by matching hues. */
function wireSpendingCategoryHover(container, categories, primaryCurrency) {
    const donutWrap = container.querySelector('.spending-donut-wrap');
    const svg = donutWrap.querySelector('.spending-donut');
    const tooltip = donutWrap.querySelector('#spending-donut-tooltip');
    const legend = container.querySelector('.legend');
    if (!svg || !legend) return;

    function setActive(index) {
        svg.classList.toggle('has-active', index !== null);
        legend.classList.toggle('has-active', index !== null);
        svg.querySelectorAll('.spending-segment').forEach(seg => {
            seg.classList.toggle('is-active', Number(seg.dataset.index) === index);
        });
        legend.querySelectorAll('.legend-item').forEach(row => {
            row.classList.toggle('is-active', Number(row.dataset.index) === index);
        });

        if (index === null) {
            tooltip.hidden = true;
            return;
        }
        const cat = categories[index];
        tooltip.innerHTML = `
            <span class="spending-donut-tooltip-value">${formatMoney(cat.total_minor, primaryCurrency)}</span>
            <span class="spending-donut-tooltip-label">${escapeHTML(localizeCategoryName(cat.name))} &middot; ${cat.percentage.toFixed(0)}%</span>
        `;
        tooltip.hidden = false;
    }

    svg.querySelectorAll('.spending-segment').forEach(seg => {
        const index = Number(seg.dataset.index);
        seg.addEventListener('pointerenter', () => setActive(index));
        seg.addEventListener('pointerleave', () => setActive(null));
        seg.addEventListener('focus', () => setActive(index));
        seg.addEventListener('blur', () => setActive(null));
    });

    legend.querySelectorAll('.legend-item').forEach(row => {
        const index = Number(row.dataset.index);
        row.addEventListener('pointerenter', () => setActive(index));
        row.addEventListener('pointerleave', () => setActive(null));
        row.addEventListener('focus', () => setActive(index));
        row.addEventListener('blur', () => setActive(null));
    });
}

async function loadSpendingByCategory() {
    const donutWrap = document.getElementById('spending-category-donut');
    const legend = document.getElementById('spending-category-legend');
    const container = document.getElementById('spending-category-container');

    const active = currentAccounts.filter(a => a.status === 'active');
    if (active.length === 0) {
        donutWrap.innerHTML = '';
        donutWrap.style.display = 'none';
        legend.innerHTML = `<div class="empty-state">${escapeHTML(t('dynamic.no_active_accounts', 'No active accounts yet.'))}</div>`;
        return;
    }

    const now = new Date();
    const startDate = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10);
    const endDate = now.toISOString().slice(0, 10);

    let data;
    try {
        data = await apiFetch(
            `/insights/spending-by-category?start_date=${startDate}&end_date=${endDate}`
        );
    } catch (err) {
        donutWrap.innerHTML = '';
        donutWrap.style.display = 'none';
        legend.innerHTML = `<div class="empty-state">${escapeHTML(t('dynamic.load_categories_error', 'Nu s-au putut încărca categoriile: {message}', { message: err.message }))}</div>`;
        return;
    }

    const rawCategories = data.categories.filter(c => c.total_minor > 0);
    if (rawCategories.length === 0) {
        donutWrap.innerHTML = '';
        donutWrap.style.display = 'none';
        legend.innerHTML = `<div class="empty-state">${escapeHTML(t('dynamic.no_monthly_spending', 'No spending this month yet.'))}</div>`;
        return;
    }

    // Same "mixed currencies can't be summed" simplification as
    // renderHeadlineBalance - amounts are shown in the first active
    // account's currency, since the backend has no "home currency" concept.
    const primaryCurrency = active[0].currency;
    const categories = foldSpendingCategories(rawCategories);

    donutWrap.style.display = '';
    renderSpendingDonut(donutWrap, categories, primaryCurrency);

    legend.innerHTML = categories.map((cat, i) => `
        <div class="legend-item" data-index="${i}" tabindex="0">
            <span class="dot" style="background-color: ${cat.color};"></span>
            ${escapeHTML(localizeCategoryName(cat.name))} (${cat.percentage.toFixed(0)}%) &middot; ${formatMoney(cat.total_minor, primaryCurrency)}
        </div>
    `).join('');

    wireSpendingCategoryHover(container, categories, primaryCurrency);
}

async function loadAccounts() {
    const grid = document.getElementById('accounts-grid');
    try {
        currentAccounts = await apiFetch('/accounts');
    } catch (err) {
        grid.innerHTML = `<div class="empty-state">${escapeHTML(t('dynamic.load_accounts_error', 'Nu s-au putut încărca conturile: {message}', { message: err.message }))}</div>`;
        return;
    }

    renderAccountsGrid();
    renderHeadlineBalance();
    renderSavingsAccountsList();
    populateTransferAccountSelects();
    populatePaymentsAccountSelect();
}

function renderAccountsGrid() {
    const grid = document.getElementById('accounts-grid');
    if (currentAccounts.length === 0) {
        grid.innerHTML = `<div class="empty-state">${escapeHTML(t('dynamic.no_accounts_yet', 'Niciun cont încă. Creează primul cont.'))}</div>`;
        return;
    }
    grid.innerHTML = currentAccounts.map(acc => `
        <div class="account-card ${acc.status === 'closed' ? 'closed' : ''}">
            <div class="acc-icon"><i data-lucide="${CURRENCY_ICONS[acc.currency] || 'wallet'}"></i></div>
            <div class="acc-info">
                <h3>${escapeHTML(acc.name)}</h3>
                <p>${escapeHTML(acc.currency)}${acc.product_type !== 'checking' ? ` &middot; ${(acc.interest_rate_bps / 100).toFixed(1)}% p.a.` : ''}</p>
            </div>
            <div class="acc-balance" data-account-id="${escapeHTML(acc.id)}">${formatMoney(acc.balance_minor, acc.currency)}</div>
            ${acc.status === 'closed' ? `<span class="acc-status">${escapeHTML(t('dynamic.account_closed', 'Închis'))}</span>` : ''}
            ${!isSpendable(acc) ? `<span class="acc-status locked">${escapeHTML(t('dynamic.account_locked', 'Blocat'))}</span>` : ''}
            <button type="button" class="acc-statement-btn" data-account-id="${escapeHTML(acc.id)}"
                    data-account-name="${escapeHTML(acc.name)}" title="Descarcă extras de cont">
                <i data-lucide="file-down"></i>
            </button>
        </div>
    `).join('');
    grid.querySelectorAll('.acc-statement-btn').forEach((btn) => {
        btn.addEventListener('click', (event) => {
            event.stopPropagation();
            openStatementModal(btn.dataset.accountId, btn.dataset.accountName);
        });
    });
    // Each card starts out showing its true final balance (see the innerHTML
    // above, for correctness with JS disabled/before this runs); this replays
    // it as a count from whatever we last showed for that account, so a
    // balance change from a transfer/payment ticks up or down instead of
    // silently appearing already-updated on the next refresh.
    grid.querySelectorAll('.acc-balance').forEach((el) => {
        const acc = currentAccounts.find((a) => a.id === el.dataset.accountId);
        if (acc) animateBalanceFor(`account:${acc.id}`, el, acc.balance_minor, acc.currency);
    });
    if (window.lucide) lucide.createIcons();
}

function renderHeadlineBalance() {
    const el = document.getElementById('total-balance');
    const active = currentAccounts.filter(a => a.status === 'active');
    if (active.length === 0) {
        animateBalanceFor('headline:RON', el, 0, 'RON');
        return;
    }
    // Accounts can hold different currencies, which can't be summed together -
    // the headline number totals accounts in the first active account's
    // currency only (there's no "home currency" concept in the backend).
    // The currency is baked into the key itself (not tracked separately) so
    // a currency switch (e.g. the first active account changed) naturally
    // looks up a fresh, never-seen key instead of counting from a total that
    // was in a different currency entirely.
    const primaryCurrency = active[0].currency;
    const total = active
        .filter(a => a.currency === primaryCurrency)
        .reduce((sum, a) => sum + a.balance_minor, 0);
    animateBalanceFor(`headline:${primaryCurrency}`, el, total, primaryCurrency);
}

/* -------------------------------------------------------------------------
 * Account statement download - the "extras de cont" icon on each account
 * card (see renderAccountsGrid above) opens a small period picker, then
 * downloads GET /accounts/{id}/statement/pdf as an actual file. A real
 * file save, not a preview: fetched as a blob (the API is a different
 * origin, so a plain <a href> wouldn't reliably carry the session cookie -
 * same reasoning as previewDocumentPdf), then "clicked" through a hidden,
 * temporary <a download> to trigger the browser's save dialog.
 * ------------------------------------------------------------------------- */

let statementAccountId = null;

function openStatementModal(accountId, accountName) {
    statementAccountId = accountId;
    const modal = document.getElementById('statement-modal');
    document.getElementById('statement-error').hidden = true;
    document.getElementById('statement-account-name').textContent = accountName;

    const today = new Date();
    const monthAgo = new Date(today);
    monthAgo.setDate(monthAgo.getDate() - 30);
    document.getElementById('statement-period-end').value = today.toISOString().slice(0, 10);
    document.getElementById('statement-period-start').value = monthAgo.toISOString().slice(0, 10);

    modal.hidden = false;
}

function closeStatementModal() {
    document.getElementById('statement-modal').hidden = true;
    statementAccountId = null;
}

function showStatementError(message) {
    const errorEl = document.getElementById('statement-error');
    errorEl.textContent = message;
    errorEl.hidden = false;
}

function wireStatementModal() {
    const modal = document.getElementById('statement-modal');
    if (!modal) return;

    document.getElementById('close-statement-modal').addEventListener('click', closeStatementModal);
    document.getElementById('cancel-statement').addEventListener('click', closeStatementModal);

    document.getElementById('statement-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        if (!statementAccountId) return;

        const start = document.getElementById('statement-period-start').value;
        const end = document.getElementById('statement-period-end').value;
        if (start > end) {
            showStatementError('Data de început trebuie să fie înainte de data de sfârșit.');
            return;
        }

        const submitBtn = document.getElementById('statement-submit-btn');
        submitBtn.disabled = true;
        try {
            const params = new URLSearchParams({ period_start: start, period_end: end });
            const res = await fetch(
                `${API_BASE_URL}/accounts/${statementAccountId}/statement/pdf?${params}`,
                { credentials: 'include' },
            );
            if (!res.ok) {
                const body = await res.json().catch(() => ({}));
                throw new Error(body?.error?.message || 'Extrasul nu a putut fi generat.');
            }
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `extras-cont-${start}-${end}.pdf`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
            closeStatementModal();
        } catch (err) {
            showStatementError(err.message || 'Extrasul nu a putut fi generat.');
        } finally {
            submitBtn.disabled = false;
        }
    });
}

async function loadTransactions() {
    const list = document.getElementById('transactions-list');
    const active = currentAccounts.filter(a => a.status === 'active');
    if (active.length === 0) {
        list.innerHTML = `<div class="empty-state" data-i18n="dashboard.no_activity">${t('dashboard.no_activity')}</div>`;
        return;
    }


    try {
        // Fetch the 5 most recent per account, then re-sort/trim across
        // accounts - this widget only ever shows the 5 most recent overall
        // (see loadAllTransactions for the full, grouped-by-month history).
        const perAccount = await Promise.all(
            active.map(acc => apiFetch(`/accounts/${acc.id}/transactions?limit=5`))
        );
        const entries = perAccount.flat().sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 5);

        if (entries.length === 0) {
            list.innerHTML = `<div class="empty-state" data-i18n="dashboard.no_activity">${t('dashboard.no_activity')}</div>`;
            return;
        }

        list.innerHTML = entries.map(entry => `
            <div class="transaction-item">
                <div class="tx-icon ${entry.direction === 'credit' ? 'income' : 'expense'}">
                    <i data-lucide="${entry.direction === 'credit' ? 'arrow-down-left' : 'arrow-up-right'}"></i>
                </div>
                <div class="tx-details">
                    <h4>${escapeHTML(localizeTransactionDescription(entry.description))}</h4>
                    <span class="time">${formatDateTime(entry.created_at)}</span>
                </div>
                <div class="tx-amount ${entry.direction === 'credit' ? 'positive' : 'negative'}">
                    ${entry.direction === 'credit' ? '+' : '-'} ${formatMoney(entry.amount_minor, entry.currency)}
                </div>
            </div>
        `).join('');
        if (window.lucide) lucide.createIcons();
    } catch (err) {
        list.innerHTML = `<div class="empty-state">${escapeHTML(t('dynamic.load_transactions_error', 'Nu s-au putut încărca tranzacțiile: {message}', { message: err.message }))}</div>`;
    }
}

/* --- All transactions, grouped by month --- */

async function loadAllTransactions() {
    const container = document.getElementById('all-transactions-list');
    if (!container) return;

    const active = currentAccounts.filter(a => a.status === 'active');
    if (active.length === 0) {
        container.innerHTML = `<div class="empty-state" data-i18n="dashboard.no_activity">${t('dashboard.no_activity')}</div>`;
        return;
    }

    container.innerHTML = `<div class="loading-state">${escapeHTML(t('common.loading', 'Se încarcă...'))}</div>`;

    try {
        const accountById = Object.fromEntries(active.map(a => [a.id, a]));
        // /transactions caps at 200 per request (see transactions/service.py::MAX_LIMIT) -
        // fine for "all" in a demo-sized account; a real full history would need pagination.
        const perAccount = await Promise.all(
            active.map(acc => apiFetch(`/accounts/${acc.id}/transactions?limit=200`))
        );
        const entries = perAccount
            .flat()
            .map(entry => ({ ...entry, accountName: accountById[entry.account_id]?.name }))
            .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

        if (entries.length === 0) {
            container.innerHTML = `<div class="empty-state" data-i18n="dashboard.no_activity">${t('dashboard.no_activity')}</div>`;
            return;
        }

        renderTransactionsByMonth(container, entries);
    } catch (err) {
        container.innerHTML = `<div class="empty-state">${escapeHTML(t('dynamic.load_transactions_error', 'Nu s-au putut încărca tranzacțiile: {message}', { message: err.message }))}</div>`;
    }
}

function monthGroupKey(isoString) {
    const d = new Date(isoString);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function monthGroupLabel(isoString) {
    const label = new Date(isoString).toLocaleDateString(document.documentElement.lang || 'ro', { month: 'long', year: 'numeric' });
    return label.charAt(0).toUpperCase() + label.slice(1);
}

function renderTransactionsByMonth(container, entries) {
    // Entries already sorted newest-first, so insertion order into the Map
    // naturally puts the most recent month first too.
    const groups = new Map();
    for (const entry of entries) {
        const key = monthGroupKey(entry.created_at);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(entry);
    }

    container.innerHTML = [...groups.values()].map(monthEntries => `
        <div class="month-group">
            <h3 class="month-header">${monthGroupLabel(monthEntries[0].created_at)}</h3>
            <div class="transactions-list">
                ${monthEntries.map(entry => `
                    <div class="transaction-item">
                        <div class="tx-icon ${entry.direction === 'credit' ? 'income' : 'expense'}">
                            <i data-lucide="${entry.direction === 'credit' ? 'arrow-down-left' : 'arrow-up-right'}"></i>
                        </div>
                        <div class="tx-details">
                            <h4>${escapeHTML(localizeTransactionDescription(entry.description))}</h4>
                            <span class="time">${formatDateTime(entry.created_at)}${entry.accountName ? ' · ' + escapeHTML(entry.accountName) : ''}</span>
                        </div>
                        <div class="tx-amount ${entry.direction === 'credit' ? 'positive' : 'negative'}">
                            ${entry.direction === 'credit' ? '+' : '-'} ${formatMoney(entry.amount_minor, entry.currency)}
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
    `).join('');

    if (window.lucide) lucide.createIcons();
}

function formatDateTime(isoString) {
    const date = new Date(isoString);
    const language = document.documentElement.lang || 'ro';
    return date.toLocaleDateString(language, { day: 'numeric', month: 'short' }) +
        ', ' + date.toLocaleTimeString(language, { hour: '2-digit', minute: '2-digit' });
}

/* --- New account modal --- */

function wireNewAccountModal() {
    const modal = document.getElementById('new-account-modal');
    const form = document.getElementById('new-account-form');
    const errorEl = document.getElementById('new-account-error');

    document.getElementById('open-new-account-btn').addEventListener('click', () => {
        errorEl.hidden = true;
        form.reset();
        modal.hidden = false;
    });
    document.getElementById('close-new-account-modal').addEventListener('click', () => { modal.hidden = true; });
    document.getElementById('cancel-new-account').addEventListener('click', () => { modal.hidden = true; });

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        errorEl.hidden = true;
        try {
            await apiFetch('/accounts', {
                method: 'POST',
                body: JSON.stringify({
                    name: document.getElementById('new-account-name').value,
                    currency: document.getElementById('new-account-currency').value,
                }),
            });
            modal.hidden = true;
            await refreshDashboard();
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.hidden = false;
        }
    });
}

/* --- Savings / term-deposit accounts (Investiții & Bugetare) --- */

let accountProducts = null;

async function loadAccountProducts() {
    try {
        accountProducts = await apiFetch('/accounts/products');
        const savingsLabel = document.getElementById('savings-rate-label');
        const termLabel = document.getElementById('term-deposit-rate-label');
        if (savingsLabel) {
            savingsLabel.textContent = `${(accountProducts.savings_interest_rate_bps / 100).toFixed(1)}% p.a.`;
        }
        if (termLabel && accountProducts.term_deposit_options.length) {
            const maxRate = Math.max(...accountProducts.term_deposit_options.map((o) => o.interest_rate_bps));
            termLabel.textContent = t('savings.up_to_rate', 'până la {rate}% p.a.', { rate: (maxRate / 100).toFixed(1) });
        }
    } catch {
        // The product picker just keeps its placeholder labels - not
        // critical enough to show an error banner for.
    }
}

function wireSavingsModal() {
    const modal = document.getElementById('new-savings-modal');
    const form = document.getElementById('new-savings-form');
    const errorEl = document.getElementById('new-savings-error');
    const titleEl = document.getElementById('new-savings-modal-title');
    const termRow = document.getElementById('new-savings-term-row');
    const termSelect = document.getElementById('new-savings-term');
    const rateHint = document.getElementById('new-savings-rate-hint');
    const currencySelect = document.getElementById('new-savings-currency');
    const projectionRow = document.getElementById('new-savings-projection-row');
    const projectionAmountInput = document.getElementById('new-savings-projection-amount');
    const projectionBox = document.getElementById('new-savings-projection-box');
    let productType = 'savings';

    function updateRateHint() {
        if (!accountProducts) {
            rateHint.textContent = '';
            return;
        }
        if (productType === 'savings') {
            rateHint.textContent = t('savings.interest_monthly', 'Dobândă: {rate}% p.a., calculată lunar.', {
                rate: (accountProducts.savings_interest_rate_bps / 100).toFixed(1),
            });
        } else {
            const months = Number(termSelect.value);
            const option = accountProducts.term_deposit_options.find((o) => o.term_months === months);
            rateHint.textContent = option
                ? t('savings.interest_term', 'Dobândă: {rate}% p.a., plătită la final. Banii sunt blocați {months} luni.', {
                    rate: (option.interest_rate_bps / 100).toFixed(1),
                    months,
                })
                : '';
        }
    }

    // Purely an estimate shown while filling in the modal - the account
    // itself always opens empty (or with the referral welcome balance);
    // funding it is still a separate transfer afterwards, same as any
    // other account.
    function updateProjection() {
        if (productType !== 'term_deposit' || !accountProducts) {
            projectionBox.hidden = true;
            return;
        }
        const principalMajor = parseFloat(projectionAmountInput.value);
        const months = Number(termSelect.value);
        const option = accountProducts.term_deposit_options.find((o) => o.term_months === months);
        if (!option || !Number.isFinite(principalMajor) || principalMajor <= 0) {
            projectionBox.hidden = true;
            return;
        }
        const currency = currencySelect.value;
        const principalMinor = Math.round(principalMajor * 100);
        const interestMinor = Math.floor((principalMinor * option.interest_rate_bps * months) / (12 * 10_000));
        const totalMinor = principalMinor + interestMinor;

        projectionBox.hidden = false;
        projectionBox.innerHTML = `
            ${escapeHTML(t('savings.projection_deposit', 'Depui {amount} acum, pe {months} luni la {rate}% p.a.', {
                amount: formatMoney(principalMinor, currency),
                months,
                rate: (option.interest_rate_bps / 100).toFixed(1),
            }))}
            <div class="projection-total">${formatMoney(totalMinor, currency)}</div>
            <div>${escapeHTML(t('savings.projection_maturity', 'la maturitate (din care {interest} dobândă)', {
                interest: formatMoney(interestMinor, currency),
            }))}</div>
        `;
    }

    function openModal(type) {
        productType = type;
        errorEl.hidden = true;
        form.reset();
        if (type === 'savings') {
            titleEl.textContent = t('savings.new_savings_title', 'Cont de economii nou');
            termRow.hidden = true;
            projectionRow.hidden = true;
            projectionBox.hidden = true;
        } else {
            titleEl.textContent = t('savings.new_term_title', 'Cont cu dobândă fixă nou');
            termRow.hidden = false;
            projectionRow.hidden = false;
            if (accountProducts) {
                termSelect.innerHTML = accountProducts.term_deposit_options
                    .map((o) => `<option value="${o.term_months}">${escapeHTML(t('savings.term_option', '{months} luni - {rate}% p.a.', {
                        months: o.term_months,
                        rate: (o.interest_rate_bps / 100).toFixed(1),
                    }))}</option>`)
                    .join('');
            }
        }
        updateRateHint();
        updateProjection();
        modal.hidden = false;
    }

    document.getElementById('open-savings-btn').addEventListener('click', () => openModal('savings'));
    document.getElementById('open-term-deposit-btn').addEventListener('click', () => openModal('term_deposit'));
    document.getElementById('close-new-savings-modal').addEventListener('click', () => { modal.hidden = true; });
    document.getElementById('cancel-new-savings').addEventListener('click', () => { modal.hidden = true; });
    termSelect.addEventListener('change', () => { updateRateHint(); updateProjection(); });
    currencySelect.addEventListener('change', updateProjection);
    projectionAmountInput.addEventListener('input', updateProjection);

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        errorEl.hidden = true;
        try {
            await apiFetch('/accounts', {
                method: 'POST',
                body: JSON.stringify({
                    name: document.getElementById('new-savings-name').value,
                    currency: document.getElementById('new-savings-currency').value,
                    product_type: productType,
                    term_months: productType === 'term_deposit' ? Number(termSelect.value) : null,
                }),
            });
            modal.hidden = true;
            await refreshDashboard();
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.hidden = false;
        }
    });
}

function renderSavingsAccountsList() {
    const list = document.getElementById('savings-accounts-list');
    if (!list) return;
    const savingsAccounts = currentAccounts.filter((a) => a.product_type !== 'checking');
    if (savingsAccounts.length === 0) {
        list.innerHTML = `<div class="empty-state" data-i18n="savings.no_accounts">${t('savings.no_accounts', 'Niciun cont de economii încă.')}</div>`;
        return;
    }
    list.innerHTML = savingsAccounts.map((acc) => {
        const rate = `${(acc.interest_rate_bps / 100).toFixed(1)}% p.a.`;
        const locked = !isSpendable(acc);
        const maturityLabel = acc.product_type === 'term_deposit'
            ? (locked
                ? t('dynamic.savings_locked', 'Locked until {date}', { date: new Date(acc.maturity_date).toLocaleDateString(document.documentElement.lang || 'ro') })
                : t('dynamic.savings_matured', 'Maturity reached ({date}) - you can withdraw', { date: new Date(acc.maturity_date).toLocaleDateString(document.documentElement.lang || 'ro') }))
            : t('dynamic.savings_flexible', 'Flexible - withdraw anytime');
        return `
            <div class="pot-item savings-account-item">
                <div class="pot-header">
                    <span class="pot-icon"><i data-lucide="${acc.product_type === 'term_deposit' ? 'lock' : 'piggy-bank'}"></i></span>
                    <div class="pot-name">${escapeHTML(acc.name)}</div>
                    <div class="pot-amounts" data-account-id="${escapeHTML(acc.id)}">${formatMoney(acc.balance_minor, acc.currency)} &middot; ${rate}</div>
                </div>
                <div class="savings-account-maturity ${locked ? 'locked' : ''}">${maturityLabel}</div>
            </div>
        `;
    }).join('');
    list.querySelectorAll('.pot-amounts').forEach((el) => {
        const acc = savingsAccounts.find((a) => a.id === el.dataset.accountId);
        if (!acc) return;
        const rate = `${(acc.interest_rate_bps / 100).toFixed(1)}% p.a.`;
        animateBalanceFor(`savings:${acc.id}`, el, acc.balance_minor, acc.currency, {
            format: (amount) => `${formatMoney(amount, acc.currency)} · ${rate}`,
        });
    });
    if (window.lucide) lucide.createIcons();
}

/* --- Transfer modal --- */

function wireTransferModal() {
    const modal = document.getElementById('transfer-modal');
    const form = document.getElementById('transfer-form');
    const errorEl = document.getElementById('transfer-error');
    const fromSelect = document.getElementById('transfer-from');

    document.getElementById('open-transfer-btn').addEventListener('click', () => {
        errorEl.hidden = true;
        form.reset();
        populateTransferAccountSelects();
        modal.hidden = false;
    });
    document.getElementById('close-transfer-modal').addEventListener('click', () => { modal.hidden = true; });
    document.getElementById('cancel-transfer').addEventListener('click', () => { modal.hidden = true; });

    fromSelect.addEventListener('change', () => populateTransferToOptions());

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        errorEl.hidden = true;

        const fromAccount = currentAccounts.find(a => a.id === fromSelect.value);
        const amountMajor = parseFloat(document.getElementById('transfer-amount').value);
        if (!fromAccount || !Number.isFinite(amountMajor) || amountMajor <= 0) {
            errorEl.textContent = t('savings.required_fields', 'Completează toate câmpurile obligatorii.');
            errorEl.hidden = false;
            return;
        }

        const idempotencyKey = crypto.randomUUID();
        const body = JSON.stringify({
            from_account_id: fromSelect.value,
            to_account_id: document.getElementById('transfer-to').value,
            amount_minor: Math.round(amountMajor * 100),
            currency: fromAccount.currency,
            description: document.getElementById('transfer-description').value || undefined,
        });

        try {
            const result = await submitWithFaceConfirmation('/transfers', idempotencyKey, body);
            if (result === CONFIRMATION_CANCELLED) return; // user closed the camera modal - stay put, silently
            modal.hidden = true;
            await refreshDashboard();
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.hidden = false;
        }
    });
}

/* --- Scheduled/recurring transfers --- */

const SCHEDULED_TRANSFER_FREQUENCY_KEYS = { weekly: 'dynamic.scheduled_weekly', monthly: 'dynamic.scheduled_monthly' };
const SCHEDULED_TRANSFER_STATUS_KEYS = { active: 'dynamic.status_active', paused: 'dynamic.status_paused', cancelled: 'dynamic.status_cancelled', completed: 'dynamic.status_completed' };

function populateScheduledTransferAccountSelects() {
    const fromSelect = document.getElementById('scheduled-transfer-from');
    if (!fromSelect) return;
    const spendable = currentAccounts.filter(isSpendable);
    fromSelect.innerHTML = spendable.map(acc =>
        `<option value="${acc.id}">${escapeHTML(acc.name)} (${acc.currency})</option>`
    ).join('');
    populateScheduledTransferToOptions();
}

function populateScheduledTransferToOptions() {
    const fromSelect = document.getElementById('scheduled-transfer-from');
    const toSelect = document.getElementById('scheduled-transfer-to');
    if (!fromSelect || !toSelect) return;
    const active = currentAccounts.filter(a => a.status === 'active');
    const fromCurrency = active.find(a => a.id === fromSelect.value)?.currency;
    const eligible = active.filter(a => a.id !== fromSelect.value && a.currency === fromCurrency);
    toSelect.innerHTML = eligible.length
        ? eligible.map(acc => `<option value="${acc.id}">${escapeHTML(acc.name)} (${acc.currency})</option>`).join('')
        : `<option value="" disabled selected>${escapeHTML(t('savings.no_other_account_same_currency', 'Niciun alt cont în aceeași monedă'))}</option>`;
}

function wireScheduledTransfersModal() {
    const modal = document.getElementById('scheduled-transfer-modal');
    const form = document.getElementById('scheduled-transfer-form');
    const errorEl = document.getElementById('scheduled-transfer-error');
    const fromSelect = document.getElementById('scheduled-transfer-from');
    if (!modal || !form) return;

    document.getElementById('open-scheduled-transfer-btn').addEventListener('click', () => {
        errorEl.hidden = true;
        form.reset();
        populateScheduledTransferAccountSelects();
        modal.hidden = false;
    });
    document.getElementById('close-scheduled-transfer-modal').addEventListener('click', () => { modal.hidden = true; });
    document.getElementById('cancel-scheduled-transfer').addEventListener('click', () => { modal.hidden = true; });

    fromSelect.addEventListener('change', () => populateScheduledTransferToOptions());

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        errorEl.hidden = true;

        const fromAccount = currentAccounts.find(a => a.id === fromSelect.value);
        const amountMajor = parseFloat(document.getElementById('scheduled-transfer-amount').value);
        if (!fromAccount || !Number.isFinite(amountMajor) || amountMajor <= 0) {
            errorEl.textContent = t('savings.required_fields', 'Completează toate câmpurile obligatorii.');
            errorEl.hidden = false;
            return;
        }

        const frequency = document.getElementById('scheduled-transfer-frequency').value || null;
        const startInDays = parseInt(document.getElementById('scheduled-transfer-start-days').value, 10) || 0;

        try {
            await apiFetch('/scheduled-transfers', {
                method: 'POST',
                body: JSON.stringify({
                    from_account_id: fromSelect.value,
                    to_account_id: document.getElementById('scheduled-transfer-to').value,
                    amount_minor: Math.round(amountMajor * 100),
                    currency: fromAccount.currency,
                    frequency,
                    start_at: new Date(Date.now() + startInDays * 86400000).toISOString(),
                    description: document.getElementById('scheduled-transfer-description').value || undefined,
                }),
            });
            modal.hidden = true;
            await loadScheduledTransfers();
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.hidden = false;
        }
    });
}

async function loadScheduledTransfers() {
    const list = document.getElementById('scheduled-transfers-list');
    if (!list) return;
    try {
        const scheduled = await apiFetch('/scheduled-transfers');
        renderScheduledTransfersList(scheduled);
    } catch (err) {
        list.innerHTML = `<div class="empty-state">${escapeHTML(t('dynamic.load_scheduled_error', 'Nu s-au putut încărca transferurile programate: {message}', { message: err.message }))}</div>`;
    }
}

function renderScheduledTransfersList(scheduled) {
    const list = document.getElementById('scheduled-transfers-list');
    if (scheduled.length === 0) {
        list.innerHTML = `<div class="empty-state">${escapeHTML(t('dynamic.no_scheduled_transfers', 'Niciun transfer programat.'))}</div>`;
        return;
    }
    list.innerHTML = scheduled.map(s => {
        const fromAccount = currentAccounts.find(a => a.id === s.from_account_id);
        const toAccount = currentAccounts.find(a => a.id === s.to_account_id);
        const freqLabel = s.frequency
            ? t(SCHEDULED_TRANSFER_FREQUENCY_KEYS[s.frequency], s.frequency)
            : t('dynamic.scheduled_once', 'Once');
        const canAct = s.status === 'active' || s.status === 'paused';
        return `
        <div class="scheduled-transfer-item">
            <div>
                <div class="name">${escapeHTML(fromAccount ? fromAccount.name : '?')} → ${escapeHTML(toAccount ? toAccount.name : '?')}</div>
                <div class="meta">${formatMoney(s.amount_minor, s.currency)} &middot; ${freqLabel} &middot; ${SCHEDULED_TRANSFER_STATUS_KEYS[s.status] ? t(SCHEDULED_TRANSFER_STATUS_KEYS[s.status], s.status) : escapeHTML(s.status)}</div>
                ${s.last_error ? `<div class="meta scheduled-transfer-error-note">${escapeHTML(s.last_error)}</div>` : ''}
            </div>
            ${canAct ? `
                <div class="scheduled-transfer-actions">
                    ${s.status === 'active'
                        ? `<button class="link-btn" data-id="${s.id}" data-action="pause">${t('dynamic.scheduled_pause', 'Pause')}</button>`
                        : `<button class="link-btn" data-id="${s.id}" data-action="resume">${t('dynamic.scheduled_resume', 'Resume')}</button>`
                    }
                    <button class="link-btn" data-id="${s.id}" data-action="cancel">${t('common.Anulează', 'Cancel')}</button>
                </div>
            ` : ''}
        </div>
        `;
    }).join('');

    list.querySelectorAll('button[data-action]').forEach(btn => {
        btn.addEventListener('click', async () => {
            try {
                await apiFetch(`/scheduled-transfers/${btn.dataset.id}/${btn.dataset.action}`, { method: 'POST' });
                await loadScheduledTransfers();
            } catch (err) {
                alert(err.message);
            }
        });
    });
}

// Sentinel returned by submitWithFaceConfirmation when the user cancels the
// face-confirm modal - distinguishes "cancelled, do nothing" from a real
// response, without resorting to throwing a non-Error value.
const CONFIRMATION_CANCELLED = Symbol('confirmation-cancelled');

/** Shared by the transfer and payment forms: submits a money-moving POST,
 * and if the backend rejects it with 428 (amount over the face-confirmation
 * threshold - see backend/app/modules/face_auth), opens the camera modal,
 * gets a confirmation token, and retries once with it attached. Reuses the
 * same Idempotency-Key on the retry - it's the same request, just proven. */
async function submitWithFaceConfirmation(path, idempotencyKey, body) {
    try {
        return await apiFetch(path, {
            method: 'POST',
            headers: { 'Idempotency-Key': idempotencyKey },
            body,
        });
    } catch (err) {
        // Distinct from a plain 428: there is no token this user could
        // possibly supply (Face ID was never enrolled at all), so the fix
        // is "go enroll it", not "retry the camera".
        if (err.code === 'face_enrollment_required') {
            // The backend's own message is an English default (same as
            // FaceConfirmationRequiredError) - use the Romanian one here
            // instead, matching the rest of this flow.
            promptFaceEnrollmentRequired(
                'Această plată necesită Face ID activat, pentru că e prima ta plată către această persoană sau depășește pragul de siguranță.'
            );
            return CONFIRMATION_CANCELLED;
        }
        if (err.status !== 428) throw err;

        const token = await requestFaceConfirmationToken();
        if (!token) return CONFIRMATION_CANCELLED;

        return await apiFetch(path, {
            method: 'POST',
            headers: { 'Idempotency-Key': idempotencyKey, 'X-Face-Confirmation': token },
            body,
        });
    }
}

/** Shown when a mandatory Face ID action (see face_auth/service.py::
 * enforce_face_confirmation - a large transfer, a first payment to someone
 * new) hits a user with no Face ID enrolled at all: there is no token they
 * could supply, so the fix is "go enroll it", not "retry". Navigates
 * straight to the Face Login settings view once acknowledged. */
function promptFaceEnrollmentRequired(message) {
    alert(message || 'Această acțiune necesită Face ID activat. Te redirecționăm către activare.');
    goToProfileView('face-login');
}

/** Payment-only wrapper around submitWithFaceConfirmation: if the backend
 * blocks the payment with 409 subscription_price_increase (see
 * payments/service.py::_detect_subscription_price_increase), asks the user
 * whether to continue anyway - mentioning the merchant's cancel URL if one
 * was saved on that contact - and retries once with confirm_price_increase
 * set, which can itself still hit the face-confirmation step above. */
async function submitPayment(idempotencyKey, bodyObj) {
    try {
        return await submitWithFaceConfirmation('/payments', idempotencyKey, JSON.stringify(bodyObj));
    } catch (err) {
        if (err.status !== 409 || err.code !== 'subscription_price_increase') throw err;

        const wantsToContinue = await showPriceIncreaseModal(err.details || {});
        if (!wantsToContinue) return CONFIRMATION_CANCELLED;

        bodyObj.confirm_price_increase = true;
        return await submitWithFaceConfirmation('/payments', idempotencyKey, JSON.stringify(bodyObj));
    }
}

/** In-app replacement for window.confirm() when a payment is blocked as a
 * likely subscription price hike - resolves true ("Continuă oricum") or
 * false (cancel/close), never rejects. */
function showPriceIncreaseModal(details) {
    return new Promise((resolve) => {
        const modal = document.getElementById('price-increase-modal');
        const merchantEl = document.getElementById('price-increase-merchant');
        const oldEl = document.getElementById('price-increase-old');
        const newEl = document.getElementById('price-increase-new');
        const websiteLink = document.getElementById('price-increase-website-link');
        const confirmBtn = document.getElementById('price-increase-confirm');
        const cancelBtn = document.getElementById('price-increase-cancel');

        merchantEl.textContent = details.beneficiary_name || t('price_increase.default_merchant', 'Acest abonament');
        oldEl.textContent = formatMoney(details.previous_amount_minor, details.currency);
        newEl.textContent = formatMoney(details.new_amount_minor, details.currency);

        if (details.website) {
            websiteLink.href = details.website;
            websiteLink.hidden = false;
        } else {
            websiteLink.hidden = true;
        }

        modal.hidden = false;
        if (window.lucide) lucide.createIcons();

        function cleanup(result) {
            modal.hidden = true;
            confirmBtn.onclick = null;
            cancelBtn.onclick = null;
            resolve(result);
        }

        confirmBtn.onclick = () => cleanup(true);
        cancelBtn.onclick = () => cleanup(false);
    });
}

function faceConfirmDefaultReason() {
    return t('face_confirm.default_reason', 'Suma depășește pragul de confirmare - verifică-ți identitatea prin cameră.');
}

/** Opens the face-confirm modal, captures a photo, exchanges it for a
 * short-lived confirmation token via POST /auth/face/confirm. Resolves with
 * the token, or null if the user cancels. Never rejects - camera/API errors
 * show inline in the modal and let the user retry or cancel. `reason`
 * overrides the modal's explanatory text for callers other than the
 * large-transfer step-up this was originally built for. */
function requestFaceConfirmationToken(reason = faceConfirmDefaultReason()) {
    return new Promise((resolve) => {
        const modal = document.getElementById('face-confirm-modal');
        const video = document.getElementById('face-confirm-video');
        const canvas = document.getElementById('face-confirm-canvas');
        const errorEl = document.getElementById('face-confirm-error');
        const captureBtn = document.getElementById('capture-face-confirm');
        const cancelBtn = document.getElementById('cancel-face-confirm');
        const closeBtn = document.getElementById('close-face-confirm-modal');

        let stream = null;
        errorEl.hidden = true;
        document.getElementById('face-confirm-reason').textContent = reason;
        modal.hidden = false;

        function cleanup(result) {
            if (stream) stream.getTracks().forEach(track => track.stop());
            stream = null;
            video.srcObject = null;
            modal.hidden = true;
            setFaceFlashlight(false, modal);
            captureBtn.onclick = null;
            cancelBtn.onclick = null;
            closeBtn.onclick = null;
            resolve(result);
        }

        navigator.mediaDevices.getUserMedia({ video: true })
            .then((s) => { stream = s; video.srcObject = s; setFaceFlashlight(true, modal); })
            .catch(() => {
                errorEl.textContent = t('face_confirm.camera_error', 'Nu s-a putut accesa camera. Verifică permisiunile browserului.');
                errorEl.hidden = false;
            });

        captureBtn.onclick = () => {
            errorEl.hidden = true;
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            canvas.getContext('2d').drawImage(video, 0, 0);

            canvas.toBlob(async (blob) => {
                const formData = new FormData();
                formData.append('file', blob, 'confirm.jpg');
                try {
                    const res = await fetch(`${API_BASE_URL}/auth/face/confirm`, {
                        method: 'POST',
                        credentials: 'include',
                        body: formData,
                    });
                    if (!res.ok) {
                        const errBody = await res.json().catch(() => ({}));
                        throw new Error(errBody?.error?.message || `Request failed (${res.status})`);
                    }
                    const { token } = await res.json();
                    cleanup(token);
                } catch (err) {
                    errorEl.textContent = err.message;
                    errorEl.hidden = false;
                }
            }, 'image/jpeg', 0.92);
        };

        cancelBtn.onclick = () => cleanup(null);
        closeBtn.onclick = () => cleanup(null);
    });
}

function populateTransferAccountSelects() {
    const fromSelect = document.getElementById('transfer-from');
    if (!fromSelect) return;
    const spendable = currentAccounts.filter(isSpendable);
    fromSelect.innerHTML = spendable.map(acc =>
        `<option value="${acc.id}">${escapeHTML(acc.name)} (${acc.currency})</option>`
    ).join('');
    populateTransferToOptions();
}

function populateTransferToOptions() {
    const fromSelect = document.getElementById('transfer-from');
    const toSelect = document.getElementById('transfer-to');
    if (!fromSelect || !toSelect) return;
    const active = currentAccounts.filter(a => a.status === 'active');
    // Only offer accounts sharing the "from" account's currency - a transfer
    // needs both sides to match (see backend/docs/AUTH_HANDOFF.md's sibling,
    // frontend/README.md, for the /transfers contract).
    const fromCurrency = active.find(a => a.id === fromSelect.value)?.currency;
    const eligible = active.filter(a => a.id !== fromSelect.value && a.currency === fromCurrency);
    toSelect.innerHTML = eligible.length
        ? eligible.map(acc => `<option value="${acc.id}">${escapeHTML(acc.name)} (${acc.currency})</option>`).join('')
        : `<option value="" disabled selected>${escapeHTML(t('savings.no_other_account_same_currency', 'Niciun alt cont în aceeași monedă'))}</option>`;
}

/* --- Cards --- */

const CARD_STATUS_LABELS = { active: 'Activ', frozen: 'Blocat', cancelled: 'Anulat' };
let loadedCards = [];

/** Shows or re-masks a card's expiry/CVV and flips the eye icon to match.
 * Split out of the eye button's click handler so the Face ID gate above it
 * can decide WHETHER to reveal before this actually does it. */
function applyCardSecretsVisibility(card, btn, revealing) {
    const secrets = card.querySelectorAll('.card-secret');
    secrets.forEach(el => { el.textContent = revealing ? el.dataset.value : (el.dataset.reveal === 'cvv' ? '•••' : '••/••'); });
    btn.innerHTML = `<i data-lucide="${revealing ? 'eye-off' : 'eye'}"></i>`;
    const hintKey = revealing ? 'cards.hide_details' : 'cards.show_details';
    btn.title = t(hintKey, revealing ? 'Hide expiry and CVV' : 'Show expiry and CVV');
    btn.setAttribute('aria-label', btn.title);
    if (window.lucide) lucide.createIcons();
}

async function loadCards() {
    const list = document.getElementById('cards-list');
    if (!list) return;
    try {
        const cards = await apiFetch('/cards');
        currentCards = cards;
        loadedCards = cards;
        renderCardsList(cards);
    } catch (err) {
        list.innerHTML = `<div class="empty-state">${escapeHTML(t('errors.generic', 'Could not load cards'))}: ${escapeHTML(err.message)}</div>`;
    }
}

function renderCardsList(cards) {
    const list = document.getElementById('cards-list');
    if (cards.length === 0) {
        list.innerHTML = `<div class="empty-state">${t('cards.empty', 'Niciun card încă. Generează primul card virtual.')}</div>`;
        return;
    }

    // A cancelled card never comes back to life (see the confirm() prompt
    // below) - showing it grayed out forever is just clutter, so once it's
    // cancelled it drops out of view entirely, same as if it were deleted.
    // The backend still soft-cancels (status='cancelled', row + audit trail
    // kept) rather than actually dropping the row - this filter is purely
    // what the user sees.
    const visibleCards = cards.filter(c => c.status !== 'cancelled');
    if (visibleCards.length === 0) {
        list.innerHTML = `<div class="empty-state">${t('cards.empty', 'Niciun card încă. Generează primul card virtual.')}</div>`;
        return;
    }

    const accountById = Object.fromEntries(currentAccounts.map(a => [a.id, a]));

    list.innerHTML = visibleCards.map(card => {
        const account = accountById[card.account_id];
        const formattedNumber = card.card_number.replace(/(.{4})/g, '$1 ').trim();
        const expiry = `${String(card.expiry_month).padStart(2, '0')}/${String(card.expiry_year).slice(-2)}`;
        return `
        <div class="credit-card virtual">
            <div class="card-header">
                <span class="card-type">${t('cards.label', 'Card')}${account ? ' &middot; ' + escapeHTML(account.name) : ''}</span>
                <span class="card-logo">VISA</span>
            </div>
            <div class="card-number">${escapeHTML(formattedNumber)}</div>
            <div class="card-footer">
                <div class="card-details">
                    <div class="detail">
                        <span class="label">${t('cards.expiry', 'Expiră')}</span>
                        <span class="card-secret" data-reveal="expiry" data-value="${escapeHTML(expiry)}">••/••</span>
                    </div>
                    <div class="detail">
                        <span class="label">${t('cards.cvv', 'CVV')}</span>
                        <span class="card-secret" data-reveal="cvv" data-value="${escapeHTML(card.cvv)}">•••</span>
                    </div>
                    ${card.spending_limit_minor != null ? `
                        <div class="detail">
                            <span class="label">${t('cards.limit', 'Limită')}</span>
                            <span>${formatMoney(card.spending_limit_minor, account ? account.currency : 'RON')}</span>
                        </div>
                    ` : ''}
                    <button class="card-eye-btn" title="${t('cards.show_details', 'Arată expirarea și CVV')}" aria-label="${t('cards.show_details', 'Arată expirarea și CVV')}"><i data-lucide="eye"></i></button>
                </div>
                <button class="status-toggle-btn ${card.status}" data-card-id="${card.id}" data-action="${card.status === 'frozen' ? 'unfreeze' : 'freeze'}" title="${t(card.status === 'frozen' ? 'cards.unfreeze_hint' : 'cards.freeze_hint', card.status === 'frozen' ? 'Apasă pentru a debloca cardul' : 'Apasă pentru a bloca temporar cardul')}">
                    <i data-lucide="${card.status === 'frozen' ? 'snowflake' : 'shield-check'}"></i>
                    <span>${t(`cards.status_${card.status}`, CARD_STATUS_LABELS[card.status] || card.status)}</span>
                </button>
            </div>
            <div class="card-actions-row">
                <button class="card-limit-btn" data-card-id="${card.id}" data-current-limit="${card.spending_limit_minor ?? ''}" title="${t('cards.limit_hint', 'Setează limita de cheltuieli')}">
                    <i data-lucide="sliders-horizontal"></i>
                    <span>${t('cards.limit', 'Limită')}</span>
                </button>
                <button class="card-cancel-btn" data-card-id="${card.id}" title="${t('cards.cancel_hint', 'Anulează definitiv cardul')}">
                    <i data-lucide="trash-2"></i>
                    <span>${t('cards.cancel', 'Anulează')}</span>
                </button>
            </div>
        </div>
        `;
    }).join('');

    if (window.lucide) lucide.createIcons();

    list.querySelectorAll('.card-eye-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const card = btn.closest('.credit-card');
            const secrets = card.querySelectorAll('.card-secret');
            const revealing = secrets[0].textContent !== secrets[0].dataset.value;
            // Hiding back to masked never needs a fresh proof of identity -
            // only revealing the real expiry/CVV does. Face ID is mandatory
            // for this, not an optional extra: a user who hasn't enrolled it
            // gets sent to set it up instead of seeing the card.
            if (revealing) {
                let faceEnrolled = false;
                try {
                    faceEnrolled = (await apiFetch('/auth/face/status')).enrolled;
                } catch (err) {
                    alert('Nu am putut verifica starea Face ID. Încearcă din nou.');
                    return;
                }
                if (!faceEnrolled) {
                    promptFaceEnrollmentRequired(
                        'Activează Face ID ca să poți vedea numărul complet și CVV-ul cardului.'
                    );
                    return;
                }
                btn.disabled = true;
                const token = await requestFaceConfirmationToken(
                    'Verifică-ți identitatea prin cameră ca să vezi numărul complet și CVV-ul cardului.'
                );
                btn.disabled = false;
                if (!token) return;
            }

            applyCardSecretsVisibility(card, btn, revealing);
        });
    });

    list.querySelectorAll('.card-cancel-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm(t('cards.cancel_confirm', 'Sigur anulezi acest card? Nu poate fi reactivat.'))) return;
            try {
                await apiFetch(`/cards/${btn.dataset.cardId}`, { method: 'DELETE' });
                await loadCards();
            } catch (err) {
                alert(err.message);
            }
        });
    });

    list.querySelectorAll('.status-toggle-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const path = btn.dataset.action === 'freeze' ? 'freeze' : 'unfreeze';
            btn.disabled = true;
            btn.classList.add('is-toggling');
            try {
                await apiFetch(`/cards/${btn.dataset.cardId}/${path}`, { method: 'POST' });
                await loadCards();
            } catch (err) {
                btn.disabled = false;
                btn.classList.remove('is-toggling');
                alert(err.message);
            }
        });
    });

    list.querySelectorAll('.card-limit-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const currentLimit = btn.dataset.currentLimit
                ? (Number(btn.dataset.currentLimit) / 100).toString()
                : '';
            const input = prompt(
                t('cards.limit_prompt', 'New spending limit (leave blank to remove the limit):'),
                currentLimit
            );
            if (input === null) return;

            const trimmed = input.trim();
            const spendingLimitMinor = trimmed ? Math.round(parseFloat(trimmed) * 100) : null;
            if (trimmed && (!Number.isFinite(spendingLimitMinor) || spendingLimitMinor <= 0)) {
                alert(t('cards.invalid_limit', 'Enter a valid amount greater than 0.'));
                return;
            }

            try {
                await apiFetch(`/cards/${btn.dataset.cardId}/spending-limit`, {
                    method: 'PATCH',
                    body: JSON.stringify({ spending_limit_minor: spendingLimitMinor }),
                });
                await loadCards();
            } catch (err) {
                alert(err.message);
            }
        });
    });
}

function wireNewCardModal() {
    const modal = document.getElementById('new-card-modal');
    const form = document.getElementById('new-card-form');
    const errorEl = document.getElementById('new-card-error');
    const accountSelect = document.getElementById('new-card-account');

    document.getElementById('open-new-card-btn').addEventListener('click', () => {
        errorEl.hidden = true;
        form.reset();
        const active = currentAccounts.filter(a => a.status === 'active');
        accountSelect.innerHTML = active.length
            ? active.map(acc => `<option value="${acc.id}">${escapeHTML(acc.name)} (${acc.currency})</option>`).join('')
            : `<option value="" disabled selected>${escapeHTML(t('card_modal.create_account_first', 'Create an account first'))}</option>`;
        modal.hidden = false;
    });
    document.getElementById('close-new-card-modal').addEventListener('click', () => { modal.hidden = true; });
    document.getElementById('cancel-new-card').addEventListener('click', () => { modal.hidden = true; });

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        errorEl.hidden = true;

        const limitInput = document.getElementById('new-card-limit').value;
        const limitMinor = limitInput ? Math.round(parseFloat(limitInput) * 100) : null;

        try {
            await apiFetch('/cards', {
                method: 'POST',
                body: JSON.stringify({
                    account_id: accountSelect.value,
                    spending_limit_minor: limitMinor,
                }),
            });
            modal.hidden = true;
            await loadCards();
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.hidden = false;
        }
    });
}

function wireCardOrderModal() {
    const modal = document.getElementById('card-order-modal');
    const form = document.getElementById('card-order-form');
    const errorEl = document.getElementById('card-order-error');
    const accountSelect = document.getElementById('card-order-account');
    const cardChoiceSelect = document.getElementById('card-order-card-choice');
    const cardHint = document.getElementById('card-order-card-hint');

    // Cards that already have a physical order can't be offered again (see
    // the backend's matching guard in card_orders/service.py) - fetched
    // once when the modal opens, alongside the account list.
    let orderedCardIds = new Set();

    function updateCardChoices() {
        const eligible = currentCards.filter(c =>
            c.account_id === accountSelect.value &&
            c.status !== 'cancelled' &&
            !orderedCardIds.has(c.id)
        );

        cardChoiceSelect.innerHTML = [
            '<option value="">Card nou (emite un card separat)</option>',
            ...eligible.map(c =>
                `<option value="${c.id}">Fă fizic cardul virtual care se termină în ${c.last4}</option>`
            ),
        ].join('');

        // Exactly one eligible virtual card on this account - that's almost
        // certainly what "order a physical card" means here, so default to
        // reusing it instead of silently minting an unrelated second card.
        if (eligible.length === 1) {
            cardChoiceSelect.value = eligible[0].id;
        }

        cardHint.hidden = eligible.length === 0;
        cardHint.textContent = eligible.length === 0 ? '' :
            'Poți transforma un card virtual existent în fizic (păstrează același număr) sau comanda unul nou.';
    }

    document.getElementById('open-card-order-btn').addEventListener('click', async () => {
        errorEl.hidden = true;
        form.reset();
        const countryInput = document.getElementById('card-order-country');
        countryInput.value = t('card_modal.default_country', 'Romania');
        countryInput.dataset.currentDefault = countryInput.value;
        const active = currentAccounts.filter(a => a.status === 'active');
        accountSelect.innerHTML = active.length
            ? active.map(acc => `<option value="${acc.id}">${escapeHTML(acc.name)} (${acc.currency})</option>`).join('')
            : `<option value="" disabled selected>${escapeHTML(t('card_modal.create_account_first', 'Create an account first'))}</option>`;

        try {
            const orders = await apiFetch('/card-orders');
            orderedCardIds = new Set(orders.map(o => o.card_id).filter(Boolean));
        } catch (err) {
            orderedCardIds = new Set();
        }

        updateCardChoices();
        modal.hidden = false;
    });
    accountSelect.addEventListener('change', updateCardChoices);

    document.getElementById('close-card-order-modal').addEventListener('click', () => { modal.hidden = true; });
    document.getElementById('cancel-card-order').addEventListener('click', () => { modal.hidden = true; });

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        errorEl.hidden = true;

        try {
            const order = await apiFetch('/card-orders', {
                method: 'POST',
                body: JSON.stringify({
                    account_id: accountSelect.value,
                    card_id: cardChoiceSelect.value || null,
                    full_name: document.getElementById('card-order-name').value,
                    phone: document.getElementById('card-order-phone').value,
                    address: document.getElementById('card-order-address').value,
                    city: document.getElementById('card-order-city').value,
                    postal_code: document.getElementById('card-order-postal').value,
                    country: document.getElementById('card-order-country').value,
                }),
            });
            modal.hidden = true;
            const formattedNumber = order.card.card_number.replace(/(.{4})/g, '$1 ').trim();
            alert(t('card_modal.order_success', 'Comanda a fost trimisă! Cardul tău: {number}', { number: formattedNumber }));
            await loadCards();
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.hidden = false;
        }
    });
}

/* --- Payments (IBAN-to-IBAN, cross-user) --- */

function populatePaymentsAccountSelect() {
    const select = document.getElementById('payments-account');
    if (!select) return;
    const spendable = currentAccounts.filter(isSpendable);
    const previousValue = select.value;
    select.innerHTML = spendable.length
        ? spendable.map(acc => `<option value="${acc.id}">${escapeHTML(acc.name)} (${acc.currency})</option>`).join('')
        : `<option value="" disabled selected>${escapeHTML(t('payments.no_account_create_first', 'Creează mai întâi un cont'))}</option>`;
    if (spendable.some(a => a.id === previousValue)) select.value = previousValue;
    updateMyIbanDisplay();
}

function updateMyIbanDisplay() {
    const select = document.getElementById('payments-account');
    const iban = document.getElementById('payments-my-iban');
    if (!select || !iban) return;
    const account = currentAccounts.find(a => a.id === select.value);
    iban.textContent = account ? account.iban : '—';
}

async function loadBeneficiaries() {
    const list = document.getElementById('beneficiaries-list');
    if (!list) return;
    try {
        const contacts = await apiFetch('/beneficiaries');
        renderBeneficiariesList(contacts);
    } catch (err) {
        list.innerHTML = `<div class="empty-state">${t('payments.contacts_load_error')}: ${escapeHTML(err.message)}</div>`;
    }
}

function renderBeneficiariesList(contacts) {
    const list = document.getElementById('beneficiaries-list');
    if (contacts.length === 0) {
        list.innerHTML = `<div class="empty-state" data-i18n="payments.no_contacts">${t('payments.no_contacts')}</div>`;
        return;
    }
    list.innerHTML = contacts.map(c => `
        <div class="contact-item" data-id="${c.id}" data-iban="${escapeHTML(c.iban)}" data-name="${escapeHTML(c.display_name)}">
            <div class="contact-item-fill">
                <div class="name">${escapeHTML(c.display_name)}${c.is_subscription ? ` <span class="contact-subscription-badge" data-i18n="payments.subscription_badge">${t('payments.subscription_badge', 'Abonament')}</span>` : ''}</div>
                <div class="iban">${escapeHTML(c.iban)}</div>
                ${c.website ? `<a class="contact-website" href="${escapeHTML(c.website)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">${escapeHTML(c.website)}</a>` : ''}
            </div>
            <button type="button" class="contact-remove-btn" data-id="${c.id}" title="${escapeHTML(t('payments.remove_contact_title', 'Șterge contactul'))}" aria-label="${escapeHTML(t('payments.remove_contact_title', 'Șterge contactul'))}"><i data-lucide="x"></i></button>
            <i data-lucide="chevron-right" class="icon"></i>
        </div>
    `).join('');
    if (window.lucide) lucide.createIcons();

    list.querySelectorAll('.contact-item-fill').forEach(el => {
        el.addEventListener('click', () => {
            const item = el.closest('.contact-item');
            document.getElementById('payments-iban').value = item.dataset.iban;
            document.getElementById('payments-beneficiary').value = item.dataset.name;
        });
    });

    list.querySelectorAll('.contact-remove-btn').forEach(btn => {
        btn.addEventListener('click', async (event) => {
            event.stopPropagation();
            if (!confirm(t('payments.remove_contact_confirm', 'Ștergi acest contact salvat?'))) return;
            try {
                await apiFetch(`/beneficiaries/${btn.dataset.id}`, { method: 'DELETE' });
                await loadBeneficiaries();
            } catch (err) {
                alert(err.message);
            }
        });
    });
}

function wireAddBeneficiaryForm() {
    const toggleBtn = document.getElementById('add-beneficiary-btn');
    const form = document.getElementById('add-beneficiary-form');
    const errorEl = document.getElementById('add-beneficiary-error');
    if (!toggleBtn || !form) return;

    toggleBtn.addEventListener('click', () => {
        form.hidden = !form.hidden;
        errorEl.hidden = true;
        if (!form.hidden) document.getElementById('add-beneficiary-name').focus();
    });

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        errorEl.hidden = true;
        try {
            await apiFetch('/beneficiaries', {
                method: 'POST',
                body: JSON.stringify({
                    display_name: document.getElementById('add-beneficiary-name').value,
                    iban: document.getElementById('add-beneficiary-iban').value.replace(/\s+/g, '').toUpperCase(),
                    website: document.getElementById('add-beneficiary-website').value || undefined,
                    is_subscription: document.getElementById('add-beneficiary-is-subscription').checked,
                }),
            });
            form.reset();
            form.hidden = true;
            await loadBeneficiaries();
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.hidden = false;
        }
    });
}

async function loadPayments() {
    const list = document.getElementById('payments-list');
    if (!list) return;
    try {
        const payments = await apiFetch('/payments');
        renderPaymentsList(payments);
    } catch (err) {
        list.innerHTML = `<div class="empty-state">${t('payments.history_load_error')}: ${escapeHTML(err.message)}</div>`;
    }
}

function renderPaymentsList(payments) {
    const list = document.getElementById('payments-list');
    if (payments.length === 0) {
        list.innerHTML = `<div class="empty-state" data-i18n="payments.no_payments">${t('payments.no_payments')}</div>`;
        return;
    }
    list.innerHTML = payments.map(p => `
        <div class="payment-item">
            <div>
                <div class="name">${escapeHTML(p.to_iban)}</div>
                <div class="meta">${formatDateTime(p.created_at)}</div>
            </div>
            <div class="amount">${escapeHTML(t('dynamic.payment_amount', '-'))}${formatMoney(p.amount_minor, p.currency)}</div>
        </div>
    `).join('');
}

function wirePaymentsForm() {
    const form = document.getElementById('payments-form');
    const errorEl = document.getElementById('payments-error');
    const successEl = document.getElementById('payments-success');
    const accountSelect = document.getElementById('payments-account');
    const ibanInput = document.getElementById('payments-iban');
    const ibanHolderEl = document.getElementById('payments-iban-holder');
    const beneficiaryInput = document.getElementById('payments-beneficiary');
    const saveBeneficiaryCheckbox = document.getElementById('payments-save-beneficiary');
    const ibanScanBtn = document.getElementById('iban-scan-btn');
    const ibanScanInput = document.getElementById('iban-scan-input');
    const ibanScanStatus = document.getElementById('iban-scan-status');

    accountSelect.addEventListener('change', updateMyIbanDisplay);

    // Scan a photo (card, invoice, screenshot) instead of typing/pasting
    // the IBAN - see backend/app/modules/iban_ocr.
    ibanScanBtn.addEventListener('click', () => ibanScanInput.click());
    ibanScanInput.addEventListener('change', async () => {
        const file = ibanScanInput.files[0];
        if (!file) return;

        ibanScanStatus.hidden = false;
        ibanScanStatus.className = 'field-hint';
        ibanScanStatus.textContent = t('common.reading_file', 'Se citește fișierul...');

        const formData = new FormData();
        formData.append('file', file);
        try {
            const res = await fetch(`${API_BASE_URL}/iban-ocr/extract`, {
                method: 'POST',
                credentials: 'include',
                body: formData,
            });
            if (!res.ok) {
                const body = await res.json().catch(() => ({}));
                throw new Error(body?.error?.message || `Request failed (${res.status})`);
            }
            const result = await res.json();
            if (result.iban && !result.low_confidence) {
                ibanInput.value = result.iban;
                ibanInput.dispatchEvent(new Event('input'));
                ibanScanStatus.className = 'field-hint ocr-success';
                ibanScanStatus.textContent = t('payments.iban_read', 'IBAN citit: {iban}', { iban: result.iban });
            } else {
                ibanScanStatus.className = 'field-hint ocr-warning';
                ibanScanStatus.textContent = t('payments.iban_not_found_scan', 'Nu am găsit un IBAN clar în fișier - introdu-l manual.');
            }
        } catch (err) {
            ibanScanStatus.className = 'field-hint ocr-warning';
            ibanScanStatus.textContent = err.message;
        } finally {
            ibanScanInput.value = '';
        }
    });

    // Live IBAN -> holder name lookup, like a real bank's payee-name check
    // before you send money. Debounced so it doesn't fire on every keystroke.
    let ibanLookupTimer = null;
    ibanInput.addEventListener('input', () => {
        clearTimeout(ibanLookupTimer);
        ibanHolderEl.textContent = '';
        const iban = ibanInput.value.replace(/\s+/g, '').toUpperCase();
        if (iban.length < 15) return;

        ibanLookupTimer = setTimeout(async () => {
            try {
                const holder = await apiFetch(`/accounts/by-iban/${encodeURIComponent(iban)}`);
                ibanHolderEl.textContent = `${t('payments.account_holder')}: ${holder.first_name} ${holder.last_name}`;
                if (!beneficiaryInput.value) {
                    beneficiaryInput.value = `${holder.first_name} ${holder.last_name}`;
                }
            } catch {
                ibanHolderEl.textContent = t('payments.iban_not_found');
            }
        }, 400);
    });

    document.getElementById('copy-my-iban-btn').addEventListener('click', async () => {
        const iban = document.getElementById('payments-my-iban').textContent;
        if (!iban || iban === '—') return;
        try {
            await navigator.clipboard.writeText(iban);
        } catch {
            // Clipboard API can be unavailable (e.g. insecure context) - not critical.
        }
    });

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        errorEl.hidden = true;
        successEl.hidden = true;

        const amountInput = document.getElementById('payments-amount').value;
        const amountMinor = Math.round(parseFloat(amountInput) * 100);
        const iban = document.getElementById('payments-iban').value.replace(/\s+/g, '').toUpperCase();

        const idempotencyKey = crypto.randomUUID();
        const bodyObj = {
            from_account_id: accountSelect.value,
            to_iban: iban,
            beneficiary_name: document.getElementById('payments-beneficiary').value,
            amount_minor: amountMinor,
            description: document.getElementById('payments-description').value || undefined,
            save_beneficiary: saveBeneficiaryCheckbox.checked,
        };

        try {
            const result = await submitPayment(idempotencyKey, bodyObj);
            if (result === CONFIRMATION_CANCELLED) return; // user closed the camera modal - stay put, silently
            successEl.textContent = t('payments.sent_success');
            successEl.hidden = false;
            form.reset();
            ibanHolderEl.textContent = '';
            await refreshDashboard();
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.hidden = false;
        }
    });
}

/* --- Profile view (bank-themed emoji avatar picker) --- */

const EMOJI_AVATAR_OPTIONS = [
    '🏦', '💰', '💳', '💵', '💴', '💶', '💷', '🪙', '📈', '📉',
    '💹', '🔒', '🔐', '🛡️', '👛', '💎', '🧾', '🐷', '🤑', '🏧',
];

function avatarStorageKey(user) {
    return `bank_avatar_emoji:${user.id}`;
}

function applyAvatar(user) {
    const avatarEl = document.getElementById('user-avatar');
    const emoji = localStorage.getItem(avatarStorageKey(user));
    if (emoji) {
        avatarEl.classList.add('avatar-emoji');
        avatarEl.textContent = emoji;
    } else {
        avatarEl.classList.remove('avatar-emoji');
        avatarEl.innerHTML = `<img src="https://ui-avatars.com/api/?name=${encodeURIComponent(user.first_name + ' ' + user.last_name)}&background=2DD4BF&color=fff" alt="">`;
    }
}

/** Sets up the auto-hide profile menu: opens on click of the header
 * name/avatar, closes on an outside click or Escape. Each item redirects to
 * its own dedicated view (view-avatar / view-referral / view-change-password)
 * rather than showing anything inline in the menu itself. */
function wireProfilePanel(user) {
    const panel = document.getElementById('profile-panel');
    const trigger = document.getElementById('user-profile-btn');
    const grid = document.getElementById('emoji-grid');
    const preview = document.getElementById('profile-avatar-preview');

    document.getElementById('profile-panel-name').textContent = `${user.first_name} ${user.last_name}`;
    document.getElementById('profile-panel-email').textContent = user.email;

    grid.innerHTML = EMOJI_AVATAR_OPTIONS.map(emoji =>
        `<button type="button" class="emoji-option" data-emoji="${emoji}">${emoji}</button>`
    ).join('');

    function refreshSelection() {
        const current = localStorage.getItem(avatarStorageKey(user)) || '🏦';
        preview.textContent = current;
        grid.querySelectorAll('.emoji-option').forEach(btn => {
            btn.classList.toggle('selected', btn.dataset.emoji === current);
        });
    }
    refreshSelection();

    grid.querySelectorAll('.emoji-option').forEach(btn => {
        btn.addEventListener('click', () => {
            localStorage.setItem(avatarStorageKey(user), btn.dataset.emoji);
            applyAvatar(user);
            refreshSelection();
        });
    });

    function openPanel() { panel.hidden = false; }
    function closePanel() { panel.hidden = true; }

    trigger.addEventListener('click', (event) => {
        // Stops this same click from immediately reaching the document
        // listener below and closing the panel it just opened.
        event.stopPropagation();
        document.getElementById('notifications-panel').hidden = true;
        if (panel.hidden) openPanel(); else closePanel();
    });
    panel.addEventListener('click', (event) => event.stopPropagation());
    document.addEventListener('click', () => {
        if (!panel.hidden) closePanel();
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !panel.hidden) closePanel();
    });

    panel.querySelectorAll('.profile-menu-item').forEach(btn => {
        btn.addEventListener('click', () => {
            closePanel();
            goToProfileView(btn.dataset.target);
        });
    });

    document.querySelectorAll('.back-to-dashboard-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.view').forEach(view => view.classList.remove('active'));
            document.getElementById('view-dashboard').classList.add('active');
            document.querySelector('.nav-item[data-view="dashboard"]').classList.add('active');
            stopFaceCamera(); // no-op if the camera was never started
            refreshDashboard();
        });
    });

    wireReferralCode();
    wireChangePasswordForm();
    wireFaceLoginPanel();
}

/** Switches to one of the profile menu's own views - not a sidebar nav item,
 * so this deactivates the sidebar explicitly rather than reusing its click
 * handler. */
function goToProfileView(target) {
    document.querySelectorAll('.nav-item').forEach(nav => nav.classList.remove('active'));
    document.querySelectorAll('.view').forEach(view => view.classList.remove('active'));
    document.getElementById(`view-${target}`).classList.add('active');

    if (target === 'referral') loadReferralCode();
    if (target === 'face-login') loadFaceStatus();
    if (target === 'documents-to-sign') loadDocumentsToSign();
}

/* --- Face login enrollment (profile menu section) ---
 * DIY, camera-based - see backend/app/modules/face_auth for the caveat that
 * this is demo-grade biometric auth, not a real security boundary. */

let faceCameraStream = null;

function stopFaceCamera() {
    if (faceCameraStream) {
        faceCameraStream.getTracks().forEach(track => track.stop());
        faceCameraStream = null;
    }
    const video = document.getElementById('face-video');
    if (video) video.srcObject = null;
    document.getElementById('face-start-camera-btn').hidden = false;
    document.getElementById('face-capture-btn').hidden = true;
    setFaceFlashlight(false);
}

let faceStatusEnrolled = null;

function renderFaceStatus(enrolled) {
    const statusText = document.getElementById('face-status-text');
    const removeBtn = document.getElementById('face-remove-btn');
    statusText.textContent = enrolled
        ? t('profile.face_active', 'Face Login e activat pe contul tău.')
        : t('profile.face_inactive', 'Face Login nu e activat încă. Pornește camera și fă o poză ca să-l activezi.');
    removeBtn.hidden = !enrolled;
}

async function loadFaceStatus() {
    try {
        const { enrolled } = await apiFetch('/auth/face/status');
        faceStatusEnrolled = enrolled;
        renderFaceStatus(enrolled);
    } catch (err) {
        document.getElementById('face-status-text').textContent = `${t('profile.face_status_error', 'Nu s-a putut verifica starea')}: ${err.message}`;
    }
}

function wireFaceLoginPanel() {
    const video = document.getElementById('face-video');
    const canvas = document.getElementById('face-canvas');
    const startBtn = document.getElementById('face-start-camera-btn');
    const captureBtn = document.getElementById('face-capture-btn');
    const removeBtn = document.getElementById('face-remove-btn');
    const errorEl = document.getElementById('face-enroll-error');
    const successEl = document.getElementById('face-enroll-success');

    startBtn.addEventListener('click', async () => {
        errorEl.hidden = true;
        successEl.hidden = true;
        try {
            faceCameraStream = await navigator.mediaDevices.getUserMedia({ video: true });
            video.srcObject = faceCameraStream;
            startBtn.hidden = true;
            captureBtn.hidden = false;
            setFaceFlashlight(true);
        } catch {
            errorEl.textContent = t('face_confirm.camera_error', 'Nu s-a putut accesa camera. Verifică permisiunile browserului.');
            errorEl.hidden = false;
        }
    });

    captureBtn.addEventListener('click', () => {
        errorEl.hidden = true;
        successEl.hidden = true;

        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext('2d').drawImage(video, 0, 0);

        canvas.toBlob(async (blob) => {
            const formData = new FormData();
            formData.append('file', blob, 'face.jpg');
            try {
                await fetch(`${API_BASE_URL}/auth/face/enroll`, {
                    method: 'POST',
                    credentials: 'include',
                    body: formData,
                }).then(async (res) => {
                    if (!res.ok) {
                        const body = await res.json().catch(() => ({}));
                        throw new Error(body?.error?.message || `Request failed (${res.status})`);
                    }
                });
                successEl.textContent = t('profile.face_success', 'Face Login activat cu succes!');
                successEl.hidden = false;
                stopFaceCamera();
                await loadFaceStatus();
            } catch (err) {
                errorEl.textContent = err.message;
                errorEl.hidden = false;
            }
        }, 'image/jpeg', 0.92);
    });

    removeBtn.addEventListener('click', async () => {
        try {
            await apiFetch('/auth/face/enroll', { method: 'DELETE' });
            await loadFaceStatus();
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.hidden = false;
        }
    });
}

/* --- Notifications dropdown (bell icon) --- */

async function refreshNotificationsBadge() {
    const badge = document.getElementById('notifications-badge');
    try {
        const { count } = await apiFetch('/notifications/unread-count');
        badge.hidden = count === 0;
    } catch {
        badge.hidden = true;
    }
}

function renderNotifications(notifications) {
    const list = document.getElementById('notifications-list');
    if (notifications.length === 0) {
        list.innerHTML = `<div class="empty-state">${escapeHTML(t('common.no_notifications', 'Nicio notificare încă.'))}</div>`;
        return;
    }
    list.innerHTML = notifications.map(n => `
        <div class="notification-item ${n.read_at ? '' : 'unread'}">
            <div class="notification-dot"></div>
            <div>
                <div class="notification-title">${escapeHTML(n.title)}</div>
                <div class="notification-body">${escapeHTML(n.body)}</div>
                <div class="notification-time">${formatDateTime(n.created_at)}</div>
            </div>
        </div>
    `).join('');
}

async function loadNotifications() {
    const list = document.getElementById('notifications-list');
    try {
        const notifications = await apiFetch('/notifications');
        renderNotifications(notifications);
        if (notifications.some(n => !n.read_at)) {
            await apiFetch('/notifications/mark-read', { method: 'POST' });
            document.getElementById('notifications-badge').hidden = true;
        }
    } catch (err) {
        list.innerHTML = `<div class="empty-state">${escapeHTML(t('dynamic.load_notifications_error', 'Nu s-au putut încărca notificările: {message}', { message: err.message }))}</div>`;
    }
}

/** Sets up the auto-hide notifications dropdown: opens on click of the
 * header bell, closes on an outside click or Escape. Loads the list and
 * marks everything read (clearing the badge) each time it's opened. */
function wireNotificationsPanel() {
    const panel = document.getElementById('notifications-panel');
    const trigger = document.getElementById('notifications-btn');

    function openPanel() {
        panel.hidden = false;
        loadNotifications();
    }
    function closePanel() { panel.hidden = true; }

    trigger.addEventListener('click', (event) => {
        event.stopPropagation();
        document.getElementById('profile-panel').hidden = true;
        if (panel.hidden) openPanel(); else closePanel();
    });
    panel.addEventListener('click', (event) => event.stopPropagation());
    document.addEventListener('click', () => {
        if (!panel.hidden) closePanel();
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !panel.hidden) closePanel();
    });

    refreshNotificationsBadge();
}

/* --- Referral code (panel section 2) --- */

// Fetched once per page load - the code never changes once generated, and
// the panel can be opened/closed freely without re-fetching every time.
let referralCodeLoaded = false;

async function loadReferralCode() {
    if (referralCodeLoaded) return;
    referralCodeLoaded = true;
    const el = document.getElementById('referral-code-value');
    try {
        const { code } = await apiFetch('/users/me/referral-code');
        el.textContent = code;
    } catch {
        el.textContent = '—';
        referralCodeLoaded = false; // allow a retry next time the panel opens
    }
}

function wireReferralCode() {
    document.getElementById('copy-referral-code-btn').addEventListener('click', async () => {
        const code = document.getElementById('referral-code-value').textContent;
        if (!code || code === '…' || code === '—') return;
        try {
            await navigator.clipboard.writeText(code);
        } catch {
            // Clipboard API can be unavailable (e.g. insecure context) - not critical.
        }
    });
}

/* --- Change password (panel section 3) --- */

function wireChangePasswordForm() {
    const form = document.getElementById('change-password-form');
    const errorEl = document.getElementById('change-password-error');
    const successEl = document.getElementById('change-password-success');

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        errorEl.hidden = true;
        successEl.hidden = true;

        const currentPassword = document.getElementById('current-password').value;
        const newPassword = document.getElementById('new-password-profile').value;
        const confirmPassword = document.getElementById('new-password-profile-confirm').value;

        if (newPassword !== confirmPassword) {
            errorEl.textContent = t('recovery.password_mismatch', 'Parolele nu coincid.');
            errorEl.hidden = false;
            return;
        }

        try {
            await apiFetch('/auth/change-password', {
                method: 'POST',
                body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
            });
            successEl.textContent = t('profile.password_changed', 'Parola a fost schimbată.');
            successEl.hidden = false;
            form.reset();
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.hidden = false;
        }
    });
}
