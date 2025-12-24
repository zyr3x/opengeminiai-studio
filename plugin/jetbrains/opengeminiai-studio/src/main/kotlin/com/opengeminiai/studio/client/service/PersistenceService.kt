package com.opengeminiai.studio.client.service

import com.google.gson.GsonBuilder
import com.opengeminiai.studio.client.model.Conversation
import com.opengeminiai.studio.client.model.StorageWrapper
import com.intellij.openapi.project.Project
import java.io.File

object PersistenceService {
    private val gson = GsonBuilder().setPrettyPrinting().create()

    fun save(project: Project, conversations: List<Conversation>) {
        try {
            val ideaDir = File(project.basePath, ".idea")
            if (!ideaDir.exists()) ideaDir.mkdirs()
            val file = File(ideaDir, "opengeminiai.json")
            val wrapper = StorageWrapper(conversations)
            file.writeText(gson.toJson(wrapper))
        } catch (e: Exception) { e.printStackTrace() }
    }

    fun load(project: Project): List<Conversation> {
        try {
            val file = File(project.basePath, ".idea/opengeminiai.json")
            if (!file.exists()) return ArrayList()
            val json = file.readText()
            val wrapper = gson.fromJson(json, StorageWrapper::class.java)
            return wrapper.conversations ?: ArrayList()
        } catch (e: Exception) { return ArrayList() }
    }
}