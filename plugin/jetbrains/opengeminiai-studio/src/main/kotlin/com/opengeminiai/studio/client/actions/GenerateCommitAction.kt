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
import com.intellij.ui.AnimatedIcon
import java.util.concurrent.atomic.AtomicBoolean

class GenerateCommitAction : DumbAwareAction() {

    private val isGenerating = AtomicBoolean(false)

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

        if (isGenerating.get()) {
            e.presentation.isEnabled = false
            e.presentation.text = "Generating Commit Message..."
            e.presentation.icon = AnimatedIcon.Default()
        } else {
            e.presentation.isEnabled = project != null
            e.presentation.text = "Generate Commit Message (OpenGeminiAI Studio)"
            e.presentation.icon = Icons.Logo
        }
    }

    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val commitMessageControl = e.getData(VcsDataKeys.COMMIT_MESSAGE_CONTROL) ?: return

        if (isGenerating.get()) return

        val changes = getIncludedChanges(e)

        if (changes.isEmpty()) {
            commitMessageControl.setCommitMessage("Error: No changes detected. Make sure you have modified files in the active changelist.")
            return
        }

        isGenerating.set(true)
        
        val wrapper = PersistenceService.load(project)
        val settings = wrapper.settings ?: com.opengeminiai.studio.client.model.AppSettings()
        val model = settings.defaultCommitModel
        val baseUrl = settings.baseUrl

        ProgressManager.getInstance().run(object : Task.Backgroundable(project, "Generating Commit Message", true) {
            override fun run(indicator: ProgressIndicator) {
                try {
                    val systemPrompt = ApiClient.getPromptText(project, settings.commitPromptKey, ApiClient.PromptType.Commit)
                    val contentBuilder = StringBuilder()
                    
                    val maxFiles = settings.commitMaxFiles
                    val maxChars = settings.commitMaxContextLength

                    // Limit total processed files to avoid timeout/too large request
                    changes.take(maxFiles).forEach { change ->
                         if (indicator.isCanceled) return

                         val path = change.afterRevision?.file?.name ?: change.beforeRevision?.file?.name ?: "unknown"
                         val isDirectory = change.afterRevision?.file?.isDirectory == true || change.beforeRevision?.file?.isDirectory == true

                         if (!isDirectory) {
                             // Skip binary files check attempt (simple check via extension or virtualFile if available)
                             val virtualFile = change.virtualFile
                             if (virtualFile != null && virtualFile.fileType.isBinary) {
                                 contentBuilder.append("File: $path (Binary file changed)\n\n")
                             } else {
                                 contentBuilder.append("File: $path\n")
                                 try {
                                     val before = change.beforeRevision?.content
                                     val after = change.afterRevision?.content

                                     when {
                                         before != null && after != null -> {
                                             val cleanContent = after.take(2000)
                                             contentBuilder.append("Status: Modified\nContent Preview:\n$cleanContent\n")
                                             if (after.length > 2000) contentBuilder.append("...(truncated)\n")
                                         }
                                         after != null -> {
                                             val cleanContent = after.take(2000)
                                             contentBuilder.append("Status: Created\nContent:\n$cleanContent\n")
                                             if (after.length > 2000) contentBuilder.append("...(truncated)\n")
                                         }
                                         before != null -> {
                                             contentBuilder.append("Status: Deleted\n")
                                         }
                                     }
                                 } catch (e: Exception) {
                                     contentBuilder.append("(Error reading file content)\n")
                                 }
                                 contentBuilder.append("\n")
                             }
                         }
                    }

                    var diffText = contentBuilder.toString()
                    if (diffText.length > maxChars) diffText = diffText.take(maxChars) + "\n...(truncated globally)..."

                    val fullPrompt = "Generate a concise, conventional git commit message (e.g., 'feat: ...', 'fix: ...') for the following changes. Output ONLY the message text.\n\n$diffText"

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
                } finally {
                    isGenerating.set(false)
                }
            }
            
            override fun onCancel() {
                isGenerating.set(false)
                super.onCancel()
            }
        })
    }
}
