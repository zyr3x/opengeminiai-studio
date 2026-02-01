package com.opengeminiai.studio.client.actions

import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.project.DumbAwareAction
import com.intellij.openapi.project.Project
import com.intellij.openapi.vcs.changes.ChangeListManager
import com.intellij.openapi.application.ApplicationManager
import com.opengeminiai.studio.client.service.ChatInterfaceService
import com.opengeminiai.studio.client.Icons
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

class ProjectHealthAction : DumbAwareAction("Project Health Check", "Analyzes recent project activity and health", Icons.Logo) {

    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val changeListManager = ChangeListManager.getInstance(project)
        val affectedFiles = changeListManager.affectedPaths

        val report = StringBuilder()
        report.append("### PROJECT HEALTH REPORT\n")
        report.append("* **Project:** ${project.name}\n")
        report.append("* **Analysis Time:** ${LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"))}\n\n")

        report.append("#### Current Activity\n")
        if (affectedFiles.isEmpty()) {
            report.append("* No uncommitted changes detected.\n")
        } else {
            report.append("* **Modified Files (${affectedFiles.size}):**\n")
            affectedFiles.take(15).forEach { report.append("  - ${it.name}\n") }
            if (affectedFiles.size > 15) report.append("  - ... and ${affectedFiles.size - 15} more\n")
        }

        val prompt = """
            Analyze the following project activity and provide a brief 'Health Check' summary.
            Focus on identifying the current development focus, potential risks (like many modified files), and suggestions for next steps.
            
            ${report.toString()}
        """.trimIndent()

        ChatInterfaceService.getInstance(project).sendMessage(prompt)
    }
}