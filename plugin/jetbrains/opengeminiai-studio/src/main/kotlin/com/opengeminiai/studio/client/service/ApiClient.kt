package com.opengeminiai.studio.client.service

import com.opengeminiai.studio.client.model.*
import com.google.gson.Gson
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
    private const val BASE_URL = "http://localhost:8080"

    val CHAT_PROMPT = """
    You are an expert developer.
    1. Answer using Markdown.
    2. To MODIFY files, output JSON:
    ```json
    {
      "action": "propose_changes",
      "changes": [ { "path": "/abs/path", "content": "NEW CONTENT" } ]
    }
    ```
    """.trimIndent()

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

    // Internal DTO to send only role/content to the API (ignoring local fields like 'changes')
    private data class ApiChatMessage(val role: String, val content: String)
    private data class ChatRequest(val model: String, val messages: List<ApiChatMessage>, val stream: Boolean = false)

    /**
     * Creates an OkHttp Call object for a chat completion request.
     * The call is not executed by this function.
     */
    fun createChatCompletionCall(history: List<ChatMessage>, model: String, systemPrompt: String): Call {
        // Map persistent ChatMessage to purely API-focused ApiChatMessage
        val msgs = mutableListOf(ApiChatMessage("system", systemPrompt))
        msgs.addAll(history.map { ApiChatMessage(it.role, it.content) })

        val body = gson.toJson(ChatRequest(model, msgs, false)).toRequestBody("application/json".toMediaType())
        val request = Request.Builder().url("$BASE_URL/v1/chat/completions").post(body).build()
        return client.newCall(request)
    }

    /**
     * Executes an OkHttp Call and processes its response.
     * @param call The OkHttp Call to execute.
     * @return The parsed content of the AI response.
     * @throws Exception if the request fails or parsing errors occur.
     */
    fun processCallResponse(call: Call): String {
        call.execute().use { resp ->
            val str = resp.body?.string() ?: ""
            if (!resp.isSuccessful) return "Error ${resp.code}: ${str.take(200)} "

            // Handle SSE (Streaming) response if detected
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
                            } catch (e: Exception) {
                                // Ignore malformed chunks
                            }
                        }
                    }
                }
                return sb.toString()
            }

            // Handle Standard JSON response
            return try {
                val parsed = gson.fromJson(str, OpenAIResponse::class.java)
                parsed.choices.firstOrNull()?.message?.content ?: ""
            } catch (e: Exception) {
                "Parse Error: ${e.message}"
            }
        }
    }

    fun getModels(): List<String> {
        try {
            val req = Request.Builder().url("$BASE_URL/v1/models").get().build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return listOf("gemini-2.0-flash-exp")
                val str = resp.body?.string() ?: return listOf()
                val parsed = gson.fromJson(str, ModelsResponse::class.java)
                return parsed.data.map { it.id }
            }
        } catch (e: Exception) {
            return listOf("gemini-2.0-flash-exp")
        }
    }
}