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

    initDashboard();
});

/* -------------------------------------------------------------------------
 * AI chat - talks to POST /chat (see backend app/modules/chat/router.py).
 * History now lives server-side (conversations/messages tables) - the client
 * only holds the id of the conversation in progress, so it survives a reload.
 * ------------------------------------------------------------------------- */

let currentConversationId = null;
let conversationHistory = [];

const CHAT_WELCOME_TEXT =
    'Salut! Sunt asistentul tău bancar. Pot să îți verific soldul conturilor și să răspund la întrebări despre bancă. Cu ce te pot ajuta?';

const CHAT_ERRORS = {
    unavailable: 'Asistentul AI nu este disponibil momentan. Încearcă din nou.',
    invalid: 'Mesajul nu poate fi trimis. Verifică ce ai scris.',
    generic: 'A apărut o problemă. Încearcă din nou.',
};

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
        return CHAT_ERRORS.unavailable;
    }
    if (err.status === 422) return CHAT_ERRORS.invalid;
    return CHAT_ERRORS.generic;
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
            '<div class="typing-label">Asistentul gândește...</div>' +
            '<div class="typing-dots">' +
            '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>' +
            '</div>',
    });
    if (sendButton) sendButton.disabled = true;

    try {
        // apiFetch already prefixes /api/v1 and sends the session cookie.
        const response = await apiFetch('/chat', {
            method: 'POST',
            body: JSON.stringify({ message, conversation_id: currentConversationId }),
        });

        typingBubble.remove();
        appendChatBubble('ai', response.reply);
        setCurrentConversationId(response.conversation_id);
        void loadConversationHistory();
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
    const chatMessages = document.getElementById('chat-messages');
    chatMessages.innerHTML = '';
    appendChatBubble('ai', CHAT_WELCOME_TEXT);
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
    if (elapsedMinutes < 1) return 'acum câteva secunde';
    if (elapsedMinutes === 1) return 'acum un minut';
    if (elapsedMinutes < 60) return `acum ${elapsedMinutes} minute`;
    if (elapsedMinutes < 120) return 'acum o oră';
    if (elapsedMinutes < 24 * 60) return `acum ${Math.floor(elapsedMinutes / 60)} ore`;

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const conversationDay = new Date(date);
    conversationDay.setHours(0, 0, 0, 0);
    const dayDifference = Math.floor((today - conversationDay) / 86400000);
    if (dayDifference === 1) return 'ieri';
    if (dayDifference < 7) return `acum ${dayDifference} zile`;
    return date.toLocaleDateString('ro-RO', { day: 'numeric', month: 'short' });
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
    list.innerHTML = '<p class="conversation-history-empty">Se încarcă...</p>';

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
        list.innerHTML = '<p class="conversation-history-empty">Nu ai conversații salvate.</p>';
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

// AI Human-in-the-Loop Actions
function confirmAIAction(buttonElement) {
    const card = buttonElement.closest('.human-in-the-loop-card');
    card.innerHTML = `
        <div style="color: var(--income-green); font-weight: 500; display: flex; align-items: center; gap: 8px;">
            <i data-lucide="check" style="width: 18px; height: 18px;"></i> Acțiune confirmată cu succes! Transferul a fost programat.
        </div>
    `;
    if (window.lucide) lucide.createIcons();
}

function cancelAIAction(buttonElement) {
    const card = buttonElement.closest('.human-in-the-loop-card');
    card.innerHTML = `
        <div style="color: var(--text-muted); font-style: italic;">
            Acțiune anulată. Dacă te răzgândești, anunță-mă.
        </div>
    `;
}

/* =========================================================================
 * Live backend wiring (accounts, transactions, transfers). Everything above
 * this line is the original static prototype's demo-only logic (nav, chat
 * simulation) - see api.js for the fetch wrapper this uses.
 * ========================================================================= */

let currentAccounts = [];

const CURRENCY_ICONS = { RON: 'coins', EUR: 'euro', USD: 'dollar-sign' };

async function initDashboard() {
    const user = await requireSession();
    if (!user) return; // requireSession already redirected to login.html

    document.getElementById('user-name').textContent = `${user.first_name} ${user.last_name}`;
    applyAvatar(user);

    document.getElementById('logout-btn').addEventListener('click', async () => {
        try {
            await apiFetch('/auth/logout', { method: 'POST' });
        } finally {
            window.location.href = 'login.html';
        }
    });

    wireNewAccountModal();
    wireTransferModal();
    wireNewCardModal();
    wireCardOrderModal();
    wirePaymentsForm();
    wireProfilePanel(user);
    wireNotificationsPanel();

    await refreshDashboard();
}

async function refreshDashboard() {
    await loadAccounts();
    await loadTransactions();
    await loadCards();
    await loadBeneficiaries();
    await loadPayments();
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
                <p>${escapeHTML(acc.currency)}</p>
            </div>
            <div class="acc-balance">${formatMoney(acc.balance_minor, acc.currency)}</div>
            ${acc.status === 'closed' ? '<span class="acc-status">Închis</span>' : ''}
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
        list.innerHTML = '<div class="empty-state">Fără activitate încă.</div>';
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
            list.innerHTML = '<div class="empty-state">Fără activitate încă.</div>';
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
        container.innerHTML = '<div class="empty-state">Fără activitate încă.</div>';
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
            container.innerHTML = '<div class="empty-state">Fără activitate încă.</div>';
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

        try {
            await apiFetch('/transfers', {
                method: 'POST',
                headers: { 'Idempotency-Key': crypto.randomUUID() },
                body: JSON.stringify({
                    from_account_id: fromSelect.value,
                    to_account_id: document.getElementById('transfer-to').value,
                    amount_minor: Math.round(amountMajor * 100),
                    currency: fromAccount.currency,
                    description: document.getElementById('transfer-description').value || undefined,
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

function populateTransferAccountSelects() {
    const fromSelect = document.getElementById('transfer-from');
    if (!fromSelect) return;
    const active = currentAccounts.filter(a => a.status === 'active');
    fromSelect.innerHTML = active.map(acc =>
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

async function loadCards() {
    const list = document.getElementById('cards-list');
    if (!list) return;
    try {
        const cards = await apiFetch('/cards');
        renderCardsList(cards);
    } catch (err) {
        list.innerHTML = `<div class="empty-state">Nu s-au putut încărca cardurile: ${escapeHTML(err.message)}</div>`;
    }
}

function renderCardsList(cards) {
    const list = document.getElementById('cards-list');
    if (cards.length === 0) {
        list.innerHTML = '<div class="empty-state">Niciun card încă. Generează primul card virtual.</div>';
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
                <span class="card-type">Card${account ? ' &middot; ' + escapeHTML(account.name) : ''}</span>
                <span class="card-logo">VISA</span>
            </div>
            <div class="card-number">${escapeHTML(formattedNumber)}</div>
            <div class="card-footer">
                <div class="card-details">
                    <div class="detail">
                        <span class="label">Expiră</span>
                        <span class="card-secret" data-reveal="expiry" data-value="${escapeHTML(expiry)}">••/••</span>
                    </div>
                    <div class="detail">
                        <span class="label">CVV</span>
                        <span class="card-secret" data-reveal="cvv" data-value="${escapeHTML(card.cvv)}">•••</span>
                    </div>
                    ${card.spending_limit_minor != null ? `
                        <div class="detail">
                            <span class="label">Limită</span>
                            <span>${formatMoney(card.spending_limit_minor, account ? account.currency : 'RON')}</span>
                        </div>
                    ` : ''}
                    <button class="card-eye-btn" title="Arată expirare și CVV" aria-label="Arată expirare și CVV"><i data-lucide="eye"></i></button>
                </div>
                <div class="status-indicator ${card.status}">${CARD_STATUS_LABELS[card.status] || card.status}</div>
            </div>
            ${!isCancelled ? `<button class="card-cancel-btn" data-card-id="${card.id}">Anulează cardul</button>` : ''}
        </div>
        `;
    }).join('');

    if (window.lucide) lucide.createIcons();

    list.querySelectorAll('.card-eye-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const card = btn.closest('.credit-card');
            const secrets = card.querySelectorAll('.card-secret');
            const revealing = secrets[0].textContent !== secrets[0].dataset.value;
            secrets.forEach(el => { el.textContent = revealing ? el.dataset.value : (el.dataset.reveal === 'cvv' ? '•••' : '••/••'); });
            btn.innerHTML = `<i data-lucide="${revealing ? 'eye-off' : 'eye'}"></i>`;
            btn.title = revealing ? 'Ascunde expirare și CVV' : 'Arată expirare și CVV';
            if (window.lucide) lucide.createIcons();
        });
    });

    list.querySelectorAll('.card-cancel-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm('Sigur anulezi acest card? Nu poate fi reactivat.')) return;
            try {
                await apiFetch(`/cards/${btn.dataset.cardId}`, { method: 'DELETE' });
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
    const active = currentAccounts.filter(a => a.status === 'active');
    const previousValue = select.value;
    select.innerHTML = active.length
        ? active.map(acc => `<option value="${acc.id}">${escapeHTML(acc.name)} (${acc.currency})</option>`).join('')
        : '<option value="" disabled selected>Creează mai întâi un cont</option>';
    if (active.some(a => a.id === previousValue)) select.value = previousValue;
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
        list.innerHTML = `<div class="empty-state">Nu s-au putut încărca contactele: ${escapeHTML(err.message)}</div>`;
    }
}

function renderBeneficiariesList(contacts) {
    const list = document.getElementById('beneficiaries-list');
    if (contacts.length === 0) {
        list.innerHTML = '<div class="empty-state">Niciun contact încă - apare automat după prima plată.</div>';
        return;
    }
    list.innerHTML = contacts.map(c => `
        <div class="contact-item" data-iban="${escapeHTML(c.iban)}" data-name="${escapeHTML(c.display_name)}">
            <div>
                <div class="name">${escapeHTML(c.display_name)}</div>
                <div class="iban">${escapeHTML(c.iban)}</div>
            </div>
            <i data-lucide="chevron-right" class="icon"></i>
        </div>
    `).join('');
    if (window.lucide) lucide.createIcons();

    list.querySelectorAll('.contact-item').forEach(el => {
        el.addEventListener('click', () => {
            document.getElementById('payments-iban').value = el.dataset.iban;
            document.getElementById('payments-beneficiary').value = el.dataset.name;
        });
    });
}

async function loadPayments() {
    const list = document.getElementById('payments-list');
    if (!list) return;
    try {
        const payments = await apiFetch('/payments');
        renderPaymentsList(payments);
    } catch (err) {
        list.innerHTML = `<div class="empty-state">Nu s-a putut încărca istoricul: ${escapeHTML(err.message)}</div>`;
    }
}

function renderPaymentsList(payments) {
    const list = document.getElementById('payments-list');
    if (payments.length === 0) {
        list.innerHTML = '<div class="empty-state">Nicio plată încă.</div>';
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

    accountSelect.addEventListener('change', updateMyIbanDisplay);

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

        try {
            await apiFetch('/payments', {
                method: 'POST',
                headers: { 'Idempotency-Key': crypto.randomUUID() },
                body: JSON.stringify({
                    from_account_id: accountSelect.value,
                    to_iban: iban,
                    beneficiary_name: document.getElementById('payments-beneficiary').value,
                    amount_minor: amountMinor,
                    description: document.getElementById('payments-description').value || undefined,
                }),
            });
            successEl.textContent = 'Plata a fost trimisă cu succes!';
            successEl.hidden = false;
            form.reset();
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
            refreshDashboard();
        });
    });

    wireReferralCode();
    wireChangePasswordForm();
}

/** Switches to one of the profile menu's own views - not a sidebar nav item,
 * so this deactivates the sidebar explicitly rather than reusing its click
 * handler. */
function goToProfileView(target) {
    document.querySelectorAll('.nav-item').forEach(nav => nav.classList.remove('active'));
    document.querySelectorAll('.view').forEach(view => view.classList.remove('active'));
    document.getElementById(`view-${target}`).classList.add('active');

    if (target === 'referral') loadReferralCode();
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
