// Main controller

let modelsList = [];
let monitorWs = null;
let logsWs = null;
let taskWs = null;
let profiles = [];

document.addEventListener('DOMContentLoaded', async () => {
    // 1. Fetch initial data
    await fetchModels();
    await fetchStatus();
    await fetchProfiles();

    // 2. Setup websockets
    setupWebSockets();

    // 3. Bind events — original
    document.getElementById('btn-launch').addEventListener('click', launchModel);
    document.getElementById('btn-stop').addEventListener('click', stopModel);
    document.getElementById('model-select').addEventListener('change', onModelSelectChange);
    document.getElementById('btn-load-ctx').addEventListener('click', loadContext);
    document.getElementById('btn-save-ctx').addEventListener('click', saveContext);

    // 4. Bind events — task router
    document.getElementById('task-type').addEventListener('change', onTaskTypeChange);
    document.getElementById('btn-send-task').addEventListener('click', sendTask);

    // Initial context load
    loadContext();
});


// ═══════════════════════════════════════════════════════════════
// Task Router
// ═══════════════════════════════════════════════════════════════

async function fetchProfiles() {
    try {
        const res = await fetch('/api/tasks/profiles');
        if (!res.ok) return;
        profiles = await res.json();

        const select = document.getElementById('task-type');
        select.innerHTML = '<option value="">-- Select task type --</option>';

        profiles.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.name;
            opt.textContent = `${p.name} — ${p.description}`;
            select.appendChild(opt);
        });
    } catch (err) {
        console.error("Failed to fetch profiles:", err);
    }
}

function onTaskTypeChange(e) {
    const name = e.target.value;
    const profile = profiles.find(p => p.name === name);
    const infoDiv = document.getElementById('profile-info');

    if (profile) {
        infoDiv.style.display = 'block';

        // Model badge
        const modelBadge = document.getElementById('badge-model');
        modelBadge.textContent = profile.model;
        modelBadge.className = 'badge badge-model';

        // Hardware badge
        const hwBadge = document.getElementById('badge-hardware');
        hwBadge.textContent = profile.hardware.toUpperCase();
        hwBadge.className = `badge badge-${profile.hardware}`;

        // Priority badge
        const priBadge = document.getElementById('badge-priority');
        priBadge.textContent = `P${profile.priority}`;
        priBadge.className = 'badge badge-priority';

        // Guide text
        document.getElementById('profile-guide').textContent = profile.guide;
    } else {
        infoDiv.style.display = 'none';
    }
}

function sendTask() {
    const taskType = document.getElementById('task-type').value;
    const prompt = document.getElementById('task-prompt').value.trim();

    if (!taskType) { alert('Select a task type'); return; }
    if (!prompt) { alert('Enter a prompt'); return; }

    const outputBox = document.getElementById('task-output');
    const statusText = document.getElementById('task-status-text');
    const tpsBadge = document.getElementById('task-tps');

    // Clear output
    outputBox.textContent = '';
    statusText.textContent = 'Sending...';
    tpsBadge.style.display = 'none';

    // Send via task WebSocket
    if (taskWs && taskWs.isConnected) {
        taskWs.send(JSON.stringify({ task_type: taskType, prompt: prompt }));
    } else {
        statusText.textContent = 'WebSocket not connected!';
    }
}

function handleTaskEvent(rawData) {
    try {
        const msg = JSON.parse(rawData);
        const outputBox = document.getElementById('task-output');
        const statusText = document.getElementById('task-status-text');
        const tpsBadge = document.getElementById('task-tps');

        switch (msg.event) {
            case 'status':
                statusText.textContent = msg.data;
                break;

            case 'token':
                outputBox.textContent += msg.data;
                outputBox.scrollTop = outputBox.scrollHeight;
                statusText.textContent = 'Generating...';
                break;

            case 'done':
                statusText.textContent = 'Completed ✓';
                if (msg.data && msg.data.tokens_per_sec) {
                    tpsBadge.textContent = `${msg.data.tokens_per_sec} tok/s`;
                    tpsBadge.style.display = 'inline-block';
                }
                // Refresh history
                fetchHistory();
                break;

            case 'error':
                statusText.textContent = `Error: ${msg.data}`;
                break;
        }
    } catch (e) {
        console.error("Task event parse error:", e);
    }
}

async function fetchHistory() {
    try {
        const res = await fetch('/api/tasks/history');
        if (!res.ok) return;
        const items = await res.json();

        const container = document.getElementById('task-history');
        if (items.length === 0) {
            container.innerHTML = '<p class="text-muted">No tasks yet.</p>';
            return;
        }

        container.innerHTML = items.reverse().map(item => `
            <div class="history-item">
                <span class="hi-profile">${item.profile_name}</span>
                <span class="hi-model">${item.model_used}</span>
                <span class="hi-tps">${item.tokens_per_sec} tok/s</span>
                <span class="hi-duration">${item.duration_sec}s</span>
            </div>
        `).join('');
    } catch (err) {
        console.error("Failed to fetch history:", err);
    }
}


// ═══════════════════════════════════════════════════════════════
// Original: Models, Launch, Status
// ═══════════════════════════════════════════════════════════════

async function fetchModels() {
    try {
        const res = await fetch('/api/models');
        if (!res.ok) throw new Error("Failed to fetch models");
        modelsList = await res.json();

        const select = document.getElementById('model-select');
        select.innerHTML = '<option value="">-- Select a model --</option>';

        modelsList.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.name;
            opt.textContent = `${m.name} [${m.backend}] ${m.size_gb ? '(' + m.size_gb + ' GB)' : ''}`;
            if (m.path) opt.dataset.path = m.path;
            select.appendChild(opt);
        });
    } catch (err) {
        console.error(err);
    }
}

function onModelSelectChange(e) {
    const name = e.target.value;
    const model = modelsList.find(m => m.name === name);
    document.getElementById('backend-input').value = model ? (model.backend || 'auto') : '';
    document.getElementById('path-input').value = model ? (model.path || 'N/A') : '';
}

async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        if (res.ok) {
            const data = await res.json();
            updateActiveModelUI(data.model);
            if (window.updateCharts) window.updateCharts(data.resources);
        }
    } catch (err) { console.error("Status fetch failed:", err); }
}

async function launchModel() {
    const name = document.getElementById('model-select').value;
    if (!name) { alert("Please select a model"); return; }

    const payload = {
        name,
        backend: document.getElementById('backend-input').value,
        gpu_layers: parseInt(document.getElementById('gpu-layers').value) || -1,
        ctx_size: parseInt(document.getElementById('ctx-size').value) || 2048,
    };

    const path = document.getElementById('path-input').value;
    if (path !== 'N/A') payload.path = path;
    const quant = document.getElementById('quant-dropdown').value;
    if (quant) payload.quantization = quant;

    try {
        const res = await fetch('/api/launch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok) {
            fetchStatus();
            document.getElementById('log-output').textContent = `Launching ${name}...\n`;
        } else {
            alert(`Error: ${data.detail?.warning || data.detail || 'Launch failed'}`);
        }
    } catch (err) { alert("Network error launching model"); }
}

async function stopModel() {
    try {
        const res = await fetch('/api/stop', { method: 'POST' });
        if (res.ok) {
            fetchStatus();
            document.getElementById('log-output').textContent += `\n[Model stopped]\n`;
        }
    } catch (err) { console.error(err); }
}

function updateActiveModelUI(modelInfo) {
    const activeText = document.getElementById('active-model-info');
    const card = document.getElementById('active-model-card');
    if (modelInfo) {
        activeText.innerHTML = `
            <strong>Name:</strong> ${modelInfo.name}<br>
            <strong>Backend:</strong> ${modelInfo.backend}<br>
            <strong>Context:</strong> ${modelInfo.ctx_size || 2048}<br>
            <strong>GPU Layers:</strong> ${modelInfo.gpu_layers || 0}`;
        card.classList.add('pulse');
    } else {
        activeText.textContent = "No model running.";
        card.classList.remove('pulse');
    }
}

async function loadContext() {
    try {
        const res = await fetch('/api/context');
        if (res.ok) {
            const data = await res.json();
            document.getElementById('context-viewer').textContent = JSON.stringify(data, null, 2);
        }
    } catch (err) { console.error("Failed to load context:", err); }
}

async function saveContext() {
    try {
        const text = document.getElementById('context-viewer').textContent;
        const data = JSON.parse(text);
        const res = await fetch('/api/context', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (res.ok) alert("Context saved successfully");
        else alert("Failed to save context");
    } catch (err) { alert("Invalid JSON format"); }
}


// ═══════════════════════════════════════════════════════════════
// WebSockets
// ═══════════════════════════════════════════════════════════════

function setupWebSockets() {
    if (!window.HyperWebSocket) return;

    // Monitor stream
    monitorWs = new HyperWebSocket('/ws/monitor', (data) => {
        try {
            const snapshot = JSON.parse(data);
            if (window.updateCharts) window.updateCharts(snapshot);
        } catch (e) { }
    });
    monitorWs.connect();

    // Logs stream
    const logBox = document.getElementById('log-output');
    logsWs = new HyperWebSocket('/ws/logs', (data) => {
        logBox.textContent += data;
        logBox.scrollTop = logBox.scrollHeight;
    });
    logsWs.connect();

    // Task stream
    taskWs = new HyperWebSocket('/ws/task', handleTaskEvent);
    taskWs.connect();
}
