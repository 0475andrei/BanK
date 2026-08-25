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
    wireChatAttach();
    wireDocumentAttach();
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
        if (document.getElementById('view-dashboard')?.classList.contains('active')) {
            renderSavingsAccountsList();
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
        statusEl.textContent = 'Se citește fișierul...';

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
                chatInput.value = `IBAN citit din fișierul atașat: ${result.iban}`;
                await sendMessage();
            } else {
                statusEl.className = 'field-hint ocr-warning';
                statusEl.textContent = 'Nu am găsit un IBAN clar în fișier - te rog scrie-l manual.';
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
            statusEl.textContent = 'Fișierul depășește 5 MB.';
            attachInput.value = '';
            return;
        }

        statusEl.hidden = false;
        statusEl.className = 'field-hint';
        statusEl.textContent = 'Se încarcă documentul...';

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
            showToast('Document atașat. Poți pune întrebări despre el.');
        } catch (err) {
            statusEl.hidden = false;
            statusEl.className = 'field-hint ocr-warning';
            statusEl.textContent = err.message;
        } finally {
            attachInput.value = '';
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

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'document-chip-close';
    closeBtn.setAttribute('aria-label', 'Detașează documentul');
    closeBtn.textContent = '✕';
    closeBtn.addEventListener('click', () => {
        clearActiveDocument();
        showToast('Document detașat.');
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

/** Builds a chat bubble matching the existing markup and appends it. */
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

    const bubble = document.createElement('div');
    bubble.className = options.bubbleClass ? `bubble ${options.bubbleClass}` : 'bubble';
    if (options.html) {
        bubble.innerHTML = options.html;
    } else {
        // textContent, not innerHTML: the reply is model-authored text and must
        // never be interpreted as markup.
        bubble.textContent = text;
    }
    wrapper.appendChild(bubble);

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
        const aiBubble = appendChatBubble('ai', response.reply);
        if (response.proposal) {
            renderProposalCard(response.proposal, aiBubble);
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
            return { ...conversation, preview: preview || 'Conversație nouă' };
        }));

        renderConversationHistory();

        const rememberedId = sessionStorage.getItem('bank.currentConversationId');
        if (!currentConversationId && rememberedId && conversationHistory.some(item => item.id === rememberedId)) {
            await openConversation(rememberedId);
        }
    } catch (err) {
        list.innerHTML = '';
        showConversationHistoryError('Istoricul conversațiilor nu a putut fi încărcat. Încearcă din nou.');
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
        renameButton.title = 'Redenumește conversația';
        renameButton.setAttribute('aria-label', 'Redenumește conversația');
        renameButton.innerHTML = '<i data-lucide="pencil"></i>';
        renameButton.addEventListener('click', () => beginConversationRename(item, conversation));

        const deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'conversation-history-action';
        deleteButton.title = 'Șterge conversația';
        deleteButton.setAttribute('aria-label', 'Șterge conversația');
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
    renderConversationHistory();
    showConversationHistoryError();

    try {
        const messages = await apiFetch(`/chat/conversations/${conversationId}/messages`);
        const chatMessages = document.getElementById('chat-messages');
        chatMessages.innerHTML = '';
        const dialogue = messages.filter(message =>
            (message.role === 'user' || message.role === 'assistant') && message.content
        );
        if (dialogue.length) {
            dialogue.forEach(message => appendChatBubble(message.role === 'user' ? 'user' : 'ai', message.content));
        } else {
            appendChatBubble('ai', CHAT_WELCOME_TEXT);
        }
    } catch (err) {
        showConversationHistoryError('Conversația nu a putut fi încărcată. Încearcă din nou.');
    }
}

function beginConversationRename(item, conversation) {
    const selectButton = item.querySelector('.conversation-history-select');
    const actions = item.querySelector('.conversation-history-actions');
    if (!selectButton || !actions) return;

    item.classList.add('editing');
    selectButton.replaceChildren();
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'conversation-history-rename-input';
    input.value = conversation.title || conversation.preview;
    input.maxLength = 120;
    input.setAttribute('aria-label', 'Nume conversație');
    input.addEventListener('click', event => event.stopPropagation());
    input.addEventListener('keydown', event => {
        if (event.key === 'Enter') saveConversationRename(conversation, input.value);
        if (event.key === 'Escape') renderConversationHistory();
    });
    selectButton.appendChild(input);

    actions.replaceChildren();
    const saveButton = document.createElement('button');
    saveButton.type = 'button';
    saveButton.className = 'conversation-history-action';
    saveButton.title = 'Salvează numele';
    saveButton.setAttribute('aria-label', 'Salvează numele');
    saveButton.innerHTML = '<i data-lucide="check"></i>';
    saveButton.addEventListener('click', () => saveConversationRename(conversation, input.value));

    const cancelButton = document.createElement('button');
    cancelButton.type = 'button';
    cancelButton.className = 'conversation-history-action';
    cancelButton.title = 'Renunță';
    cancelButton.setAttribute('aria-label', 'Renunță');
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
        showConversationHistoryError('Numele conversației nu poate fi gol.');
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
        showConversationHistoryError('Conversația nu a putut fi redenumită. Încearcă din nou.');
    }
}

async function deleteConversation(conversation) {
    const approved = window.confirm(`Sigur vrei să ștergi conversația „${truncateConversationPreview(conversation.preview)}”?`);
    if (!approved) return;

    try {
        await apiFetch(`/chat/conversations/${conversation.id}`, { method: 'DELETE' });
        conversationHistory = conversationHistory.filter(item => item.id !== conversation.id);
        if (currentConversationId === conversation.id) startNewConversation();
        renderConversationHistory();
    } catch (err) {
        showConversationHistoryError('Conversația nu a putut fi ștearsă. Încearcă din nou.');
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
    body.innerHTML = `<strong>Propunere de acțiune</strong><p>${escapeHTML(proposal.summary)}</p>`;
    card.appendChild(body);

    const actions = document.createElement('div');
    actions.className = 'hitl-actions';

    const confirmBtn = document.createElement('button');
    confirmBtn.type = 'button';
    confirmBtn.className = 'btn btn-primary';
    confirmBtn.textContent = 'Confirmă';
    confirmBtn.addEventListener('click', () => openStepUpModal(proposal.id, card));

    const rejectBtn = document.createElement('button');
    rejectBtn.type = 'button';
    rejectBtn.className = 'btn btn-secondary';
    rejectBtn.textContent = 'Anulează';
    rejectBtn.addEventListener('click', () => handleRejectProposal(proposal.id, card));

    actions.appendChild(confirmBtn);
    actions.appendChild(rejectBtn);
    card.appendChild(actions);

    container.appendChild(card);
    if (window.lucide) lucide.createIcons();
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
        ? '<i data-lucide="check-circle"></i> Confirmată'
        : '<i data-lucide="x-circle"></i> Anulată';
    actions.replaceWith(label);
    if (window.lucide) lucide.createIcons();
}

async function handleRejectProposal(proposalId, card) {
    const buttons = card.querySelectorAll('button');
    buttons.forEach(btn => { btn.disabled = true; });
    try {
        await apiFetch(`/chat/proposals/${proposalId}/reject`, { method: 'POST' });
        markProposalCardResolved(card, 'rejected');
        showToast('Propunerea a fost anulată.');
    } catch (err) {
        buttons.forEach(btn => { btn.disabled = false; });
        showToast('Eroare la anulare.');
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
        showToast('Acțiunea a fost confirmată și executată cu succes!');
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
        showStepUpError(err.message || 'Autentificare eșuată.');
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

/* =========================================================================
 * Live backend wiring (accounts, transactions, transfers). Everything above
 * this line is the original static prototype's demo-only logic (nav, chat
 * simulation) - see api.js for the fetch wrapper this uses.
 * ========================================================================= */

let currentAccounts = [];

const CURRENCY_ICONS = { RON: 'coins', EUR: 'euro', USD: 'dollar-sign' };

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

/** Shows the admin-panel link if this user is an admin.
 *
 * Asks the server (GET /admin/me) rather than reading a role off the user
 * object: the role is not part of UserRead, and a client-side flag would be
 * cosmetic anyway - the real gate is require_admin on every /admin route.
 * Any failure (403 for a normal user, or anything else) just leaves the link
 * hidden, so this can never break the dashboard for a non-admin. */
async function revealAdminLinkIfAdmin() {
    try {
        await apiFetch('/admin/me');
        document.getElementById('admin-panel-link').hidden = false;
    } catch {
        /* not an admin, or the admin module is unavailable - leave it hidden */
    }
}

async function initDashboard() {
    const user = await requireSession();
    if (!user) return; // requireSession already redirected to login.html

    document.getElementById('user-name').textContent = `${user.first_name} ${user.last_name}`;
    applyAvatar(user);
    void revealAdminLinkIfAdmin();

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

/** Builds the ring's SVG markup: one <circle> per category, each a full
 * circle whose stroke-dasharray only paints its own arc (with a small gap
 * on either side instead of a border - see dataviz skill's anti-patterns.md
 * on borders between marks). Positioning, the mount animation, and the
 * hover pop-out are ALL one CSS `transform` chain on the circle itself
 * (`translate() rotate() scale()`, right-to-left composition) driven by
 * --rot/--hx/--hy/--scale custom properties - deliberately NOT split across
 * an SVG `rotate` attribute on a wrapping <g> plus a separate CSS transform
 * on the child, which would nest the child's translate inside the parent's
 * rotation and swing the hover offset off in the wrong direction. */
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
               role="img" aria-label="${escapeHTML(cat.name)}"
               style="--rot: ${(startAngleDeg - 90).toFixed(3)}deg; --hx-active: ${dx.toFixed(2)}px; --hy-active: ${dy.toFixed(2)}px; --seg-delay: ${i * 70}ms;">
                <circle
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
        <svg class="spending-donut" viewBox="0 0 ${SPENDING_DONUT_SIZE} ${SPENDING_DONUT_SIZE}" role="group" aria-label="Cheltuieli pe categorii">
            ${buildSpendingDonutSegments(categories)}
        </svg>
        <div class="spending-donut-center">
            <span class="spending-donut-total-label">Total</span>
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
            <span class="spending-donut-tooltip-label">${escapeHTML(cat.name)} &middot; ${cat.percentage.toFixed(0)}%</span>
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
        legend.innerHTML = '<div class="empty-state">Niciun cont activ încă.</div>';
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
        legend.innerHTML = `<div class="empty-state">Nu s-au putut încărca categoriile: ${escapeHTML(err.message)}</div>`;
        return;
    }

    const rawCategories = data.categories.filter(c => c.total_minor > 0);
    if (rawCategories.length === 0) {
        donutWrap.innerHTML = '';
        donutWrap.style.display = 'none';
        legend.innerHTML = '<div class="empty-state">Nicio cheltuială luna aceasta încă.</div>';
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
            ${escapeHTML(cat.name)} (${cat.percentage.toFixed(0)}%) &middot; ${formatMoney(cat.total_minor, primaryCurrency)}
        </div>
    `).join('');

    wireSpendingCategoryHover(container, categories, primaryCurrency);
}

async function loadAccounts() {
    const grid = document.getElementById('accounts-grid');
    try {
        currentAccounts = await apiFetch('/accounts');
    } catch (err) {
        grid.innerHTML = `<div class="empty-state">Nu s-au putut încărca conturile: ${escapeHTML(err.message)}</div>`;
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
        grid.innerHTML = '<div class="empty-state">Niciun cont încă. Creează primul cont.</div>';
        return;
    }
    grid.innerHTML = currentAccounts.map(acc => `
        <div class="account-card ${acc.status === 'closed' ? 'closed' : ''}">
            <div class="acc-icon"><i data-lucide="${CURRENCY_ICONS[acc.currency] || 'wallet'}"></i></div>
            <div class="acc-info">
                <h3>${escapeHTML(acc.name)}</h3>
                <p>${escapeHTML(acc.currency)}${acc.product_type !== 'checking' ? ` &middot; ${(acc.interest_rate_bps / 100).toFixed(1)}% p.a.` : ''}</p>
            </div>
            <div class="acc-balance">${formatMoney(acc.balance_minor, acc.currency)}</div>
            ${acc.status === 'closed' ? '<span class="acc-status">Închis</span>' : ''}
            ${!isSpendable(acc) ? '<span class="acc-status locked">Blocat</span>' : ''}
        </div>
    `).join('');
    if (window.lucide) lucide.createIcons();
}

function renderHeadlineBalance() {
    const el = document.getElementById('total-balance');
    const active = currentAccounts.filter(a => a.status === 'active');
    if (active.length === 0) {
        el.innerHTML = formatMoney(0, 'RON');
        return;
    }
    // Accounts can hold different currencies, which can't be summed together -
    // the headline number totals accounts in the first active account's
    // currency only (there's no "home currency" concept in the backend).
    const primaryCurrency = active[0].currency;
    const total = active
        .filter(a => a.currency === primaryCurrency)
        .reduce((sum, a) => sum + a.balance_minor, 0);
    el.textContent = formatMoney(total, primaryCurrency);
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
                    <h4>${escapeHTML(entry.description)}</h4>
                    <span class="time">${formatDateTime(entry.created_at)}</span>
                </div>
                <div class="tx-amount ${entry.direction === 'credit' ? 'positive' : 'negative'}">
                    ${entry.direction === 'credit' ? '+' : '-'} ${formatMoney(entry.amount_minor, entry.currency)}
                </div>
            </div>
        `).join('');
        if (window.lucide) lucide.createIcons();
    } catch (err) {
        list.innerHTML = `<div class="empty-state">Nu s-au putut încărca tranzacțiile: ${escapeHTML(err.message)}</div>`;
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

    container.innerHTML = '<div class="loading-state">Se încarcă...</div>';

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
        container.innerHTML = `<div class="empty-state">Nu s-au putut încărca tranzacțiile: ${escapeHTML(err.message)}</div>`;
    }
}

function monthGroupKey(isoString) {
    const d = new Date(isoString);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function monthGroupLabel(isoString) {
    const label = new Date(isoString).toLocaleDateString('ro-RO', { month: 'long', year: 'numeric' });
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
                            <h4>${escapeHTML(entry.description)}</h4>
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
    return date.toLocaleDateString('ro-RO', { day: 'numeric', month: 'short' }) +
        ', ' + date.toLocaleTimeString('ro-RO', { hour: '2-digit', minute: '2-digit' });
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
            rateHint.textContent =
                `Dobândă: ${(accountProducts.savings_interest_rate_bps / 100).toFixed(1)}% p.a., calculată lunar.`;
        } else {
            const months = Number(termSelect.value);
            const option = accountProducts.term_deposit_options.find((o) => o.term_months === months);
            rateHint.textContent = option
                ? `Dobândă: ${(option.interest_rate_bps / 100).toFixed(1)}% p.a., plătită la final. Banii sunt blocați ${months} luni.`
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
            Depui ${formatMoney(principalMinor, currency)} acum, pe ${months} luni la ${(option.interest_rate_bps / 100).toFixed(1)}% p.a.
            <div class="projection-total">${formatMoney(totalMinor, currency)}</div>
            <div>la maturitate (din care ${formatMoney(interestMinor, currency)} dobândă)</div>
        `;
    }

    function openModal(type) {
        productType = type;
        errorEl.hidden = true;
        form.reset();
        if (type === 'savings') {
            titleEl.textContent = 'Cont de economii nou';
            termRow.hidden = true;
            projectionRow.hidden = true;
            projectionBox.hidden = true;
        } else {
            titleEl.textContent = 'Cont cu dobândă fixă nou';
            termRow.hidden = false;
            projectionRow.hidden = false;
            if (accountProducts) {
                termSelect.innerHTML = accountProducts.term_deposit_options
                    .map((o) => `<option value="${o.term_months}">${o.term_months} luni - ${(o.interest_rate_bps / 100).toFixed(1)}% p.a.</option>`)
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
                ? `Blocat până la ${new Date(acc.maturity_date).toLocaleDateString('ro-RO')}`
                : `Maturitate atinsă (${new Date(acc.maturity_date).toLocaleDateString('ro-RO')}) - poți retrage`)
            : 'Flexibil - retragi oricând';
        return `
            <div class="pot-item savings-account-item">
                <div class="pot-header">
                    <span class="pot-icon"><i data-lucide="${acc.product_type === 'term_deposit' ? 'lock' : 'piggy-bank'}"></i></span>
                    <div class="pot-name">${escapeHTML(acc.name)}</div>
                    <div class="pot-amounts">${formatMoney(acc.balance_minor, acc.currency)} &middot; ${rate}</div>
                </div>
                <div class="savings-account-maturity ${locked ? 'locked' : ''}">${maturityLabel}</div>
            </div>
        `;
    }).join('');
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
            errorEl.textContent = 'Completează toate câmpurile obligatorii.';
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

const SCHEDULED_TRANSFER_FREQUENCY_LABELS = { weekly: 'Săptămânal', monthly: 'Lunar' };
const SCHEDULED_TRANSFER_STATUS_LABELS = {
    active: 'Activ', paused: 'Pauzat', cancelled: 'Anulat', completed: 'Finalizat',
};

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
        : '<option value="" disabled selected>Niciun alt cont în aceeași monedă</option>';
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
            errorEl.textContent = 'Completează toate câmpurile obligatorii.';
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
        list.innerHTML = `<div class="empty-state">Nu s-au putut încărca transferurile programate: ${escapeHTML(err.message)}</div>`;
    }
}

function renderScheduledTransfersList(scheduled) {
    const list = document.getElementById('scheduled-transfers-list');
    if (scheduled.length === 0) {
        list.innerHTML = '<div class="empty-state">Niciun transfer programat.</div>';
        return;
    }
    list.innerHTML = scheduled.map(s => {
        const fromAccount = currentAccounts.find(a => a.id === s.from_account_id);
        const toAccount = currentAccounts.find(a => a.id === s.to_account_id);
        const freqLabel = s.frequency ? SCHEDULED_TRANSFER_FREQUENCY_LABELS[s.frequency] : 'O singură dată';
        const canAct = s.status === 'active' || s.status === 'paused';
        return `
        <div class="scheduled-transfer-item">
            <div>
                <div class="name">${escapeHTML(fromAccount ? fromAccount.name : '?')} → ${escapeHTML(toAccount ? toAccount.name : '?')}</div>
                <div class="meta">${formatMoney(s.amount_minor, s.currency)} &middot; ${freqLabel} &middot; ${SCHEDULED_TRANSFER_STATUS_LABELS[s.status] || s.status}</div>
                ${s.last_error ? `<div class="meta scheduled-transfer-error-note">${escapeHTML(s.last_error)}</div>` : ''}
            </div>
            ${canAct ? `
                <div class="scheduled-transfer-actions">
                    ${s.status === 'active'
                        ? `<button class="link-btn" data-id="${s.id}" data-action="pause">Pauză</button>`
                        : `<button class="link-btn" data-id="${s.id}" data-action="resume">Reia</button>`
                    }
                    <button class="link-btn" data-id="${s.id}" data-action="cancel">Anulează</button>
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

        merchantEl.textContent = details.beneficiary_name || 'Acest abonament';
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

const FACE_CONFIRM_DEFAULT_REASON = 'Suma depășește pragul de confirmare - verifică-ți identitatea prin cameră.';

/** Opens the face-confirm modal, captures a photo, exchanges it for a
 * short-lived confirmation token via POST /auth/face/confirm. Resolves with
 * the token, or null if the user cancels. Never rejects - camera/API errors
 * show inline in the modal and let the user retry or cancel. `reason`
 * overrides the modal's explanatory text for callers other than the
 * large-transfer step-up this was originally built for. */
function requestFaceConfirmationToken(reason = FACE_CONFIRM_DEFAULT_REASON) {
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
            captureBtn.onclick = null;
            cancelBtn.onclick = null;
            closeBtn.onclick = null;
            resolve(result);
        }

        navigator.mediaDevices.getUserMedia({ video: true })
            .then((s) => { stream = s; video.srcObject = s; })
            .catch(() => {
                errorEl.textContent = 'Nu s-a putut accesa camera. Verifică permisiunile browserului.';
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
        : '<option value="" disabled selected>Niciun alt cont în aceeași monedă</option>';
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
    btn.title = revealing ? 'Ascunde expirare și CVV' : 'Arată expirare și CVV';
    if (window.lucide) lucide.createIcons();
}

async function loadCards() {
    const list = document.getElementById('cards-list');
    if (!list) return;
    try {
        const cards = await apiFetch('/cards');
        loadedCards = cards;
        renderCardsList(cards);
    } catch (err) {
        list.innerHTML = `<div class="empty-state">Nu s-au putut încărca cardurile: ${escapeHTML(err.message)}</div>`;
    }
}

function renderCardsList(cards) {
    const list = document.getElementById('cards-list');
    if (cards.length === 0) {
        list.innerHTML = `<div class="empty-state">${t('cards.empty', 'Niciun card încă. Generează primul card virtual.')}</div>`;
        return;
    }

    const accountById = Object.fromEntries(currentAccounts.map(a => [a.id, a]));

    list.innerHTML = cards.map(card => {
        const account = accountById[card.account_id];
        const isCancelled = card.status === 'cancelled';
        const formattedNumber = card.card_number.replace(/(.{4})/g, '$1 ').trim();
        const expiry = `${String(card.expiry_month).padStart(2, '0')}/${String(card.expiry_year).slice(-2)}`;
        return `
        <div class="credit-card virtual ${isCancelled ? 'cancelled' : ''}">
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
                ${isCancelled
                    ? `<div class="status-indicator cancelled">${t('cards.status_cancelled', CARD_STATUS_LABELS.cancelled)}</div>`
                    : `<button class="status-toggle-btn ${card.status}" data-card-id="${card.id}" data-action="${card.status === 'frozen' ? 'unfreeze' : 'freeze'}" title="${t(card.status === 'frozen' ? 'cards.unfreeze_hint' : 'cards.freeze_hint', card.status === 'frozen' ? 'Apasă pentru a debloca cardul' : 'Apasă pentru a bloca temporar cardul')}">
                        <i data-lucide="${card.status === 'frozen' ? 'snowflake' : 'shield-check'}"></i>
                        <span>${t(`cards.status_${card.status}`, CARD_STATUS_LABELS[card.status] || card.status)}</span>
                    </button>`
                }
            </div>
            ${!isCancelled ? `
                <div class="card-actions-row">
                    <button class="card-limit-btn" data-card-id="${card.id}" data-current-limit="${card.spending_limit_minor ?? ''}">${t('cards.limit')}</button>
                    <button class="card-cancel-btn" data-card-id="${card.id}">${t('cards.cancel')}</button>
                </div>
            ` : ''}
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
            // only revealing the real expiry/CVV does, and only for users who
            // actually opted into Face ID (same "optional extra" philosophy
            // as the face-confirmation step-up on large transfers).
            if (revealing) {
                let faceEnrolled = false;
                try {
                    faceEnrolled = (await apiFetch('/auth/face/status')).enrolled;
                } catch (err) {
                    // Can't check - fail open to the pre-existing behaviour
                    // rather than locking the user out of their own card.
                }
                if (faceEnrolled) {
                    btn.disabled = true;
                    const token = await requestFaceConfirmationToken(
                        'Verifică-ți identitatea prin cameră ca să vezi numărul complet și CVV-ul cardului.'
                    );
                    btn.disabled = false;
                    if (!token) return;
                }
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
                'Noua limită de cheltuieli (lasă gol pentru a elimina limita):',
                currentLimit
            );
            if (input === null) return;

            const trimmed = input.trim();
            const spendingLimitMinor = trimmed ? Math.round(parseFloat(trimmed) * 100) : null;
            if (trimmed && (!Number.isFinite(spendingLimitMinor) || spendingLimitMinor <= 0)) {
                alert('Introdu o sumă validă, mai mare decât 0.');
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
            : '<option value="" disabled selected>Creează mai întâi un cont</option>';
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

    document.getElementById('open-card-order-btn').addEventListener('click', () => {
        errorEl.hidden = true;
        form.reset();
        document.getElementById('card-order-country').value = 'România';
        const active = currentAccounts.filter(a => a.status === 'active');
        accountSelect.innerHTML = active.length
            ? active.map(acc => `<option value="${acc.id}">${escapeHTML(acc.name)} (${acc.currency})</option>`).join('')
            : '<option value="" disabled selected>Creează mai întâi un cont</option>';
        modal.hidden = false;
    });
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
            alert(`Comanda a fost trimisă! Cardul tău: ${formattedNumber}`);
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
        : '<option value="" disabled selected>Creează mai întâi un cont</option>';
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
                <div class="name">${escapeHTML(c.display_name)}${c.is_subscription ? ' <span class="contact-subscription-badge">Abonament</span>' : ''}</div>
                <div class="iban">${escapeHTML(c.iban)}</div>
                ${c.website ? `<a class="contact-website" href="${escapeHTML(c.website)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">${escapeHTML(c.website)}</a>` : ''}
            </div>
            <button type="button" class="contact-remove-btn" data-id="${c.id}" title="Șterge contactul" aria-label="Șterge contactul"><i data-lucide="x"></i></button>
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
            if (!confirm('Ștergi acest contact salvat?')) return;
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
                <div class="meta">${new Date(p.created_at).toLocaleString('ro-RO')}</div>
            </div>
            <div class="amount">-${formatMoney(p.amount_minor, p.currency)}</div>
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
        ibanScanStatus.textContent = 'Se citește fișierul...';

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
                ibanScanStatus.textContent = `IBAN citit: ${result.iban}`;
            } else {
                ibanScanStatus.className = 'field-hint ocr-warning';
                ibanScanStatus.textContent = 'Nu am găsit un IBAN clar în fișier - introdu-l manual.';
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
        } catch {
            errorEl.textContent = 'Nu s-a putut accesa camera. Verifică permisiunile browserului.';
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
        list.innerHTML = '<div class="empty-state">Nicio notificare încă.</div>';
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
        list.innerHTML = `<div class="empty-state">Nu s-au putut încărca notificările: ${escapeHTML(err.message)}</div>`;
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
            errorEl.textContent = 'Parolele nu coincid.';
            errorEl.hidden = false;
            return;
        }

        try {
            await apiFetch('/auth/change-password', {
                method: 'POST',
                body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
            });
            successEl.textContent = 'Parola a fost schimbată.';
            successEl.hidden = false;
            form.reset();
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.hidden = false;
        }
    });
}
