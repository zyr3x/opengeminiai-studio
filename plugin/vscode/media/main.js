const vscode = acquireVsCodeApi();

// State
let attachments = [];
let chats = [];
let currentChatId = null;
let isGenerating = false;

// Elements
const chatContainer = document.getElementById('chat-container');
const inputArea = document.getElementById('input-area');
const attachmentsList = document.getElementById('attachments-list');
const sidebar = document.getElementById('history-sidebar');
const historyList = document.getElementById('history-list');
const historySearch = document.getElementById('history-search');
const sendBtn = document.getElementById('send-btn');
const tokenCountLabel = document.createElement('span');
tokenCountLabel.className = 'token-count';
tokenCountLabel.innerText = '~0 tokens';
document.querySelector('.right-controls').insertBefore(tokenCountLabel, sendBtn); // Add before Send button

// --- Initialization ---
window.addEventListener('message', event => {
    const message = event.data;
    switch (message.type) {
        case 'render':
            chats = message.chats;
            currentChatId = message.currentId;
            isGenerating = false;
            updateSendButtonState();
            renderAll();
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

inputArea.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
    // Auto-resize
    e.target.style.height = 'auto';
    e.target.style.height = e.target.scrollHeight + 'px';
});

function sendMessage() {
    const text = inputArea.value.trim();
    if (!text && attachments.length === 0) return;

    vscode.postMessage({ type: 'send', text, attachments });
    inputArea.value = '';
    inputArea.style.height = 'auto';
    attachments = [];
    renderAttachments();
}

document.getElementById('attach-btn').onclick = () => {
    vscode.postMessage({ type: 'addContext' });
};

// Sidebar Logic
document.querySelector('.header-left .icon-btn').onclick = toggleSidebar;
document.querySelector('.history-header .icon-btn').onclick = toggleSidebar; // Close btn inside sidebar

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

        const delBtn = document.createElement('span');
        delBtn.className = 'delete-chat';
        delBtn.innerText = '🗑️';
        delBtn.onclick = (e) => {
            e.stopPropagation();
            vscode.postMessage({ type: 'deleteChat', id: chat.id });
        };

        item.appendChild(title);
        item.appendChild(delBtn);
        historyList.appendChild(item);
    });
}

historySearch.addEventListener('input', renderHistory);

function scrollToBottom() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

// Drag & Drop
const dropOverlay = document.createElement('div');
dropOverlay.className = 'drag-overlay';
dropOverlay.innerHTML = '<div class="drag-overlay-content">Drop files to attach</div>';
document.body.appendChild(dropOverlay);

window.addEventListener('dragenter', () => dropOverlay.classList.add('active'));
window.addEventListener('dragleave', (e) => {
    if (e.clientX === 0 || e.clientY === 0) dropOverlay.classList.remove('active');
});
window.addEventListener('drop', (e) => {
    e.preventDefault();
    dropOverlay.classList.remove('active');

    const files = [];
    if (e.dataTransfer.items) {
        for (let i = 0; i < e.dataTransfer.items.length; i++) {
            const item = e.dataTransfer.items[i];
            if (item.kind === 'file') {
                const f = item.getAsFile();
                if (f) files.push(f.path); // VS Code webview specific property
            }
        }
    }
    if (files.length) vscode.postMessage({ type: 'filesDropped', paths: files });
});
window.addEventListener('dragover', e => e.preventDefault());
