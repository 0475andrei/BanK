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
