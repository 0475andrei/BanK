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

// Function to send a message in the AI Chat view
function sendMessage() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();

    if (message) {
        const chatMessages = document.getElementById('chat-messages');

        // Add User Message
        const userMsgDiv = document.createElement('div');
        userMsgDiv.className = 'message user';
        userMsgDiv.innerHTML = `<div class="bubble">${escapeHTML(message)}</div>`;
        chatMessages.appendChild(userMsgDiv);

        // Clear input
        input.value = '';

        // Scroll to bottom
        chatMessages.scrollTop = chatMessages.scrollHeight;

        // Simulate AI thinking and replying
        setTimeout(() => {
            const aiMsgDiv = document.createElement('div');
            aiMsgDiv.className = 'message ai';
            aiMsgDiv.innerHTML = `
                <div class="avatar"><i data-lucide="sparkles"></i></div>
                <div class="bubble">Analizez cererea ta... (Aceasta este o simulare a asistentului AI)</div>
            `;
            chatMessages.appendChild(aiMsgDiv);
            if (window.lucide) lucide.createIcons();
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }, 800);
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

    await refreshDashboard();
}

async function refreshDashboard() {
    await loadAccounts();
    await loadTransactions();
    await loadCards();
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
        return `
        <div class="credit-card virtual ${isCancelled ? 'cancelled' : ''}">
            <div class="card-header">
                <span class="card-type">Card Virtual${account ? ' &middot; ' + escapeHTML(account.name) : ''}</span>
                <span class="card-logo">VISA</span>
            </div>
            <div class="card-number">**** **** **** ${escapeHTML(card.last4)}</div>
            <div class="card-footer">
                <div class="card-details">
                    ${card.spending_limit_minor != null ? `
                        <div class="detail">
                            <span class="label">Limită</span>
                            <span>${formatMoney(card.spending_limit_minor, account ? account.currency : 'RON')}</span>
                        </div>
                    ` : ''}
                </div>
                <div class="status-indicator ${card.status}">${CARD_STATUS_LABELS[card.status] || card.status}</div>
            </div>
            ${!isCancelled ? `<button class="card-cancel-btn" data-card-id="${card.id}">Anulează cardul</button>` : ''}
        </div>
        `;
    }).join('');

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
            const issued = await apiFetch('/cards', {
                method: 'POST',
                body: JSON.stringify({
                    account_id: accountSelect.value,
                    spending_limit_minor: limitMinor,
                }),
            });
            modal.hidden = true;
            showCardReveal(issued.card_number);
            await loadCards();
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.hidden = false;
        }
    });

    document.getElementById('close-card-reveal-modal').addEventListener('click', hideCardReveal);
    document.getElementById('close-card-reveal').addEventListener('click', hideCardReveal);
}

function showCardReveal(cardNumber) {
    const formatted = cardNumber.replace(/(\d{4})(?=\d)/g, '$1 ');
    document.getElementById('card-reveal-number').textContent = formatted;
    document.getElementById('card-reveal-modal').hidden = false;
}

function hideCardReveal() {
    document.getElementById('card-reveal-modal').hidden = true;
}
