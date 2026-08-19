document.addEventListener('DOMContentLoaded', () => {
    // Initialize Lucide icons
    if (window.lucide) {
        lucide.createIcons();
    }

    // Navigation Logic
    const navItems = document.querySelectorAll('.nav-item');
    const views = document.querySelectorAll('.view');

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            // Remove active class from all nav items
            navItems.forEach(nav => nav.classList.remove('active'));
            // Add active class to clicked item
            item.classList.add('active');

            // Hide all views
            views.forEach(view => view.classList.remove('active'));

            // Show the corresponding view
            const viewId = `view-${item.dataset.view}`;
            document.getElementById(viewId).classList.add('active');
        });
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

    initDashboard();
});

/* -------------------------------------------------------------------------
 * AI chat - talks to POST /chat (see backend app/modules/chat/router.py).
 * ------------------------------------------------------------------------- */

// The conversation so far, as the backend returns it. Nothing is persisted
// server-side yet, so this is what threads context across turns - it lives for
// one page load only. Deliberately NOT in localStorage: these Message objects
// carry tool calls and results, which have no business sitting in browser
// storage.
let chatHistory = [];

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

    const typingBubble = appendChatBubble('ai', '', {
        bubbleClass: 'typing',
        html: '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>',
    });
    if (sendButton) sendButton.disabled = true;

    try {
        // apiFetch already prefixes /api/v1 and sends the session cookie.
        const response = await apiFetch('/chat', {
            method: 'POST',
            body: JSON.stringify({ message, history: chatHistory }),
        });

        typingBubble.remove();
        appendChatBubble('ai', response.reply);
        // The server owns the transcript shape; take it back verbatim.
        chatHistory = response.history;
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
    document.getElementById('user-avatar').src =
        `https://ui-avatars.com/api/?name=${encodeURIComponent(user.first_name + ' ' + user.last_name)}&background=2DD4BF&color=fff`;

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
        const perAccount = await Promise.all(
            active.map(acc => apiFetch(`/accounts/${acc.id}/transactions?limit=5`))
        );
        const entries = perAccount.flat().sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

        if (entries.length === 0) {
            list.innerHTML = '<div class="empty-state">Fără activitate încă.</div>';
            return;
        }

        list.innerHTML = entries.slice(0, 8).map(entry => `
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
