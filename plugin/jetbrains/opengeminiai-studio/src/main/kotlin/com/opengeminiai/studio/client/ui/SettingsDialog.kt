package com.opengeminiai.studio.client.ui

import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.DialogPanel
import com.intellij.openapi.ui.DialogWrapper
import com.intellij.ui.dsl.builder.Align
import com.intellij.ui.dsl.builder.bindItem
import com.intellij.ui.dsl.builder.bindText
import com.intellij.ui.dsl.builder.panel
import com.opengeminiai.studio.client.model.AppSettings
import com.opengeminiai.studio.client.service.ApiClient
import javax.swing.JComponent

class SettingsDialog(
    project: Project,
    private val settings: AppSettings,
    private val availableModels: List<String>
) : DialogWrapper(project) {

    private lateinit var mainPanel: DialogPanel

    private val availablePrompts = ApiClient.getAvailablePromptKeys()

    // Model Bindings
    private var chatModel: String? = settings.defaultChatModel
        set(value) { field = value; if (value != null) settings.defaultChatModel = value }

    private var quickEditModel: String? = settings.defaultQuickEditModel
        set(value) { field = value; if (value != null) settings.defaultQuickEditModel = value }

    private var commitModel: String? = settings.defaultCommitModel
        set(value) { field = value; if (value != null) settings.defaultCommitModel = value }

    private var titleModel: String? = settings.defaultTitleModel
        set(value) { field = value; if (value != null) settings.defaultTitleModel = value }

    // Prompt Bindings
    private var chatPrompt: String? = settings.chatPromptKey
        set(value) { field = value; if (value != null) settings.chatPromptKey = value }

    private var quickEditPrompt: String? = settings.quickEditPromptKey
        set(value) { field = value; if (value != null) settings.quickEditPromptKey = value }

    private var commitPrompt: String? = settings.commitPromptKey
        set(value) { field = value; if (value != null) settings.commitPromptKey = value }

    private var titlePrompt: String? = settings.titlePromptKey
        set(value) { field = value; if (value != null) settings.titlePromptKey = value }

    init {
        title = "OpenGeminiAI Settings"
        init()
    }

    override fun createCenterPanel(): JComponent {
        mainPanel = panel {
            group("Connection") {
                row("API Base URL:") {
                    textField()
                        .bindText(settings::baseUrl)
                        .align(Align.FILL)
                }
            }
            group("Models") {
                row("Chat Model:") {
                    comboBox(availableModels).bindItem(::chatModel)
                }
                row("Quick Edit Model:") {
                    comboBox(availableModels).bindItem(::quickEditModel)
                }
                row("Git Commit Model:") {
                    comboBox(availableModels).bindItem(::commitModel)
                }
                row("Chat Title Model:") {
                    comboBox(availableModels).bindItem(::titleModel)
                }
            }
            group("System Prompts") {
                row("Chat Prompt:") {
                    comboBox(availablePrompts).bindItem(::chatPrompt)
                }
                row("Quick Edit Prompt:") {
                    comboBox(availablePrompts).bindItem(::quickEditPrompt)
                }
                row("Git Commit Prompt:") {
                    comboBox(availablePrompts).bindItem(::commitPrompt)
                }
                row("Chat Title Prompt:") {
                    comboBox(availablePrompts).bindItem(::titlePrompt)
                }
            }
            group("Context Filters") {
                row("Ignored Directories (comma-separated):") {
                    textField()
                        .bindText(settings::ignoredDirectories)
                        .align(Align.FILL)
                        .comment("Folders like node_modules, __pycache__, etc.")
                }
                row("Ignored Extensions (comma-separated):") {
                    textField()
                        .bindText(settings::ignoredExtensions)
                        .align(Align.FILL)
                        .comment("Binary files, logs, etc.")
                }
            }
        }
        return mainPanel
    }

    override fun doOKAction() {
        mainPanel.apply()
        super.doOKAction()
    }
}