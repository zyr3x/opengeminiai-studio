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
import okhttp3.Call
import java.awt.*
import java.awt.datatransfer.DataFlavor
import java.awt.dnd.* 
import java.awt.event.*
import java.io.File
import java.util.UUID
import javax.swing.*
import java.util.regex.Pattern

class MainPanel(val project: Project) {

    private val gson = Gson()
    private val chatListModel = DefaultListModel<Conversation>()
    private var currentConversation: Conversation? = null

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
    // private val statusLabel = JLabel("Ready") // Removed per Task 2

    // -- HEADER INFO --
    private val headerInfoLabel = JLabel("", SwingConstants.CENTER)

    // -- CONTROLS --
    private val modelsModel = DefaultComboBoxModel<String>(arrayOf("gemini-2.0-flash-exp"))
    private val modeModel = DefaultComboBoxModel<String>(arrayOf("Chat", "QuickEdit"))
    private val modelComboBox = ComboBox(modelsModel)
    private val modeComboBox = ComboBox(modeModel)
    private var sendBtn: JButton? = null
    private var currentApiCall: Call? = null

    // -- STATE FOR MODES --
    private var lastChatModel: String = "gemini-2.0-flash-exp"
    private var lastQuickEditModel: String = "gemini-2.0-flash-exp"

    // -- HISTORY --
    private val historyList = JBList(chatListModel)

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

        // -- LOGIC: Persist Model Selection per Mode --
        modeComboBox.addItemListener { e ->
            if (e.stateChange == ItemEvent.SELECTED) {
                val newMode = e.item as String
                val modelToRestore = if (newMode == "Chat") lastChatModel else lastQuickEditModel

                val listeners = modelComboBox.itemListeners
                listeners.forEach { modelComboBox.removeItemListener(it) }
                modelComboBox.selectedItem = modelToRestore
                listeners.forEach { modelComboBox.addItemListener(it) }
                
                updateHeaderInfo() // Update header on mode change
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
                updateHeaderInfo() // Update header on model change
            }
        }

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

        // TASK 3: Header Info Label
        headerInfoLabel.font = JBUI.Fonts.smallFont()
        headerInfoLabel.foreground = JBColor.GRAY
        
        val rightActions = JPanel(FlowLayout(FlowLayout.RIGHT, 0, 0))
        val newChatBtn = createIconButton(AllIcons.General.Add, "New Chat") { createNewChat() }
        rightActions.add(newChatBtn)

        header.add(leftActions, BorderLayout.WEST)
        header.add(headerInfoLabel, BorderLayout.CENTER) // Centered info
        header.add(rightActions, BorderLayout.EAST)

        // --- BOTTOM PANEL ---
        val bottomPanel = JPanel(BorderLayout()).apply {
            isOpaque = false
            background = JBColor.background()
            border = JBUI.Borders.empty(8)
        }

        // Input Wrapper
        val inputWrapper = object : JPanel(BorderLayout()) {
            init {
                isOpaque = false // Important: JPanel itself is transparent so rounded shape is visible
            }
            override fun paint(g: Graphics) { // Override paint to draw background and border before children
                val g2 = g as Graphics2D
                g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
                val cornerRadius = 12 // A bit more rounded

                // Draw background for the whole wrapper area
                g2.color = JBColor.background() // Use system background color
                g2.fillRoundRect(0, 0, width, height, cornerRadius, cornerRadius)

                // Draw border for the whole wrapper area
                g2.color = JBColor.border()
                g2.drawRoundRect(0, 0, width - 1, height - 1, cornerRadius, cornerRadius)

                super.paint(g) // Now paint children (attachmentsPanel, inputScroll)
            }
        }

        inputArea.lineWrap = true
        inputArea.wrapStyleWord = true
        inputArea.border = JBUI.Borders.empty(6)
        inputArea.isOpaque = false // Make the JTextArea itself transparent

        // --- KEY BINDINGS: Enter to Send, Shift+Enter for Newline ---
        val shiftEnter = KeyStroke.getKeyStroke(KeyEvent.VK_ENTER, InputEvent.SHIFT_DOWN_MASK)
        val enter = KeyStroke.getKeyStroke(KeyEvent.VK_ENTER, 0)

        // 1. Shift+Enter -> Insert Break (Standard behavior)
        inputArea.getInputMap(JComponent.WHEN_FOCUSED).put(shiftEnter, "insert-break")

        // 2. Enter -> Send Message
        inputArea.getInputMap(JComponent.WHEN_FOCUSED).put(enter, "sendMessage")
        inputArea.actionMap.put("sendMessage", object : AbstractAction() {
            override fun actionPerformed(e: ActionEvent?) {
                sendMessage()
            }
        })

        val inputScroll = JBScrollPane(inputArea)
        inputScroll.border = null
        inputScroll.isOpaque = false // Make the JScrollPane transparent
        inputScroll.viewport.isOpaque = false // Make the JViewport transparent
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
        modelComboBox.border = null // Remove border
        modelComboBox.isOpaque = false // Try to remove background artifacts
        modelComboBox.background = JBColor.background() // Use panel background to blend in
        modelComboBox.putClientProperty("ComboBox.isSquare", true) // Flat look
        modelComboBox.renderer = object : DefaultListCellRenderer() {
            override fun getListCellRendererComponent(list: JList<*>?, value: Any?, index: Int, isSelected: Boolean, cellHasFocus: Boolean): Component {
                val l = super.getListCellRendererComponent(list, value, index, isSelected, cellHasFocus) as JLabel
                if (!isSelected) l.background = JBColor.background()
                l.foreground = if (isSelected) list?.selectionForeground ?: JBColor.foreground() else list?.foreground ?: JBColor.foreground()
                return l
            }
        }

        // --- TASK 1: REMOVE TEXT FROM CHAT / QUICK EDIT & Make icons more visible ---
        modeComboBox.preferredSize = Dimension(70, 28) // Increased size for better icon visibility
        modeComboBox.border = null // Remove border
        modeComboBox.isOpaque = false // Try to remove background artifacts
        modeComboBox.background = JBColor.background() // Use panel background to blend in
        modeComboBox.putClientProperty("ComboBox.isSquare", true) // Flat look
        modeComboBox.renderer = object : DefaultListCellRenderer() {
            override fun getListCellRendererComponent(list: JList<*>?, value: Any?, index: Int, isSelected: Boolean, cellHasFocus: Boolean): Component {
                val l = super.getListCellRendererComponent(list, value, index, isSelected, cellHasFocus) as JLabel
                l.text = "" // No text, just icon
                l.horizontalAlignment = SwingConstants.CENTER
                if (!isSelected) l.background = JBColor.background()
                l.foreground = if (isSelected) list?.selectionForeground ?: JBColor.foreground() else list?.foreground ?: JBColor.foreground()
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

        // Task 2: Remove status text ("Ready")
        // rightControls.add(statusLabel)
        rightControls.add(Box.createHorizontalStrut(5))
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
        val model = modelComboBox.item as? String ?: "gemini-2.0-flash-exp"
        val displayTitle = if (title.length > 25) title.substring(0, 22) + "..." else title
        // Task 3: Show full model name and title at the top
        headerInfoLabel.text = "<html><b>$displayTitle</b> <span style='color:gray'>($model)</span></html>"
        headerInfoLabel.toolTipText = "$title using $model"
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
        historyList.updateUI()
    }

    private fun openSelectedChat() {
        val selected = historyList.selectedValue
        if (selected != null) loadChat(selected)
    }

    private fun loadChat(chat: Conversation) {
        currentConversation = chat
        chatContentPanel.removeAll()
        chat.messages.forEach { msg ->
            addBubble(msg.role, msg.content)

            msg.changes?.let { changes ->
                if (changes.isNotEmpty()) {
                    val widget = ChatComponents.createChangeWidget(project, changes)
                    chatContentPanel.add(widget)
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
        chatContentPanel.add(Box.createVerticalStrut(10))
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
            // statusLabel.text = "Sending..." // Removed
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
        chat.messages.add(ChatMessage("user", fullContent))

        if (chat.messages.size == 1) {
            val titleText = if (textInput.isNotEmpty()) textInput else "Files Analysis"
            chat.title = if (titleText.length > 30) titleText.substring(0, 27) + "..." else titleText
            historyList.repaint()
            updateHeaderInfo()
        }

        inputArea.text = ""
        attachedFiles.clear()
        attachmentsPanel.removeAll()
        refreshAttachmentsPanel()

        scrollToBottom()

        PersistenceService.save(project, chatListModel.elements().toList())

        val model = modelComboBox.item as? String ?: "gemini-2.0-flash-exp"
        val mode = modeComboBox.item as? String ?: "Chat"
        val prompt = if (mode == "QuickEdit") ApiClient.QUICK_EDIT_PROMPT else ApiClient.CHAT_PROMPT

        updateSendButtonState(true)

        ApplicationManager.getApplication().executeOnPooledThread {
            var callToExecute: Call? = null
            try {
                callToExecute = ApiClient.createChatCompletionCall(chat.messages, model, prompt)
                currentApiCall = callToExecute

                val response = ApiClient.processCallResponse(callToExecute)

                SwingUtilities.invokeLater {
                    handleAIResponse(response, chat)
                    // statusLabel.text = "Ready"
                }
            } catch (e: Exception) {
                if (e is java.net.SocketException && (e.message == "Canceled" || e.message?.contains("canceled", ignoreCase = true) == true)) {
                    SwingUtilities.invokeLater {
                        // statusLabel.text = "Cancelled"
                        addBubble("assistant", "Request cancelled by user.")
                    }
                } else {
                    SwingUtilities.invokeLater {
                        // statusLabel.text = "Error: ${e.message ?: "Unknown"}"
                        addBubble("assistant", "An error occurred: ${e.message ?: "Unknown"}")
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
                } catch (e: Exception) { /* Ignore malformed JSON */ }
            }
        }

        val changes = changeRequest?.changes

        if (textPart.isNotBlank()) {
            addBubble("assistant", textPart)
            chat.messages.add(ChatMessage("assistant", textPart, changes))
        } else if (changes != null && changes.isNotEmpty()) {
            // If only changes, still add a message to history to track it
            chat.messages.add(ChatMessage("assistant", "", changes))
        }

        if (changes != null && changes.isNotEmpty()) {
            val widget = ChatComponents.createChangeWidget(project, changes)
            chatContentPanel.add(widget)
            chatContentPanel.add(Box.createVerticalStrut(10))
        }

        PersistenceService.save(project, chatListModel.elements().toList())
        scrollToBottom()
    }

    private fun stopSending() {
        currentApiCall?.cancel()
    }

    private fun refreshModels() {
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                val modelIds = ApiClient.getModels()
                SwingUtilities.invokeLater {
                    modelsModel.removeAllElements()
                    if (modelIds.isNotEmpty()) modelIds.forEach { modelsModel.addElement(it) }
                    else modelsModel.addElement("gemini-2.0-flash-exp")

                    val currentMode = modeComboBox.item
                    val targetModel = if (currentMode == "Chat") lastChatModel else lastQuickEditModel
                    if (modelIds.contains(targetModel)) {
                         modelComboBox.selectedItem = targetModel
                    }
                    
                    updateHeaderInfo()
                    // statusLabel.text = "Models refreshed"
                }
            } catch (e: Exception) {
                SwingUtilities.invokeLater { 
                    // statusLabel.text = "Failed to refresh models" 
                }
            }
        }
    }
}
