package com.opengeminiai.studio.client.service

import com.google.gson.GsonBuilder
import com.opengeminiai.studio.client.model.Conversation
import com.opengeminiai.studio.client.model.StorageWrapper
import com.opengeminiai.studio.client.model.AppSettings
import com.intellij.openapi.project.Project
import java.io.File

object PersistenceService {
    private val gson = GsonBuilder().setPrettyPrinting().create()
    private val saveLock = Any()

    // Storage Paths
    private const val LEGACY_FILE = "opengeminiai.json"
    private const val FOLDER_NAME = "opengeminiai"
    private const val SETTINGS_FILE = "settings.json"
    private const val CHATS_DIR = "chats"

    fun save(project: Project, conversations: List<Conversation>, settings: AppSettings) {
        synchronized(saveLock) {
            try {
                val ideaDir = File(project.basePath, ".idea")
                if (!ideaDir.exists()) return // Should usually exist in a valid project

                val baseDir = File(ideaDir, FOLDER_NAME)
                if (!baseDir.exists()) baseDir.mkdirs()

                val chatsDir = File(baseDir, CHATS_DIR)
                if (!chatsDir.exists()) chatsDir.mkdirs()

                // 1. Save Settings
                val settingsFile = File(baseDir, SETTINGS_FILE)
                settingsFile.writeText(gson.toJson(settings))

                // 2. Save Conversations (individual files)
                val activeIds = conversations.map { it.id }.toSet()
                
                conversations.forEach { chat ->
                    // Sanitize ID just in case
                    val safeId = chat.id.replace("[^a-zA-Z0-9-]".toRegex(), "")
                    val chatFile = File(chatsDir, "$safeId.json")
                    chatFile.writeText(gson.toJson(chat))
                }

                // 3. Clean up deleted conversations (files that exist but are not in the current list)
                chatsDir.listFiles()?.forEach { file ->
                    if (file.isFile && file.extension == "json") {
                        val id = file.nameWithoutExtension
                        if (!activeIds.contains(id)) {
                            file.delete()
                        }
                    }
                }

                // 4. Handle Legacy: Rename old file if it exists to mark migration as done
                val legacyFile = File(ideaDir, LEGACY_FILE)
                if (legacyFile.exists()) {
                    legacyFile.renameTo(File(ideaDir, "$LEGACY_FILE.old"))
                }

            } catch (e: Exception) { e.printStackTrace() }
        }
    }

    fun load(project: Project): StorageWrapper {
        val ideaDir = File(project.basePath, ".idea")
        val baseDir = File(ideaDir, FOLDER_NAME)
        val legacyFile = File(ideaDir, LEGACY_FILE)

        var settings = AppSettings()
        val conversations = ArrayList<Conversation>()

        // 1. Try New Folder Structure First
        if (baseDir.exists()) {
            // Load Settings
            val settingsFile = File(baseDir, SETTINGS_FILE)
            if (settingsFile.exists()) {
                try {
                    val loadedSettings = gson.fromJson(settingsFile.readText(), AppSettings::class.java)
                    if (loadedSettings != null) settings = loadedSettings
                } catch (e: Exception) { e.printStackTrace() }
            }

            // Load Chats
            val chatsDir = File(baseDir, CHATS_DIR)
            if (chatsDir.exists()) {
                chatsDir.listFiles()?.forEach { file ->
                    if (file.isFile && file.extension == "json") {
                        try {
                            val chat = gson.fromJson(file.readText(), Conversation::class.java)
                            if (chat != null) conversations.add(chat)
                        } catch (e: Exception) { e.printStackTrace() }
                    }
                }
            }
            
            // Sort by timestamp descending (newest first)
            conversations.sortByDescending { it.timestamp }
            
            return StorageWrapper(conversations, settings)
        }

        // 2. Fallback to Legacy File (Migration will happen on next save)
        if (legacyFile.exists()) {
            try {
                val json = legacyFile.readText()
                val wrapper = gson.fromJson(json, StorageWrapper::class.java)
                
                val safeConversations = wrapper?.conversations ?: ArrayList()
                val safeSettings = wrapper?.settings ?: AppSettings()
                
                return StorageWrapper(safeConversations, safeSettings)
            } catch (e: Exception) { e.printStackTrace() }
        }

        return StorageWrapper(ArrayList(), AppSettings())
    }
}
