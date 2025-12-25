package com.opengeminiai.studio.client.model

import java.util.UUID
import java.text.SimpleDateFormat
import java.util.Date

data class Conversation(
    val id: String = UUID.randomUUID().toString(),
    var title: String = "New Chat",
    val messages: ArrayList<ChatMessage> = ArrayList(),
    var timestamp: Long = System.currentTimeMillis()
) {
    fun getFormattedDate(): String {
        return SimpleDateFormat("MMM dd, HH:mm").format(Date(timestamp))
    }
    override fun toString(): String = title
}

const val DEFAULT_SYSTEM_PROMPT = """You are an expert developer.
1. Answer using Markdown.
2. To MODIFY files, output JSON:
```json
{
  "action": "propose_changes",
  "changes": [ { "path": "/abs/path", "content": "NEW CONTENT" } ]
}
```"""

data class AppSettings(
    var defaultChatModel: String = "gemini-2.5-flash",
    var defaultQuickEditModel: String = "gemini-2.5-flash",
    var defaultCommitModel: String = "gemini-2.5-flash",

    // Prompt Selections (Keys from the API or "Default")
    var chatPromptKey: String = "Default",
    var quickEditPromptKey: String = "Default",
    var commitPromptKey: String = "Default"
)

data class StorageWrapper(
    val conversations: List<Conversation>,
    val settings: AppSettings? = null
)

data class ChatMessage(
    val role: String,
    val content: String,
    val changes: List<FileChange>? = null
)

data class ChangeRequest(val action: String?, val changes: List<FileChange>?)
data class FileChange(val path: String, val content: String)

data class StreamChunk(val choices: List<StreamChoice>)
data class StreamChoice(val delta: StreamDelta)
data class StreamDelta(val content: String?)

data class OpenAIResponse(val choices: List<Choice>)
data class Choice(val message: ChatMessage)
data class ModelsResponse(val data: List<ModelEntry>)
data class ModelEntry(val id: String)

// New DTO for System Prompts
data class SystemPromptEntry(
    val enabled: Boolean,
    val prompt: String,
    val disable_tools: Boolean? = null,
    val enable_native_tools: Boolean? = null
)