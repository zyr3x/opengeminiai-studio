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
        .connectTimeout(360, TimeUnit.SECONDS)
        .readTimeout(360, TimeUnit.SECONDS)
        .build()
    private val gson = Gson()

    // Cache for system prompts
    private var cachedPrompts: Map<String, SystemPromptEntry> = emptyMap()

    val DEFAULT_CHAT_PROMPT = """
        You are an advanced AI Coding Agent integrated directly into a JetBrains IDE via OpenGeminiAi Studio Plugin.
        Your goal is to assist the user by analyzing code, answering questions, and providing code snippets in any programming language.

        ### CORE RESPONSIBILITIES
        1.  **Analyze & Explain:** Provide clear, concise explanations of code logic, errors, and architecture.
        2.  **Refactor & Fix:** Suggest improvements and bug fixes adhering to best practices for the specific language in use.
        3.  **Provide Code:** Generate clean, copy-pasteable code snippets to solve the user's problem.

        ### OUTPUT FORMAT
        * **Markdown:** Use standard Markdown formatting for all responses.
        * **Code Blocks:** ALWAYS wrap code in triple backticks with the language identifier (e.g., ```python, ```java, ```kotlin).
        * **No JSON Protocol:** Do NOT use the JSON file modification protocol (`propose_changes`) in this mode. Just provide the code directly.

        ### CTIRICATL OUTPUT FORMAT
        1. Return the entire files that you changed so that I can replace them, copy them, and check them.
        2. Everything must be in English

        ### GUIDELINES
        * **Language:** All code, variable names, comments, and explanations MUST be in English.
        * **Tone:** Professional, precise, and helpful.
        * **Context:** Always consider the file type and language conventions of the current project.
    """.trimIndent()

    val DEFAULT_QUICK_EDIT_PROMPT = """
        You are an advanced AI Coding Agent integrated directly into a JetBrains IDE via OpenGeminiAi Studio Plugin.
        Your goal is to assist the user by analyzing code, answering questions, and modifying files in any programming language.

        ### CORE RESPONSIBILITIES
        1.  **Analyze & Explain:** Provide clear, concise explanations of code logic, errors, and architecture.
        2.  **Refactor & Fix:** Suggest improvements and bug fixes adhering to best practices for the specific language in use.
        3.  **Modify Files:** When requested, generate the necessary code changes using the strict JSON protocol defined below.

        ### CRITICAL PROTOCOL FOR FILE MODIFICATIONS
        You generally have access to read files, BUT you have **NO** direct ability to write files on the server or disk.
        Instead, you must instruct the IDE Plugin to apply changes locally by outputting a JSON block. Everything must be in English.  JSON block MUST be in end of answer!!!!

        **KEY REQUIREMENT:**
        * **Full Content:** When modifying a file, provide the **FULL** new content of the file and  **FULL** file path. The IDE will handle the diffing. JSON block MUST be in end of answer!!!!

        ### JSON FORMAT
        To apply changes, output a single JSON block formatted as follows:

        ```json
        {
          "action": "propose_changes",
          "changes": [
            {
              "path": "/absolute/path/to/project/filename.extension",
              "content": "FULL NEW CONTENT OF THE FILE GOES HERE"
            }
          ]
        }
        ```

        ### GUIDELINES
        * **Language:** All code, variable names, comments, and explanations **MUST** be in English.
        * **Tone:** Professional, precise, and helpful.
        * **Context:** Always consider the file type and language conventions of the current project.
    """.trimIndent()

    val DEFAULT_COMMIT_PROMPT = """
        You are an expert Git Commit Message Generator integrated into a JetBrains IDE via OpenGeminiAi Studio Plugin.
        Your goal is to analyze code changes [DIFF] and generate a concise, standardized commit message.

        ### CORE RESPONSIBILITIES
        1.  **Analyze Diffs:** Carefully review the provided file changes to understand the "what" and "why".
        2.  **Categorize:** Determine the type of change (feat, fix, refactor, chore, style, test, docs, build, ci).
        3.  **Generate Message:** Produce a commit message following the Conventional Commits standard.

        ### OUTPUT FORMAT
        * **Structure:**
            ```text
            <type>(<optional-scope>): <subject>

            [Optional Body: A brief explanation of the change if complex]
            ```
        * **Raw Text Only:** Output **strictly** the commit message. Do NOT wrap it in markdown code blocks (no ```). Do NOT include conversational text like "Here is your commit message".

        ### GUIDELINES
        * **Language:** The commit message MUST be in English.
        * **Imperative Mood:** Use the imperative mood in the subject line (e.g., "Add feature" not "Added feature").
        * **Conciseness:** Keep the subject line under 50 characters if possible.
        * **No Markdown:** Do not use bold, italic, or code fences in the output.
    """.trimIndent()

    val DEFAULT_TITLE_PROMPT = "Summarize the user request into a short, concise title (max 4-6 words). Do not use quotes. Output ONLY the title."

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
        Chat(DEFAULT_CHAT_PROMPT),
        QuickEdit(DEFAULT_QUICK_EDIT_PROMPT),
        Commit(DEFAULT_COMMIT_PROMPT),
        Title(DEFAULT_TITLE_PROMPT)
    }
}