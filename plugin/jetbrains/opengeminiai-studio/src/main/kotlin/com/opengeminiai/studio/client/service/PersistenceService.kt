package com.opengeminiai.studio.client.service

import com.google.gson.GsonBuilder
import com.opengeminiai.studio.client.model.Conversation
import com.opengeminiai.studio.client.model.StorageWrapper
import com.opengeminiai.studio.client.model.AppSettings
import com.intellij.openapi.project.Project
import java.io.File

object PersistenceService {
    private val gson = GsonBuilder().setPrettyPrinting().create()

    fun save(project: Project, conversations: List<Conversation>, settings: AppSettings) {
        try {
            val ideaDir = File(project.basePath, ".idea")
            if (!ideaDir.exists()) ideaDir.mkdirs()
            val file = File(ideaDir, "opengeminiai.json")
            val wrapper = StorageWrapper(conversations, settings)
            file.writeText(gson.toJson(wrapper))
        } catch (e: Exception) { e.printStackTrace() }
    }

    fun load(project: Project): StorageWrapper {
        try {
            val file = File(project.basePath, ".idea/opengeminiai.json")
            if (!file.exists()) return StorageWrapper(ArrayList(), AppSettings())
            val json = file.readText()
            var wrapper = gson.fromJson(json, StorageWrapper::class.java)
            if (wrapper.conversations == null) wrapper = wrapper.copy(conversations = ArrayList())
            if (wrapper.settings == null) wrapper = wrapper.copy(settings = AppSettings())
            return wrapper
        } catch (e: Exception) { return StorageWrapper(ArrayList(), AppSettings()) }
    }
}