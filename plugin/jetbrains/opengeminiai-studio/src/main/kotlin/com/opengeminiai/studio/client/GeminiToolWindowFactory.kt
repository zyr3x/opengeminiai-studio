package com.opengeminiai.studio.client

import com.opengeminiai.studio.client.ui.MainPanel
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.*
import com.intellij.ui.content.ContentFactory

class GeminiToolWindowFactory : ToolWindowFactory {
    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val panel = MainPanel(project)
        val content = ContentFactory.getInstance().createContent(panel.getContent(), "", false)
        toolWindow.contentManager.addContent(content)

        toolWindow.setIcon(Icons.Logo)
    }
}