import * as vscode from 'vscode';
import { ApiClient } from '../services/ApiClient';
import { Conversation, ChatMessage } from '../model';

export class ChatViewProvider implements vscode.WebviewViewProvider {
    private _view?: vscode.WebviewView;
    private conversations: Conversation[] = [];
    private currentId?: string;

    constructor(private context: vscode.ExtensionContext) {
        this.conversations = context.globalState.get('history', []);
    }

    resolveWebviewView(webviewView: vscode.WebviewView) {
        this._view = webviewView;
        webviewView.webview.options = { enableScripts: true };
        webviewView.webview.html = this.getHtml();

        webviewView.webview.onDidReceiveMessage(async (m) => {
            switch (m.type) {
                case 'send': await this.handleSend(m.text, m.mode, m.attachments); break;
                case 'newChat': this.createNewChat(); break;
                case 'deleteChat': this.deleteChat(m.id); break;
                case 'saveDraft': this.saveDraft(m.text); break;
                case 'applyChange': await this.applyFileChange(m.path, m.content); break;
                case 'loadChat': this.loadChat(m.id); break;
            }
        });
        
        // Wait for webview to load then update
        setTimeout(() => this.updateUI(), 500);
    }

    /**
     * Public method to send a message from external commands (e.g. /explain)
     */
    public async sendMessage(text: string) {
        // Focus the view
        await vscode.commands.executeCommand('opengeminiai.chatView.focus');
        // Default to 'Chat' mode
        await this.handleSend(text, 'Chat', []);
    }

    private async handleSend(text: string, mode: string, attachments: any[]) {
        if (!this.currentId) this.createNewChat();
        const chat = this.conversations.find(c => c.id === this.currentId);
        if (!chat) return;

        // Build Full Content with attachments
        let fullContent = text;
        if (attachments && attachments.length > 0) {
            attachments.forEach(a => {
                fullContent += `\ncode_path=${a.path}`;
            });
        }

        chat.messages.push({ role: 'user', content: fullContent });
        chat.draftInput = ""; // Clear draft on send

        const systemPrompt = await ApiClient.getPromptText(mode);
        const model = vscode.workspace.getConfiguration('opengeminiai').get(mode === 'Chat' ? 'chatModel' : 'editModel') as string;

        const assistantMsg: ChatMessage = { role: 'assistant', content: "" };
        chat.messages.push(assistantMsg);

        this.updateUI();

        await ApiClient.streamChat([{ role: 'system', content: systemPrompt }, ...chat.messages.slice(0, -1)], model, (chunk) => {
            assistantMsg.content += chunk;
            this._view?.webview.postMessage({ type: 'stream', content: assistantMsg.content });
        });

        // Parse JSON Protocol for changes
        this.parseChanges(assistantMsg);
        this.save();
        this.updateUI();
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
        // VS Code Diff viewer
        const uri = vscode.Uri.file(path);
        const tempUri = vscode.Uri.parse(`untitled:${path}`);
        const edit = new vscode.WorkspaceEdit();
        
        // Create file if not exists or overwrite
        edit.insert(tempUri, new vscode.Position(0, 0), content);
        
        await vscode.workspace.applyEdit(edit);
        await vscode.commands.executeCommand('vscode.diff', uri, tempUri);
    }

    private createNewChat() {
        const chat: Conversation = { id: Date.now().toString(), title: "New Chat", messages: [], timestamp: Date.now(), draftInput: "" };
        this.conversations.unshift(chat);
        this.currentId = chat.id;
        this.save();
        this.updateUI();
    }

    private deleteChat(id: string) {
        this.conversations = this.conversations.filter(c => c.id !== id);
        // If we deleted the current chat, switch to another one or reset
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

    private saveDraft(text: string) {
        const chat = this.conversations.find(c => c.id === this.currentId);
        if (chat) { chat.draftInput = text; this.save(); }
    }

    private save() { this.context.globalState.update('history', this.conversations); }
    
    private updateUI() { 
        this._view?.webview.postMessage({ type: 'render', chats: this.conversations, currentId: this.currentId }); 
    }

    private getHtml() { 
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenGemini Studio</title>
    <style>
        body { padding: 0; margin: 0; font-family: var(--vscode-font-family); color: var(--vscode-foreground); background: var(--vscode-editor-background); }
        .container { display: flex; flex-direction: column; height: 100vh; }
        .header { padding: 10px; background: var(--vscode-sideBarSectionHeader-background); display: flex; justify-content: space-between; align-items: center; }
        .chat-list { flex: 1; overflow-y: auto; padding: 10px; display: flex; flex-direction: column; gap: 10px; }
        .message { padding: 8px 12px; border-radius: 6px; max-width: 90%; word-wrap: break-word; }
        .message.user { align-self: flex-end; background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); }
        .message.assistant { align-self: flex-start; background: var(--vscode-editor-inactiveSelectionBackground); border: 1px solid var(--vscode-widget-border); }
        .input-area { padding: 10px; border-top: 1px solid var(--vscode-panel-border); display: flex; gap: 5px; background: var(--vscode-sideBar-background); }
        textarea { flex: 1; background: var(--vscode-input-background); color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border); padding: 5px; resize: none; height: 40px; font-family: inherit; }
        button { background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; padding: 5px 10px; cursor: pointer; }
        button:hover { background: var(--vscode-button-hoverBackground); }
        pre { background: var(--vscode-textBlockQuote-background); padding: 5px; overflow-x: auto; }
        .actions { margin-top: 5px; display: flex; gap: 5px; font-size: 0.8em; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <span id="chat-title">New Chat</span>
            <button onclick="newChat()">+</button>
        </div>
        <div class="chat-list" id="chat-list"></div>
        <div class="input-area">
            <textarea id="message-input" placeholder="Ask AI... (Cmd+Enter to send)"></textarea>
            <button onclick="sendMessage()">Send</button>
        </div>
    </div>
    <script>
        const vscode = acquireVsCodeApi();
        const chatList = document.getElementById('chat-list');
        const input = document.getElementById('message-input');
        const title = document.getElementById('chat-title');
        let currentChatId = null;

        window.addEventListener('message', event => {
            const message = event.data;
            switch (message.type) {
                case 'render':
                    render(message.chats, message.currentId);
                    break;
                case 'stream':
                    appendStream(message.content);
                    break;
            }
        });

        function render(chats, currentId) {
            currentChatId = currentId;
            chatList.innerHTML = '';
            const chat = chats.find(c => c.id === currentId);
            if (!chat) return;
            
            title.innerText = chat.title || 'Chat';
            
            chat.messages.forEach(msg => {
                const div = document.createElement('div');
                div.className = 'message ' + msg.role;
                // Simple Markdown-ish rendering
                const content = msg.content.replace(/</g, '&lt;').replace(/>/g, '&gt;');
                div.innerHTML = \`<div class="content">\${content.replace(/\n/g, '<br>')}</div>\`;
                
                if (msg.changes && msg.changes.length > 0) {
                    const btn = document.createElement('button');
                    btn.innerText = 'Review Changes';
                    btn.style.marginTop = '5px';
                    btn.onclick = () => {
                        vscode.postMessage({ type: 'applyChange', path: msg.changes[0].path, content: msg.changes[0].content });
                    };
                    div.appendChild(btn);
                }
                chatList.appendChild(div);
            });
            scrollToBottom();
        }

        function appendStream(text) {
            const lastMsg = chatList.lastElementChild;
            if (lastMsg && lastMsg.classList.contains('assistant')) {
                const contentDiv = lastMsg.querySelector('.content');
                contentDiv.innerText = text;
            }
            scrollToBottom();
        }

        function sendMessage() {
            const text = input.value.trim();
            if (!text) return;
            input.value = '';
            vscode.postMessage({ type: 'send', text: text, mode: 'Chat' });
        }
        
        function newChat() {
            vscode.postMessage({ type: 'newChat' });
        }

        function scrollToBottom() {
            chatList.scrollTop = chatList.scrollHeight;
        }

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                sendMessage();
            }
        });
    </script>
</body>
</html>`; 
    }
}