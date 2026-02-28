const vscode = acquireVsCodeApi();

// State
let attachments = [];
let chats = [];
let currentChatId = null;
let isGenerating = false;

// Elements
const chatContainer = document.getElementById('chat-container');
const chatInput = document.getElementById('chat-input');
const attachmentsList = document.getElementById('attachments-list');
const sidebar = document.getElementById('history-sidebar');
const historyList = document.getElementById('history-list');
const historySearch = document.getElementById('history-search');
const sendBtn = document.getElementById('send-btn');
const tokenCountLabel = document.createElement('span');
tokenCountLabel.className = 'token-count';
tokenCountLabel.innerText = '~0 tokens';
const controlsRight = document.querySelector('.right-controls');
if (controlsRight) controlsRight.insertBefore(tokenCountLabel, sendBtn); // Add before Send button

// --- Initialization ---
window.addEventListener('message', event => {
    const message = event.data;
    console.log('Main: Received message', message.type);

    try {
        switch (message.type) {
            case 'render':
                chats = message.chats;
                currentChatId = message.currentId;
                isGenerating = false;
                updateSendButtonState();
                renderAllEnhanced(message);
                break;
            case 'stream':
                isGenerating = true;
                updateSendButtonState();
                appendStreamContent(message.content, message.chatId);
                break;
            case 'endStream':
                isGenerating = false;
                updateSendButtonState();
                break;
            case 'addAttachments':
                attachments = [...attachments, ...message.attachments];
                renderAttachments();
                updateTokenCount();
                break;
            case 'updateAppState':
                if (message.state) {
                    lastRenderState = message.state;
                    if (message.state.availableModels) {
                        updateModelOptions(message.state.availableModels, message.state.model);
                    }
                    const modeSelect = document.getElementById('mode-select');
                    if (modeSelect) modeSelect.value = message.state.mode || 'Chat';
                }
                break;
        }
    } catch (err) {
        console.error('Main: Error processing message', message.type, err);
    }
});

vscode.postMessage({ type: 'init' });

// --- Rendering ---

function renderAll() {
    renderHistory();
    renderChat();
    updateHeader();
}

function updateHeader() {
    const chat = chats.find(c => c.id === currentChatId);
    document.getElementById('header-title').innerText = chat ? chat.title : 'New Chat';
}

function renderChat() {
    chatContainer.innerHTML = '';
    const chat = chats.find(c => c.id === currentChatId);
    if (!chat) return;

    chat.messages.forEach(msg => {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${msg.role}`;

        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';

        // Render Markdown content
        bubble.innerHTML = window.marked ? marked.parse(msg.content) : msg.content;

        // Highlight Code Blocks (if hljs exists)
        if (window.hljs) {
            bubble.querySelectorAll('pre code').forEach((block) => {
                hljs.highlightElement(block);
            });
        }

        // --- Change Widget Rendering ---
        if (msg.changes && msg.changes.length > 0) {
            const widget = renderChangeWidget(msg.changes);
            bubble.appendChild(widget);
        }

        msgDiv.appendChild(bubble);
        chatContainer.appendChild(msgDiv);
    });

    scrollToBottom();
}

function renderChangeWidget(changes) {
    const widget = document.createElement('div');
    widget.className = 'change-widget';

    changes.forEach(change => {
        const row = document.createElement('div');
        row.className = 'change-entry';

        // File Info
        const fileInfo = document.createElement('div');
        fileInfo.className = 'file-info';
        fileInfo.onclick = () => vscode.postMessage({ type: 'showDiff', path: change.path, content: change.content });

        const icon = document.createElement('span');
        icon.className = 'file-icon codicon codicon-file'; // Needs codicons or emoji
        icon.innerText = '📄 ';

        const name = document.createElement('span');
        name.className = 'file-name';
        name.innerText = change.path.split('/').pop();
        name.title = change.path;

        fileInfo.appendChild(icon);
        fileInfo.appendChild(name);

        // Actions
        const actions = document.createElement('div');
        actions.className = 'change-actions';

        const applyBtn = document.createElement('a');
        applyBtn.className = 'action-link apply';
        applyBtn.innerText = 'Apply';
        applyBtn.onclick = (e) => {
            e.stopPropagation();
            vscode.postMessage({ type: 'applyChange', path: change.path, content: change.content });
            applyBtn.innerText = '✓ Applied';
        };

        const undoBtn = document.createElement('a');
        undoBtn.className = 'action-link undo';
        undoBtn.innerText = 'Undo';
        undoBtn.onclick = (e) => {
            e.stopPropagation();
            vscode.postMessage({ type: 'undoChange', path: change.path });
            applyBtn.innerText = 'Apply';
        };

        actions.appendChild(applyBtn);
        actions.appendChild(undoBtn);

        row.appendChild(fileInfo);
        row.appendChild(actions);
        widget.appendChild(row);
    });

    return widget;
}

function appendStreamContent(content, chatId) {
    if (chatId !== currentChatId) return;

    // Simple streaming logic: updates the last assistant message
    // In a real robust app, we'd find the specific message ID. Here we assume last.
    const lastMsg = chatContainer.querySelector('.message.assistant:last-child .message-bubble');
    if (lastMsg) {
        lastMsg.innerHTML = window.marked ? marked.parse(content) : content;
        // Re-highlight
        if (window.hljs) lastMsg.querySelectorAll('pre code').forEach(hljs.highlightElement);
    } else {
        // If no message bubble created yet, trigger a full re-render (fallback)
        // Or create one
    }
    scrollToBottom();
}

function renderAttachments() {
    attachmentsList.innerHTML = '';
    attachments.forEach((att, index) => {
        const chip = document.createElement('span');
        chip.className = 'attachment-chip';
        chip.innerHTML = `<span>📄 ${att.name}</span><span class="remove-attachment" onclick="removeAttachment(${index})">✕</span>`;
        attachmentsList.appendChild(chip);
    });
}

window.removeAttachment = (index) => {
    attachments.splice(index, 1);
    renderAttachments();
};

// --- Interactions ---

document.getElementById('send-btn').onclick = sendMessage;

chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
    // Auto-resize
    e.target.style.height = 'auto';
    e.target.style.height = e.target.scrollHeight + 'px';
});

function sendMessage() {
    if (!chatInput) return;
    const text = chatInput.value ? chatInput.value.trim() : '';
    if (!text && attachments.length === 0) return;

    if (isGenerating) {
        vscode.postMessage({ type: 'stop' });
        return;
    }

    vscode.postMessage({ type: 'send', text, attachments });
    chatInput.value = '';
    chatInput.style.height = 'auto';
    attachments = [];
    renderAttachments();
}

function updateSendButtonState() {
    if (!sendBtn) return;
    if (isGenerating) {
        sendBtn.innerText = 'Stop';
        sendBtn.classList.add('stop-btn');
    } else {
        sendBtn.innerText = 'Send';
        sendBtn.classList.remove('stop-btn');
    }
}

window.sendCtx = (option) => {
    document.getElementById('ctx-menu').style.display = 'none';
    vscode.postMessage({ type: 'openContextDialog', option });
};

document.getElementById('attach-btn').onclick = (e) => {
    e.stopPropagation();
    const menu = document.getElementById('ctx-menu');
    menu.style.display = 'block';
    menu.style.left = e.clientX + 'px';
    menu.style.top = (e.clientY - menu.offsetHeight) + 'px';
};

document.getElementById('tools-btn').onclick = (e) => {
    e.stopPropagation();
    showToolsMenu(e);
};

document.addEventListener('click', () => {
    document.getElementById('ctx-menu').style.display = 'none';
    const toolsMenu = document.getElementById('tools-menu');
    if (toolsMenu) toolsMenu.style.display = 'none';
});

function showToolsMenu(e) {
    let menu = document.getElementById('tools-menu');
    if (!menu) {
        menu = document.createElement('div');
        menu.id = 'tools-menu';
        menu.className = 'menu';
        document.body.appendChild(menu);
    }

    const chat = chats.find(c => c.id === currentChatId);
    // Note: State comes from ChatViewProvider via 'render' message
    // We'll use the state passed in 'render' (state variable)
    const state = lastRenderState || {};

    menu.innerHTML = `
        <div class="menu-item ${state.toolsMode === 'Auto' ? 'active' : ''}" onclick="updateState('toolsMode', 'Auto')">Mode: Auto</div>
        <div class="menu-item ${state.toolsMode === 'Manual' ? 'active' : ''}" onclick="updateState('toolsMode', 'Manual')">Mode: Manual</div>
        <div class="menu-item ${state.toolsMode === 'Disabled' ? 'active' : ''}" onclick="updateState('toolsMode', 'Disabled')">Mode: Disabled</div>
    `;

    if (state.toolsMode === 'Manual' && state.availableTools) {
        menu.innerHTML += '<div class="menu-separator"></div>';
        // Add specific tools if available
        // This is simplified, real implementation would list tools
    }

    menu.style.display = 'block';
    menu.style.left = e.clientX + 'px';
    menu.style.top = (e.clientY - menu.offsetHeight) + 'px';
}

let lastRenderState = null;
const originalRenderAll = renderAll;
function renderAllEnhanced(message) {
    if (!message || !message.state) {
        originalRenderAll();
        return;
    }
    lastRenderState = message.state;
    // Update mode/model selects if they exist
    const modeSelect = document.getElementById('mode-select');
    if (modeSelect) modeSelect.value = message.state.mode || 'Chat';

    if (message.state.availableModels) {
        updateModelOptions(message.state.availableModels, message.state.model);
    }
    originalRenderAll();
}

function updateModelOptions(models, current) {
    const select = document.getElementById('model-select');
    if (!select || !Array.isArray(models)) return;

    select.innerHTML = '';
    models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m;
        opt.innerText = m;
        if (m === current) opt.selected = true;
        select.appendChild(opt);
    });
}

window.updateState = (key, value) => {
    vscode.postMessage({ type: 'updateState', key, value });
};

// Sidebar Logic
document.querySelector('.header-left .icon-btn').onclick = toggleSidebar;
document.querySelector('.close-sidebar-btn').onclick = toggleSidebar; // Close btn inside sidebar

function toggleSidebar() {
    sidebar.classList.toggle('open');
}

function renderHistory() {
    historyList.innerHTML = '';
    const filter = historySearch.value.toLowerCase();

    chats.forEach(chat => {
        if (filter && !chat.title.toLowerCase().includes(filter)) return;

        const item = document.createElement('div');
        item.className = 'history-item' + (chat.id === currentChatId ? ' active' : '');
        item.onclick = () => {
            vscode.postMessage({ type: 'loadChat', id: chat.id });
            toggleSidebar();
        };

        const title = document.createElement('span');
        title.className = 'history-title';
        title.innerText = chat.title;

        const actions = document.createElement('div');
        actions.className = 'history-actions';

        const editBtn = document.createElement('span');
        editBtn.className = 'action-icon';
        editBtn.innerText = '✏️';
        editBtn.onclick = (e) => {
            e.stopPropagation();
            vscode.postMessage({ type: 'requestRename', id: chat.id, currentTitle: chat.title });
        };

        const delBtn = document.createElement('span');
        delBtn.className = 'action-icon';
        delBtn.innerText = '🗑️';
        delBtn.onclick = (e) => {
            e.stopPropagation();
            vscode.postMessage({ type: 'deleteChat', id: chat.id });
        };

        actions.appendChild(editBtn);
        actions.appendChild(delBtn);
        item.appendChild(title);
        item.appendChild(actions);
        historyList.appendChild(item);
    });
}

historySearch.addEventListener('input', renderHistory);

function scrollToBottom() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

// Paste Handler for File Attachments
chatInput.addEventListener('paste', (e) => {
    const clipboardData = e.clipboardData || window.clipboardData;
    if (!clipboardData) return;

    const files = [];

    // 1. Try to get actual file objects (may have .path in some environments)
    if (clipboardData.files && clipboardData.files.length > 0) {
        for (let i = 0; i < clipboardData.files.length; i++) {
            const f = clipboardData.files[i];
            if (f.path) files.push(f.path);
        }
    }

    // 2. If no files with paths found, check text/plain for path-like strings
    // (Common when copying files in VS Code or some OS configurations)
    if (files.length === 0) {
        const text = clipboardData.getData('text/plain');
        if (text && (text.includes('/') || text.includes('\\')) && text.length < 500) {
            // Check if it looks like a path (starts with / or has drive letter)
            if (text.startsWith('/') || /^[a-zA-Z]:\\/.test(text)) {
                console.log('Main: Detected path-like string in paste:', text);
                files.push(text.trim());
            }
        }
    }

    if (files.length > 0) {
        vscode.postMessage({ type: 'filesDropped', paths: files });
    }
});

// Drag & Drop
const dropOverlay = document.createElement('div');
dropOverlay.className = 'drag-overlay';
dropOverlay.innerHTML = '<div class="drag-overlay-content">Drop files to attach</div>';
document.body.appendChild(dropOverlay);

window.addEventListener('dragenter', (e) => {
    e.preventDefault();
    dropOverlay.classList.add('active');
});

window.addEventListener('dragleave', (e) => {
    if (e.clientX === 0 || e.clientY === 0) dropOverlay.classList.remove('active');
});

window.addEventListener('dragover', e => e.preventDefault());

window.addEventListener('drop', (e) => {
    e.preventDefault();
    dropOverlay.classList.remove('active');

    console.log('Main: Drop event detected');
    const files = [];

    // 1. Try to get paths from dataTransfer.files
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        for (let i = 0; i < e.dataTransfer.files.length; i++) {
            const f = e.dataTransfer.files[i];
            if (f.path) files.push(f.path);
        }
    }

    // 2. Try to get paths from dataTransfer.items or strings
    if (files.length === 0) {
        // Dragging from VS Code Explorer often provides paths in text/plain
        const text = e.dataTransfer.getData('text/plain');
        if (text) {
            const lines = text.split('\n').map(l => l.trim()).filter(l => l);
            for (const line of lines) {
                if (line.startsWith('/') || /^[a-zA-Z]:\\/.test(line)) {
                    files.push(line);
                }
            }
        }
    }

    if (files.length > 0) {
        vscode.postMessage({ type: 'filesDropped', paths: files });
    } else {
        console.warn('Main: No file paths found in drop event.');
    }
});
