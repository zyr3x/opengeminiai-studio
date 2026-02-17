import * as vscode from 'vscode';
import { ApiClient } from '../services/ApiClient';
import { Conversation, ChatMessage, Attachment, AppState } from '../model';
import * as path from 'path';

export class ChatViewProvider implements vscode.WebviewViewProvider {
    private _view?: vscode.WebviewView;
    private conversations: Conversation[] = [];
    private currentId?: string;
    
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
        const savedState = context.globalState.get<Partial<AppState>>('appState', {});
        this.appState = { ...this.appState, ...savedState };

        this.registerCommands();
    }

    private registerCommands() {
        this.context.subscriptions.push(
            vscode.commands.registerCommand('opengeminiai.generateCommit', async () => {
                await this.handleGenerateCommit();
            })
        );
    }

    async resolveWebviewView(webviewView: vscode.WebviewView) {
        this._view = webviewView;
        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this.context.extensionUri] 
        };
        
        webviewView.webview.html = this.getHtml(webviewView.webview);
        this.refreshBackendData();

        webviewView.webview.onDidReceiveMessage(async (m) => {
            switch (m.type) {
                case 'init': this.updateUI(); break;
                case 'send': await this.handleSend(m.text, m.attachments); break;
                case 'newChat': this.createNewChat(); break;
                case 'deleteChat': this.deleteChat(m.id); break;
                case 'loadChat': this.loadChat(m.id); break;
                case 'saveDraft': this.saveDraft(m.text, m.attachments); break;
                case 'applyChange': await this.applyFileChange(m.path, m.content); break;
                case 'updateState': this.updateState(m.key, m.value); break;
                case 'addContext': this.openContextDialog(m.option); break;
                case 'openSettings': vscode.commands.executeCommand('workbench.action.openSettings', 'opengeminiai'); break;
                case 'filesDropped': this.handleFilesDropped(m.paths); break;
            }
        });
    }

    private async refreshBackendData() {
        try {
            const [models, tools] = await Promise.all([
                ApiClient.getModels(),
                ApiClient.getMcpTools()
            ]);
            this.appState.availableModels = models;
            this.appState.availableTools = tools;
            this.updateUI();
        } catch {}
    }

    private async handleGenerateCommit() {
        await vscode.commands.executeCommand('opengeminiai-sidebar.focus');
        if (!this.currentId) this.createNewChat();
        
        const diff = await this.getGitDiff();
        if (!diff) {
            vscode.window.showInformationMessage("No staged changes found.");
            return;
        }

        await this.handleSend("/commit", [{
            type: 'text',
            name: 'git_diff',
            data: diff
        }]);
    }

    private async getGitDiff(): Promise<string | null> {
        try {
            const { execSync } = require('child_process');
            const workspace = vscode.workspace.workspaceFolders?.[0];
            if (workspace) {
                return execSync('git diff --cached', { cwd: workspace.uri.fsPath }).toString();
            }
        } catch {}
        return null;
    }

    public async sendMessage(text: string) {
        await vscode.commands.executeCommand('opengeminiai-sidebar.focus');
        if (!this.currentId) this.createNewChat();
        setTimeout(() => this.handleSend(text), 200);
    }

    private async handleSend(text: string, incomingAttachments?: Attachment[]) {
        if (!this.currentId) this.createNewChat();
        const chat = this.conversations.find(c => c.id === this.currentId);
        if (!chat) return;

        const attachments = incomingAttachments || chat.draftAttachments || [];
        let fullContent = text;
        
        if (attachments.length > 0) {
            fullContent += "\n\n";
            attachments.forEach(a => {
                if (a.type === 'file') {
                    fullContent += `code_path=${a.data}\n`;
                } else {
                    fullContent += `\n:::CTX:${a.name}:text:::\n${a.data}\n:::END:::`;
                }
            });
        }

        chat.messages.push({ role: 'user', content: fullContent });
        const assistantMsg: ChatMessage = { role: 'assistant', content: "" };
        chat.messages.push(assistantMsg);

        chat.draftInput = "";
        chat.draftAttachments = [];
        
        this.save();
        this.updateUI();

        if (chat.title === "New Chat") this.generateTitle(chat, text);

        try {
            const mode = text.startsWith('/commit') ? 'Commit' : this.appState.mode;
            const systemPrompt = await ApiClient.getPromptText(mode);
            
            let toolsToSend: string[] | null = null;
            if (this.appState.toolsMode === 'Disabled') toolsToSend = ['TOOLS_DISABLED'];
            else if (this.appState.toolsMode === 'Manual') toolsToSend = this.appState.selectedTools;

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
            this.updateUI();
        }
    }

    private async generateTitle(chat: Conversation, content: string) {
        try {
            const prompt = await ApiClient.getPromptText('Title');
            let title = "";
            await ApiClient.streamChat(
                [{ role: 'system', content: prompt }, { role: 'user', content: content.substring(0, 500) }],
                'gemini-2.5-flash',
                (chunk) => title += chunk
            );
            chat.title = title.replace(/["\n]/g, '').trim();
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

    private async applyFileChange(filePath: string, content: string) {
        const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
        const editor = await vscode.window.showTextDocument(doc);
        const fullRange = new vscode.Range(doc.positionAt(0), doc.positionAt(doc.getText().length));
        await editor.edit(edit => edit.replace(fullRange, content));
    }

    private handleFilesDropped(paths: string[]) {
        const attachments = paths.map(p => ({
            type: 'file' as const,
            name: path.basename(p),
            data: p
        }));
        this._view?.webview.postMessage({ type: 'addAttachments', attachments });
    }

    private createNewChat() {
        const id = Date.now().toString();
        this.conversations.unshift({ id, title: "New Chat", messages: [], timestamp: Date.now(), draftInput: "", draftAttachments: [] });
        this.currentId = id;
        this.save();
        this.updateUI();
    }

    private deleteChat(id: string) {
        this.conversations = this.conversations.filter(c => c.id !== id);
        if (this.currentId === id) this.currentId = this.conversations[0]?.id;
        this.save();
        this.updateUI();
    }
    
    private loadChat(id: string) {
        this.currentId = id;
        this.updateUI();
    }

    private saveDraft(text: string, attachments: Attachment[]) {
        const chat = this.conversations.find(c => c.id === this.currentId);
        if (chat) { chat.draftInput = text; chat.draftAttachments = attachments; this.save(); }
    }

    private updateState(key: keyof AppState, value: any) {
        (this.appState as any)[key] = value;
        this.context.globalState.update('appState', this.appState);
        this.updateUI();
    }

    private async openContextDialog(option?: string) {
        if (option === 'open_files') {
            const attachments = vscode.workspace.textDocuments
                .filter(d => !d.isUntitled)
                .map(d => ({ type: 'file' as const, name: path.basename(d.fileName), data: d.fileName }));
            this._view?.webview.postMessage({ type: 'addAttachments', attachments });
            return;
        }

        const uris = await vscode.window.showOpenDialog({ canSelectMany: true, canSelectFolders: true });
        if (uris) {
            const attachments = uris.map(u => ({ type: 'file' as const, name: path.basename(u.fsPath), data: u.fsPath }));
            this._view?.webview.postMessage({ type: 'addAttachments', attachments });
        }
    }

    private save() { this.context.globalState.update('history', this.conversations); }
    private updateUI() { this._view?.webview.postMessage({ type: 'render', chats: this.conversations, currentId: this.currentId, state: this.appState }); }

    private getHtml(webview: vscode.Webview) {
        const csp = webview.cspSource;
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${csp} 'unsafe-inline' https:; script-src ${csp} 'unsafe-inline' https:; img-src ${csp} https: data:;">
    <title>OG Studio</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <style>
        :root { --bg: var(--vscode-sideBar-background); --fg: var(--vscode-sideBar-foreground); --border: var(--vscode-panel-border); }
        body { margin: 0; padding: 0; font-family: var(--vscode-font-family); background: var(--bg); color: var(--fg); height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
        .header { padding: 8px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
        .sidebar-toggle { cursor: pointer; padding: 4px; font-size: 16px; }
        .main { flex: 1; overflow-y: auto; padding: 10px; display: flex; flex-direction: column; gap: 12px; transition: background 0.2s; }
        .main.drag-over { background: rgba(127, 127, 127, 0.2); }
        .bubble { padding: 8px 12px; border-radius: 6px; font-size: 13px; max-width: 95%; }
        .user { align-self: flex-end; background: var(--vscode-button-secondaryBackground); }
        .assistant { align-self: flex-start; background: var(--vscode-editor-background); border: 1px solid var(--border); }
        pre { background: #1e1e1e; padding: 8px; border-radius: 4px; overflow-x: auto; }
        .footer { padding: 8px; border-top: 1px solid var(--border); }
        .input-box { display: flex; background: var(--vscode-input-background); border: 1px solid var(--border); border-radius: 4px; padding: 4px; }
        textarea { flex: 1; background: transparent; border: none; color: var(--vscode-input-foreground); outline: none; resize: none; min-height: 40px; }
        .actions { display: flex; justify-content: space-between; margin-top: 6px; }
        .btn { cursor: pointer; border: none; background: var(--vscode-button-background); color: var(--vscode-button-foreground); padding: 4px 8px; border-radius: 2px; font-size: 11px; }
        select { background: var(--vscode-dropdown-background); color: var(--vscode-dropdown-foreground); font-size: 11px; }
        .menu { position: absolute; background: var(--vscode-menu-background); border: 1px solid var(--border); z-index: 100; display: none; }
        .menu div { padding: 4px 12px; cursor: pointer; }
        .menu div:hover { background: var(--vscode-menu-item-activeBackground); }
        .chat-list { position: fixed; top: 0; left: -250px; width: 250px; height: 100%; background: var(--vscode-sideBar-background); border-right: 1px solid var(--border); transition: left 0.3s; z-index: 1000; display: flex; flex-direction: column; }
        .chat-list.open { left: 0; }
        .chat-item { padding: 8px 12px; cursor: pointer; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; font-size: 12px; }
        .chat-item:hover { background: var(--vscode-list-hoverBackground); }
        .chat-item.active { background: var(--vscode-list-activeSelectionBackground); color: var(--vscode-list-activeSelectionForeground); }
    </style>
</head>
<body>
    <div id="sidebar" class="chat-list">
        <div class="header">
            <span>Conversations</span>
            <button class="btn" onclick="toggleSidebar()">✕</button>
        </div>
        <div id="history-list" style="flex:1; overflow-y:auto"></div>
    </div>

    <div class="header">
        <div style="display:flex; align-items:center; gap:8px">
            <span class="sidebar-toggle" onclick="toggleSidebar()">☰</span>
            <span id="title">New Chat</span>
        </div>
        <div style="display:flex; gap:4px">
            <button class="btn" onclick="vscode.postMessage({type:'newChat'})">+</button>
            <button class="btn" onclick="vscode.postMessage({type:'openSettings'})">⚙️</button>
        </div>
    </div>
    <div class="main" id="list"></div>
    <div class="footer">
        <div id="attachments" style="display:flex; gap:4px; margin-bottom:4px; flex-wrap:wrap"></div>
        <div class="input-box"><textarea id="input" placeholder="Ask AI... (Drag & Drop files here)"></textarea></div>
        <div class="actions">
            <div style="display:flex; gap:4px">
                <button class="btn" id="attach-btn">📎</button>
                <select id="mode-select"><option value="Chat">Chat</option><option value="QuickEdit">Edit</option></select>
                <select id="model-select"></select>
            </div>
            <button class="btn" id="send-btn">Send</button>
        </div>
    </div>

    <div id="ctx-menu" class="menu">
        <div onclick="sendCtx('files')">Files and Folders</div>
        <div onclick="sendCtx('open_files')">Add All Open Files</div>
    </div>

    <script>
        const vscode = acquireVsCodeApi();
        let attachments = [];
        
        const attachBtn = document.getElementById('attach-btn');
        const menu = document.getElementById('ctx-menu');
        const sidebar = document.getElementById('sidebar');

        // Drag and Drop Logic
        const dropZone = document.body;
        const mainList = document.getElementById('list');
        
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.stopPropagation();
            mainList.classList.add('drag-over');
        });

        dropZone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            e.stopPropagation();
            // Only remove if we left the window, otherwise it flickers
            if (e.clientX === 0 || e.clientY === 0) {
                 mainList.classList.remove('drag-over');
            }
        });

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            mainList.classList.remove('drag-over');
            
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                const files = Array.from(e.dataTransfer.files).map(f => f.path);
                vscode.postMessage({type: 'filesDropped', paths: files});
            }
        });

        function toggleSidebar() { sidebar.classList.toggle('open'); }

        attachBtn.onclick = (e) => {
            menu.style.display = 'block';
            menu.style.left = e.pageX + 'px';
            menu.style.top = (e.pageY - 60) + 'px';
        };

        window.onclick = (e) => {
             if (e.target !== attachBtn) menu.style.display = 'none';
             if (!sidebar.contains(e.target) && !e.target.classList.contains('sidebar-toggle')) sidebar.classList.remove('open');
        };

        function sendCtx(opt) { vscode.postMessage({type: 'addContext', option: opt}); }

        document.getElementById('send-btn').onclick = () => {
            const text = document.getElementById('input').value;
            vscode.postMessage({type: 'send', text, attachments});
            document.getElementById('input').value = '';
            attachments = [];
            renderAtts();
        };

        window.onmessage = (e) => {
            const d = e.data;
            if (d.type === 'render') {
                const currentChat = d.chats.find(c=>c.id===d.currentId);
                document.getElementById('title').innerText = currentChat?.title || 'New Chat';
                
                // Render History Sidebar
                const hist = document.getElementById('history-list');
                hist.innerHTML = '';
                d.chats.forEach(c => {
                    const item = document.createElement('div');
                    item.className = 'chat-item' + (c.id === d.currentId ? ' active' : '');
                    item.innerHTML = "\uD83D\uDDE2 " + c.title;
                    const del = document.createElement('span');
                    del.innerHTML = '🗑️';
                    del.style.cursor = 'pointer';
                    del.onclick = (e) => { e.stopPropagation(); vscode.postMessage({type:'deleteChat', id: c.id}); };
                    item.onclick = () => { vscode.postMessage({type:'loadChat', id: c.id}); toggleSidebar(); };
                    item.appendChild(del);
                    hist.appendChild(item);
                });

                const list = document.getElementById('list');
                list.innerHTML = '';
                (currentChat?.messages || []).forEach(m => {
                    const div = document.createElement('div');
                    div.className = 'bubble ' + m.role;
                    div.innerHTML = marked.parse(m.content);
                    if (m.changes) {
                        m.changes.forEach(c => {
                            const b = document.createElement('button');
                            b.className = 'btn'; b.style.marginTop = '4px';
                            b.innerText = 'Apply to ' + c.path.split('/').pop();
                            b.onclick = () => vscode.postMessage({type: 'applyChange', path: c.path, content: c.content});
                            div.appendChild(b);
                        });
                    }
                    list.appendChild(div);
                });
                list.scrollTop = list.scrollHeight;

                const modelSelect = document.getElementById('model-select');
                modelSelect.innerHTML = '';
                d.state.availableModels.forEach(m => {
                    const opt = document.createElement('option');
                    opt.value = m; opt.text = m; opt.selected = m === d.state.model;
                    modelSelect.appendChild(opt);
                });
                document.getElementById('mode-select').value = d.state.mode;
            }
            if (d.type === 'addAttachments') {
                attachments = [...attachments, ...d.attachments];
                renderAtts();
            }
            if (d.type === 'stream') {
                const last = document.querySelector('.assistant:last-child');
                if (last) last.innerHTML = marked.parse(d.content);
                document.getElementById('list').scrollTop = document.getElementById('list').scrollHeight;
            }
        };

        function renderAtts() {
            const div = document.getElementById('attachments');
            div.innerHTML = '';
            attachments.forEach((a, i) => {
                const s = document.createElement('span');
                s.innerText = '📄 ' + a.name + ' ✕';
                s.style = 'font-size:10px; background:#444; padding:2px 4px; border-radius:4px; cursor:pointer';
                s.onclick = () => { attachments.splice(i, 1); renderAtts(); };
                div.appendChild(s);
            });
        }

        document.getElementById('mode-select').onchange = (e) => vscode.postMessage({type:'updateState', key:'mode', value:e.target.value});
        document.getElementById('model-select').onchange = (e) => vscode.postMessage({type:'updateState', key:'model', value:e.target.value});
    </script>
</body>
</html>`;
    }
}
