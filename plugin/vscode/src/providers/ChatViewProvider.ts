import * as vscode from 'vscode';
import { ApiClient } from '../services/ApiClient';
import { Conversation, ChatMessage, Attachment, AppState } from '../model';
import * as path from 'path';
import * as fs from 'fs';

export class ChatViewProvider implements vscode.WebviewViewProvider {
    private _view?: vscode.WebviewView;
    private conversations: Conversation[] = [];
    private currentId?: string;

    // Undo Buffer: filePath -> originalContent
    private undoBuffer: Map<string, string> = new Map();

    private appState: AppState = {
        mode: 'Chat',
        model: 'gemini-2.5-flash',
        toolsMode: 'Auto',
        selectedTools: [],
        availableModels: ['gemini-2.5-flash'],
        availableTools: null
    };

    constructor(private context: vscode.ExtensionContext, private outputChannel?: vscode.OutputChannel) {
        this.log("Initializing ChatViewProvider...");
        this.loadConversations();
        const savedState = context.globalState.get<Partial<AppState>>('appState', {});
        this.appState = { ...this.appState, ...savedState };

        this.registerCommands();
    }

    private log(message: string) {
        if (this.outputChannel) {
            this.outputChannel.appendLine(`[${new Date().toLocaleTimeString()}] ${message}`);
        }
        console.log(message);
    }

    private registerCommands() {
        this.context.subscriptions.push(
            vscode.commands.registerCommand('opengeminiai.generateCommit', async () => {
                await this.handleGenerateCommit();
            })
        );
    }

    // Abort Controller for stopping generation
    private abortController: AbortController | null = null;

    async resolveWebviewView(webviewView: vscode.WebviewView) {
        this._view = webviewView;
        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this.context.extensionUri]
        };

        webviewView.webview.html = this.getHtml(webviewView.webview);
        this.refreshBackendData();

        webviewView.webview.onDidReceiveMessage(async (m) => {
            this.log(`Received message from webview: ${m.type}`);
            switch (m.type) {
                case 'init': this.updateUI(); break;
                case 'send': await this.handleSend(m.text, m.attachments); break;
                case 'stop': this.handleStop(); break;
                case 'regenerate': await this.handleRegenerate(m.chatId, m.msgIndex); break;
                case 'newChat': this.createNewChat(); break;
                case 'deleteChat': this.deleteChat(m.id); break;
                case 'deleteMessage': this.deleteMessage(m.chatId, m.msgIndex); break;
                case 'loadChat': this.loadChat(m.id); break;
                case 'requestRename': this.handleRequestRename(m.id, m.currentTitle); break;
                case 'renameChat': this.renameChat(m.id, m.title); break;
                case 'saveDraft': this.saveDraft(m.text, m.attachments); break;
                case 'applyChange': await this.applyFileChange(m.path, m.content); break;
                case 'undoChange': await this.undoFileChange(m.path); break;
                case 'showDiff': await this.handleShowDiff(m.path, m.content); break;
                case 'openFile': await this.handleOpenFile(m.path); break;
                case 'viewContext': await this.handleViewContext(m.name, m.content); break;
                case 'updateState': this.updateState(m.key, m.value); break;
                case 'addContext': this.openContextDialog(m.option); break;
                case 'openSettings': vscode.commands.executeCommand('workbench.action.openSettings', 'opengeminiai'); break;
                case 'filesDropped': this.handleFilesDropped(m.paths); break;
            }
        });
    }

    private handleStop() {
        if (this.abortController) {
            this.abortController.abort();
            this.abortController = null;
            this._view?.webview.postMessage({ type: 'endStream' });
        }
    }

    private async handleRegenerate(chatId: string, msgIndex: number) {
        const chat = this.conversations.find(c => c.id === chatId);
        if (!chat) return;

        // Remove the assistant message and all subsequent messages
        chat.messages = chat.messages.slice(0, msgIndex);
        this.saveChat(chat);
        this.updateUI();

        // Trigger regeneration by sending a dummy request with the existing history
        // We need to re-invoke the streaming logic, but without adding a new user message.
        // So we call a specialized internal method or adapt handleSend.
        // Ideally, we just call the stream logic directly.

        await this.streamResponse(chat);
    }

    private async refreshBackendData(retries = 3) {
        try {
            const [models, tools] = await Promise.all([
                ApiClient.getModels(),
                ApiClient.getMcpTools()
            ]);
            if (models && models.length > 0) {
                this.appState.availableModels = models;
                if (!this.appState.availableModels.includes(this.appState.model)) {
                    this.appState.model = this.appState.availableModels[0];
                }
            }
            this.appState.availableTools = tools;
            this.updateUI();
        } catch (err) {
            this.log(`Failed to refresh backend data: ${err}`);
            if (retries > 0) {
                setTimeout(() => this.refreshBackendData(retries - 1), 5000);
            }
        }
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
                // Use stdio: 'ignore' to suppress fatal error if not a git repo
                return execSync('git diff --cached', {
                    cwd: workspace.uri.fsPath,
                    stdio: ['ignore', 'pipe', 'ignore']
                }).toString();
            }
        } catch { }
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
                let p = a.data.split('?')[0]; // strip trailing query params like ?
                if (a.type === 'file') {
                    fullContent += `code_path=${p}\n`;
                } else if (a.type === 'image') {
                    fullContent += `image_path=${p}\n`;
                } else if (a.type === 'pdf') {
                    fullContent += `pdf_path=${p}\n`;
                } else {
                    fullContent += `\n:::CTX:${a.name}:text:::\n${p}\n:::END:::`;
                }
            });
        }

        chat.messages.push({ role: 'user', content: fullContent, timestamp: Date.now() });
        chat.draftInput = "";
        chat.draftAttachments = [];
        this.saveChat(chat);
        this.updateUI();

        if (chat.title === "New Chat") this.generateTitle(chat, text);

        await this.streamResponse(chat);
    }

    private async streamResponse(chat: Conversation) {
        const assistantMsg: ChatMessage = { role: 'assistant', content: "", timestamp: Date.now() };
        chat.messages.push(assistantMsg);

        // Let the UI know a new message was added and is starting to generate
        this._view?.webview.postMessage({ type: 'stream', content: '', chatId: chat.id });
        this.updateUI();

        this.abortController = new AbortController();

        try {
            const mode = this.appState.mode; // Use current mode for prompt
            const systemPrompt = await ApiClient.getPromptText(mode);

            let toolsToSend: string[] | null = null;
            if (this.appState.toolsMode === 'Disabled') toolsToSend = ['TOOLS_DISABLED'];
            else if (this.appState.toolsMode === 'Manual') toolsToSend = this.appState.selectedTools;

            const requestMessages = [
                { role: 'system', content: systemPrompt },
                ...chat.messages.slice(0, -1).map(m => ({ role: m.role, content: m.content }))
            ];

            // Note: ApiClient needs to support AbortSignal in a real implementation,
            // but for now we just stop processing chunks on the client side if aborted.

            await ApiClient.streamChat(
                requestMessages,
                this.appState.model,
                (chunk) => {
                    if (this.abortController?.signal.aborted) return;
                    assistantMsg.content += chunk;
                    this._view?.webview.postMessage({ type: 'stream', content: assistantMsg.content, chatId: chat.id });
                },
                toolsToSend
            );

            if (!this.abortController?.signal.aborted) {
                this.parseChanges(assistantMsg);
                this.saveChat(chat);
                // Final full render to ensure markdown parsing is correct
                this.updateUI();
            }
        } catch (err: any) {
            if (!this.abortController?.signal.aborted) {
                assistantMsg.content += `\n\n[Error: ${err.message}]`;
                this.updateUI();
            }
        } finally {
            this.abortController = null;
            this._view?.webview.postMessage({ type: 'endStream' });
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
            chat.title = title.replace(/[\"\n]/g, '').trim();
            this.saveChat(chat);
            this.updateUI();
        } catch { }
    }

    private parseChanges(msg: ChatMessage) {
        const regex = /```json\s*([\s\S]*?)\s*```/g;
        msg.content = msg.content.replace(regex, (match, p1) => {
            try {
                const parsed = JSON.parse(p1);
                if (parsed.action === 'propose_changes') {
                    msg.changes = parsed.changes;
                    return ''; // Remove the block from content
                }
            } catch { }
            return match;
        }).trim();
    }

    private async handleShowDiff(filePath: string, newContent: string) {
        try {
            const uri = vscode.Uri.file(filePath);
            const diffUri = vscode.Uri.parse(`gemini-diff:${filePath}?type=proposed`);

            // Update the virtual document content
            await vscode.commands.executeCommand('opengeminiai.updateDiffBuffer', diffUri, newContent);

            // Open Diff View
            const fileName = path.basename(filePath);
            await vscode.commands.executeCommand('vscode.diff', uri, diffUri, `AI Diff: ${fileName}`);
        } catch (e: any) {
            vscode.window.showErrorMessage(`Failed to open diff: ${e.message}`);
        }
    }

    private async handleOpenFile(filePath: string) {
        try {
            // Check if absolute, else make it absolute
            let absolutePath = filePath;
            if (!path.isAbsolute(absolutePath)) {
                const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
                if (workspaceFolder) {
                    absolutePath = path.join(workspaceFolder.uri.fsPath, filePath);
                }
            }

            const uri = vscode.Uri.file(absolutePath);

            // vscode.open handles both text and binary/image files natively
            await vscode.commands.executeCommand('vscode.open', uri);
        } catch (e: any) {
            vscode.window.showErrorMessage(`Failed to open file: ${e.message}`);
        }
    }

    private async handleViewContext(name: string, content: string) {
        try {
            // First decode HTML entities that might have been escaped by marked if it was parsed
            const unescapedContent = content
                .replace(/&lt;/g, "<")
                .replace(/&gt;/g, ">")
                .replace(/&amp;/g, "&")
                .replace(/&#39;/g, "'")
                .replace(/&quot;/g, '"');

            // Find a suitable language ID based on the name
            let language = 'markdown'; // default
            if (name.toLowerCase().includes('commit')) {
                language = 'git-commit';
            } else if (name.endsWith('.ts') || name.endsWith('.js')) {
                language = 'typescript';
            } else if (name.endsWith('.json')) {
                language = 'json';
            }

            const doc = await vscode.workspace.openTextDocument({
                content: unescapedContent,
                language: language
            });
            await vscode.window.showTextDocument(doc, { preview: true });
        } catch (e: any) {
            vscode.window.showErrorMessage(`Failed to view context: ${e.message}`);
        }
    }

    private async applyFileChange(filePath: string, content: string) {
        try {
            const uri = vscode.Uri.file(filePath);

            // 1. Save Original for Undo
            try {
                const doc = await vscode.workspace.openTextDocument(uri);
                this.undoBuffer.set(filePath, doc.getText());
            } catch {
                // File might be new
                this.undoBuffer.set(filePath, "");
            }

            // 2. Apply Edit
            const edit = new vscode.WorkspaceEdit();

            // Check if file exists to decide between create or replace
            try {
                await vscode.workspace.fs.stat(uri);
                // File exists
                const doc = await vscode.workspace.openTextDocument(uri);
                const fullRange = new vscode.Range(doc.positionAt(0), doc.positionAt(doc.getText().length));
                edit.replace(uri, fullRange, content);
            } catch {
                // File does not exist
                edit.createFile(uri, { overwrite: true });
                edit.insert(uri, new vscode.Position(0, 0), content);
            }

            await vscode.workspace.applyEdit(edit);

            // 3. Show Document
            const doc = await vscode.workspace.openTextDocument(uri);
            await vscode.window.showTextDocument(doc);

        } catch (e: any) {
            vscode.window.showErrorMessage(`Failed to apply changes: ${e.message}`);
        }
    }

    private async undoFileChange(filePath: string) {
        const original = this.undoBuffer.get(filePath);
        if (original === undefined) {
            vscode.window.showErrorMessage("No undo history for this file.");
            return;
        }

        try {
            const uri = vscode.Uri.file(filePath);
            const edit = new vscode.WorkspaceEdit();

            if (original === "") {
                edit.deleteFile(uri);
            } else {
                const doc = await vscode.workspace.openTextDocument(uri);
                const fullRange = new vscode.Range(doc.positionAt(0), doc.positionAt(doc.getText().length));
                edit.replace(uri, fullRange, original);
            }

            await vscode.workspace.applyEdit(edit);
            vscode.window.showInformationMessage(`Undid changes to ${path.basename(filePath)}`);
        } catch (e: any) {
            vscode.window.showErrorMessage(`Failed to undo: ${e.message}`);
        }
    }

    private handleFilesDropped(paths: string[]) {
        const attachments = paths.map(p => {
            const ext = path.extname(p).toLowerCase();
            let type: 'file' | 'image' | 'pdf' = 'file';
            if (['.png', '.jpg', '.jpeg', '.gif', '.webp'].includes(ext)) {
                type = 'image';
            } else if (ext === '.pdf') {
                type = 'pdf';
            }
            return {
                type,
                name: path.basename(p.split('?')[0]),
                data: p.split('?')[0]
            };
        });
        this._view?.webview.postMessage({ type: 'addAttachments', attachments });
    }

    private createNewChat() {
        const id = Date.now().toString();
        const newChat: Conversation = {
            id,
            title: "New Chat",
            messages: [],
            timestamp: Date.now(),
            model: this.appState.model,
            draftInput: "",
            draftAttachments: []
        };
        this.conversations.unshift(newChat);
        this.currentId = id;
        this.saveChat(newChat);
        this.updateUI();
    }

    private deleteChat(id: string) {
        this.conversations = this.conversations.filter(c => c.id !== id);
        this.deleteChatFile(id);
        if (this.currentId === id) this.currentId = this.conversations[0]?.id;
        this.updateUI();
    }

    private deleteMessage(chatId: string, msgIndex: number) {
        const chat = this.conversations.find(c => c.id === chatId);
        if (!chat) return;
        chat.messages.splice(msgIndex, 1);
        this.saveChat(chat);
        this.updateUI();
    }

    private loadChat(id: string) {
        this.currentId = id;
        this.updateUI();
    }

    private async handleRequestRename(id: string, currentTitle: string) {
        const title = await vscode.window.showInputBox({
            prompt: 'Enter new chat title',
            value: currentTitle
        });
        if (title) {
            this.renameChat(id, title);
        }
    }

    private renameChat(id: string, title: string) {
        const chat = this.conversations.find(c => c.id === id);
        if (chat) {
            chat.title = title;
            this.saveChat(chat);
            this.updateUI();
        }
    }

    private saveDraft(text: string, attachments: Attachment[]) {
        const chat = this.conversations.find(c => c.id === this.currentId);
        if (chat) {
            chat.draftInput = text;
            chat.draftAttachments = attachments;
            this.saveChat(chat);
        }
    }

    private updateState(key: keyof AppState, value: any) {
        (this.appState as any)[key] = value;
        this.context.globalState.update('appState', this.appState);
        this.updateUI();
    }

    private async openContextDialog(option?: string) {
        if (option === 'open_files') {
            const attachments = vscode.workspace.textDocuments
                .filter(d => !d.isUntitled && d.uri.scheme === 'file')
                .map(d => ({ type: 'file' as const, name: path.basename(d.fileName), data: d.fileName }));
            this._view?.webview.postMessage({ type: 'addAttachments', attachments });
            return;
        }

        if (option === 'project_structure') {
            const projectStructure = await this.getProjectStructure();
            if (projectStructure) {
                this._view?.webview.postMessage({
                    type: 'addAttachments', attachments: [{
                        type: 'text',
                        name: 'Project Structure',
                        data: projectStructure
                    }]
                });
            }
            return;
        }

        if (option === 'commits') {
            await this.handleAttachCommits();
            return;
        }

        if (option === 'image') {
            const uris = await vscode.window.showOpenDialog({
                canSelectMany: true,
                filters: { 'Images': ['png', 'jpg', 'jpeg', 'gif', 'webp'] }
            });
            if (uris) {
                const attachments = uris.map(u => ({ type: 'image' as const, name: path.basename(u.fsPath), data: u.fsPath }));
                this._view?.webview.postMessage({ type: 'addAttachments', attachments });
            }
            return;
        }

        if (option === 'pdf') {
            const uris = await vscode.window.showOpenDialog({
                canSelectMany: true,
                filters: { 'PDF': ['pdf'] }
            });
            if (uris) {
                const attachments = uris.map(u => ({ type: 'pdf' as const, name: path.basename(u.fsPath), data: u.fsPath }));
                this._view?.webview.postMessage({ type: 'addAttachments', attachments });
            }
            return;
        }

        const uris = await vscode.window.showOpenDialog({ canSelectMany: true, canSelectFolders: true });
        if (uris) {
            const attachments = uris.map(u => ({ type: 'file' as const, name: path.basename(u.fsPath), data: u.fsPath }));
            this._view?.webview.postMessage({ type: 'addAttachments', attachments });
        }
    }

    private async getProjectStructure(): Promise<string | null> {
        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (!workspaceFolders) return null;

        let structure = "";
        for (const folder of workspaceFolders) {
            structure += `Project Root: ${folder.uri.fsPath}\nProject Structure:\n`;
            structure += await this.buildTree(folder.uri.fsPath, "", 0);
        }
        return structure;
    }

    private async buildTree(dirPath: string, prefix: string, depth: number): Promise<string> {
        if (depth > 5) return ""; // Hard limit

        let result = "";
        try {
            const entries = await fs.promises.readdir(dirPath, { withFileTypes: true });

            // Sort: directories first, then files
            entries.sort((a, b) => {
                if (a.isDirectory() && !b.isDirectory()) return -1;
                if (!a.isDirectory() && b.isDirectory()) return 1;
                return a.name.localeCompare(b.name);
            });

            const ignores = ['node_modules', '.git', '.idea', 'out', 'dist', 'build', '.next', '.vscode'];
            const filtered = entries.filter(e => !ignores.includes(e.name) && !e.name.startsWith('.'));

            for (let i = 0; i < filtered.length; i++) {
                const entry = filtered[i];
                const isLast = i === filtered.length - 1;
                const marker = isLast ? "└── " : "├── ";
                result += `${prefix}${marker}${entry.name}\n`;

                if (entry.isDirectory()) {
                    const nextPrefix = prefix + (isLast ? "    " : "│   ");
                    result += await this.buildTree(path.join(dirPath, entry.name), nextPrefix, depth + 1);
                }
            }
        } catch { } // Ignore read errors
        return result;
    }

    private async handleAttachCommits() {
        try {
            const { execSync } = require('child_process');
            const workspace = vscode.workspace.workspaceFolders?.[0];
            if (!workspace) return;

            const logOutput = execSync('git log -n 50 --pretty=format:"%H|%s|%ar"', {
                cwd: workspace.uri.fsPath,
                encoding: 'utf8',
                stdio: ['ignore', 'pipe', 'ignore']
            });

            if (!logOutput) {
                vscode.window.showInformationMessage("No commits found.");
                return;
            }

            const commits: (vscode.QuickPickItem & { hash: string })[] = logOutput.split('\n').filter(Boolean).map((line: string) => {
                const [hash, subject, timeAgo] = line.split('|');
                return {
                    label: `$(git-commit) ${subject}`,
                    description: timeAgo,
                    detail: hash,
                    hash: hash
                };
            });

            const selected = await vscode.window.showQuickPick(commits, {
                canPickMany: true,
                title: "Select Commits to Attach",
                placeHolder: "Search commits..."
            });

            if (selected && selected.length > 0) {
                for (const commit of selected) {
                    try {
                        const diffOutput = execSync(`git show ${commit.hash} --patch`, {
                            cwd: workspace.uri.fsPath,
                            encoding: 'utf8',
                            maxBuffer: 1024 * 1024 * 10 // 10MB
                        });

                        this._view?.webview.postMessage({
                            type: 'addAttachments', attachments: [{
                                type: 'text',
                                name: `Commit ${commit.hash.substring(0, 7)}`,
                                data: `Commit: ${commit.hash}\nSubject: ${commit.label.replace('$(git-commit) ', '')}\n\n${diffOutput}`
                            }]
                        });
                    } catch (e: any) {
                        vscode.window.showErrorMessage(`Failed to fetch diff for commit ${commit.hash}: ${e.message}`);
                    }
                }
            }
        } catch (e: any) {
            vscode.window.showErrorMessage(`Failed to list commits. This workspace might not be a git repository.`);
        }
    }

    private updateUI() {
        this.log(`Updating UI (currentId: ${this.currentId}, conversations: ${this.conversations.length})`);
        this._view?.webview.postMessage({ type: 'render', chats: this.conversations, currentId: this.currentId, state: this.appState });
    }

    // --- File-Based Storage Implementation ---
    private getStorageDir(): string | null {
        if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
            const rootPath = vscode.workspace.workspaceFolders[0].uri.fsPath;
            const dir = path.join(rootPath, ".opengemini", "chats");
            if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
            return dir;
        }
        return null;
    }

    private loadConversations() {
        this.conversations = [];
        const dir = this.getStorageDir();
        if (dir) {
            try {
                const files = fs.readdirSync(dir);
                for (const file of files) {
                    if (file.endsWith(".json")) {
                        try {
                            const content = fs.readFileSync(path.join(dir, file), 'utf8');
                            const chat = JSON.parse(content);
                            if (chat && chat.id) this.conversations.push(chat);
                        } catch { }
                    }
                }
            } catch { }
        }
        this.conversations.sort((a, b) => b.timestamp - a.timestamp);
    }

    private saveChat(chat: Conversation) {
        const dir = this.getStorageDir();
        if (dir) {
            const safeId = chat.id.replace(/[^a-zA-Z0-9-]/g, "");
            try {
                fs.writeFileSync(path.join(dir, `${safeId}.json`), JSON.stringify(chat, null, 2));
            } catch { }
        }
    }

    private deleteChatFile(id: string) {
        const dir = this.getStorageDir();
        if (dir) {
            const safeId = id.replace(/[^a-zA-Z0-9-]/g, "");
            const filePath = path.join(dir, `${safeId}.json`);
            if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
        }
    }
    // ------------------------------------------

    private getHtml(webview: vscode.Webview) {
        const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this.context.extensionUri, 'media', 'main.js'));
        const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(this.context.extensionUri, 'media', 'style.css'));
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OG Studio</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <link rel="stylesheet" href="${styleUri}">
</head>
<body>
    <div id="history-sidebar" class="history-sidebar">
        <div class="header">
            <span>Conversations</span>
            <button class="icon-btn close-sidebar-btn">✕</button>
        </div>
        <div class="history-header">
            <input type="text" id="history-search" class="search-bar" placeholder="Search history...">
        </div>
        <div id="history-list" class="history-list"></div>
    </div>

    <div class="header">
        <div class="header-left">
            <button class="icon-btn">☰</button>
            <span id="header-title" class="title">New Chat</span>
        </div>
        <div class="header-right">
            <button class="icon-btn" onclick="vscode.postMessage({type:'newChat'})" title="New Chat">+</button>
            <button class="icon-btn" onclick="vscode.postMessage({type:'openSettings'})" title="Settings">⚙️</button>
        </div>
    </div>

    <div id="chat-container"></div>

    <div id="input-area" class="input-area">
        <div class="input-container">
            <div id="attachments-list" class="attachments-list"></div>
            <textarea id="chat-input" placeholder="Ask AI... (Drag & Drop files)" rows="1"></textarea>
            <div class="controls">
                <div class="left-controls">
                    <button class="icon-btn" id="attach-btn" title="Add Context">📎</button>
                    <button class="icon-btn" id="tools-btn" title="MCP Tools">🛠️</button>
                    <div id="mode-toggle" class="mode-toggle">
                        <button class="icon-btn mode-btn active" data-mode="Chat" title="Chat" type="button">💬</button>
                        <button class="icon-btn mode-btn" data-mode="QuickEdit" title="Quick Edit" type="button">✏️</button>
                    </div>
                    <select id="model-select"></select>
                </div>
                <div class="right-controls">
                    <button id="send-btn" class="send-btn">Send</button>
                </div>
            </div>
        </div>
    </div>

    <div id="ctx-menu" class="menu">
         <div class="menu-header">Add Context</div>
         <div class="menu-item" onclick="sendCtx('files')">📁 Files and Folders</div>
         <div class="menu-item" onclick="sendCtx('open_files')">📄 Add All Open Files</div>
         <div class="menu-item" onclick="sendCtx('image')">🖼️ Add Image...</div>
         <div class="menu-item" onclick="sendCtx('pdf')">📕 Add PDF...</div>
         <div class="menu-separator"></div>
         <div class="menu-item" onclick="sendCtx('project_structure')">🗂️ Project Structure</div>
         <div class="menu-separator"></div>
         <div class="menu-item" onclick="sendCtx('commits')">⎇ Commits</div>
    </div>

    <script src="${scriptUri}"></script>
</body>
</html>`;
    }
}
