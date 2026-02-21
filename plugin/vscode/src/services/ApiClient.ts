import axios from 'axios';
import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { execSync } from 'child_process';
import { McpToolsResponse } from '../model';

export class ApiClient {
    private static getBaseUrl(): string {
        const config = vscode.workspace.getConfiguration('opengeminiai');
        return config.get<string>('serverUrl', 'http://localhost:8080').replace(/\/$/, '');
    }

    static async getPromptText(type: string): Promise<string> {
        // 1. Check Project Overrides (.opengemini/prompts/...)
        const workspace = vscode.workspace.workspaceFolders?.[0];
        if (workspace) {
            const fileName = type === 'Chat' ? 'chat.md' : type === 'QuickEdit' ? 'edit.md' : type === 'Commit' ? 'commit.md' : 'title.md';
            const localPath = path.join(workspace.uri.fsPath, '.opengemini', 'prompts', fileName);
            if (fs.existsSync(localPath)) {
                return this.substituteVariables(fs.readFileSync(localPath, 'utf8'));
            }
        }

        // 2. Check Configuration Keys (Server-side prompts)
        const config = vscode.workspace.getConfiguration('opengeminiai');
        let key = 'Default';
        if (type === 'Chat') key = config.get<string>('chatPromptKey', 'Default');
        else if (type === 'QuickEdit') key = config.get<string>('quickEditPromptKey', 'Default');
        else if (type === 'Commit') key = config.get<string>('commitPromptKey', 'Default');

        if (key !== 'Default') {
            try {
                const prompts = await this.getSystemPrompts();
                if (prompts && prompts[key]) return this.substituteVariables(prompts[key].prompt);
            } catch { }
        }

        // 3. Fallback to Hardcoded Defaults
        return this.substituteVariables(this.getDefaultPrompt(type));
    }

    private static getDefaultPrompt(type: string): string {
        if (type === 'Chat') return `You are an advanced AI Coding Agent integrated directly into VS Code via OpenGeminiAi Studio.
Your goal is to assist the user by analyzing code, answering questions, and providing code snippets.

### OUTPUT FORMAT
* **Markdown:** Use standard Markdown formatting for all responses.
* **Code Blocks:** ALWAYS wrap code in triple backticks with the language identifier.`;

        if (type === 'QuickEdit') return `You are an advanced AI Coding Agent integrated into VS Code.
Your goal is to modify files based on user requests.

### CRITICAL PROTOCOL FOR FILE MODIFICATIONS
You generally have access to read files, BUT you have **NO** direct ability to write files.
Instead, you must instruct the IDE Plugin to apply changes locally by outputting a JSON block.

### JSON FORMAT
To apply changes, output a single JSON block formatted as follows at the END of your answer:

\`\`\`json
{
  "action": "propose_changes",
  "changes": [
    {
      "path": "/absolute/path/to/project/filename.extension",
      "content": "FULL NEW CONTENT OF THE FILE GOES HERE"
    }
  ]
}
\`\`\``;

        if (type === 'Commit') return `Generate a professional git commit message based on the provided changes. Follow Conventional Commits format.`;

        return "Summarize the user request into a short, concise title (max 4-6 words).";
    }

    private static substituteVariables(text: string): string {
        const workspace = vscode.workspace.workspaceFolders?.[0];
        const now = new Date().toLocaleString();
        const os = `${process.platform} ${process.arch}`;
        const branch = this.getBranch();

        let result = text
            .replace(/{project_name}/g, workspace?.name || 'Unknown')
            .replace(/{project_path}/g, workspace?.uri.fsPath || '')
            .replace(/{current_datetime}/g, now)
            .replace(/{user_name}/g, process.env.USER || 'User')
            .replace(/{current_branch}/g, branch);

        if (text.includes('### SYSTEM CONTEXT')) return result; // Don't double append

        result += `\n\n### SYSTEM CONTEXT\n* **Project:** ${workspace?.name}\n* **Path:** ${workspace?.uri.fsPath}\n* **Date:** ${now}\n* **OS:** ${os}\n* **Branch:** ${branch}\n`;
        return result;
    }

    private static getBranch(): string {
        try {
            const workspace = vscode.workspace.workspaceFolders?.[0];
            if (workspace) {
                return execSync('git rev-parse --abbrev-ref HEAD', { cwd: workspace.uri.fsPath }).toString().trim();
            }
        } catch { }
        return 'Unknown';
    }

    static async getModels(): Promise<string[]> {
        try {
            const res = await axios.get(`${this.getBaseUrl()}/v1/models`, { timeout: 3000 });
            if (res.data && res.data.data) {
                return res.data.data.map((m: any) => m.id);
            }
        } catch { }
        return ['gemini-2.5-flash', 'gemini-2.5-flash-thinking'];
    }

    static async getSystemPrompts(): Promise<Record<string, { prompt: string }> | null> {
        try {
            const res = await axios.get(`${this.getBaseUrl()}/v1/system_prompts`, { timeout: 3000 });
            return res.data;
        } catch { return null; }
    }

    static async getMcpTools(): Promise<McpToolsResponse | null> {
        try {
            const res = await axios.get(`${this.getBaseUrl()}/api/mcp/list`, { timeout: 3000 });
            return res.data;
        } catch { return null; }
    }

    static async streamChat(messages: any[], model: string, onChunk: (val: string) => void, tools: string[] | null = null) {
        const body: any = {
            model,
            messages,
            stream: true,
            mcp_tools: tools
        };

        const response = await axios.post(`${this.getBaseUrl()}/v1/chat/completions`, body, { responseType: 'stream' });

        return new Promise<void>((resolve, reject) => {
            response.data.on('data', (chunk: Buffer) => {
                const lines = chunk.toString().split('\n');
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = line.slice(6).trim();
                        if (data === '[DONE]') break;
                        try {
                            const parsed = JSON.parse(data);
                            const content = parsed.choices?.[0]?.delta?.content;
                            if (content) onChunk(content);
                        } catch { }
                    }
                }
            });
            response.data.on('end', resolve);
            response.data.on('error', reject);
        });
    }
}