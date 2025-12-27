package com.opengeminiai.studio.client

import com.opengeminiai.studio.client.ui.MainPanel
import com.opengeminiai.studio.client.ui.WebPanel
import com.intellij.openapi.project.Project
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.wm.*
import com.intellij.ui.content.ContentFactory

class GeminiToolWindowFactory : ToolWindowFactory, DumbAware {
    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val contentFactory = ContentFactory.getInstance()

        // Tab 1: Native Studio (Chat & Quick Edit)
        val mainPanel = MainPanel(project)
        val studioContent = contentFactory.createContent(mainPanel.getContent(), "Studio", false)
        studioContent.putUserData(ToolWindow.SHOW_CONTENT_ICON, true)
        studioContent.icon = Icons.Logo
        toolWindow.contentManager.addContent(studioContent)

        // Tab 2: Gemini Web View
        val webPanel = WebPanel()
        val webContent = contentFactory.createContent(webPanel.getContent(), "Gemini Web", false)
        toolWindow.contentManager.addContent(webContent)

        toolWindow.setIcon(Icons.Logo)
    }
}
