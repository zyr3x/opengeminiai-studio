package com.opengeminiai.studio.client.service

import com.intellij.openapi.components.Service
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindowManager
import com.opengeminiai.studio.client.ui.MainPanel
import javax.swing.SwingUtilities

@Service(Service.Level.PROJECT)
class ChatInterfaceService(val project: Project) {

    private var mainPanel: MainPanel? = null

    fun registerPanel(panel: MainPanel) {
        this.mainPanel = panel
    }

    fun sendMessage(text: String) {
        val toolWindow = ToolWindowManager.getInstance(project).getToolWindow("OpenGeminiAI Studio")
        toolWindow?.activate {
            SwingUtilities.invokeLater {
                mainPanel?.setPendingInput(text)
                mainPanel?.sendMessage()
            }
        }
    }

    fun addContext(title: String, content: String) {
        val toolWindow = ToolWindowManager.getInstance(project).getToolWindow("OpenGeminiAI Studio")
        toolWindow?.activate {
            SwingUtilities.invokeLater {
                mainPanel?.addTextAttachment(title, content)
            }
        }
    }

    companion object {
        fun getInstance(project: Project): ChatInterfaceService = project.getService(ChatInterfaceService::class.java)
    }
}
