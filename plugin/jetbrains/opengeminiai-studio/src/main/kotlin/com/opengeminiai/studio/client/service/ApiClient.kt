package com.opengeminiai.studio.client.service

import com.opengeminiai.studio.client.model.*
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

object ApiClient {
    private val client = OkHttpClient.Builder()
        .connectTimeout(60, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()
    private val gson = Gson()

    // Cache for system prompts
    private var cachedPrompts: Map<String, SystemPromptEntry> = emptyMap()

    val QUICK_EDIT_PROMPT = """
    You are a code editing engine.
    Output ONLY the JSON block to apply changes.
    ```json
    {
      "action": "propose_changes",
      "changes": [ { "path": "/abs/path", "content": "NEW CONTENT" } ]
    }
    ```
    """.trimIndent()

    val DEFAULT_COMMIT_PROMPT = "You are a git commit message generator."

    private data class ApiChatMessage(val role: String, val content: String)
    private data class ChatRequest(val model: String, val messages: List<ApiChatMessage>, val stream: Boolean = false)

    fun createChatCompletionCall(history: List<ChatMessage>, model: String, systemPrompt: String, baseUrl: String, stream: Boolean = false): Call {
        val msgs = mutableListOf(ApiChatMessage("system", systemPrompt))
        msgs.addAll(history.map { ApiChatMessage(it.role, it.content) })

        // Remove trailing slash if present to avoid double slashes
        val cleanUrl = baseUrl.trimEnd('/')

        val body = gson.toJson(ChatRequest(model, msgs, stream)).toRequestBody("application/json".toMediaType())
        val request = Request.Builder().url("$cleanUrl/v1/chat/completions").post(body).build()
        return client.newCall(request)
    }

    fun streamChatCompletion(call: Call, onChunk: (String) -> Unit): String {
        val fullContent = StringBuilder()
        call.execute().use { resp ->
            if (!resp.isSuccessful) {
                val err = "Error ${resp.code}: ${resp.message}"
                onChunk(err)
                return err
            }

            val source = resp.body?.source()
            if (source == null) return ""

            while (!source.exhausted()) {
                val line = source.readUtf8Line() ?: break
                if (line.trim().startsWith("data:")) {
                    val json = line.trim().substring(5).trim()
                    if (json == "[DONE]") break
                    if (json.isNotEmpty()) {
                        try {
                            val chunk = gson.fromJson(json, StreamChunk::class.java)
                            val delta = chunk.choices.firstOrNull()?.delta?.content
                            if (!delta.isNullOrEmpty()) {
                                onChunk(delta)
                                fullContent.append(delta)
                            }
                        } catch (e: Exception) { }
                    }
                }
            }
        }
        return fullContent.toString()
    }

    fun processCallResponse(call: Call): String {
        call.execute().use { resp ->
            val str = resp.body?.string() ?: ""
            if (!resp.isSuccessful) return "Error ${resp.code}: ${str.take(200)} "

            if (str.trim().startsWith("data:")) {
                val sb = StringBuilder()
                str.lines().forEach { line ->
                    val trimmed = line.trim()
                    if (trimmed.startsWith("data:")) {
                        val json = trimmed.substring(5).trim()
                        if (json != "[DONE]" && json.isNotEmpty()) {
                            try {
                                val chunk = gson.fromJson(json, StreamChunk::class.java)
                                val content = chunk.choices.firstOrNull()?.delta?.content
                                if (content != null) sb.append(content)
                            } catch (e: Exception) { }
                        }
                    }
                }
                return sb.toString()
            }

            return try {
                val parsed = gson.fromJson(str, OpenAIResponse::class.java)
                parsed.choices.firstOrNull()?.message?.content ?: ""
            } catch (e: Exception) {
                "Parse Error: ${e.message}"
            }
        }
    }

    fun getModels(baseUrl: String): List<String> {
        try {
            val cleanUrl = baseUrl.trimEnd('/')
            val req = Request.Builder().url("$cleanUrl/v1/models").get().build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return listOf("gemini-2.5-flash")
                val str = resp.body?.string() ?: return listOf()
                val parsed = gson.fromJson(str, ModelsResponse::class.java)
                return parsed.data.map { it.id }
            }
        } catch (e: Exception) {
            return listOf("gemini-2.5-flash")
        }
    }

    // --- System Prompt Logic ---

    fun fetchSystemPrompts(baseUrl: String): Map<String, SystemPromptEntry> {
        return try {
            val cleanUrl = baseUrl.trimEnd('/')
            val req = Request.Builder().url("$cleanUrl/v1/system_prompts").get().build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return emptyMap()
                val str = resp.body?.string() ?: return emptyMap()
                val type = object : TypeToken<Map<String, SystemPromptEntry>>() {}.type
                val map: Map<String, SystemPromptEntry> = gson.fromJson(str, type)
                // Filter only enabled
                cachedPrompts = map.filter { it.value.enabled }
                cachedPrompts
            }
        } catch (e: Exception) {
            emptyMap()
        }
    }

    fun getAvailablePromptKeys(): List<String> {
        return listOf("Default") + cachedPrompts.keys.sorted()
    }

    fun getPromptText(key: String, type: PromptType): String {
        if (key == "Default") return type.defaultText
        return cachedPrompts[key]?.prompt ?: type.defaultText
    }

    enum class PromptType(val defaultText: String) {
        Chat(DEFAULT_SYSTEM_PROMPT),
        QuickEdit(QUICK_EDIT_PROMPT),
        Commit(DEFAULT_COMMIT_PROMPT)
    }
}