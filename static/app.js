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

const showPlanFeatureBtn = document.getElementById('show-plan-feature-modal');
const planFeatureModal = document.getElementById('plan-feature-modal');
const planFeatureForm = document.getElementById('plan-feature-form');

const swarmToggleBtn = document.getElementById('swarm-toggle-btn');
let swarmEnabled = false;

const modalCloseBtns = document.querySelectorAll('.modal-close');

// --- Init & Auth ---
async function init() {
    if (authToken) {
        const valid = await checkToken(authToken);
        if (valid) {
            try {
                const swarmRes = await apiCall('/swarm/status');
                swarmEnabled = swarmRes.swarm_enabled;
                if(swarmToggleBtn) updateSwarmUI();
            } catch(e) {}
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
if (showPlanFeatureBtn) {
    showPlanFeatureBtn.addEventListener('click', () => planFeatureModal.classList.remove('hidden'));
}

modalCloseBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        addCredModal.classList.add('hidden');
        addTaskModal.classList.add('hidden');
        if (planFeatureModal) planFeatureModal.classList.add('hidden');
    });
});

if (swarmToggleBtn) {
    swarmToggleBtn.addEventListener('click', async () => {
        swarmEnabled = !swarmEnabled;
        updateSwarmUI();
        try {
            await apiCall('/swarm/toggle', { method: 'POST', body: { enabled: swarmEnabled } });
        } catch(e) {
            swarmEnabled = !swarmEnabled; // revert on fail
            updateSwarmUI();
            alert("Failed to toggle Swarm. Check connection.");
        }
    });
}

const retryFailedBtn = document.getElementById('retry-failed-btn');
if (retryFailedBtn) {
    retryFailedBtn.addEventListener('click', async () => {
        const oldText = retryFailedBtn.textContent;
        retryFailedBtn.textContent = 'Retrying...';
        try {
            await apiCall('/tasks/retry_failed', { method: 'POST' });
            await loadTasks();
        } catch(e) {
            alert('Failed to retry tasks: ' + e.message);
        } finally {
            retryFailedBtn.textContent = oldText;
        }
    });
}

function updateSwarmUI() {
    if (swarmEnabled) {
        swarmToggleBtn.textContent = '🛑 Stop Auto-Swarm';
        swarmToggleBtn.style.background = 'rgba(220, 38, 38, 0.2)';
        swarmToggleBtn.style.color = 'var(--error)';
        swarmToggleBtn.style.borderColor = 'var(--error)';
    } else {
        swarmToggleBtn.textContent = '🚀 Start Auto-Swarm';
        swarmToggleBtn.style.background = '';
        swarmToggleBtn.style.color = 'var(--accent)';
        swarmToggleBtn.style.borderColor = 'var(--accent)';
    }
}

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
            <td>Tier ${t.complexity_score || 1}</td>
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

if (planFeatureForm) {
    planFeatureForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = document.getElementById('plan-submit-btn');
        const originalText = btn.textContent;
        btn.textContent = 'Starting AI Planner...';
        btn.disabled = true;
        
        const payload = {
            project_id: document.getElementById('plan-project').value,
            repo_url: document.getElementById('plan-repo').value,
            feature_description: document.getElementById('plan-desc').value
        };
        
        try {
            const res = await apiCall('/plan_feature', { method: 'POST', body: payload });
            const jobId = res.job_id;
            
            btn.textContent = 'Planning in background (0s)...';
            let elapsed = 0;
            
            const pollInterval = setInterval(async () => {
                elapsed += 2;
                btn.textContent = `Planning in background (${elapsed}s)...`;
                
                try {
                    const statusRes = await apiCall(`/plan_feature/${jobId}`);
                    if (statusRes.status === 'completed') {
                        clearInterval(pollInterval);
                        planFeatureForm.reset();
                        planFeatureModal.classList.add('hidden');
                        loadTasks();
                        document.querySelector('[data-tab="tasks"]').click();
                        btn.textContent = originalText;
                        btn.disabled = false;
                    } else if (statusRes.status === 'failed') {
                        clearInterval(pollInterval);
                        alert("AI Planning failed: " + statusRes.error);
                        btn.textContent = originalText;
                        btn.disabled = false;
                    }
                } catch (pollErr) {
                    console.warn("Poll error:", pollErr);
                }
            }, 2000);
            
        } catch (err) {
            alert("Failed to start planning job.");
            console.error(err);
            btn.textContent = originalText;
            btn.disabled = false;
        }
    });
}

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
