package com.opengeminiai.studio.client.ui

import com.opengeminiai.studio.client.model.*
import com.opengeminiai.studio.client.service.ApiClient
import com.opengeminiai.studio.client.service.PersistenceService
import com.google.gson.Gson
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.ui.components.*
import com.intellij.ui.dsl.builder.*
import com.intellij.openapi.ui.ComboBox
import com.intellij.util.ui.JBUI
import com.intellij.ui.JBSplitter
import com.intellij.icons.AllIcons
import com.intellij.ui.JBColor
import okhttp3.Call // Import okhttp3.Call
import java.awt.*
import java.awt.event.*
import java.util.UUID
import javax.swing.*
import java.util.regex.Pattern

class MainPanel(val project: Project) {

    private val gson = Gson()
    private val chatListModel = DefaultListModel<Conversation>()
    private var currentConversation: Conversation? = null

    // -- LAYOUTS --
    private val cardLayout = CardLayout()
    private val centerPanel = JPanel(cardLayout)

    // -- CHAT VIEW --
    private val chatContentPanel = JPanel()
    private val scrollPane = JBScrollPane(chatContentPanel)
    private val inputArea = JBTextArea()
    private val statusLabel = JLabel("Ready")

    // -- CONTROLS --
    private val modelsModel = DefaultComboBoxModel<String>(arrayOf("gemini-2.0-flash-exp"))
    private val modeModel = DefaultComboBoxModel<String>(arrayOf("Chat", "QuickEdit"))
    private val modelComboBox = ComboBox(modelsModel)
    private val modeComboBox = ComboBox(modeModel)
    private var sendBtn: JButton? = null // Make sendBtn a class property
    private var currentApiCall: Call? = null // To hold the ongoing OkHttp call for cancellation

    // -- HISTORY --
    private val historyList = JBList(chatListModel)

    init {
        chatContentPanel.layout = BoxLayout(chatContentPanel, BoxLayout.Y_AXIS)
        chatContentPanel.border = JBUI.Borders.empty(5)
        chatContentPanel.background = JBColor.background()

        scrollPane.border = null
        scrollPane.verticalScrollBar.unitIncrement = 16

        // History List Renderer
        historyList.cellRenderer = object : DefaultListCellRenderer() {
            override fun getListCellRendererComponent(list: JList<*>?, value: Any?, index: Int, isSelected: Boolean, cellHasFocus: Boolean): Component {
                val c = super.getListCellRendererComponent(list, value, index, isSelected, cellHasFocus) as JLabel
                val conv = value as Conversation
                c.text = "<html><b>${conv.title}</b><br/><span style='color:gray; font-size: 10px'>${conv.getFormattedDate()}</span></html>"
                c.border = JBUI.Borders.empty(5, 8)
                return c
            }
        }

        // Mouse Listeners
        historyList.addMouseListener(object : MouseAdapter() {
            override fun mouseClicked(e: MouseEvent) {
                if (SwingUtilities.isLeftMouseButton(e) && e.clickCount == 2) {
                    openSelectedChat()
                }
                if (SwingUtilities.isRightMouseButton(e)) {
                    val index = historyList.locationToIndex(e.point)
                    historyList.selectedIndex = index
                    val popup = JPopupMenu()
                    val del = JMenuItem("Delete")
                    del.addActionListener { deleteSelectedChat() }
                    popup.add(del)
                    popup.show(e.component, e.x, e.y)
                }
            }
        })

        centerPanel.add(scrollPane, "CHAT")
        centerPanel.add(JBScrollPane(historyList), "HISTORY")

        val saved = PersistenceService.load(project)
        saved.forEach { chatListModel.addElement(it) }

        if (chatListModel.isEmpty) createNewChat()
        else loadChat(chatListModel.firstElement())

        refreshModels()
    }

    fun getContent(): JComponent {
        val mainWrapper = JPanel(BorderLayout())

        // --- HEADER ---
        val header = JPanel(BorderLayout())
        header.border = JBUI.Borders.empty(4)

        val leftActions = JPanel(FlowLayout(FlowLayout.LEFT, 0, 0))
        val historyBtn = createIconButton(AllIcons.Vcs.History, "History") { showHistory() }
        leftActions.add(historyBtn)

        val rightActions = JPanel(FlowLayout(FlowLayout.RIGHT, 0, 0))
        val newChatBtn = createIconButton(AllIcons.General.Add, "New Chat") { createNewChat() }
        rightActions.add(newChatBtn)

        header.add(leftActions, BorderLayout.WEST)
        header.add(rightActions, BorderLayout.EAST)

        // --- BOTTOM PANEL ---
        val bottomPanel = JPanel(BorderLayout())
        bottomPanel.border = JBUI.Borders.empty(8)

        inputArea.lineWrap = true
        val inputScroll = JBScrollPane(inputArea)
        inputScroll.preferredSize = Dimension(-1, 80)
        inputScroll.border = BorderFactory.createLineBorder(JBColor.border())

        val controls = JPanel(BorderLayout())
        controls.border = JBUI.Borders.emptyTop(4)

        val leftControls = JPanel(FlowLayout(FlowLayout.LEFT, 4, 0))
        modelComboBox.preferredSize = Dimension(140, 28)
        modeComboBox.preferredSize = Dimension(90, 28)

        val refreshBtn = createIconButton(AllIcons.Actions.Refresh, "Refresh Models") { refreshModels() }

        leftControls.add(modelComboBox)
        leftControls.add(modeComboBox)
        leftControls.add(refreshBtn)

        val rightControls = JPanel(FlowLayout(FlowLayout.RIGHT, 4, 0))

        // Initialize sendBtn here
        sendBtn = createIconButton(AllIcons.Actions.Execute, "Send") { sendMessage() }

        rightControls.add(statusLabel)
        rightControls.add(Box.createHorizontalStrut(5))
        rightControls.add(sendBtn!!) // Add the send button

        controls.add(leftControls, BorderLayout.WEST)
        controls.add(rightControls, BorderLayout.EAST)

        bottomPanel.add(inputScroll, BorderLayout.CENTER)
        bottomPanel.add(controls, BorderLayout.SOUTH)

        mainWrapper.add(header, BorderLayout.NORTH)
        mainWrapper.add(centerPanel, BorderLayout.CENTER)
        mainWrapper.add(bottomPanel, BorderLayout.SOUTH)

        return mainWrapper
    }

    private fun createIconButton(icon: Icon, tooltip: String, action: () -> Unit): JButton {
        val btn = JButton(icon)
        btn.toolTipText = tooltip
        btn.preferredSize = Dimension(28, 28)
        btn.isBorderPainted = false
        btn.isContentAreaFilled = false
        btn.isFocusPainted = false
        btn.isOpaque = false
        btn.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
        btn.addActionListener { action() }
        return btn
    }

    private fun showHistory() {
        cardLayout.show(centerPanel, "HISTORY")
        historyList.updateUI()
    }

    private fun openSelectedChat() {
        val selected = historyList.selectedValue
        if (selected != null) loadChat(selected)
    }

    private fun loadChat(chat: Conversation) {
        currentConversation = chat
        chatContentPanel.removeAll()
        chat.messages.forEach { addBubble(it.role, it.content) }
        chatContentPanel.revalidate()
        chatContentPanel.repaint()

        cardLayout.show(centerPanel, "CHAT")
        scrollToBottom()
    }

    private fun createNewChat() {
        val chat = Conversation()
        chatListModel.add(0, chat)
        historyList.selectedIndex = 0
        PersistenceService.save(project, chatListModel.elements().toList())
        loadChat(chat)
    }

    private fun deleteSelectedChat() {
        val selected = historyList.selectedValue ?: return
        chatListModel.removeElement(selected)
        PersistenceService.save(project, chatListModel.elements().toList())
        if (chatListModel.isEmpty) createNewChat()
    }

    private fun addBubble(role: String, content: String) {
        val bubble = ChatComponents.createMessageBubble(role, content)
        chatContentPanel.add(bubble)
    }

    private fun scrollToBottom() {
        SwingUtilities.invokeLater {
            val v = scrollPane.verticalScrollBar
            v.value = v.maximum
        }
    }

    private fun updateSendButtonState(isSending: Boolean) {
        if (sendBtn == null) return

        if (isSending) {
            sendBtn?.icon = AllIcons.Actions.Suspend // Use suspend icon for 'stop'
            sendBtn?.toolTipText = "Stop Sending"
            // Remove all existing listeners and add the stop action
            sendBtn?.actionListeners?.forEach { sendBtn?.removeActionListener(it) }
            sendBtn?.addActionListener { stopSending() }
            inputArea.isEnabled = false
            modelComboBox.isEnabled = false
            modeComboBox.isEnabled = false
            statusLabel.text = "Sending..."
        } else {
            sendBtn?.icon = AllIcons.Actions.Execute
            sendBtn?.toolTipText = "Send"
            // Remove all existing listeners and add the send action
            sendBtn?.actionListeners?.forEach { sendBtn?.removeActionListener(it) }
            sendBtn?.addActionListener { sendMessage() }
            inputArea.isEnabled = true
            modelComboBox.isEnabled = true
            modeComboBox.isEnabled = true
            // statusLabel.text will be set by handleAIResponse or error handling
        }
    }

    private fun sendMessage() {
        // If a call is already in progress, this click acts as a stop request
        if (currentApiCall != null) {
            stopSending()
            return
        }

        val text = inputArea.text.trim()
        if (text.isEmpty() || currentConversation == null) return

        val chat = currentConversation!!

        addBubble("user", text)
        chat.messages.add(ChatMessage("user", text))

        if (chat.messages.size == 1) {
            chat.title = if (text.length > 30) text.substring(0, 27) + "..." else text
            historyList.repaint()
        }

        inputArea.text = ""
        scrollToBottom()

        PersistenceService.save(project, chatListModel.elements().toList())

        val model = modelComboBox.item ?: "gemini-2.0-flash-exp"
        val mode = modeComboBox.item ?: "Chat"
        val prompt = if (mode == "QuickEdit") ApiClient.QUICK_EDIT_PROMPT else ApiClient.CHAT_PROMPT

        updateSendButtonState(true) // Set UI to sending state

        ApplicationManager.getApplication().executeOnPooledThread {
            var callToExecute: Call? = null // Declare a local reference to the call
            try {
                callToExecute = ApiClient.createChatCompletionCall(chat.messages, model, prompt)
                currentApiCall = callToExecute // Assign to class member for potential cancellation

                val response = ApiClient.processCallResponse(callToExecute)

                SwingUtilities.invokeLater {
                    handleAIResponse(response, chat)
                    statusLabel.text = "Ready"
                }
            } catch (e: Exception) {
                // Check if the exception is due to cancellation
                if (e is java.net.SocketException && (e.message == "Canceled" || e.message?.contains("canceled", ignoreCase = true) == true)) {
                    SwingUtilities.invokeLater {
                        statusLabel.text = "Cancelled"
                        addBubble("assistant", "Request cancelled by user.")
                    }
                } else {
                    SwingUtilities.invokeLater {
                        statusLabel.text = "Error: ${e.message ?: "Unknown"}"
                        addBubble("assistant", "An error occurred: ${e.message ?: "Unknown"}")
                    }
                }
            } finally {
                // Ensure UI state is reset on EDT, regardless of success or failure
                SwingUtilities.invokeLater {
                    // Only reset if this is the call that was actually running
                    if (currentApiCall == callToExecute) {
                        currentApiCall = null
                        updateSendButtonState(false)
                    }
                }
            }
        }
    }

    private fun handleAIResponse(response: String, chat: Conversation) {
        val matcher = Pattern.compile("[{].*[}]", Pattern.DOTALL).matcher(response)
        var textPart = response
        var changeRequest: ChangeRequest? = null

        if (matcher.find()) {
            val json = matcher.group()
            if (json.contains("propose_changes")) {
                try {
                    changeRequest = gson.fromJson(json, ChangeRequest::class.java)
                    textPart = response.replace(json, "").trim().replace("```json", "").replace("```", "").trim()
                } catch (e: Exception) { /* Silently ignore JSON parsing errors for now */ }
            }
        }

        if (textPart.isNotBlank()) {
            addBubble("assistant", textPart)
            chat.messages.add(ChatMessage("assistant", textPart))
        }

        val changes = changeRequest?.changes
        if (changes != null && changes.isNotEmpty()) {
            val widget = ChatComponents.createChangeWidget(project, changes)
            chatContentPanel.add(widget)
        }

        PersistenceService.save(project, chatListModel.elements().toList())
        scrollToBottom()
    }

    private fun stopSending() {
        currentApiCall?.cancel() // This will cause an exception in the executing pooled thread
        // The finally block in sendMessage's pooled thread will handle resetting UI state.
    }

    private fun addContext() {
        val editor = FileEditorManager.getInstance(project).selectedTextEditor
        val file = FileEditorManager.getInstance(project).selectedFiles.firstOrNull()
        if (editor != null && file != null) {
            val ctx = "\n[CONTEXT: ${file.name}]\n```\n${editor.document.text}\n```\n"
            inputArea.append(ctx)
            statusLabel.text = "Added ${file.name}"
        } else { statusLabel.text = "No file" }
    }

    private fun refreshModels() {
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                val models = ApiClient.getModels()
                SwingUtilities.invokeLater {
                    modelsModel.removeAllElements()
                    if (models.isNotEmpty()) models.forEach { modelsModel.addElement(it) }
                    else modelsModel.addElement("gemini-2.0-flash-exp")
                    statusLabel.text = "Models refreshed"
                }
            } catch (e: Exception) {
                SwingUtilities.invokeLater { statusLabel.text = "Failed to refresh models" }
            }
        }
    }
}