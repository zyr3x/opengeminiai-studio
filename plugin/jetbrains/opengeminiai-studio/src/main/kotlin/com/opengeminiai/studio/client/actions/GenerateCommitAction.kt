package com.opengeminiai.studio.client.actions

import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.vcs.VcsDataKeys
import com.intellij.openapi.vcs.ui.CommitMessage
import com.intellij.openapi.application.ApplicationManager
import com.opengeminiai.studio.client.service.ApiClient
import com.opengeminiai.studio.client.service.PersistenceService
import com.opengeminiai.studio.client.model.ChatMessage
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.project.DumbAwareAction

class GenerateCommitAction : DumbAwareAction() {
    override fun update(e: AnActionEvent) {
        val project = e.project
        val commitMessageControl = e.getData(VcsDataKeys.COMMIT_MESSAGE_CONTROL)
        val changes = e.getData(VcsDataKeys.CHANGES)
        e.presentation.isEnabledAndVisible = project != null && commitMessageControl != null && !changes.isNullOrEmpty()
        e.presentation.text = "Generate Commit Message (AI)"
        e.presentation.icon = com.intellij.icons.AllIcons.Actions.Commit
    }

    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val commitMessageControl = e.getData(VcsDataKeys.COMMIT_MESSAGE_CONTROL) ?: return
        val changes = e.getData(VcsDataKeys.CHANGES) ?: return
        
        // Load settings to get the model
        val wrapper = PersistenceService.load(project)
        val model = wrapper.settings?.defaultCommitModel ?: "gemini-2.0-flash-exp"

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
                    val call = ApiClient.createChatCompletionCall(msgs, model, "You are a git commit message generator.")
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