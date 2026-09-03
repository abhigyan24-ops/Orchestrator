const API_BASE = '/api';
let authToken = localStorage.getItem('mcp_auth_token');

// DOM Elements
const loginScreen = document.getElementById('login-screen');
const dashboard = document.getElementById('dashboard');
const authInput = document.getElementById('auth-token');
const loginBtn = document.getElementById('login-btn');
const loginError = document.getElementById('login-error');
const logoutBtn = document.getElementById('logout-btn');

const navBtns = document.querySelectorAll('.nav-btn');
const tabContents = document.querySelectorAll('.tab-content');

const credTableBody = document.querySelector('#cred-table tbody');
const taskTableBody = document.querySelector('#task-table tbody');

// Modals
const showAddCredBtn = document.getElementById('show-add-cred-modal');
const addCredModal = document.getElementById('add-cred-modal');
const addCredForm = document.getElementById('add-cred-form');

const showAddTaskBtn = document.getElementById('show-add-task-modal');
const addTaskModal = document.getElementById('add-task-modal');
const addTaskForm = document.getElementById('add-task-form');

const modalCloseBtns = document.querySelectorAll('.modal-close');

// --- Init & Auth ---
async function init() {
    if (authToken) {
        const valid = await checkToken(authToken);
        if (valid) {
            showDashboard();
            return;
        }
    }
    showLogin();
}

async function checkToken(token) {
    try {
        const res = await fetch(`${API_BASE}/credentials`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return res.ok;
    } catch (e) {
        return false;
    }
}

loginBtn.addEventListener('click', async () => {
    const token = authInput.value.trim();
    if (!token) return;
    
    loginBtn.textContent = 'Verifying...';
    const valid = await checkToken(token);
    
    if (valid) {
        authToken = token;
        localStorage.setItem('mcp_auth_token', token);
        loginError.classList.add('hidden');
        showDashboard();
    } else {
        loginError.classList.remove('hidden');
    }
    loginBtn.textContent = 'Access Brain';
});

logoutBtn.addEventListener('click', () => {
    authToken = null;
    localStorage.removeItem('mcp_auth_token');
    showLogin();
});

function showDashboard() {
    loginScreen.classList.add('hidden');
    dashboard.classList.remove('hidden');
    loadCredentials();
    loadTasks();
}

function showLogin() {
    dashboard.classList.add('hidden');
    loginScreen.classList.remove('hidden');
}

// --- Navigation ---
navBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        navBtns.forEach(b => b.classList.remove('active'));
        tabContents.forEach(t => t.classList.remove('active'));
        
        btn.classList.add('active');
        document.getElementById(`${btn.dataset.tab}-tab`).classList.add('active');
    });
});

// --- Modal Handlers ---
showAddCredBtn.addEventListener('click', () => addCredModal.classList.remove('hidden'));
showAddTaskBtn.addEventListener('click', () => addTaskModal.classList.remove('hidden'));

modalCloseBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        addCredModal.classList.add('hidden');
        addTaskModal.classList.add('hidden');
    });
});

// --- API Interactions ---
async function apiCall(endpoint, options = {}) {
    if (!options.headers) options.headers = {};
    options.headers['Authorization'] = `Bearer ${authToken}`;
    if (options.body && !(options.body instanceof FormData)) {
        options.headers['Content-Type'] = 'application/json';
        if (typeof options.body === 'object') {
            options.body = JSON.stringify(options.body);
        }
    }
    const res = await fetch(`${API_BASE}${endpoint}`, options);
    if (res.status === 401) {
        logoutBtn.click();
        throw new Error("Unauthorized");
    }
    return res.json();
}

// Credentials
async function loadCredentials() {
    const creds = await apiCall('/credentials');
    credTableBody.innerHTML = '';
    
    if (creds.length === 0) {
        credTableBody.innerHTML = '<tr><td colspan="5">No credentials configured.</td></tr>';
        return;
    }

    creds.forEach(c => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${c.tool_name}</strong></td>
            <td>${c.account_label}</td>
            <td>${c.tool_type}</td>
            <td><span class="status-badge status-${c.status}">${c.status}</span></td>
            <td><button class="delete-btn" onclick="deleteCred(${c.id})">Delete</button></td>
        `;
        credTableBody.appendChild(tr);
    });
}

addCredForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
        tool_name: document.getElementById('cred-tool').value,
        account_label: document.getElementById('cred-label').value,
        api_key: document.getElementById('cred-key').value,
        tool_type: document.getElementById('cred-type').value
    };
    
    await apiCall('/credentials', { method: 'POST', body: payload });
    addCredForm.reset();
    addCredModal.classList.add('hidden');
    loadCredentials();
});

window.deleteCred = async function(id) {
    if (!confirm('Are you sure you want to delete this credential?')) return;
    await apiCall(`/credentials/${id}`, { method: 'DELETE' });
    loadCredentials();
};

// Tasks
async function loadTasks() {
    const tasks = await apiCall('/tasks');
    taskTableBody.innerHTML = '';
    
    if (tasks.length === 0) {
        taskTableBody.innerHTML = '<tr><td colspan="6">No tasks found.</td></tr>';
        return;
    }

    tasks.forEach(t => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>#${t.id}</td>
            <td>${t.project_id}</td>
            <td>${t.title}</td>
            <td><span class="status-badge status-${t.status}">${t.status}</span></td>
            <td>${t.assigned_tool || '-'}</td>
            <td>${new Date(t.created_at).toLocaleString()}</td>
        `;
        taskTableBody.appendChild(tr);
    });
}

addTaskForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
        project_id: document.getElementById('task-project').value,
        title: document.getElementById('task-title').value,
        category: document.getElementById('task-category').value,
        description: document.getElementById('task-desc').value
    };
    
    await apiCall('/tasks', { method: 'POST', body: payload });
    addTaskForm.reset();
    addTaskModal.classList.add('hidden');
    loadTasks();
    
    // Switch to tasks tab
    document.querySelector('[data-tab="tasks"]').click();
});

// Periodic refresh for tasks (every 10s)
setInterval(() => {
    if (authToken && !dashboard.classList.contains('hidden')) {
        loadTasks();
    }
}, 10000);

// --- Setup Guide Interactivity ---
const toolCards = document.querySelectorAll('.tool-card');
const setupPanels = document.querySelectorAll('.setup-panel');
const copyBtns = document.querySelectorAll('.copy-btn');

toolCards.forEach(card => {
    card.addEventListener('click', () => {
        // Remove active class from all cards and panels
        toolCards.forEach(c => c.classList.remove('active'));
        setupPanels.forEach(p => p.classList.add('hidden'));
        
        // Add active class to clicked card and show its panel
        card.classList.add('active');
        const targetPanel = document.getElementById(card.dataset.target);
        if (targetPanel) {
            targetPanel.classList.remove('hidden');
        }
    });
});

copyBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        const targetId = btn.dataset.copy;
        const codeElement = document.getElementById(targetId);
        if (codeElement) {
            navigator.clipboard.writeText(codeElement.textContent).then(() => {
                const originalText = btn.textContent;
                btn.textContent = 'Copied!';
                btn.style.background = 'rgba(16, 185, 129, 0.2)';
                btn.style.color = 'var(--success)';
                btn.style.borderColor = 'var(--success)';
                
                setTimeout(() => {
                    btn.textContent = originalText;
                    btn.style.background = '';
                    btn.style.color = '';
                    btn.style.borderColor = '';
                }, 2000);
            });
        }
    });
});

// Run init on load
init();
