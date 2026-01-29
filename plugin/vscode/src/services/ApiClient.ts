import axios from 'axios';
import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { execSync } from 'child_process';

export class ApiClient {
    static async getPromptText(type: string): Promise<string> {
        const config = vscode.workspace.getConfiguration('opengeminiai');
        const workspace = vscode.workspace.workspaceFolders?.[0];

        let rawPrompt = this.getDefaultPrompt(type);

        // Local overrides from .opengemini/prompts/
        if (workspace) {
            const fileName = type === 'Chat' ? 'chat.md' : type === 'QuickEdit' ? 'edit.md' : type === 'Commit' ? 'commit.md' : 'title.md';
            const localPath = path.join(workspace.uri.fsPath, '.opengemini', 'prompts', fileName);
            if (fs.existsSync(localPath)) {
                rawPrompt = fs.readFileSync(localPath, 'utf8');
            }
        }

        return this.substituteVariables(rawPrompt);
    }

    private static getDefaultPrompt(type: string): string {
        // Копирует логику из ApiClient.kt
        if (type === 'Chat') return "You are an advanced AI Coding Agent... [Full Text]";
        if (type === 'QuickEdit') return "You are an advanced AI Coding Agent... [Full Protocol]";
        return "";
    }

    private static substituteVariables(text: string): string {
        const workspace = vscode.workspace.workspaceFolders?.[0];
        const now = new Date().toLocaleString();
        return text
            .replace(/{project_name}/g, workspace?.name || 'Unknown')
            .replace(/{project_path}/g, workspace?.uri.fsPath || '')
            .replace(/{current_datetime}/g, now)
            .replace(/{user_name}/g, process.env.USER || 'User')
            .replace(/{current_branch}/g, this.getBranch());
    }

    private static getBranch(): string {
        try {
            const workspace = vscode.workspace.workspaceFolders?.[0];
            return execSync('git rev-parse --abbrev-ref HEAD', { cwd: workspace?.uri.fsPath }).toString().trim();
        } catch { return 'Unknown'; }
    }

    static async streamChat(messages: any[], model: string, onChunk: (val: string) => void) {
        const baseUrl = vscode.workspace.getConfiguration('opengeminiai').get('baseUrl') as string;
        const response = await axios.post(`${baseUrl}/v1/chat/completions`, { model, messages, stream: true }, { responseType: 'stream' });

        return new Promise((resolve) => {
            response.data.on('data', (chunk: Buffer) => {
                const lines = chunk.toString().split('\n');
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = line.slice(6);
                        if (data === '[DONE]') break;
                        try {
                            const content = JSON.parse(data).choices[0].delta.content;
                            if (content) onChunk(content);
                        } catch {}
                    }
                }
            });
            response.data.on('end', resolve);
        });
    }
}