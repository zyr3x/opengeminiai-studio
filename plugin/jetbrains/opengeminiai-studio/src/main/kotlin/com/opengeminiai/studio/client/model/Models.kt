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

data class AppSettings(
    var defaultChatModel: String = "gemini-2.5-flash",
    var defaultQuickEditModel: String = "gemini-2.5-flash",
    var defaultCommitModel: String = "gemini-2.5-flash",
    var defaultTitleModel: String = "gemini-2.5-flash",

    // Connection Settings
    var baseUrl: String = "http://localhost:8080",

    // Prompt Selections (Keys from the API or "Default")
    var chatPromptKey: String = "Default",
    var quickEditPromptKey: String = "Default",
    var commitPromptKey: String = "Default",
    var titlePromptKey: String = "Default",

    // Context Filters (Comma-separated)
    var ignoredDirectories: String = "__pycache__, node_modules, .git, .idea, .vscode, venv, .venv, env, build, target, out, dist, coverage, .gradle, .DS_Store, vendor, bin, obj, .nuxt, .next",
    var ignoredExtensions: String = "pyc, pyo, pyd, class, o, so, dll, exe, dylib, jar, war, ear, zip, tar, gz, 7z, rar, iso, img, db, sqlite"
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

data class SystemPromptEntry(
    val enabled: Boolean,
    val prompt: String,
    val disable_tools: Boolean? = null,
    val enable_native_tools: Boolean? = null
)