import * as vscode from 'vscode';
import { ApiClient } from '../services/ApiClient';
import { Conversation, ChatMessage, Attachment, AppState, McpToolsResponse } from '../model';
import * as fs from 'fs';

export class ChatViewProvider implements vscode.WebviewViewProvider {
    private _view?: vscode.WebviewView;
    private conversations: Conversation[] = [];
    private currentId?: string;
    
    // State
    private appState: AppState = {
        mode: 'Chat',
        model: 'gemini-2.5-flash',
        toolsMode: 'Auto',
        selectedTools: [],
        availableModels: ['gemini-2.5-flash'],
        availableTools: null
    };

    constructor(private context: vscode.ExtensionContext) {
        this.conversations = context.globalState.get('history', []);
        // Restore last state
        const savedState = context.globalState.get<Partial<AppState>>('appState', {});
        this.appState = { ...this.appState, ...savedState };
    }

    async resolveWebviewView(webviewView: vscode.WebviewView) {
        this._view = webviewView;
        webviewView.webview.options = { 
            enableScripts: true,
            localResourceRoots: [this.context.extensionUri] 
        };
        
        webviewView.webview.html = this.getHtml(webviewView.webview);

        // Initial Data Fetch
        this.refreshBackendData();

        webviewView.webview.onDidReceiveMessage(async (m) => {
            try {
                switch (m.type) {
                    case 'init': this.updateUI(); break;
                    case 'send': await this.handleSend(m.text); break;
                    case 'newChat': this.createNewChat(); break;
                    case 'deleteChat': this.deleteChat(m.id); break;
                    case 'loadChat': this.loadChat(m.id);
                    case 'saveDraft': this.saveDraft(m.text, m.attachments); break;
                    case 'applyChange': await this.applyFileChange(m.path, m.content); break;
                    case 'updateState': this.updateState(m.key, m.value); break;
                    case 'addContext': this.openContextDialog(); break;
                    case 'openSettings': vscode.commands.executeCommand('workbench.action.openSettings', 'opengeminiai'); break;
                    case 'copy': vscode.env.clipboard.writeText(m.text); break;
                }
            } catch (e: any) {
                vscode.window.showErrorMessage(`OpenGemini Error: ${e.message}`);
            }
        });
    }

    private async refreshBackendData() {
        const [models, tools] = await Promise.all([
            ApiClient.getModels(),
            ApiClient.getMcpTools()
        ]);
        this.appState.availableModels = models;
        this.appState.availableTools = tools;
        this.updateUI();
    }

    public async sendMessage(text: string) {
        await vscode.commands.executeCommand('opengeminiai.chatView.focus');
        // Create draft if needed
        if (!this.currentId) this.createNewChat();
        // Wait for UI
        setTimeout(async () => {
             await this.handleSend(text);
        }, 500);
    }

    private async handleSend(text: string) {
        if (!this.currentId) this.createNewChat();
        const chat = this.conversations.find(c => c.id === this.currentId);
        if (!chat) return;

        // Construct full content with attachments
        let fullContent = text;
        const attachments = chat.draftAttachments || [];
        
        if (attachments.length > 0) {
            fullContent += "\n\n";
            attachments.forEach(a => {
                if (a.type === 'file') {
                    fullContent += `code_path=${a.data}`;
                    if (a.ignoreTypes) fullContent += ` ignore_type=${a.ignoreTypes}`;
                    if (a.ignoreFiles) fullContent += ` ignore_file=${a.ignoreFiles}`;
                    if (a.ignoreDirs) fullContent += ` ignore_dir=${a.ignoreDirs}`;
                    fullContent += "\n";
                } else {
                    fullContent += `\n:::CTX:${a.name}:text:::\n${a.data}\n:::END:::`;
                }
            });
        }

        // Reset draft
        chat.draftInput = "";
        chat.draftAttachments = [];

        // Add User Message
        chat.messages.push({ role: 'user', content: fullContent });
        
        // Add Assistant Placeholder
        const assistantMsg: ChatMessage = { role: 'assistant', content: "Thinking..." };
        chat.messages.push(assistantMsg);

        this.save();
        this.updateUI();

        // Generate Title if new
        if (chat.title === "New Chat" && chat.messages.length === 2) {
           this.generateTitle(chat, fullContent);
        }

        try {
            const systemPrompt = await ApiClient.getPromptText(this.appState.mode);
            
            // Tools Logic
            let toolsToSend: string[] | null = null;
            if (this.appState.toolsMode === 'Disabled') toolsToSend = ['TOOLS_DISABLED'];
            else if (this.appState.toolsMode === 'Manual') toolsToSend = this.appState.selectedTools;

            assistantMsg.content = "";
            
            await ApiClient.streamChat(
                [{ role: 'system', content: systemPrompt }, ...chat.messages.slice(0, -1)], 
                this.appState.model, 
                (chunk) => {
                    assistantMsg.content += chunk;
                    this._view?.webview.postMessage({ type: 'stream', content: assistantMsg.content, chatId: chat.id });
                },
                toolsToSend
            );

            this.parseChanges(assistantMsg);
            this.save();
            this.updateUI();
        } catch (err: any) {
            assistantMsg.content += `\n\n[Error: ${err.message}]`;
            this.save();
            this.updateUI();
        }
    }

    private async generateTitle(chat: Conversation, content: string) {
        try {
            const prompt = await ApiClient.getPromptText('Title');
            const cleanContent = content.substring(0, 1000); // Limit context
            let title = "";
            await ApiClient.streamChat(
                [{ role: 'system', content: prompt }, { role: 'user', content: cleanContent }],
                'gemini-2.5-flash',
                (chunk) => title += chunk
            );
            chat.title = title.replace(/"/g, '').trim();
            this.save();
            this.updateUI();
        } catch {}
    }

    private parseChanges(msg: ChatMessage) {
        const match = msg.content.match(/```json\s*([\s\S]*?)\s*```/);
        if (match) {
            try {
                const parsed = JSON.parse(match[1]);
                if (parsed.action === 'propose_changes') msg.changes = parsed.changes;
            } catch {}
        }
    }

    private async applyFileChange(path: string, content: string) {
        const uri = vscode.Uri.file(path);
        const tempUri = vscode.Uri.parse(`untitled:${path}`);
        const edit = new vscode.WorkspaceEdit();
        edit.insert(tempUri, new vscode.Position(0, 0), content);
        await vscode.workspace.applyEdit(edit);
        await vscode.commands.executeCommand('vscode.diff', uri, tempUri);
    }

    private createNewChat() {
        const chat: Conversation = { 
            id: Date.now().toString(), 
            title: "New Chat", 
            messages: [], 
            timestamp: Date.now(), 
            draftInput: "",
            draftAttachments: []
        };
        this.conversations.unshift(chat);
        this.currentId = chat.id;
        this.save();
        this.updateUI();
    }

    private deleteChat(id: string) {
        this.conversations = this.conversations.filter(c => c.id !== id);
        if (this.currentId === id) {
            this.currentId = this.conversations.length > 0 ? this.conversations[0].id : undefined;
        }
        this.save();
        this.updateUI();
    }
    
    private loadChat(id: string) {
        this.currentId = id;
        this.updateUI();
    }

    private saveDraft(text: string, attachments: Attachment[]) {
        const chat = this.conversations.find(c => c.id === this.currentId);
        if (chat) { 
            chat.draftInput = text; 
            chat.draftAttachments = attachments;
            this.save(); 
        }
    }

    private updateState(key: keyof AppState, value: any) {
        (this.appState as any)[key] = value;
        this.context.globalState.update('appState', this.appState);
        this.updateUI();
    }

    private async openContextDialog() {
        const uris = await vscode.window.showOpenDialog({ 
            canSelectMany: true, 
            canSelectFiles: true, 
            canSelectFolders: true 
        });
        if (uris) {
            const newAttachments = uris.map(uri => ({
                type: 'file',
                name: uri.path.split('/').pop() || 'file',
                data: uri.fsPath
            }));
            this._view?.webview.postMessage({ type: 'addAttachments', attachments: newAttachments });
        }
    }

    private save() { this.context.globalState.update('history', this.conversations); }
    
    private updateUI() { 
        this._view?.webview.postMessage({ 
            type: 'render', 
            chats: this.conversations, 
            currentId: this.currentId,
            state: this.appState
        }); 
    }

    private getHtml(webview: vscode.Webview) { 
        const cspSource = webview.cspSource;
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${cspSource} 'unsafe-inline' https:; script-src ${cspSource} 'unsafe-inline' https:; img-src ${cspSource} https: data:;">
    <title>OpenGemini Studio</title>
    <!-- Markdown & Highlight -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <style>
        :root {
            --bg: var(--vscode-editor-background);
            --fg: var(--vscode-editor-foreground);
            --border: var(--vscode-panel-border);
            --input-bg: var(--vscode-input-background);
            --input-fg: var(--vscode-input-foreground);
            --hover: var(--vscode-list-hoverBackground);
        }
        body { padding: 0; margin: 0; font-family: var(--vscode-font-family); color: var(--fg); background: var(--bg); height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
        
        /* HEADER */
        .header { padding: 8px 12px; background: var(--vscode-sideBarSectionHeader-background); border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; height: 32px; flex-shrink: 0; }
        .header-title { font-weight: bold; font-size: 13px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; max-width: 60%; }
        .icon-btn { cursor: pointer; padding: 4px; border-radius: 4px; background: transparent; border: none; color: var(--fg); display: flex; align-items: center; justify-content: center; }
        .icon-btn:hover { background: var(--hover); }

        /* MAIN LAYOUT */
        .main-container { flex: 1; position: relative; display: flex; overflow: hidden; min-height: 0; }
        
        /* SIDEBAR (HISTORY) */
        .sidebar { width: 0; transition: width 0.2s; background: var(--vscode-sideBar-background); border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; }
        .sidebar.open { width: 250px; }
        .history-list { flex: 1; overflow-y: auto; padding: 5px; }
        .history-item { padding: 8px; cursor: pointer; border-radius: 4px; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: flex; justify-content: space-between; }
        .history-item:hover { background: var(--hover); }
        .history-item.active { background: var(--vscode-list-activeSelectionBackground); color: var(--vscode-list-activeSelectionForeground); }

        /* CHAT AREA */
        .chat-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; position: relative; min-height: 0; }
        .messages-list { flex: 1; overflow-y: auto; padding: 10px; display: flex; flex-direction: column; gap: 12px; scroll-behavior: smooth; }
        
        /* BUBBLES */
        .bubble { max-width: 90%; padding: 8px 12px; border-radius: 8px; font-size: 13px; line-height: 1.4; position: relative; overflow-wrap: anywhere; }
        .bubble.user { align-self: flex-end; background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); }
        .bubble.assistant { align-self: flex-start; background: var(--vscode-editor-inactiveSelectionBackground); border: 1px solid var(--border); }
        .bubble-footer { display: flex; justify-content: flex-end; gap: 5px; margin-top: 5px; opacity: 0.6; font-size: 10px; }

        /* CONTENT RENDERING */
        .content p { margin: 5px 0; }
        .content pre { background: #1e1e1e; padding: 8px; border-radius: 4px; overflow-x: auto; max-width: 100%; white-space: pre-wrap; word-wrap: break-word; }
        .content code { font-family: var(--vscode-editor-font-family); font-size: 0.9em; }
        .change-widget { border: 1px solid var(--border); border-radius: 4px; margin-top: 8px; background: var(--bg); overflow: hidden; }
        .change-header { padding: 6px; background: var(--vscode-sideBar-background); display: flex; justify-content: space-between; align-items: center; font-size: 11px; }
        .btn-small { background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; padding: 2px 8px; border-radius: 2px; cursor: pointer; font-size: 10px; }

        /* FOOTER CONTROLS */
        .footer { border-top: 1px solid var(--border); padding: 8px; background: var(--bg); display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; }
        
        .attachments-area { display: flex; flex-wrap: wrap; gap: 5px; min-height: 0; }
        .attachment-chip { font-size: 11px; background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); padding: 2px 6px; border-radius: 10px; display: flex; align-items: center; gap: 4px; }
        .attachment-chip span { cursor: pointer; font-weight: bold; }

        .input-wrapper { display: flex; gap: 8px; border: 1px solid var(--border); border-radius: 6px; padding: 6px; background: var(--input-bg); }
        textarea { flex: 1; background: transparent; border: none; color: var(--input-fg); resize: none; min-height: 40px; font-family: inherit; outline: none; }

        .controls-row { display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: var(--vscode-descriptionForeground); }
        .controls-left, .controls-right { display: flex; gap: 8px; align-items: center; }
        
        select { background: var(--vscode-dropdown-background); color: var(--vscode-dropdown-foreground); border: 1px solid var(--vscode-dropdown-border); padding: 2px 4px; border-radius: 2px; outline: none; font-size: 11px; }
        .send-btn { background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; padding: 4px 12px; border-radius: 2px; cursor: pointer; }
        .send-btn:hover { background: var(--vscode-button-hoverBackground); }

        /* UTILS */
        .hidden { display: none !important; }
    </style>
</head>
<body>
    <div id="app">
        <!-- HEADER -->
        <div class="header">
            <div style="display:flex; gap:8px; align-items:center">
                <button class="icon-btn" id="history-toggle" title="Toggle History">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M8 1a7 7 0 1 0 7 7 7 7 0 0 0-7-7zm0 13a6 6 0 1 1 6-6 6 6 0 0 1-6 6z"/><path d="M8 3.5a.5.5 0 0 0-1 0V8a.5.5 0 0 0 .252.434l3.5 2a.5.5 0 0 0 .496-.868L8 7.71V3.5z"/></svg>
                </button>
                <span id="chat-title" class="header-title">New Chat</span>
            </div>
            <div style="display:flex; gap:8px; align-items:center">
                <button class="icon-btn" id="new-chat-btn" title="New Chat">+</button>
                <button class="icon-btn" id="settings-btn" title="Settings">⚙️</button>
            </div>
        </div>

        <div class="main-container">
            <!-- SIDEBAR -->
            <div class="sidebar" id="sidebar">
                <div style="padding:8px; border-bottom:1px solid var(--border)">
                   <input id="history-search" type="text" placeholder="Search..." style="width:90%; background:var(--input-bg); border:1px solid var(--border); color:var(--input-fg); padding:4px; border-radius:3px;">
                </div>
                <div class="history-list" id="history-list"></div>
            </div>

            <!-- CHAT AREA -->
            <div class="chat-area">
                <div class="messages-list" id="messages-list"></div>
            </div>
        </div>

        <!-- FOOTER -->
        <div class="footer">
            <div class="attachments-area" id="attachments-area"></div>
            
            <div class="input-wrapper" id="input-wrapper">
                <textarea id="message-input" placeholder="Ask AI... (Cmd+Enter to send)"></textarea>
            </div>

            <div class="controls-row">
                <div class="controls-left">
                    <button class="icon-btn" id="add-context-btn" title="Add Context">📎</button>
                    
                    <select id="mode-select">
                        <option value="Chat">Chat</option>
                        <option value="QuickEdit">Quick Edit</option>
                    </select>
                    
                    <select id="model-select"></select>
                    
                    <select id="tools-select" title="MCP Tools">
                        <option value="Auto">Tools: Auto</option>
                        <option value="Manual">Tools: Manual</option>
                        <option value="Disabled">Tools: Off</option>
                    </select>
                </div>
                <div class="controls-right">
                    <span id="token-count">~0 tokens</span>
                    <button class="send-btn" id="send-btn">Send</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        (function() {
            const vscode = acquireVsCodeApi();
            
            // State
            let state = { chats: [], currentId: null, appState: {} };
            let attachments = [];

            // DOM Elements
            const els = {
                historyList: document.getElementById('history-list'),
                messagesList: document.getElementById('messages-list'),
                input: document.getElementById('message-input'),
                title: document.getElementById('chat-title'),
                sidebar: document.getElementById('sidebar'),
                attachmentsArea: document.getElementById('attachments-area'),
                modelSelect: document.getElementById('model-select'),
                modeSelect: document.getElementById('mode-select'),
                toolsSelect: document.getElementById('tools-select'),
                tokenCount: document.getElementById('token-count')
            };

            // Initialize
            window.addEventListener('load', () => {
                vscode.postMessage({ type: 'init' });
                setupEventListeners();
            });

            window.addEventListener('message', event => {
                const msg = event.data;
                switch (msg.type) {
                    case 'render': render(msg); break;
                    case 'stream': handleStream(msg); break;
                    case 'addAttachments': addAttachments(msg.attachments); break;
                }
            });

            function setupEventListeners() {
                document.getElementById('send-btn').onclick = sendMessage;
                document.getElementById('new-chat-btn').onclick = () => vscode.postMessage({ type: 'newChat' });
                document.getElementById('history-toggle').onclick = () => els.sidebar.classList.toggle('open');
                document.getElementById('settings-btn').onclick = () => vscode.postMessage({ type: 'openSettings' });
                document.getElementById('add-context-btn').onclick = () => vscode.postMessage({ type: 'addContext' });

                els.input.onkeydown = (e) => { if(e.key === 'Enter' && (e.metaKey || e.ctrlKey)) sendMessage(); };
                els.input.oninput = () => { 
                    vscode.postMessage({ type: 'saveDraft', text: els.input.value, attachments });
                    updateTokenCount();
                };

                // Drag & Drop for Files
                const dropZone = document.getElementById('app');
                dropZone.ondragover = (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; };
                dropZone.ondrop = (e) => {
                    e.preventDefault();
                    if (e.dataTransfer.files) {
                        const newAtts = [];
                        for (let f of e.dataTransfer.files) {
                            if (f.path) newAtts.push({ type: 'file', name: f.name, data: f.path });
                        }
                        if(newAtts.length) addAttachments(newAtts);
                    }
                };

                // Config Changes
                els.modeSelect.onchange = (e) => vscode.postMessage({ type: 'updateState', key: 'mode', value: e.target.value });
                els.modelSelect.onchange = (e) => vscode.postMessage({ type: 'updateState', key: 'model', value: e.target.value });
                els.toolsSelect.onchange = (e) => vscode.postMessage({ type: 'updateState', key: 'toolsMode', value: e.target.value });
            }

            function render(data) {
                state = { chats: data.chats, currentId: data.currentId, appState: data.state };
                
                // Render Controls State
                els.modeSelect.value = state.appState.mode;
                els.toolsSelect.value = state.appState.toolsMode;
                
                // Render Models
                els.modelSelect.innerHTML = '';
                state.appState.availableModels.forEach(m => {
                    const opt = document.createElement('option');
                    opt.value = m; opt.text = m; 
                    opt.selected = m === state.appState.model;
                    els.modelSelect.appendChild(opt);
                });

                // Render Chat
                const chat = state.chats.find(c => c.id === state.currentId);
                renderMessages(chat);
                renderHistory();
                
                // Restore Inputs if not focused/typing
                if (chat && document.activeElement !== els.input) {
                    els.input.value = chat.draftInput || '';
                    attachments = chat.draftAttachments || [];
                    renderAttachments();
                }
                updateTokenCount();
            }

            function renderMessages(chat) {
                els.messagesList.innerHTML = '';
                if (!chat) {
                    els.title.textContent = 'New Chat';
                    return;
                }
                els.title.textContent = chat.title;

                chat.messages.forEach(msg => {
                    const div = document.createElement('div');
                    div.className = \`bubble \${msg.role}\`;
                    
                    // Markdown Render
                    div.innerHTML = marked.parse(msg.content);
                    
                    // Highlight Code
                    div.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));

                    // Changes Widget
                    if (msg.changes && msg.changes.length) {
                        const widget = document.createElement('div');
                        widget.className = 'change-widget';
                        msg.changes.forEach(ch => {
                             const row = document.createElement('div');
                             row.className = 'change-header';
                             row.innerHTML = \`<span>📝 \${ch.path.split('/').pop()}</span> <button class="btn-small">Apply</button>\`;
                             row.querySelector('button').onclick = () => vscode.postMessage({ type: 'applyChange', path: ch.path, content: ch.content });
                             widget.appendChild(row);
                        });
                        div.appendChild(widget);
                    }
                    
                    // Footer (Actions)
                    if (msg.role === 'assistant') {
                        const footer = document.createElement('div');
                        footer.className = 'bubble-footer';
                        footer.innerHTML = \`<span onclick="vscode.postMessage({type:'copy', text: this.closest('.bubble').innerText})" style="cursor:pointer">📋 Copy</span>\`;
                        div.appendChild(footer);
                    }

                    els.messagesList.appendChild(div);
                });
                els.messagesList.scrollTop = els.messagesList.scrollHeight;
            }

            function renderHistory() {
                els.historyList.innerHTML = '';
                state.chats.forEach(chat => {
                    const div = document.createElement('div');
                    div.className = \`history-item \${chat.id === state.currentId ? 'active' : ''}\`;
                    div.textContent = chat.title || 'New Chat';
                    div.onclick = () => vscode.postMessage({ type: 'loadChat', id: chat.id });
                    
                    const del = document.createElement('span');
                    del.innerHTML = '&times;';
                    del.style.marginLeft = '8px';
                    del.onclick = (e) => { e.stopPropagation(); vscode.postMessage({ type: 'deleteChat', id: chat.id }); };
                    
                    div.appendChild(del);
                    els.historyList.appendChild(div);
                });
            }

            function handleStream(msg) {
                // If current chat matches
                if (msg.chatId === state.currentId) {
                    const bubbles = els.messagesList.querySelectorAll('.bubble.assistant');
                    const last = bubbles[bubbles.length - 1];
                    if (last) {
                        // Re-render markdown of last bubble (inefficient but simple)
                        // Optimization: In reality we'd append text, but for Markdown streaming we parse partial
                        // For now, simpler to just replace content if it's not huge
                        const contentDiv = document.createElement('div');
                        contentDiv.innerHTML = marked.parse(msg.content);
                        // Preserve footer
                        const footer = last.querySelector('.bubble-footer');
                        last.innerHTML = '';
                        last.appendChild(contentDiv);
                        if(footer) last.appendChild(footer);
                        
                        last.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
                        els.messagesList.scrollTop = els.messagesList.scrollHeight;
                    }
                }
            }

            function addAttachments(newAtts) {
                // Dedup
                newAtts.forEach(a => {
                    if (!attachments.find(ex => ex.data === a.data)) attachments.push(a);
                });
                renderAttachments();
                vscode.postMessage({ type: 'saveDraft', text: els.input.value, attachments });
                updateTokenCount();
            }

            function renderAttachments() {
                els.attachmentsArea.innerHTML = '';
                attachments.forEach((att, idx) => {
                    const chip = document.createElement('div');
                    chip.className = 'attachment-chip';
                    chip.innerHTML = \`\${att.type === 'file' ? '📄' : '📝'} \${att.name} <span data-idx="\${idx}">&times;</span>\`;
                    chip.querySelector('span').onclick = () => {
                        attachments.splice(idx, 1);
                        renderAttachments();
                        vscode.postMessage({ type: 'saveDraft', text: els.input.value, attachments });
                        updateTokenCount();
                    };
                    els.attachmentsArea.appendChild(chip);
                });
                els.attachmentsArea.classList.toggle('hidden', attachments.length === 0);
            }

            function sendMessage() {
                const text = els.input.value.trim();
                if (!text && attachments.length === 0) return;
                
                vscode.postMessage({ type: 'send', text, attachments });
                els.input.value = '';
                attachments = [];
                renderAttachments();
                updateTokenCount();
            }

            function updateTokenCount() {
                const textLen = els.input.value.length;
                const attLen = attachments.reduce((acc, a) => acc + (a.type==='text' ? a.data.length : 1000), 0);
                const tokens = Math.floor((textLen + attLen) / 4);
                els.tokenCount.textContent = \`~\${tokens} tokens\`;
            }
        })();
    </script>
</body>
</html>`; 
    }
}
