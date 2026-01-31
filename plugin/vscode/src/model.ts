export interface Attachment {
    type: 'file' | 'text';
    name: string;
    data: string; // Absolute path for file, content for text
    ignoreTypes?: string;
    ignoreFiles?: string;
    ignoreDirs?: string;
}

export interface ChatMessage {
    role: 'system' | 'user' | 'assistant';
    content: string;
    changes?: any[];
}

export interface Conversation {
    id: string;
    title: string;
    messages: ChatMessage[];
    timestamp: number;
    draftInput: string;
    draftAttachments: Attachment[];
}

export interface McpTool {
    name: string;
    description?: string;
}

export interface McpToolsResponse {
    built_in: McpTool[];
    servers: Record<string, { methods: McpTool[] }>;
}

export interface AppState {
    mode: 'Chat' | 'QuickEdit';
    model: string;
    toolsMode: 'Auto' | 'Manual' | 'Disabled';
    selectedTools: string[];
    availableModels: string[];
    availableTools: McpToolsResponse | null;
}