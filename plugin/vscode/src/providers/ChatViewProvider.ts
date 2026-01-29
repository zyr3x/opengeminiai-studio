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
        webviewView.webview.options = { 
            enableScripts: true,
            localResourceRoots: [this.context.extensionUri] 
        };
        webviewView.webview.html = this.getHtml(webviewView.webview);

        webviewView.webview.onDidReceiveMessage(async (m) => {
            try {
                switch (m.type) {
                    case 'send': await this.handleSend(m.text, m.mode, m.attachments); break;
                    case 'newChat': this.createNewChat(); break;
                    case 'deleteChat': this.deleteChat(m.id); break;
                    case 'saveDraft': this.saveDraft(m.text); break;
                    case 'applyChange': await this.applyFileChange(m.path, m.content); break;
                    case 'loadChat': this.loadChat(m.id); break;
                }
            } catch (e: any) {
                vscode.window.showErrorMessage(`OpenGemini Error: ${e.message}`);
            }
        });
        
        // Wait for webview to load then update
        setTimeout(() => this.updateUI(), 500);
    }

    public async sendMessage(text: string) {
        await vscode.commands.executeCommand('opengeminiai.chatView.focus');
        await this.handleSend(text, 'Chat', []);
    }

    private async handleSend(text: string, mode: string, attachments: any[]) {
        if (!this.currentId) this.createNewChat();
        const chat = this.conversations.find(c => c.id === this.currentId);
        if (!chat) return;

        let fullContent = text;
        if (attachments && attachments.length > 0) {
            attachments.forEach(a => {
                fullContent += `\ncode_path=${a.path}`;
            });
        }

        chat.messages.push({ role: 'user', content: fullContent });
        chat.draftInput = "";

        const assistantMsg: ChatMessage = { role: 'assistant', content: "Thinking..." };
        chat.messages.push(assistantMsg);

        this.updateUI();

        try {
            const systemPrompt = await ApiClient.getPromptText(mode);
            const model = vscode.workspace.getConfiguration('opengeminiai').get(mode === 'Chat' ? 'chatModel' : 'editModel') as string;

            assistantMsg.content = "";
            
            await ApiClient.streamChat([{ role: 'system', content: systemPrompt }, ...chat.messages.slice(0, -1)], model, (chunk) => {
                assistantMsg.content += chunk;
                this._view?.webview.postMessage({ type: 'stream', content: assistantMsg.content });
            });

            this.parseChanges(assistantMsg);
            this.save();
            this.updateUI();
        } catch (err: any) {
            assistantMsg.content += `\n\n[Error: ${err.message}]`;
            this.save();
            this.updateUI();
        }
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
        const chat: Conversation = { id: Date.now().toString(), title: "New Chat", messages: [], timestamp: Date.now(), draftInput: "" };
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

    private saveDraft(text: string) {
        const chat = this.conversations.find(c => c.id === this.currentId);
        if (chat) { chat.draftInput = text; this.save(); }
    }

    private save() { this.context.globalState.update('history', this.conversations); }
    
    private updateUI() { 
        this._view?.webview.postMessage({ type: 'render', chats: this.conversations, currentId: this.currentId }); 
    }

    private getHtml(webview: vscode.Webview) { 
        const cspSource = webview.cspSource;
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${cspSource} 'unsafe-inline'; script-src ${cspSource} 'unsafe-inline';">
    <title>OpenGemini Studio</title>
    <style>
        body { padding: 0; margin: 0; font-family: var(--vscode-font-family); color: var(--vscode-foreground); background: var(--vscode-editor-background); }
        .container { display: flex; flex-direction: column; height: 100vh; }
        .header { padding: 10px; background: var(--vscode-sideBarSectionHeader-background); display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--vscode-panel-border); }
        .chat-list { flex: 1; overflow-y: auto; padding: 10px; display: flex; flex-direction: column; gap: 10px; }
        .message { padding: 8px 12px; border-radius: 6px; max-width: 90%; }
        .message.user { align-self: flex-end; background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); }
        .message.assistant { align-self: flex-start; background: var(--vscode-editor-inactiveSelectionBackground); border: 1px solid var(--vscode-widget-border); }
        
        /* Important: pre-wrap handles newlines correctly */
        .content { white-space: pre-wrap; word-wrap: break-word; font-family: inherit; }
        
        .input-area { padding: 10px; border-top: 1px solid var(--vscode-panel-border); display: flex; gap: 5px; background: var(--vscode-sideBar-background); }
        textarea { flex: 1; background: var(--vscode-input-background); color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border); padding: 5px; resize: none; height: 40px; font-family: inherit; }
        button { background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; padding: 5px 10px; cursor: pointer; }
        button:hover { background: var(--vscode-button-hoverBackground); }
        pre { background: var(--vscode-textBlockQuote-background); padding: 5px; overflow-x: auto; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <span id="chat-title">New Chat</span>
            <button id="new-chat-btn">+</button>
        </div>
        <div class="chat-list" id="chat-list"></div>
        <div class="input-area">
            <textarea id="message-input" placeholder="Ask AI... (Cmd+Enter to send)"></textarea>
            <button id="send-btn">Send</button>
        </div>
    </div>
    <script>
        (function() {
            const vscode = acquireVsCodeApi();
            const chatList = document.getElementById('chat-list');
            const input = document.getElementById('message-input');
            const title = document.getElementById('chat-title');
            const sendBtn = document.getElementById('send-btn');
            const newChatBtn = document.getElementById('new-chat-btn');
            let currentChatId = null;

            // Event Listeners
            window.addEventListener('DOMContentLoaded', () => {
                sendBtn.addEventListener('click', sendMessage);
                newChatBtn.addEventListener('click', newChat);
                
                input.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                        sendMessage();
                    }
                });

                input.addEventListener('input', (e) => {
                    if(currentChatId) {
                        vscode.postMessage({ type: 'saveDraft', text: e.target.value });
                    }
                });
            });

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
                if (!chat) {
                    title.innerText = 'New Chat';
                    return;
                }
                
                title.innerText = chat.title || 'Chat';
                if (chat.draftInput && !input.value) {
                    input.value = chat.draftInput;
                }
                
                chat.messages.forEach(msg => {
                    const div = document.createElement('div');
                    div.className = 'message ' + msg.role;
                    
                    // Create Content Div Safely
                    const contentDiv = document.createElement('div');
                    contentDiv.className = 'content';
                    contentDiv.textContent = msg.content;
                    div.appendChild(contentDiv);
                    
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
                    if (contentDiv) contentDiv.textContent = text;
                }
                scrollToBottom();
            }

            function sendMessage() {
                const text = input.value.trim();
                if (!text) return;
                input.value = '';
                vscode.postMessage({ type: 'send', text: text, mode: 'Chat', attachments: [] });
            }
            
            function newChat() {
                vscode.postMessage({ type: 'newChat' });
            }

            function scrollToBottom() {
                chatList.scrollTop = chatList.scrollHeight;
            }
        })();
    </script>
</body>
</html>`; 
    }
}
