import * as vscode from 'vscode';
import { ChatViewProvider } from './providers/ChatViewProvider';
import { WebPanelProvider } from './providers/WebPanelProvider';

export function activate(context: vscode.ExtensionContext) {
    const chatProvider = new ChatViewProvider(context);
    const webProvider = new WebPanelProvider();

    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider('opengeminiai.chatView', chatProvider),
        vscode.window.registerWebviewViewProvider('opengeminiai.webView', webProvider)
    );

    // Slash command shortcuts
    const commands = [
        { id: 'explain', cmd: '/explain' },
        { id: 'refactor', cmd: '/refactor' },
        { id: 'generateTests', cmd: '/test' },
        { id: 'findBugs', cmd: '/fix' }
    ];

    commands.forEach(c => {
        context.subscriptions.push(vscode.commands.registerCommand(`opengeminiai.${c.id}`, () => {
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                const selection = editor.document.getText(editor.selection);
                chatProvider.sendMessage(`${c.cmd}\n\n\`\`\`${editor.document.languageId}\n${selection}\n\`\`\``);
            }
        }));
    });
}