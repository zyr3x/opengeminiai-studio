package com.opengeminiai.studio.client.actions

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.ui.Messages
import com.opengeminiai.studio.client.service.ChatInterfaceService
import com.opengeminiai.studio.client.Icons

class AttachToChatAction : AnAction() {

    override fun update(e: AnActionEvent) {
        val project = e.project
        val editor = e.getData(CommonDataKeys.EDITOR)
        // Visible if there is a selection
        e.presentation.isEnabledAndVisible = project != null && editor != null && editor.selectionModel.hasSelection()
    }

    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val editor = e.getData(CommonDataKeys.EDITOR) ?: return
        val selectedText = editor.selectionModel.selectedText ?: return

        // Ask for a title
        val title = Messages.showInputDialog(
            project,
            "Enter a name for this attachment:",
            "Attach to Chat",
            Messages.getQuestionIcon(),
            "Selection",
            null
        )

        if (!title.isNullOrBlank()) {
            ChatInterfaceService.getInstance(project).addContext(title, selectedText)
        }
    }
}
