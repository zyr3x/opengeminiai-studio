package com.opengeminiai.studio.client.actions

import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.vcs.VcsDataKeys
import com.intellij.openapi.vcs.changes.Change
import com.intellij.openapi.vcs.changes.ChangeListManager
import com.intellij.openapi.application.ApplicationManager
import com.opengeminiai.studio.client.service.ApiClient
import com.opengeminiai.studio.client.service.PersistenceService
import com.opengeminiai.studio.client.model.ChatMessage
import com.opengeminiai.studio.client.Icons
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.project.DumbAwareAction
import com.intellij.openapi.util.IconLoader

class GenerateCommitAction : DumbAwareAction() {

    private val pluginIcon = Icons.Logo

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

        // Only set if not already set by plugin.xml, but here we enforce consistency
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

        // Pass baseUrl from settings
        val baseUrl = settings.baseUrl
        val systemPrompt = ApiClient.getPromptText(settings.commitPromptKey, ApiClient.PromptType.Commit)

        val contentBuilder = StringBuilder()
        
        // Limit total processed files to avoid timeout/too large request
        changes.take(30).forEach { change ->
             val path = change.afterRevision?.file?.name ?: change.beforeRevision?.file?.name ?: "unknown"
             val isDirectory = change.afterRevision?.file?.isDirectory == true || change.beforeRevision?.file?.isDirectory == true
             
             if (isDirectory) return@forEach

             // Skip binary files check attempt (simple check via extension or virtualFile if available)
             val virtualFile = change.virtualFile
             if (virtualFile != null && virtualFile.fileType.isBinary) {
                 contentBuilder.append("File: $path (Binary file changed)\n\n")
                 return@forEach
             }

             contentBuilder.append("File: $path\n")
             try {
                 val before = change.beforeRevision?.content
                 val after = change.afterRevision?.content

                 when {
                     before != null && after != null -> {
                         // Modification: sending only 'after' content to save tokens, 
                         // or ideally we would send a diff, but full content is often safer for context if small.
                         // Truncating large files is crucial.
                         val cleanContent = after.take(2000)
                         contentBuilder.append("Status: Modified\nContent Preview:\n$cleanContent\n")
                         if (after.length > 2000) contentBuilder.append("...(truncated)\n")
                     }
                     after != null -> {
                         // Created
                         val cleanContent = after.take(2000)
                         contentBuilder.append("Status: Created\nContent:\n$cleanContent\n")
                         if (after.length > 2000) contentBuilder.append("...(truncated)\n")
                     }
                     before != null -> {
                         // Deleted
                         contentBuilder.append("Status: Deleted\n")
                     }
                 }
             } catch (e: Exception) {
                 contentBuilder.append("(Error reading file content)\n")
             }
             contentBuilder.append("\n")
        }

        var diffText = contentBuilder.toString()
        // Global safety cap
        if (diffText.length > 30000) diffText = diffText.take(30000) + "\n...(truncated globally)..."

        val fullPrompt = "Generate a concise, conventional git commit message (e.g., 'feat: ...', 'fix: ...') for the following changes. Output ONLY the message text.\n\n$diffText"

        ProgressManager.getInstance().run(object : Task.Backgroundable(project, "Generating Commit Message", true) {
            override fun run(indicator: ProgressIndicator) {
                try {
                    val msgs = listOf(ChatMessage("user", fullPrompt))
                    val call = ApiClient.createChatCompletionCall(msgs, model, systemPrompt, baseUrl)
                    val response = ApiClient.processCallResponse(call)
                    
                    ApplicationManager.getApplication().invokeLater {
                         if (!project.isDisposed) {
                             commitMessageControl.setCommitMessage(response.trim())
                         }
                    }
                } catch (ex: Exception) {
                    ApplicationManager.getApplication().invokeLater {
                         if (!project.isDisposed) {
                             commitMessageControl.setCommitMessage("Error generating message: ${ex.message}")
                         }
                    }
                }
            }
        })
    }
}
