package com.opengeminiai.studio.client.ui

import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.DialogPanel
import com.intellij.openapi.ui.DialogWrapper
import com.intellij.ui.dsl.builder.Align
import com.intellij.ui.dsl.builder.bindItem
import com.intellij.ui.dsl.builder.bindText
import com.intellij.ui.dsl.builder.panel
import com.opengeminiai.studio.client.model.AppSettings
import javax.swing.JComponent

class SettingsDialog(
    project: Project,
    private val settings: AppSettings,
    private val availableModels: List<String>
) : DialogWrapper(project) {

    private lateinit var mainPanel: DialogPanel

    // Wrapper properties to handle nullable binding requirements for ComboBoxes
    // The bindItem functions in the DSL builder expect KMutableProperty0<T?> or MutableProperty<T?>.
    // By making these properties nullable, we match the expected signature.
    private var chatModel: String? = settings.defaultChatModel
        set(value) {
            field = value
            // Only update the non-nullable setting if a non-null value is selected
            if (value != null) {
                settings.defaultChatModel = value
            }
        }

    private var quickEditModel: String? = settings.defaultQuickEditModel
        set(value) {
            field = value
            if (value != null) {
                settings.defaultQuickEditModel = value
            }
        }

    private var commitModel: String? = settings.defaultCommitModel
        set(value) {
            field = value
            if (value != null) {
                settings.defaultCommitModel = value
            }
        }

    init {
        title = "OpenGeminiAI Settings"
        init()
    }

    override fun createCenterPanel(): JComponent {
        mainPanel = panel {
            group("Default Models") {
                row("Chat Model:") {
                    comboBox(availableModels)
                        .bindItem(::chatModel)
                }
                row("Quick Edit Model:") {
                    comboBox(availableModels)
                        .bindItem(::quickEditModel)
                }
                row("Git Commit Model:") {
                    comboBox(availableModels)
                        .bindItem(::commitModel)
                }
            }
            group("System Prompt") {
                row {
                    val textAreaCell = textArea()
                    textAreaCell
                        .bindText(settings::systemPrompt)
                        .align(Align.FILL)
                    textAreaCell.component.setRows(6)
                }.resizableRow()
            }
        }
        return mainPanel
    }

    override fun doOKAction() {
        mainPanel.apply()
        super.doOKAction()
    }
}