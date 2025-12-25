package com.opengeminiai.studio.client.actions

import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.vcs.VcsDataKeys
import com.intellij.openapi.vcs.changes.Change
import com.intellij.openapi.vcs.changes.ChangeListManager
import com.intellij.openapi.application.ApplicationManager
import com.opengeminiai.studio.client.service.ApiClient
import com.opengeminiai.studio.client.service.PersistenceService
import com.opengeminiai.studio.client.model.ChatMessage
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.project.DumbAwareAction
import com.intellij.openapi.util.IconLoader

class GenerateCommitAction : DumbAwareAction() {

    private val pluginIcon = IconLoader.getIcon("/icons/logo-light.svg", GenerateCommitAction::class.java)

    private fun getIncludedChanges(e: AnActionEvent): List<Change> {
        val selectedChanges = e.getData(VcsDataKeys.CHANGES)
        if (!selectedChanges.isNullOrEmpty()) {
            return selectedChanges.toList()
        }

        val selectedLists = e.getData(VcsDataKeys.CHANGE_LISTS)
        if (!selectedLists.isNullOrEmpty()) {
            return selectedLists.flatMap { it.changes }
        }

        val project = e.project
        if (project != null) {
            val changeListManager = ChangeListManager.getInstance(project)
            val defaultList = changeListManager.defaultChangeList
            if (defaultList != null) {
                return defaultList.changes.toList()
            }
        }

        return emptyList()
    }

    override fun update(e: AnActionEvent) {
        val project = e.project
        val commitMessageControl = e.getData(VcsDataKeys.COMMIT_MESSAGE_CONTROL)

        e.presentation.isVisible = project != null && commitMessageControl != null
        e.presentation.isEnabled = project != null

        e.presentation.text = "Generate Commit Message (OpenGeminiAI Studio)"
        e.presentation.icon = pluginIcon
    }

    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val commitMessageControl = e.getData(VcsDataKeys.COMMIT_MESSAGE_CONTROL) ?: return

        val changes = getIncludedChanges(e)

        if (changes.isEmpty()) {
            commitMessageControl.setCommitMessage("Error: No changes detected. Make sure you have modified files in the active changelist.")
            return
        }

        val wrapper = PersistenceService.load(project)
        val settings = wrapper.settings ?: com.opengeminiai.studio.client.model.AppSettings()
        val model = settings.defaultCommitModel

        // Resolve prompt. Note: fetchSystemPrompts is not called here to avoid delay.
        // We rely on previous fetches or default fallback.
        val systemPrompt = ApiClient.getPromptText(settings.commitPromptKey, ApiClient.PromptType.Commit)

        val contentBuilder = StringBuilder()
        changes.take(20).forEach { change ->
             val path = change.afterRevision?.file?.name ?: change.beforeRevision?.file?.name
             contentBuilder.append("File: $path\n")
             try {
                 val before = change.beforeRevision?.content
                 val after = change.afterRevision?.content
                 if (before != null && after != null) {
                     contentBuilder.append("New Content:\n$after\n")
                 } else if (after != null) {
                     contentBuilder.append("Created with Content:\n$after\n")
                 } else if (before != null) {
                     contentBuilder.append("Deleted.\n")
                 }
             } catch (e: Exception) { }
             contentBuilder.append("\n")
        }

        var diffText = contentBuilder.toString()
        if (diffText.length > 40000) diffText = diffText.take(40000) + "\n...(truncated)..."

        val fullPrompt = "Generate a conventional git commit message for the following changes. Output ONLY the message.\n$diffText"

        ProgressManager.getInstance().run(object : Task.Backgroundable(project, "Generating Commit Message", true) {
            override fun run(indicator: ProgressIndicator) {
                try {
                    val msgs = listOf(ChatMessage("user", fullPrompt))
                    val call = ApiClient.createChatCompletionCall(msgs, model, systemPrompt)
                    val response = ApiClient.processCallResponse(call)
                    
                    ApplicationManager.getApplication().invokeLater {
                         commitMessageControl.setCommitMessage(response.trim())
                    }
                } catch (ex: Exception) {
                    ApplicationManager.getApplication().invokeLater {
                         commitMessageControl.setCommitMessage("Error generating message: ${ex.message}")
                    }
                }
            }
        })
    }
}