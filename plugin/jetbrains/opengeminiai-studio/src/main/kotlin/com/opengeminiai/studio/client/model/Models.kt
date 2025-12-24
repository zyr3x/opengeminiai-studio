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

data class StorageWrapper(
    val conversations: List<Conversation>
)

// FIX: Added 'changes' field to persist modified files alongside the text
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