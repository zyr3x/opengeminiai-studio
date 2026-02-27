import * as vscode from 'vscode';
import { ChatViewProvider } from './providers/ChatViewProvider';
import * as path from 'path';

export function activate(context: vscode.ExtensionContext) {
    // 1. Register Diff Content Provider
    const diffContentProvider = new class implements vscode.TextDocumentContentProvider {
        onDidChangeEmitter = new vscode.EventEmitter<vscode.Uri>();
        onDidChange = this.onDidChangeEmitter.event;
        contentMap = new Map<string, string>();

        provideTextDocumentContent(uri: vscode.Uri): string {
            return this.contentMap.get(uri.toString()) || '';
        }

        update(uri: vscode.Uri, content: string) {
            this.contentMap.set(uri.toString(), content);
            this.onDidChangeEmitter.fire(uri);
        }
    };

    context.subscriptions.push(
        vscode.workspace.registerTextDocumentContentProvider('gemini-diff', diffContentProvider)
    );

    // 2. Register Helper Command for Diff
    context.subscriptions.push(vscode.commands.registerCommand('opengeminiai.updateDiffBuffer', (uri: vscode.Uri, content: string) => {
        diffContentProvider.update(uri, content);
    }));

    // 3. Register Chat Provider
    const outputChannel = vscode.window.createOutputChannel("OpenGeminiAI");
    const chatProvider = new ChatViewProvider(context, outputChannel);

    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider('opengeminiai.chatView', chatProvider)
    );

    const sendToChat = (text: string, selection?: string, fileName?: string) => {
        // Focus the chat view
        vscode.commands.executeCommand('opengeminiai.chatView.focus').then(() => {
            // Wait slightly for focus
            setTimeout(() => {
                let msg = text;
                if (selection && fileName) {
                    msg += `\n\n\`\`\`${path.extname(fileName).substring(1)}\n${selection}\n\`\`\``;
                }
                chatProvider.sendMessage(msg);
            }, 100);
        });
    };

    // 4. Register Commands
    context.subscriptions.push(
        vscode.commands.registerCommand('opengeminiai.explain', () => {
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                const selection = editor.document.getText(editor.selection);
                sendToChat('/explain\nExplain the following code:', selection, editor.document.fileName);
            }
        }),
        vscode.commands.registerCommand('opengeminiai.refactor', () => {
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                const selection = editor.document.getText(editor.selection);
                sendToChat('/refactor\nRefactor the following code:', selection, editor.document.fileName);
            }
        }),
        vscode.commands.registerCommand('opengeminiai.fix', () => {
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                const selection = editor.document.getText(editor.selection);
                sendToChat('/fix\nFind and fix bugs in the following code:', selection, editor.document.fileName);
            }
        }),
        vscode.commands.registerCommand('opengeminiai.test', () => {
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                const selection = editor.document.getText(editor.selection);
                sendToChat('/test\nGenerate unit tests for the following code:', selection, editor.document.fileName);
            }
        }),
        vscode.commands.registerCommand('opengeminiai.attachSelection', () => {
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                const selection = editor.document.getText(editor.selection);
                const fileName = path.basename(editor.document.fileName);
                chatProvider.sendMessage(`:::CTX:${fileName}:selection:::\n${selection}\n:::END:::`);
            }
        }),
        vscode.commands.registerCommand('opengeminiai.analyzeError', () => {
            // Try to get diagnostics from current file
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                const diagnostics = vscode.languages.getDiagnostics(editor.document.uri);
                if (diagnostics.length > 0) {
                    const errors = diagnostics.map(d => `[Line ${d.range.start.line + 1}] ${d.message}`).join('\n');
                    chatProvider.sendMessage(`/fix\nAnalyze and fix these errors in ${path.basename(editor.document.fileName)}:\n\n${errors}`);
                } else {
                    vscode.window.showInformationMessage("No errors found in current file.");
                }
            }
        }),
        vscode.commands.registerCommand('opengeminiai.projectHealth', () => {
            chatProvider.sendMessage("/project_health\nPerform a health check on the current project structure and main files.");
        })
    );
}