package com.opengeminiai.studio.client.ui

import com.opengeminiai.studio.client.model.*
import com.opengeminiai.studio.client.service.ApiClient
import com.opengeminiai.studio.client.service.PersistenceService
import com.opengeminiai.studio.client.Icons
import com.google.gson.Gson
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.project.Project
import com.intellij.ui.components.* import com.intellij.openapi.ui.ComboBox
import com.intellij.util.ui.JBUI
import com.intellij.util.ui.UIUtil
import com.intellij.icons.AllIcons
import com.intellij.ui.JBColor
import okhttp3.Call
import java.awt.*
import java.awt.datatransfer.DataFlavor
import java.awt.dnd.* import java.awt.event.* import java.io.File
import javax.swing.*
import java.util.regex.Pattern

class MainPanel(val project: Project) {

    private val gson = Gson()
    private val chatListModel = DefaultListModel<Conversation>()
    private var currentConversation: Conversation? = null
    private var appSettings: AppSettings = AppSettings()

    // -- ATTACHMENTS --
    private val attachedFiles = ArrayList<File>()
    private val attachmentsPanel = JPanel(FlowLayout(FlowLayout.LEFT, 4, 4))

    // -- LAYOUTS --
    private val cardLayout = CardLayout()
    private val centerPanel = JPanel(cardLayout)

    // -- CHAT VIEW --
    private val chatContentPanel = object : JPanel(), Scrollable {
        override fun getPreferredScrollableViewportSize(): Dimension = preferredSize
        override fun getScrollableUnitIncrement(visibleRect: Rectangle?, orientation: Int, direction: Int): Int = 16
        override fun getScrollableBlockIncrement(visibleRect: Rectangle?, orientation: Int, direction: Int): Int = 16
        override fun getScrollableTracksViewportWidth(): Boolean = true
        override fun getScrollableTracksViewportHeight(): Boolean = false
    }

    private val scrollPane = JBScrollPane(chatContentPanel)
    private val inputArea = JBTextArea()

    // -- HEADER INFO --
    private val headerInfoLabel = JLabel("", SwingConstants.CENTER)

    // -- CONTROLS --
    private val modelsModel = DefaultComboBoxModel<String>(arrayOf("gemini-2.5-flash"))
    private val modeModel = DefaultComboBoxModel<String>(arrayOf("Chat", "QuickEdit"))
    private val modelComboBox = ComboBox(modelsModel)
    private val modeComboBox = ComboBox(modeModel)
    private var sendBtn: JButton? = null
    private var currentApiCall: Call? = null

    // -- STATE FOR MODES --
    private var lastChatModel: String = "gemini-2.5-flash"
    private var lastQuickEditModel: String = "gemini-2.5-flash"

    // -- HISTORY VIEW (Replaces JBList) --
    private val historyContentPanel = JPanel().apply {
        layout = BoxLayout(this, BoxLayout.Y_AXIS)
        background = JBColor.background()
        border = JBUI.Borders.empty(10)
    }
    private val historyScrollPane = JBScrollPane(historyContentPanel).apply {
        border = null
        horizontalScrollBarPolicy = ScrollPaneConstants.HORIZONTAL_SCROLLBAR_NEVER
    }

    init {
        chatContentPanel.layout = BoxLayout(chatContentPanel, BoxLayout.Y_AXIS)
        chatContentPanel.border = JBUI.Borders.empty(10)
        chatContentPanel.background = JBColor.background()

        scrollPane.border = null
        scrollPane.horizontalScrollBarPolicy = ScrollPaneConstants.HORIZONTAL_SCROLLBAR_NEVER
        scrollPane.verticalScrollBar.unitIncrement = 16

        // Attachments setup
        attachmentsPanel.isOpaque = false
        attachmentsPanel.border = JBUI.Borders.empty(0, 4, 4, 4)

        // -- LOGIC: Persist Model Selection per Mode --
        modeComboBox.addItemListener { e ->
            if (e.stateChange == ItemEvent.SELECTED) {
                val newMode = e.item as String
                val modelToRestore = if (newMode == "Chat") lastChatModel else lastQuickEditModel

                val listeners = modelComboBox.itemListeners
                listeners.forEach { modelComboBox.removeItemListener(it) }
                modelComboBox.selectedItem = modelToRestore
                listeners.forEach { modelComboBox.addItemListener(it) }

                updateHeaderInfo()
            }
        }

        modelComboBox.addItemListener { e ->
            if (e.stateChange == ItemEvent.SELECTED) {
                val currentMode = modeComboBox.item
                val currentModel = e.item as String
                if (currentMode == "Chat") {
                    lastChatModel = currentModel
                } else {
                    lastQuickEditModel = currentModel
                }
                updateHeaderInfo()
            }
        }

        centerPanel.add(scrollPane, "CHAT")
        centerPanel.add(historyScrollPane, "HISTORY")

        val wrapper = PersistenceService.load(project)
        appSettings = wrapper.settings ?: AppSettings()
        wrapper.conversations.forEach { chatListModel.addElement(it) }

        // Apply default models from settings
        lastChatModel = appSettings.defaultChatModel
        lastQuickEditModel = appSettings.defaultQuickEditModel

        if (chatListModel.isEmpty) createNewChat()
        else loadChat(chatListModel.firstElement())

        refreshModels()
        refreshHistoryList() // Build the custom history UI
    }

    // --- HISTORY UI BUILDER ---

    private fun refreshHistoryList() {
        historyContentPanel.removeAll()

        val elements = chatListModel.elements().toList()
        elements.forEach { conversation ->
            historyContentPanel.add(createHistoryRow(conversation))
            historyContentPanel.add(Box.createVerticalStrut(5))
        }

        historyContentPanel.revalidate()
        historyContentPanel.repaint()
    }

    private fun createHistoryRow(conversation: Conversation): JPanel {
        val row = JPanel(BorderLayout())
        row.background = JBColor.background()
        row.border = JBUI.Borders.compound(
            JBUI.Borders.customLine(JBColor.border(), 0, 0, 1, 0), // Bottom separator
            JBUI.Borders.empty(8)
        )
        row.maximumSize = Dimension(Int.MAX_VALUE, 60)
        row.alignmentX = Component.LEFT_ALIGNMENT

        // Text Info (Left/Center)
        val infoPanel = JPanel(BorderLayout())
        infoPanel.isOpaque = false

        val titleLabel = JLabel("<html><b>${conversation.title}</b></html>")
        titleLabel.font = JBUI.Fonts.label()

        val dateLabel = JLabel(conversation.getFormattedDate())
        dateLabel.font = JBUI.Fonts.smallFont()
        dateLabel.foreground = JBColor.gray

        infoPanel.add(titleLabel, BorderLayout.CENTER)
        infoPanel.add(dateLabel, BorderLayout.SOUTH)

        // Interaction: Click to load
        val mouseAdapter = object : MouseAdapter() {
            override fun mouseClicked(e: MouseEvent) {
                if (SwingUtilities.isLeftMouseButton(e)) {
                    loadChat(conversation)
                }
            }
            override fun mouseEntered(e: MouseEvent) {
                row.background = UIUtil.getListSelectionBackground(true) // Highlight on hover
            }
            override fun mouseExited(e: MouseEvent) {
                row.background = JBColor.background()
            }
        }
        row.addMouseListener(mouseAdapter)
        // Pass events from children to parent row
        infoPanel.addMouseListener(mouseAdapter)
        titleLabel.addMouseListener(mouseAdapter)

        // Delete Button (Right)
        val deleteBtn = createIconButton(AllIcons.Actions.GC, "Delete Chat") {
             deleteSpecificChat(conversation)
        }
        val btnContainer = JPanel(FlowLayout(FlowLayout.RIGHT, 0, 0))
        btnContainer.isOpaque = false
        btnContainer.add(deleteBtn)

        row.add(infoPanel, BorderLayout.CENTER)
        row.add(btnContainer, BorderLayout.EAST)

        return row
    }

    fun getContent(): JComponent {
        val mainWrapper = JPanel(BorderLayout())

        // --- HEADER ---
        val header = JPanel(BorderLayout())
        header.border = JBUI.Borders.empty(4)

        val leftActions = JPanel(FlowLayout(FlowLayout.LEFT, 0, 0))
        val historyBtn = createIconButton(AllIcons.Vcs.History, "History") { showHistory() }
        val settingsBtn = createIconButton(AllIcons.General.Settings, "Settings") { openSettings() }
        leftActions.add(historyBtn)
        leftActions.add(settingsBtn)

        headerInfoLabel.font = JBUI.Fonts.label()
        headerInfoLabel.foreground = JBColor.foreground()

        val rightActions = JPanel(FlowLayout(FlowLayout.RIGHT, 0, 0))
        val newChatBtn = createIconButton(AllIcons.General.Add, "New Chat") { createNewChat() }
        rightActions.add(newChatBtn)

        header.add(leftActions, BorderLayout.WEST)
        header.add(headerInfoLabel, BorderLayout.CENTER)
        header.add(rightActions, BorderLayout.EAST)

        // --- BOTTOM PANEL ---
        val bottomPanel = JPanel(BorderLayout()).apply {
            isOpaque = false
            background = JBColor.background()
            border = JBUI.Borders.empty(8)
        }

        // Input Wrapper
        val inputWrapper = object : JPanel(BorderLayout()) {
            init { isOpaque = false }
            override fun paint(g: Graphics) {
                val g2 = g as Graphics2D
                g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
                val cornerRadius = 12

                g2.color = JBColor.background()
                g2.fillRoundRect(0, 0, width, height, cornerRadius, cornerRadius)

                g2.color = JBColor.border()
                g2.drawRoundRect(0, 0, width - 1, height - 1, cornerRadius, cornerRadius)

                super.paint(g)
            }
        }

        inputArea.lineWrap = true
        inputArea.wrapStyleWord = true
        inputArea.border = JBUI.Borders.empty(6)
        inputArea.isOpaque = false

        // --- KEY BINDINGS ---
        val shiftEnter = KeyStroke.getKeyStroke(KeyEvent.VK_ENTER, InputEvent.SHIFT_DOWN_MASK)
        val enter = KeyStroke.getKeyStroke(KeyEvent.VK_ENTER, 0)

        inputArea.getInputMap(JComponent.WHEN_FOCUSED).put(shiftEnter, "insert-break")
        inputArea.getInputMap(JComponent.WHEN_FOCUSED).put(enter, "sendMessage")
        inputArea.actionMap.put("sendMessage", object : AbstractAction() {
            override fun actionPerformed(e: ActionEvent?) {
                sendMessage()
            }
        })

        val inputScroll = JBScrollPane(inputArea)
        inputScroll.border = null
        inputScroll.isOpaque = false
        inputScroll.viewport.isOpaque = false
        inputScroll.preferredSize = Dimension(-1, 80)

        setupDragAndDrop(inputArea)
        setupDragAndDrop(inputScroll)

        inputWrapper.add(attachmentsPanel, BorderLayout.NORTH)
        inputWrapper.add(inputScroll, BorderLayout.CENTER)

        val controls = JPanel(BorderLayout()).apply {
            isOpaque = false
            background = JBColor.background()
            border = JBUI.Borders.emptyTop(4)
        }

        val leftControls = JPanel(FlowLayout(FlowLayout.LEFT, 4, 0)).apply {
            isOpaque = false
            background = JBColor.background()
        }

        modelComboBox.preferredSize = Dimension(160, 28)
        modelComboBox.font = JBUI.Fonts.label().deriveFont(12.0f)
        modelComboBox.border = JBUI.Borders.empty()
        modelComboBox.isOpaque = false
        modelComboBox.putClientProperty("ComboBox.isSquare", true)

        modelComboBox.renderer = object : DefaultListCellRenderer() {
            override fun getListCellRendererComponent(list: JList<*>?, value: Any?, index: Int, isSelected: Boolean, cellHasFocus: Boolean): Component {
                val l = super.getListCellRendererComponent(list, value, index, isSelected, cellHasFocus) as JLabel
                l.isOpaque = isSelected
                if (isSelected) {
                    l.background = UIUtil.getListSelectionBackground(true)
                    l.foreground = UIUtil.getListSelectionForeground(true)
                } else {
                    l.background = UIUtil.getPanelBackground()
                    l.foreground = UIUtil.getLabelForeground()
                }
                return l
            }
        }

        modeComboBox.preferredSize = Dimension(70, 28)
        modeComboBox.border = JBUI.Borders.empty()
        modeComboBox.isOpaque = false
        modeComboBox.putClientProperty("ComboBox.isSquare", true)

        modeComboBox.renderer = object : DefaultListCellRenderer() {
            override fun getListCellRendererComponent(list: JList<*>?, value: Any?, index: Int, isSelected: Boolean, cellHasFocus: Boolean): Component {
                val l = super.getListCellRendererComponent(list, value, index, isSelected, cellHasFocus) as JLabel
                l.text = ""
                l.horizontalAlignment = SwingConstants.CENTER
                l.isOpaque = isSelected

                if (isSelected) {
                    l.background = UIUtil.getListSelectionBackground(true)
                    l.foreground = UIUtil.getListSelectionForeground(true)
                } else {
                    l.background = UIUtil.getPanelBackground()
                    l.foreground = UIUtil.getLabelForeground()
                }
                when (value) {
                    "Chat" -> {
                        l.icon = AllIcons.Toolwindows.ToolWindowMessages
                        l.toolTipText = "Chat Mode"
                    }
                    "QuickEdit" -> {
                        l.icon = AllIcons.Actions.Edit
                        l.toolTipText = "Quick Edit (Code Generation)"
                    }
                }
                return l
            }
        }

        val refreshBtn = createIconButton(AllIcons.Actions.Refresh, "Refresh Models") { refreshModels() }

        leftControls.add(modeComboBox)
        leftControls.add(modelComboBox)
        leftControls.add(refreshBtn)

        val rightControls = JPanel(FlowLayout(FlowLayout.RIGHT, 4, 0)).apply {
            isOpaque = false
            background = JBColor.background()
        }

        sendBtn = createIconButton(AllIcons.Actions.Execute, "Send") { sendMessage() }

        rightControls.add(sendBtn!!)

        controls.add(leftControls, BorderLayout.WEST)
        controls.add(rightControls, BorderLayout.EAST)

        bottomPanel.add(inputWrapper, BorderLayout.CENTER)
        bottomPanel.add(controls, BorderLayout.SOUTH)

        mainWrapper.add(header, BorderLayout.NORTH)
        mainWrapper.add(centerPanel, BorderLayout.CENTER)
        mainWrapper.add(bottomPanel, BorderLayout.SOUTH)

        return mainWrapper
    }

    private fun updateHeaderInfo() {
        val title = currentConversation?.title ?: "New Chat"
        val model = modelComboBox.item as? String ?: "gemini-2.5-flash"
        // Title in header can be shorter
        val displayTitle = if (title.length > 25) title.substring(0, 22) + "..." else title

        headerInfoLabel.text = "<html><b>$displayTitle</b> <span style='color:gray'>($model)</span></html>"
        headerInfoLabel.toolTipText = "$title using $model"
        headerInfoLabel.icon = null
    }

    private fun setupDragAndDrop(component: Component) {
        val target = object : DropTargetAdapter() {
            override fun drop(dtde: DropTargetDropEvent) {
                try {
                    dtde.acceptDrop(DnDConstants.ACTION_COPY)
                    val transferable = dtde.transferable
                    if (transferable.isDataFlavorSupported(DataFlavor.javaFileListFlavor)) {
                        val files = transferable.getTransferData(DataFlavor.javaFileListFlavor) as List<File>
                        files.forEach { addAttachment(it) }
                        dtde.dropComplete(true)
                    } else {
                        dtde.rejectDrop()
                    }
                } catch (e: Exception) {
                    dtde.rejectDrop()
                }
            }
        }
        DropTarget(component, target)
    }

    private fun addAttachment(file: File) {
        if (attachedFiles.any { it.absolutePath == file.absolutePath }) return
        attachedFiles.add(file)
        val chip = ChatComponents.createAttachmentChip(file, { removeAttachment(file) }, true)
        attachmentsPanel.add(chip)
        refreshAttachmentsPanel()
    }

    private fun removeAttachment(file: File) {
        attachedFiles.removeIf { it.absolutePath == file.absolutePath }
        attachmentsPanel.removeAll()
        attachedFiles.forEach { f ->
            attachmentsPanel.add(ChatComponents.createAttachmentChip(f, { removeAttachment(f) }, true))
        }
        refreshAttachmentsPanel()
    }

    private fun refreshAttachmentsPanel() {
        attachmentsPanel.revalidate()
        attachmentsPanel.repaint()
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
        refreshHistoryList()
    }

    private fun openSelectedChat() {
        // Now handled by row click listener
    }

    private fun loadChat(chat: Conversation) {
        currentConversation = chat
        chatContentPanel.removeAll()

        chat.messages.forEachIndexed { index, msg ->
            val bubble = ChatComponents.createMessageBubble(msg.role, msg.content, index) { idxToDelete ->
                handleMessageDelete(idxToDelete)
            }
            chatContentPanel.add(bubble)
            chatContentPanel.add(Box.createVerticalStrut(10))

            msg.changes?.let { changes ->
                if (changes.isNotEmpty()) {
                    var widgetPanel: JPanel? = null
                    widgetPanel = ChatComponents.createChangeWidget(project, changes) {
                        // On Delete Widget
                        if (index < chat.messages.size) {
                             chat.messages[index] = chat.messages[index].copy(changes = null)
                             PersistenceService.save(project, chatListModel.elements().toList(), appSettings)

                             if (widgetPanel != null) {
                                 chatContentPanel.remove(widgetPanel)
                                 chatContentPanel.revalidate()
                                 chatContentPanel.repaint()
                             }
                        }
                    }
                    chatContentPanel.add(widgetPanel)
                    chatContentPanel.add(Box.createVerticalStrut(10))
                }
            }
        }
        chatContentPanel.revalidate()
        chatContentPanel.repaint()

        cardLayout.show(centerPanel, "CHAT")
        scrollToBottom()
        updateHeaderInfo()
    }

    private fun createNewChat() {
        val chat = Conversation()
        chatListModel.add(0, chat)
        PersistenceService.save(project, chatListModel.elements().toList(), appSettings)
        refreshHistoryList()
        loadChat(chat)
    }

    private fun deleteSpecificChat(chat: Conversation) {
        chatListModel.removeElement(chat)
        PersistenceService.save(project, chatListModel.elements().toList(), appSettings)

        refreshHistoryList()

        if (chatListModel.isEmpty) {
            createNewChat()
        } else if (chat == currentConversation) {
            loadChat(chatListModel.firstElement())
        }
    }

    private fun handleMessageDelete(index: Int) {
        val chat = currentConversation ?: return
        if (index >= 0 && index < chat.messages.size) {
            chat.messages.removeAt(index)
            PersistenceService.save(project, chatListModel.elements().toList(), appSettings)
            loadChat(chat)
        }
    }

    private fun addBubble(role: String, content: String): JPanel {
        val chat = currentConversation!!
        val newMessage = ChatMessage(role, content)
        chat.messages.add(newMessage)
        val newIndex = chat.messages.indexOf(newMessage)

        val bubble = ChatComponents.createMessageBubble(role, content, newIndex) { idxToDelete ->
            handleMessageDelete(idxToDelete)
        }
        chatContentPanel.add(bubble)
        chatContentPanel.add(Box.createVerticalStrut(10))
        return bubble
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
            sendBtn?.icon = AllIcons.Actions.Suspend
            sendBtn?.toolTipText = "Stop Sending"
            sendBtn?.actionListeners?.forEach { sendBtn?.removeActionListener(it) }
            sendBtn?.addActionListener { stopSending() }
            inputArea.isEnabled = false
            modelComboBox.isEnabled = false
            modeComboBox.isEnabled = false
        } else {
            sendBtn?.icon = AllIcons.Actions.Execute
            sendBtn?.toolTipText = "Send"
            sendBtn?.actionListeners?.forEach { sendBtn?.removeActionListener(it) }
            sendBtn?.addActionListener { sendMessage() }
            inputArea.isEnabled = true
            modelComboBox.isEnabled = true
            modeComboBox.isEnabled = true
        }
    }

    private fun sendMessage() {
        if (currentApiCall != null) {
            stopSending()
            return
        }

        val textInput = inputArea.text.trim()
        if ((textInput.isEmpty() && attachedFiles.isEmpty()) || currentConversation == null) return

        val chat = currentConversation!!
        val sb = StringBuilder(textInput)
        if (attachedFiles.isNotEmpty()) {
            if (sb.isNotEmpty()) sb.append("\n\n")
            attachedFiles.forEach { file ->
                val extension = file.extension.lowercase()
                when (extension) {
                    "jpg", "jpeg", "png" -> {
                        sb.append("image_path=")
                        sb.append(file.absolutePath)
                    }
                    else -> {
                        sb.append("code_path=")
                        sb.append(file.absolutePath)
                    }
                }
                sb.append("\n")
            }
        }
        val fullContent = sb.toString().trim()

        addBubble("user", fullContent)

        if (chat.messages.size == 1) {
            val titleText = if (textInput.isNotEmpty()) textInput else "Files Analysis"
            // CHANGED: Increased truncation limit to 60 characters
            chat.title = if (titleText.length > 60) titleText.substring(0, 57) + "..." else titleText

            refreshHistoryList()
            updateHeaderInfo()
        }

        inputArea.text = ""
        attachedFiles.clear()
        attachmentsPanel.removeAll()
        refreshAttachmentsPanel()
        scrollToBottom()
        PersistenceService.save(project, chatListModel.elements().toList(), appSettings)

        val model = modelComboBox.item as? String ?: "gemini-2.5-flash"
        val mode = modeComboBox.item as? String ?: "Chat"

        val prompt = if (mode == "QuickEdit") {
             ApiClient.getPromptText(appSettings.quickEditPromptKey, ApiClient.PromptType.QuickEdit)
        } else {
             ApiClient.getPromptText(appSettings.chatPromptKey, ApiClient.PromptType.Chat)
        }

        updateSendButtonState(true)

        // Create Assistant Bubble with placeholder text immediately
        val assistantBubblePanel = addBubble("assistant", "_Generating content..._")
        scrollToBottom()
        val targetBubble = assistantBubblePanel

        ApplicationManager.getApplication().executeOnPooledThread {
            var callToExecute: Call? = null
            try {
                // Prevent sending empty assistant messages to API
                val msgToSend = chat.messages.removeAt(chat.messages.size - 1)
                callToExecute = ApiClient.createChatCompletionCall(chat.messages, model, prompt, appSettings.baseUrl, true)
                currentApiCall = callToExecute
                chat.messages.add(msgToSend)

                var currentText = ""
                val fullResponse = ApiClient.streamChatCompletion(callToExecute) { chunk ->
                    currentText += chunk
                    SwingUtilities.invokeLater {
                        ChatComponents.updateMessageBubble(targetBubble, currentText)
                        scrollToBottom()
                    }
                }

                SwingUtilities.invokeLater {
                    handleFinalResponse(fullResponse, chat)
                }
            } catch (e: Exception) {
                // Filter out standard socket closure messages which happen on normal completion or user cancel
                val msg = e.message ?: ""
                val isSocketClosed = e is java.net.SocketException && (msg == "Socket closed" || msg == "Canceled")

                if (!isSocketClosed) {
                    SwingUtilities.invokeLater {
                        ChatComponents.updateMessageBubble(targetBubble, "An error occurred: $msg")
                    }
                }
            }
            finally {
                SwingUtilities.invokeLater {
                    if (currentApiCall == callToExecute) {
                        currentApiCall = null
                        updateSendButtonState(false)
                    }
                }
            }
        }
    }

    private fun handleFinalResponse(response: String, chat: Conversation) {
        var textPart = response
        var changes: List<FileChange>? = null

        // 1. Try to find JSON inside Markdown code blocks first (Most Reliable)
        val codeBlockMatcher = Pattern.compile("```json\\s*(\\{.*?\\})\\s*```", Pattern.DOTALL).matcher(response)
        if (codeBlockMatcher.find()) {
            val jsonContent = codeBlockMatcher.group(1)
            try {
                val request = gson.fromJson(jsonContent, ChangeRequest::class.java)
                if (request.action == "propose_changes") {
                    changes = request.changes
                    // Remove the entire code block from the text
                    textPart = response.replace(codeBlockMatcher.group(0), "").trim()
                }
            } catch (e: Exception) { /* Invalid JSON in block */ }
        }

        // 2. Fallback: Try to find raw JSON object if no code block match
        if (changes == null) {
            // Greedy match for a JSON-like structure containing "propose_changes"
            val rawJsonMatcher = Pattern.compile("\\{.*\\\"action\\\"\\s*:\\s*\\\"propose_changes\\\".*\\}", Pattern.DOTALL).matcher(response)
            if (rawJsonMatcher.find()) {
                val jsonContent = rawJsonMatcher.group()
                try {
                    val request = gson.fromJson(jsonContent, ChangeRequest::class.java)
                    changes = request.changes
                    textPart = response.replace(jsonContent, "").trim()
                } catch (e: Exception) { /* Invalid JSON */ }
            }
        }

        val lastMsg = chat.messages.lastOrNull()
        if (lastMsg != null && lastMsg.role == "assistant") {
             // Update model
             chat.messages[chat.messages.size - 1] = ChatMessage("assistant", textPart, changes)

             // Update UI Bubble (This renders clean text without the JSON block)
             val bubblePanel = chatContentPanel.getComponent(chatContentPanel.componentCount - 2) as JPanel
             ChatComponents.updateMessageBubble(bubblePanel, textPart)

             // Append widget if changes exist (Valid for ANY mode)
             if (changes != null && changes.isNotEmpty()) {
                var widgetPanel: JPanel? = null
                widgetPanel = ChatComponents.createChangeWidget(project, changes) {
                    val idx = chat.messages.size - 1
                    if (idx >= 0) {
                         chat.messages[idx] = chat.messages[idx].copy(changes = null)
                         PersistenceService.save(project, chatListModel.elements().toList(), appSettings)
                         if (widgetPanel != null) {
                             chatContentPanel.remove(widgetPanel)
                             chatContentPanel.revalidate()
                             chatContentPanel.repaint()
                         }
                    }
                }
                chatContentPanel.add(widgetPanel)
                chatContentPanel.add(Box.createVerticalStrut(10))
             }
        }

        PersistenceService.save(project, chatListModel.elements().toList(), appSettings)
        scrollToBottom()
    }

    private fun stopSending() {
        currentApiCall?.cancel()
    }

    private fun refreshModels() {
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                ApiClient.fetchSystemPrompts(appSettings.baseUrl)
                val modelIds = ApiClient.getModels(appSettings.baseUrl)

                SwingUtilities.invokeLater {
                    modelsModel.removeAllElements()
                    if (modelIds.isNotEmpty()) modelIds.forEach { modelsModel.addElement(it) }
                    else modelsModel.addElement("gemini-2.5-flash")

                    val currentMode = modeComboBox.item
                    val targetModel = if (currentMode == "Chat") lastChatModel else lastQuickEditModel
                    if (modelIds.contains(targetModel)) {
                         modelComboBox.selectedItem = targetModel
                    }
                    updateHeaderInfo()
                }
            } catch (e: Exception) { }
        }
    }

    private fun openSettings() {
        ApplicationManager.getApplication().executeOnPooledThread {
             ApiClient.fetchSystemPrompts(appSettings.baseUrl)
             SwingUtilities.invokeLater {
                 val models = (0 until modelsModel.size).map { modelsModel.getElementAt(it) }
                 val dialog = SettingsDialog(project, appSettings, models)
                 if (dialog.showAndGet()) {
                     PersistenceService.save(project, chatListModel.elements().toList(), appSettings)
                     refreshModels()
                 }
             }
        }
    }
}