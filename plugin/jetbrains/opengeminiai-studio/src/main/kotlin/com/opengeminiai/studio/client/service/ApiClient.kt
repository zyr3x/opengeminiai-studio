package com.opengeminiai.studio.client.service

import com.opengeminiai.studio.client.model.*
import com.google.gson.Gson
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

object ApiClient {
    private val client = OkHttpClient.Builder().connectTimeout(60, TimeUnit.SECONDS).readTimeout(120, TimeUnit.SECONDS).build()
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

    data class ChatRequest(val model: String, val messages: List<ChatMessage>, val stream: Boolean = false)

    fun sendRequest(history: List<ChatMessage>, model: String, systemPrompt: String): String {
        val msgs = mutableListOf(ChatMessage("system", systemPrompt))
        msgs.addAll(history)

        val body = gson.toJson(ChatRequest(model, msgs, false)).toRequestBody("application/json".toMediaType())
        val request = Request.Builder().url("$BASE_URL/v1/chat/completions").post(body).build()

        client.newCall(request).execute().use { resp ->
            val str = resp.body?.string() ?: ""
            if (!resp.isSuccessful) return "Error ${resp.code}"

            if (str.trim().startsWith("data:")) {
                val sb = StringBuilder()
                str.lines().forEach { line ->
                    if (line.trim().startsWith("data:") && !line.contains("[DONE]")) {
                        try {
                            val json = line.trim().removePrefix("data:").trim()
                            val chunk = gson.fromJson(json, StreamChunk::class.java)
                            val content = chunk.choices.firstOrNull()?.delta?.content
                            if (content != null) sb.append(content)
                        } catch (e: Exception) { }
                    }
                }
                return sb.toString()
            }

            return try {
                val parsed = gson.fromJson(str, OpenAIResponse::class.java)
                parsed.choices.firstOrNull()?.message?.content ?: ""
            } catch (e: Exception) { "Parse Error" }
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
        } catch (e: Exception) { return listOf("gemini-2.0-flash-exp") }
    }
}