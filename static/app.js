/**
 * ARMEDIAS AI — Frontend Controller
 * Optimized for performance and real-time state management.
 */

const socket = io();
let currentAccounts = [];

// Real-time status stream
socket.on('status_update', (data) => {
    currentAccounts = data.accounts || [];
    renderDashboard(currentAccounts);
    updateGlobalStats(currentAccounts);
});

/**
 * Updates the top stat cards with global totals.
 */
function updateGlobalStats(accounts) {
    const stats = {
        total: accounts.length,
        active: accounts.filter(a => a.is_loop_active).length,
        sent: accounts.reduce((s, a) => s + (a.sent || 0), 0),
        errors: accounts.reduce((s, a) => s + (a.errors || 0), 0)
    };

    const nodes = {
        'statTotal': stats.total,
        'statActive': stats.active,
        'statSent': stats.sent,
        'statErrors': stats.errors
    };

    for (const [id, val] of Object.entries(nodes)) {
        const el = document.getElementById(id);
        if (el && el.textContent != val) el.textContent = val;
    }
}

/**
 * Efficiently renders the account grid.
 * Only modifies DOM nodes that have actually changed.
 */
function renderDashboard(accounts) {
    const grid = document.getElementById('sessions-grid');
    if (!grid) return;

    const currentIds = new Set(accounts.map(a => `card-${a.clean_phone}`));

    // Remove stale cards
    Array.from(grid.children).forEach(child => {
        if (!currentIds.has(child.id)) child.remove();
    });

    // Update or Create cards
    accounts.forEach(acc => {
        let card = document.getElementById(`card-${acc.clean_phone}`);
        if (!card) {
            card = createCardNode(acc);
            grid.appendChild(card);
        }
        updateCardContent(card, acc);
    });
}

function createCardNode(acc) {
    const card = document.createElement('div');
    card.className = 'card';
    card.id = `card-${acc.clean_phone}`;
    card.innerHTML = `
        <div class="card-top">
          <div class="card-profile">
            <div class="avatar">${acc.phone.slice(-2)}</div>
            <div><div class="card-name">${acc.phone}</div><div class="card-sub">session_${acc.clean_phone}</div></div>
          </div>
          <div class="badge-container"></div>
        </div>
        <div class="card-meta">
          <div>Status<span class="status-text">—</span></div>
          <div>Last Sent<span class="stat-time">—</span></div>
          <div>Sent<span class="stat-sent">0</span></div>
          <div>Errors<span class="stat-errors">0</span></div>
        </div>
        <div class="card-action-bar" style="margin-top:16px; font-size:.75rem; color:var(--text2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-bottom:12px; height: 1.2em;">
            —
        </div>
        <div class="card-actions">
          <button class="btn btn-p btn-sm btn-dispatch" style="flex:2">Dispatch</button>
          <button class="btn btn-s btn-sm btn-loop"><i class="fas fa-play"></i></button>
          <button class="btn btn-s btn-sm btn-settings"><i class="fas fa-cog"></i> Settings</button>
          <button class="btn btn-d btn-sm btn-delete"><i class="fas fa-trash"></i></button>
        </div>
    `;
    return card;
}

function updateCardContent(card, acc) {
    // 1. Badge & Status
    const badgeContainer = card.querySelector('.badge-container');
    const statusSpan = card.querySelector('.status-text');
    let bClass = 'b-idle', bText = acc.state.toUpperCase();

    if (acc.state === 'sending') bClass = 'b-active';
    else if (acc.state === 'cooldown') { bClass = 'b-cooldown'; bText = `WAIT ${acc.cooldown_remaining}s`; }
    else if (acc.state === 'unauth') bClass = 'b-unauth';
    else if (acc.is_loop_active) { bClass = 'b-active'; bText = 'LOOPING'; }

    const badgeHtml = `<div class="badge ${bClass}">${bText}</div>`;
    if (badgeContainer.innerHTML !== badgeHtml) badgeContainer.innerHTML = badgeHtml;
    if (statusSpan.textContent !== bText) statusSpan.textContent = bText;

    // 2. Stats
    const time = formatTime(acc.last_dispatch_time);
    if (card.querySelector('.stat-time').textContent !== time) card.querySelector('.stat-time').textContent = time;
    if (card.querySelector('.stat-sent').textContent != acc.sent) card.querySelector('.stat-sent').textContent = acc.sent;
    if (card.querySelector('.stat-errors').textContent != acc.errors) card.querySelector('.stat-errors').textContent = acc.errors;
    if (card.querySelector('.card-action-bar').textContent !== acc.last_action) card.querySelector('.card-action-bar').textContent = acc.last_action;

    // 3. Buttons logic
    const dispatchBtn = card.querySelector('.btn-dispatch');
    const loopBtn = card.querySelector('.btn-loop');
    const settingsBtn = card.querySelector('.btn-settings');
    const deleteBtn = card.querySelector('.btn-delete');

    if (acc.state === 'unauth') {
        dispatchBtn.innerHTML = '<i class="fas fa-key"></i> Login';
        dispatchBtn.onclick = () => openLoginModal(acc.phone);
        loopBtn.style.display = 'none';
    } else {
        dispatchBtn.innerHTML = '<i class="fas fa-paper-plane"></i> Dispatch';
        dispatchBtn.onclick = () => manualDispatch(acc.clean_phone);
        loopBtn.style.display = 'inline-flex';
        loopBtn.className = `btn btn-sm btn-loop ${acc.is_loop_active ? 'btn-d' : 'btn-s'}`;
        loopBtn.innerHTML = `<i class="fas ${acc.is_loop_active ? 'fa-pause' : 'fa-play'}"></i>`;
        loopBtn.onclick = () => toggleLoop(acc.clean_phone);
    }

    settingsBtn.onclick = () => openSessionSettings(acc.clean_phone);
    deleteBtn.onclick = () => deleteAccount(acc.phone);
}

// ──────────────────────────────────────────────
// ACTIONS
// ──────────────────────────────────────────────

async function manualDispatch(phone) {
    try {
        const res = await fetch('/api/session/dispatch', { 
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify({phone}) 
        });
        const data = await res.json();
        if (data.status === 'success') toast('Dispatch triggered!'); 
        else toast(data.message, 'err');
    } catch (e) { toast('Connection failed', 'err'); }
}

async function toggleLoop(phone) {
    const acc = currentAccounts.find(a => a.clean_phone === phone);
    const endpoint = acc.is_loop_active ? '/api/session/stop' : '/api/session/start';
    try {
        const res = await fetch(endpoint, { 
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify({phone}) 
        });
        const data = await res.json();
        if (data.status === 'success') toast(acc.is_loop_active ? 'Loop paused' : 'Loop started');
        else toast(data.message, 'err');
    } catch (e) { toast('Action failed', 'err'); }
}

async function openSessionSettings(phone) {
    const acc = currentAccounts.find(a => a.clean_phone === phone);
    if (!acc) return;
    
    document.getElementById('edit-phone').value = phone;
    document.getElementById('modal-phone').textContent = `Configuring ${acc.phone}`;
    document.getElementById('edit-source').value = acc.source_channel || '';
    document.getElementById('edit-interval').value = acc.loop_interval || 15;
    
    try {
        const res = await fetch(`/api/account-targets?phone=${encodeURIComponent(acc.phone)}`);
        const data = await res.json();
        document.getElementById('edit-targets').value = data.targets || '';
    } catch (e) { document.getElementById('edit-targets').value = ''; }
    
    showModal('settings-modal');
}

async function saveSessionSettings() {
    const phone = document.getElementById('edit-phone').value;
    const interval = parseInt(document.getElementById('edit-interval').value);
    
    if (interval < 1) return toast('Interval must be at least 1 min', 'err');

    const payload = {
        phone,
        source_channel: document.getElementById('edit-source').value,
        loop_interval: interval,
        targets: document.getElementById('edit-targets').value.split('\n').map(x => x.trim()).filter(x => x)
    };

    try {
        const res = await fetch('/api/session/settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status === 'success') { toast('Settings updated'); closeModal(); }
        else toast(data.message, 'err');
    } catch (e) { toast('Save failed', 'err'); }
}

function openGlobalSettings() { showModal('global-settings-modal'); }

async function saveGlobalSettings() {
    const fd = new FormData();
    fd.append('api_id', document.getElementById('global-api-id').value);
    fd.append('api_hash', document.getElementById('global-api-hash').value);
    fd.append('source_channel', document.getElementById('global-source').value);
    fd.append('loop_interval', document.getElementById('global-interval').value);

    try {
        const res = await fetch('/save-global', { method: 'POST', body: fd });
        const data = await res.json();
        if (data.status === 'success') { 
            toast('Global configuration saved'); 
            closeModal();
        } else toast(data.message, 'err');
    } catch (e) { toast('Network error', 'err'); }
}

// ──────────────────────────────────────────────
// AUTH FLOW
// ──────────────────────────────────────────────

let pendingAuth = {};
function openLoginModal(phone) {
    pendingAuth.phone = phone;
    document.getElementById('otp-phone-display').textContent = `Authenticating ${phone}`;
    document.getElementById('otp-step-1').classList.remove('hidden');
    document.getElementById('otp-step-2').classList.add('hidden');
    showModal('otp-modal');
}

async function sendOTP() {
    const fd = new FormData();
    fd.append('api_id', document.getElementById('api-id').value);
    fd.append('api_hash', document.getElementById('api-hash').value);
    fd.append('phone', pendingAuth.phone);
    
    try {
        const res = await fetch('/api/auth/send_code', { method: 'POST', body: fd });
        const data = await res.json();
        if (data.status === 'success') {
            pendingAuth.hash = data.phone_code_hash;
            document.getElementById('otp-step-1').classList.add('hidden');
            document.getElementById('otp-step-2').classList.remove('hidden');
            toast('OTP sent to Telegram');
        } else toast(data.message, 'err');
    } catch (e) { toast('Request failed', 'err'); }
}

async function verifyOTP() {
    const fd = new FormData();
    fd.append('api_id', document.getElementById('api-id').value);
    fd.append('api_hash', document.getElementById('api-hash').value);
    fd.append('phone', pendingAuth.phone);
    fd.append('phone_code_hash', pendingAuth.hash);
    fd.append('code', document.getElementById('otp-code').value);
    
    try {
        const res = await fetch('/api/auth/sign_in', { method: 'POST', body: fd });
        const data = await res.json();
        if (data.status === 'success') { 
            toast('Authentication successful!', 'ok'); 
            closeModal(); 
        } else toast(data.message, 'err');
    } catch (e) { toast('Verification failed', 'err'); }
}

// ──────────────────────────────────────────────
// UTILS
// ──────────────────────────────────────────────

function formatTime(ts) { 
    if (!ts) return 'Never'; 
    const d = new Date(ts * 1000); 
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); 
}

function toast(msg, type = 'ok') { 
    const c = document.getElementById('toasts');
    if (!c) return;
    const t = document.createElement('div');
    t.className = `toast t-${type}`;
    t.innerHTML = `<span>${msg}</span>`;
    c.appendChild(t);
    setTimeout(() => t.classList.add('show'), 10);
    setTimeout(() => {
        t.classList.remove('show');
        setTimeout(() => t.remove(), 300);
    }, 4000);
}

function promptAddAccount() { 
    const p = prompt("Enter Telegram Phone (+ country code):"); 
    if (p) fetch('/api/add-account', { 
        method: 'POST', 
        headers: {'Content-Type': 'application/json'}, 
        body: JSON.stringify({phone: p.trim()}) 
    }).then(r => r.json()).then(d => { 
        if (d.status === 'success') toast('Account added'); 
        else toast(d.message, 'err'); 
    }); 
}

async function deleteAccount(phone) { 
    if (confirm(`Are you sure you want to delete ${phone}?`)) { 
        await fetch('/api/delete-account', { 
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify({phone}) 
        }); 
        toast('Account removed'); 
    } 
}

async function refreshLogs() { 
    const l = document.getElementById('log-content');
    if (!l) return;
    const r = await fetch('/logs');
    l.textContent = await r.text();
    l.scrollTop = l.scrollHeight;
}

function showModal(id) { document.getElementById(id).style.display = 'flex'; }
function closeModal() { document.querySelectorAll('.overlay').forEach(o => o.style.display = 'none'); }

// Init
setInterval(refreshLogs, 5000);
refreshLogs();
