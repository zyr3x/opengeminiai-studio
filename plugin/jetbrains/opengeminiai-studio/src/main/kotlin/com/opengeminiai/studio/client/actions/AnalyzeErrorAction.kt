package com.opengeminiai.studio.client.actions

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.opengeminiai.studio.client.service.ChatInterfaceService

class AnalyzeErrorAction : AnAction() {

    override fun update(e: AnActionEvent) {
        val project = e.project
        val editor = e.getData(CommonDataKeys.EDITOR)
        // Enable if text is selected, often used in Console/Log views
        e.presentation.isEnabledAndVisible = project != null && editor != null && editor.selectionModel.hasSelection()
    }

    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val editor = e.getData(CommonDataKeys.EDITOR) ?: return
        val selectedText = editor.selectionModel.selectedText ?: return

        // For error analysis, we treat it as generic text usually, or try to detect stack trace
        val prompt = "/fix\n\nError Log / Stack Trace:\n```text\n$selectedText\n```"

        ChatInterfaceService.getInstance(project).sendMessage(prompt)
    }
}