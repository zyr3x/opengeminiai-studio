package com.opengeminiai.studio.client.actions

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.opengeminiai.studio.client.service.ChatInterfaceService

class GenerateTestsAction : AnAction() {

    override fun update(e: AnActionEvent) {
        val project = e.project
        val editor = e.getData(CommonDataKeys.EDITOR)
        e.presentation.isEnabledAndVisible = project != null && editor != null && editor.selectionModel.hasSelection()
    }

    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val editor = e.getData(CommonDataKeys.EDITOR) ?: return
        val selectedText = editor.selectionModel.selectedText ?: return
        val psiFile = e.getData(CommonDataKeys.PSI_FILE)
        val ext = psiFile?.virtualFile?.extension ?: "txt"
        val prompt = "/test \n\n```$ext\n$selectedText\n```"

        ChatInterfaceService.getInstance(project).sendMessage(prompt)
    }
}