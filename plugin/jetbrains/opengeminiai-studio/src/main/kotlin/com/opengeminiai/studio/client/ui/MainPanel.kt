package com.opengeminiai.studio.client.ui

import com.opengeminiai.studio.client.model.*
import com.opengeminiai.studio.client.service.ApiClient
import com.opengeminiai.studio.client.service.ChatInterfaceService
import com.opengeminiai.studio.client.service.PersistenceService
import com.opengeminiai.studio.client.Icons
import com.google.gson.Gson
import com.intellij.execution.configurations.GeneralCommandLine
import com.intellij.execution.util.ExecUtil
import com.intellij.openapi.actionSystem.*
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.fileChooser.FileChooser
import com.intellij.openapi.fileChooser.FileChooserDescriptorFactory
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.roots.ProjectRootManager
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.ui.components.*
import com.intellij.util.ui.JBUI
import com.intellij.util.ui.UIUtil
import com.intellij.icons.AllIcons
import com.intellij.ide.DataManager
import com.intellij.openapi.ui.popup.JBPopup
import com.intellij.openapi.ui.popup.JBPopupFactory
import com.intellij.ui.JBColor
import com.intellij.ui.ColoredListCellRenderer
import com.intellij.ui.SimpleTextAttributes
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.ui.DialogWrapper
import javax.swing.event.DocumentEvent
import javax.swing.event.DocumentListener
import okhttp3.Call
import java.awt.*
import java.awt.datatransfer.DataFlavor
import java.awt.datatransfer.StringSelection
import java.awt.dnd.*
import java.awt.event.* import java.io.File
import javax.swing.* import java.util.regex.Pattern

class MainPanel(val project: Project) {

    private val gson = Gson()
    private val chatListModel = DefaultListModel<Conversation>()
    private var currentConversation: Conversation? = null
    private var appSettings: AppSettings = AppSettings()

    // -- ATTACHMENTS --
    private sealed class ContextItem {
        abstract val name: String
        abstract val icon: Icon
    }

    // Updated FileContext with separate parameter fields
    private data class FileContext(
        val file: File,
        var ignoreTypes: String = "",
        var ignoreFiles: String = "",
        var ignoreDirs: String = ""
    ) : ContextItem() {
        override val name: String = file.name
        override val icon: Icon = if (file.isDirectory) AllIcons.Nodes.Folder else AllIcons.FileTypes.Any_type

        fun hasParams(): Boolean = ignoreTypes.isNotBlank() || ignoreFiles.isNotBlank() || ignoreDirs.isNotBlank()

        fun getParamsSummary(): String {
            return ""
        }
    }

    private data class TextContext(override var name: String, var content: String, override val icon: Icon) : ContextItem()

    private val attachments = ArrayList<ContextItem>()

    private val attachmentsPanel = JPanel(FlowLayout(FlowLayout.LEFT, 0, 0)).apply {
        isOpaque = false
        border = JBUI.Borders.empty(4, 8, 0, 8)
        isVisible = false
    }

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
    private val tokenCountLabel = JLabel("~0 tokens") // Token Counter

    // -- HEADER INFO --
    private val headerInfoLabel = JLabel("", SwingConstants.CENTER)

    // -- CONTROLS --
    private var availableModels = mutableListOf("gemini-2.5-flash")
    private var currentMode = "Chat"
    private var currentModel = "gemini-2.5-flash"

    private val modeButton = JButton().apply {
        preferredSize = Dimension(28, 28)
        isBorderPainted = false
        isContentAreaFilled = false
        isFocusPainted = false
        isOpaque = false
        cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
        toolTipText = "Select Mode"
        addActionListener { showModePopup(it.source as Component) }
    }

    private val modelButton = JButton().apply {
        isBorderPainted = false
        isContentAreaFilled = false
        isFocusPainted = false
        isOpaque = false
        cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
        toolTipText = "Select Model"
        horizontalAlignment = SwingConstants.LEFT
        addActionListener { showModelPopup(it.source as Component) }
    }

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
        // Register this panel with the service
        ChatInterfaceService.getInstance(project).registerPanel(this)

        chatContentPanel.layout = BoxLayout(chatContentPanel, BoxLayout.Y_AXIS)
        chatContentPanel.border = JBUI.Borders.empty(10)
        chatContentPanel.background = JBColor.background()

        scrollPane.border = null
        scrollPane.horizontalScrollBarPolicy = ScrollPaneConstants.HORIZONTAL_SCROLLBAR_NEVER
        scrollPane.verticalScrollBar.unitIncrement = 16

        // Initialize Token Counter Logic
        tokenCountLabel.font = JBUI.Fonts.smallFont()
        tokenCountLabel.foreground = JBColor.GRAY
        tokenCountLabel.border = JBUI.Borders.emptyRight(8)

        inputArea.document.addDocumentListener(object : DocumentListener {
            override fun insertUpdate(e: DocumentEvent?) { updateTokenCount() }
            override fun removeUpdate(e: DocumentEvent?) { updateTokenCount() }
            override fun changedUpdate(e: DocumentEvent?) { updateTokenCount() }
        })

        centerPanel.add(scrollPane, "CHAT")
        centerPanel.add(historyScrollPane, "HISTORY")

        val wrapper = PersistenceService.load(project)
        appSettings = wrapper.settings ?: AppSettings()
        wrapper.conversations.forEach { chatListModel.addElement(it) }

        lastChatModel = appSettings.defaultChatModel
        lastQuickEditModel = appSettings.defaultQuickEditModel

        // Initialize Mode
        setMode("Chat")

        if (chatListModel.isEmpty) createNewChat()
        else loadChat(chatListModel.firstElement())

        refreshModels()
        refreshHistoryList()
    }

    // Called by external actions
    fun setPendingInput(text: String, files: List<File> = emptyList()) {
        inputArea.text = text
        files.forEach { addAttachment(FileContext(it)) }
        updateTokenCount()
        inputArea.requestFocusInWindow()
    }

    private fun updateTokenCount() {
        val textLen = inputArea.text.length
        // Rough estimation: 1 token ~ 4 chars for English
        var attachmentLen = 0L
        attachments.forEach {
            if (it is FileContext && it.file.exists()) attachmentLen += it.file.length()
            else if (it is TextContext) attachmentLen += it.content.length
        }

        val totalChars = textLen + attachmentLen
        val estimatedTokens = totalChars / 4

        tokenCountLabel.text = "~$estimatedTokens tokens"

        if (estimatedTokens > 100000) {
            tokenCountLabel.foreground = JBColor.RED
            tokenCountLabel.toolTipText = "Context is very large, might exceed model limits"
        } else {
            tokenCountLabel.foreground = JBColor.GRAY
            tokenCountLabel.toolTipText = "Estimated token count"
        }
    }

    // --- HISTORY UI BUILDER ---
    private fun refreshHistoryList() {
        historyContentPanel.removeAll()
        chatListModel.elements().toList().forEach {
            historyContentPanel.add(createHistoryRow(it))
            historyContentPanel.add(Box.createVerticalStrut(5))
        }
        historyContentPanel.revalidate(); historyContentPanel.repaint()
    }

    private fun createHistoryRow(conversation: Conversation): JPanel {
        val row = JPanel(BorderLayout())
        row.background = JBColor.background()
        row.border = JBUI.Borders.compound(JBUI.Borders.customLine(JBColor.border(), 0, 0, 1, 0), JBUI.Borders.empty(8))
        row.maximumSize = Dimension(Int.MAX_VALUE, 60)
        row.alignmentX = Component.LEFT_ALIGNMENT

        val infoPanel = JPanel(BorderLayout()).apply { isOpaque = false }
        val displayTitle = if (conversation.title.length > 40) conversation.title.take(37) + "..." else conversation.title
        val titleLabel = JLabel("<html><b>$displayTitle</b></html>").apply {
            font = JBUI.Fonts.label()
            toolTipText = conversation.title
        }
        val dateLabel = JLabel(conversation.getFormattedDate()).apply { font = JBUI.Fonts.smallFont(); foreground = JBColor.gray }

        infoPanel.add(titleLabel, BorderLayout.CENTER)
        infoPanel.add(dateLabel, BorderLayout.SOUTH)

        val mouseAdapter = object : MouseAdapter() {
            override fun mouseClicked(e: MouseEvent) { if (SwingUtilities.isLeftMouseButton(e)) loadChat(conversation) }
            override fun mouseEntered(e: MouseEvent) { row.background = UIUtil.getListSelectionBackground(true) }
            override fun mouseExited(e: MouseEvent) { row.background = JBColor.background() }
        }
        row.addMouseListener(mouseAdapter); infoPanel.addMouseListener(mouseAdapter); titleLabel.addMouseListener(mouseAdapter)

        val renameBtn = createIconButton(AllIcons.Actions.Edit, "Rename Chat") { renameSpecificChat(conversation) }
        val deleteBtn = createIconButton(AllIcons.Actions.GC, "Delete Chat") { deleteSpecificChat(conversation) }
        val btnContainer = JPanel(FlowLayout(FlowLayout.RIGHT, 0, 0)).apply {
            isOpaque = false
            add(renameBtn)
            add(deleteBtn)
        }

        row.add(infoPanel, BorderLayout.CENTER); row.add(btnContainer, BorderLayout.EAST)
        return row
    }

    fun getContent(): JComponent {
        val mainWrapper = JPanel(BorderLayout())

        // Header
        val header = JPanel(BorderLayout()).apply { border = JBUI.Borders.empty(4) }
        val leftActions = JPanel(FlowLayout(FlowLayout.LEFT, 0, 0))
        leftActions.add(createIconButton(AllIcons.Vcs.History, "History") { showHistory() })
        leftActions.add(createIconButton(AllIcons.General.Settings, "Settings") { openSettings() })

        headerInfoLabel.font = JBUI.Fonts.label(); headerInfoLabel.foreground = JBColor.foreground()

        val rightActions = JPanel(FlowLayout(FlowLayout.RIGHT, 0, 0))
        rightActions.add(createIconButton(AllIcons.General.Add, "New Chat") { createNewChat() })

        header.add(leftActions, BorderLayout.WEST)
        header.add(headerInfoLabel, BorderLayout.CENTER)
        header.add(rightActions, BorderLayout.EAST)

        // Bottom Panel
        val bottomPanel = JPanel(BorderLayout()).apply { isOpaque = false; background = JBColor.background(); border = JBUI.Borders.empty(8) }

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

        inputArea.lineWrap = true; inputArea.wrapStyleWord = true; inputArea.border = JBUI.Borders.empty(6); inputArea.isOpaque = false
        val shiftEnter = KeyStroke.getKeyStroke(KeyEvent.VK_ENTER, InputEvent.SHIFT_DOWN_MASK)
        val enter = KeyStroke.getKeyStroke(KeyEvent.VK_ENTER, 0)
        inputArea.getInputMap(JComponent.WHEN_FOCUSED).put(shiftEnter, "insert-break")
        inputArea.getInputMap(JComponent.WHEN_FOCUSED).put(enter, "sendMessage")
        inputArea.actionMap.put("sendMessage", object : AbstractAction() { override fun actionPerformed(e: ActionEvent?) { sendMessage() } })

        val inputScroll = JBScrollPane(inputArea).apply { border = null; isOpaque = false; viewport.isOpaque = false; preferredSize = Dimension(-1, 80) }
        setupDragAndDrop(inputArea); setupDragAndDrop(inputScroll)

        inputWrapper.add(attachmentsPanel, BorderLayout.NORTH)
        inputWrapper.add(inputScroll, BorderLayout.CENTER)

        val controls = JPanel(BorderLayout()).apply { isOpaque = false; background = JBColor.background(); border = JBUI.Borders.emptyTop(4) }
        val leftControls = JPanel(FlowLayout(FlowLayout.LEFT, 4, 0)).apply { isOpaque = false; background = JBColor.background() }

        val addContextBtn = createIconButton(AllIcons.General.Add, "Add Context") { e -> showAddContextPopup(e.source as Component) }

        leftControls.add(addContextBtn)
        leftControls.add(modeButton)
        leftControls.add(modelButton)

        val rightControls = JPanel(FlowLayout(FlowLayout.RIGHT, 4, 0)).apply { isOpaque = false; background = JBColor.background() }
        rightControls.add(tokenCountLabel) // Add Token Counter here

        val copyBtn = createIconButton(AllIcons.Actions.Copy, "Copy Prompt") { copyPromptToClipboard() }
        rightControls.add(copyBtn)

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

    // --- CONTEXT & LOGIC ---

    private fun showModePopup(component: Component) {
        val actions = DefaultActionGroup()
        actions.add(object : AnAction("Chat", "Standard chat mode", AllIcons.Actions.ListFiles) {
            override fun actionPerformed(e: AnActionEvent) { setMode("Chat") }
        })
        actions.add(object : AnAction("Quick Edit", "Code editing mode", AllIcons.Actions.Edit) {
            override fun actionPerformed(e: AnActionEvent) { setMode("QuickEdit") }
        })
        JBPopupFactory.getInstance().createActionGroupPopup("Select Mode", actions, DataManager.getInstance().getDataContext(component), JBPopupFactory.ActionSelectionAid.SPEEDSEARCH, true).showUnderneathOf(component)
    }

    private fun setMode(mode: String) {
        currentMode = mode
        modeButton.icon = if (mode == "Chat") AllIcons.Actions.ListFiles else AllIcons.Actions.Edit

        val targetModel = if (mode == "Chat") lastChatModel else lastQuickEditModel
        setModel(targetModel)
    }

    private fun showModelPopup(component: Component) {
        val actions = DefaultActionGroup()
        availableModels.forEach { modelName ->
            actions.add(object : AnAction(modelName, "Select $modelName model", AllIcons.Actions.Properties) {
                override fun actionPerformed(e: AnActionEvent) {
                    setModel(modelName)
                }
            })
        }
        JBPopupFactory.getInstance().createActionGroupPopup("Select Model", actions, DataManager.getInstance().getDataContext(component), JBPopupFactory.ActionSelectionAid.SPEEDSEARCH, true).showUnderneathOf(component)
    }

    private fun setModel(model: String) {
        currentModel = model
        modelButton.icon = AllIcons.Actions.Properties
        if (currentMode == "Chat") lastChatModel = model else lastQuickEditModel = model
        updateHeaderInfo()
    }

    private fun showAddContextPopup(component: Component) {
        val actions = DefaultActionGroup()
        actions.add(object : AnAction("Files and Folders", "Attach files", AllIcons.Nodes.Folder) {
            override fun actionPerformed(e: AnActionEvent) {
                val descriptor = FileChooserDescriptorFactory.createMultipleFilesNoJarsDescriptor()
                FileChooser.chooseFiles(descriptor, project, null) { files -> files.forEach { addAttachment(FileContext(File(it.path))) } }
            }
        })
        actions.add(object : AnAction("Add All Open Files", "Attach currently open files", AllIcons.Actions.ListFiles) {
            override fun actionPerformed(e: AnActionEvent) {
                val openFiles = FileEditorManager.getInstance(project).openFiles
                openFiles.forEach { vf -> addAttachment(FileContext(File(vf.path))) }
            }
        })
        actions.add(object : AnAction("Add Image...", "Attach image", AllIcons.FileTypes.Image) {
            override fun actionPerformed(e: AnActionEvent) {
                val descriptor = FileChooserDescriptorFactory.createSingleFileDescriptor().withFileFilter { it.extension?.lowercase() in listOf("jpg", "jpeg", "png") }
                FileChooser.chooseFiles(descriptor, project, null) { files -> files.firstOrNull()?.let { addAttachment(FileContext(File(it.path))) } }
            }
        })
        actions.addSeparator()
        actions.add(object : AnAction("Project Structure", "Paste project tree", AllIcons.Actions.ListFiles) {
            override fun actionPerformed(e: AnActionEvent) {
                val sb = StringBuilder("Project Root: ${project.basePath}\nProject Structure:\n")
                ProjectRootManager.getInstance(project).contentRoots.forEach { buildFileTree(it, "", sb, 0) }
                addAttachment(TextContext("Project Structure", sb.toString(), AllIcons.Actions.ListFiles))
            }
        })
        actions.add(object : AnAction("Commits", "Reference git commits", AllIcons.Vcs.CommitNode) {
            override fun actionPerformed(e: AnActionEvent) {
                val commits = getRecentCommits(project)
                if (commits.isEmpty()) {
                    Messages.showInfoMessage(project, "No recent commits found or git not configured.", "Commits")
                    return
                }
                val list = JBList(commits)
                list.selectionMode = ListSelectionModel.MULTIPLE_INTERVAL_SELECTION
                list.cellRenderer = object : ColoredListCellRenderer<CommitItem>() {
                    override fun customizeCellRenderer(list: JList<out CommitItem>, value: CommitItem, index: Int, selected: Boolean, hasFocus: Boolean) {
                        append(value.hash, SimpleTextAttributes.GRAYED_ATTRIBUTES)
                        append("  ")
                        append(value.message, SimpleTextAttributes.REGULAR_ATTRIBUTES)
                        append("  ")
                        append(value.time, SimpleTextAttributes.GRAYED_SMALL_ATTRIBUTES)
                    }
                }
                JBPopupFactory.getInstance().createListPopupBuilder(list)
                    .setTitle("Select Commits")
                    .setItemChoosenCallback {
                        ApplicationManager.getApplication().executeOnPooledThread {
                            list.selectedValuesList.forEach { commit ->
                                val sb = StringBuilder("Commit: ${commit.hash} - ${commit.message}\n")
                                try {
                                    val cmd = GeneralCommandLine("git", "show", commit.hash).apply { workDirectory = File(project.basePath ?: "") }
                                    val out = ExecUtil.execAndGetOutput(cmd)
                                    if (out.exitCode == 0) sb.append(out.stdout)
                                } catch (ex: Exception) {}
                                SwingUtilities.invokeLater { addAttachment(TextContext("Commit ${commit.hash.take(7)}", sb.toString(), AllIcons.Vcs.CommitNode)) }
                            }
                        }
                    }.createPopup().showUnderneathOf(component)
            }
        })

        JBPopupFactory.getInstance().createActionGroupPopup("Add Context", actions, DataManager.getInstance().getDataContext(component), JBPopupFactory.ActionSelectionAid.SPEEDSEARCH, true).showUnderneathOf(component)
    }

    private data class CommitItem(val hash: String, val message: String, val time: String)

    private fun getRecentCommits(project: Project): List<CommitItem> {
        val list = mutableListOf<CommitItem>()
        val basePath = project.basePath ?: return list
        try {
            val cmd = GeneralCommandLine("git", "log", "-n", "30", "--pretty=format:%h|%s|%ar").apply { workDirectory = File(basePath) }
            val output = ExecUtil.execAndGetOutput(cmd)
            if (output.exitCode == 0) output.stdout.lines().forEach { line ->
                val parts = line.split("|", limit = 3)
                if (parts.size == 3) list.add(CommitItem(parts[0], parts[1], parts[2]))
            }
        } catch (e: Exception) {}
        return list
    }

    private fun addAttachment(item: ContextItem) {
        if (item is FileContext && attachments.filterIsInstance<FileContext>().any { it.file.absolutePath == item.file.absolutePath }) return
        attachments.add(item)
        refreshAttachmentsPanel()
        updateTokenCount()
    }

    private fun removeAttachment(item: ContextItem) {
        attachments.remove(item)
        refreshAttachmentsPanel()
        updateTokenCount()
    }

    private fun refreshAttachmentsPanel() {
        attachmentsPanel.removeAll()
        if (attachments.isEmpty()) {
            attachmentsPanel.isVisible = false
        } else {
            attachmentsPanel.isVisible = true
            val count = attachments.size
            val summaryBtn = JButton("$count item${if (count > 1) "s" else ""} attached", AllIcons.FileTypes.Any_type).apply {
                isBorderPainted = false; isContentAreaFilled = false; cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
                addActionListener { showAttachmentsPopup(this) }
            }
            attachmentsPanel.add(summaryBtn)
        }
        attachmentsPanel.revalidate(); attachmentsPanel.repaint()
    }

    private fun showAttachmentsPopup(anchor: Component) {
        val panel = JPanel().apply { layout = BoxLayout(this, BoxLayout.Y_AXIS); border = JBUI.Borders.empty(8); background = JBColor.background() }
        var popup: JBPopup? = null

        fun reload() {
            panel.removeAll()
            if (attachments.isEmpty()) { popup?.cancel(); return }
            attachments.forEach { item ->
                // Use GridBagLayout for better vertical alignment
                val row = JPanel(GridBagLayout()).apply {
                    isOpaque = false
                    alignmentX = Component.LEFT_ALIGNMENT
                    maximumSize = Dimension(500, 32)
                    border = JBUI.Borders.empty(2, 0)
                }

                val gbc = GridBagConstraints()
                gbc.gridy = 0
                gbc.fill = GridBagConstraints.NONE
                gbc.anchor = GridBagConstraints.WEST

                // 1. Name Label
                gbc.gridx = 0
                gbc.weightx = 0.0
                gbc.insets = JBUI.insetsRight(8)
                val nameLabel = JLabel(if (item.name.length > 35) item.name.take(32) + "..." else item.name, item.icon, SwingConstants.LEFT)
                if (item is TextContext) {
                    nameLabel.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
                    nameLabel.toolTipText = "Edit"
                    nameLabel.addMouseListener(object : MouseAdapter() { override fun mouseClicked(e: MouseEvent) { showEditContextDialog(item) { } } })
                }
                row.add(nameLabel, gbc)

                // 2. Info Icon (if needed)
                if (item is FileContext && item.hasParams()) {
                    gbc.gridx = 1
                    gbc.insets = JBUI.insetsRight(8)
                    val paramsLabel = JBLabel(item.getParamsSummary(), AllIcons.General.Information, SwingConstants.LEFT).apply {
                        font = JBUI.Fonts.smallFont()
                        foreground = JBColor.GRAY
                        toolTipText = "Has filters"
                    }
                    row.add(paramsLabel, gbc)
                }

                // 3. Spacer
                gbc.gridx = 2
                gbc.weightx = 1.0
                gbc.fill = GridBagConstraints.HORIZONTAL
                gbc.insets = JBUI.emptyInsets()
                row.add(Box.createHorizontalGlue(), gbc)

                // 4. Buttons
                gbc.weightx = 0.0
                gbc.fill = GridBagConstraints.NONE
                gbc.anchor = GridBagConstraints.EAST
                gbc.insets = JBUI.insetsLeft(2)

                var col = 3
                // Only show edit parameters for directories
                if (item is FileContext && item.file.isDirectory) {
                    gbc.gridx = col++
                    val editParamsBtn = JButton(AllIcons.General.Inline_edit).apply {
                        preferredSize = Dimension(22, 22)
                        isBorderPainted = false
                        isContentAreaFilled = false
                        isFocusPainted = false
                        isOpaque = false
                        cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
                        toolTipText = "Edit Parameters"
                        addActionListener { showEditFileParamsDialog(item) { reload(); panel.revalidate(); panel.repaint(); popup?.pack(true, true) } }
                    }
                    row.add(editParamsBtn, gbc)
                }

                gbc.gridx = col
                val delBtn = JButton(AllIcons.Actions.Close).apply {
                    preferredSize = Dimension(22, 22)
                    isBorderPainted = false
                    isContentAreaFilled = false
                    isFocusPainted = false
                    isOpaque = false
                    cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
                    addActionListener { removeAttachment(item); reload(); panel.revalidate(); panel.repaint(); popup?.pack(true, true) }
                }
                row.add(delBtn, gbc)

                panel.add(row)
            }
        }
        reload()
        popup = JBPopupFactory.getInstance().createComponentPopupBuilder(panel, null).setTitle("Attached Context").setResizable(false).setMovable(true).setRequestFocus(true).createPopup()
        popup?.showUnderneathOf(anchor)
    }

    private fun showEditContextDialog(item: TextContext, onClose: () -> Unit) {
        val dialog = object : DialogWrapper(project) {
            val textArea = JTextArea(item.content)
            init { title = "Edit ${item.name}"; init() }
            override fun createCenterPanel() = JBScrollPane(textArea).apply { preferredSize = Dimension(500, 400) }
            override fun doOKAction() { item.content = textArea.text; super.doOKAction(); onClose() }
        }
        dialog.show()
    }

    private fun showEditFileParamsDialog(item: FileContext, onParamsChanged: () -> Unit) {
        val dialog = object : DialogWrapper(project) {
            val typeField = JTextField(item.ignoreTypes)
            val fileField = JTextField(item.ignoreFiles)
            val dirField = JTextField(item.ignoreDirs)

            init {
                title = "Edit Parameters for ${item.file.name}"
                init()
            }

            override fun createCenterPanel(): JComponent {
                val panel = JPanel(GridBagLayout())
                val gbc = GridBagConstraints()
                gbc.insets = JBUI.insets(4)
                gbc.fill = GridBagConstraints.HORIZONTAL

                // Row 1: Ignore Types
                gbc.gridx = 0; gbc.gridy = 0; gbc.weightx = 0.0
                panel.add(JLabel("Ignore Types:"), gbc)
                gbc.gridx = 1; gbc.weightx = 1.0
                panel.add(typeField, gbc)

                // Row 2: Ignore Files
                gbc.gridx = 0; gbc.gridy = 1; gbc.weightx = 0.0
                panel.add(JLabel("Ignore Files:"), gbc)
                gbc.gridx = 1; gbc.weightx = 1.0
                panel.add(fileField, gbc)

                // Row 3: Ignore Dirs
                gbc.gridx = 0; gbc.gridy = 2; gbc.weightx = 0.0
                panel.add(JLabel("Ignore Dirs:"), gbc)
                gbc.gridx = 1; gbc.weightx = 1.0
                panel.add(dirField, gbc)

                // Hint
                gbc.gridx = 1; gbc.gridy = 3; gbc.weightx = 1.0
                val hint = JLabel("<html><small style='color:gray'>Separate multiple values with | (pipe). Example: xml|json</small></html>")
                panel.add(hint, gbc)

                return panel
            }

            override fun doOKAction() {
                item.ignoreTypes = typeField.text.trim()
                item.ignoreFiles = fileField.text.trim()
                item.ignoreDirs = dirField.text.trim()
                super.doOKAction()
                onParamsChanged()
            }
        }
        dialog.show()
    }

    // --- MESSAGE SENDING WITH SLASH COMMANDS ---

    private fun processSlashCommands(initialText: String): Pair<String, String?> {
        var text = initialText
        var promptOverride: String? = null
        if (text.startsWith("/")) {
            val parts = text.split(Regex("\\s+"), limit = 2)
            val command = parts[0].lowercase()
            val arg = if (parts.size > 1) parts[1] else ""

            when (command) {
                "/doc" -> {
                    promptOverride = "Generate comprehensive documentation (JavaDoc/KDoc/Docstring) for the provided code. Do not change the logic, just add comments."
                    if (arg.isBlank()) text = "Please document the attached context."
                }
                "/test" -> {
                    promptOverride = "Generate unit tests for the provided code. Use the most popular testing framework for this language."
                    if (arg.isBlank()) text = "Please generate tests for the attached context."
                }
                "/refactor" -> {
                    promptOverride = "Refactor the provided code to be more clean, efficient, and maintainable. Explain your changes."
                    if (arg.isBlank()) text = "Please refactor the attached context."
                }
                "/fix" -> {
                    promptOverride = "Analyze the provided code or error message and propose a fix."
                    if (arg.isBlank()) text = "Please fix the bugs in the attached context."
                }
                "/explain" -> {
                    promptOverride = "Explain how the provided code works in simple terms."
                    if (arg.isBlank()) text = "Please explain the attached context."
                }
            }
        }
        return Pair(text, promptOverride)
    }

    private fun buildFullContent(textInput: String): String {
        val sb = StringBuilder(textInput)
        if (attachments.isNotEmpty()) {
            if (sb.isNotEmpty()) sb.append("\n\n")
            attachments.filterIsInstance<FileContext>().forEach { item ->
                val ext = item.file.extension.lowercase()
                val prefix = if (ext in listOf("jpg", "png")) "image_path=" else "code_path="

                sb.append("$prefix${item.file.absolutePath}")

                // Append parameters if they exist
                if (item.ignoreTypes.isNotBlank()) sb.append(" ignore_type=${item.ignoreTypes}")
                if (item.ignoreFiles.isNotBlank()) sb.append(" ignore_file=${item.ignoreFiles}")
                if (item.ignoreDirs.isNotBlank()) sb.append(" ignore_dir=${item.ignoreDirs}")

                sb.append("\n")
            }
            attachments.filterIsInstance<TextContext>().forEach { item ->
                val type = if (item.name.contains("Commit")) "commit" else if (item.name.contains("Structure")) "structure" else "text"
                sb.append("\n\n:::CTX:${item.name}:$type:::\n${item.content}\n:::END:::")
            }
        }
        return sb.toString().trim()
    }

    private fun copyPromptToClipboard() {
        val rawInput = inputArea.text.trim()
        if (rawInput.isEmpty() && attachments.isEmpty()) return

        val (processedText, _) = processSlashCommands(rawInput)
        val fullContent = buildFullContent(processedText)

        val selection = StringSelection(fullContent)
        Toolkit.getDefaultToolkit().systemClipboard.setContents(selection, null)
    }

    private fun generateChatTitle(chat: Conversation, userContent: String) {
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                val systemPrompt = "Summarize the following user request into a short, concise title (max 4-6 words). Do not use quotes. Output ONLY the title."
                // Truncate content to avoid excessive token usage
                val contentPreview = if (userContent.length > 1000) userContent.take(1000) + "..." else userContent

                val msgs = listOf(ChatMessage("user", contentPreview))
                val call = ApiClient.createChatCompletionCall(msgs, appSettings.defaultChatModel, systemPrompt, appSettings.baseUrl, false)
                val response = ApiClient.processCallResponse(call)

                val newTitle = response.trim().removeSurrounding("\"").removeSuffix(".")

                if (newTitle.isNotBlank() && !newTitle.startsWith("Error") && !newTitle.contains("Error")) {
                    SwingUtilities.invokeLater {
                        // Only update if it still has the default name and exists in the list
                        if (chatListModel.contains(chat) && chat.title == "New Chat") {
                            chat.title = newTitle
                            if (currentConversation == chat) updateHeaderInfo()
                            refreshHistoryList()

                            val conversationsToSave = chatListModel.elements().toList()
                            ApplicationManager.getApplication().executeOnPooledThread {
                                PersistenceService.save(project, conversationsToSave, appSettings)
                            }
                        }
                    }
                }
            } catch (e: Exception) { }
        }
    }

    // Made public so it can be called from ChatInterfaceService
    fun sendMessage() {
        if (currentApiCall != null) { stopSending(); return }

        val rawInput = inputArea.text.trim()
        if ((rawInput.isEmpty() && attachments.isEmpty()) || currentConversation == null) return

        val (processedText, promptOverride) = processSlashCommands(rawInput)
        val fullContent = buildFullContent(processedText)

        val chat = currentConversation!!

        // Auto-title generation check
        val shouldGenerateTitle = chat.messages.isEmpty() && chat.title == "New Chat"

        addBubble("user", fullContent)

        // Reset inputs
        inputArea.text = ""; attachments.clear(); refreshAttachmentsPanel(); updateTokenCount()

        // Save state in background
        val conversationsToSave = chatListModel.elements().toList()
        ApplicationManager.getApplication().executeOnPooledThread {
             PersistenceService.save(project, conversationsToSave, appSettings)
        }

        // Trigger title generation if applicable
        if (shouldGenerateTitle) {
            generateChatTitle(chat, fullContent)
        }

        // API Call Preparation
        val model = currentModel
        val mode = currentMode

        val systemPrompt = promptOverride ?: if (mode == "QuickEdit") {
             ApiClient.getPromptText(appSettings.quickEditPromptKey, ApiClient.PromptType.QuickEdit)
        } else {
             ApiClient.getPromptText(appSettings.chatPromptKey, ApiClient.PromptType.Chat)
        }

        updateSendButtonState(true)
        val assistantBubblePanel = addBubble("assistant", "_Generating content..._")
        scrollToBottom()
        val targetBubble = assistantBubblePanel

        ApplicationManager.getApplication().executeOnPooledThread {
            var callToExecute: Call? = null
            try {
                // Remove the "Generaring..." placeholder message from history before sending
                val msgToSend = chat.messages.removeAt(chat.messages.size - 1)

                callToExecute = ApiClient.createChatCompletionCall(chat.messages, model, systemPrompt, appSettings.baseUrl, true)
                currentApiCall = callToExecute

                // Add it back
                chat.messages.add(msgToSend)

                var currentText = ""
                val fullResponse = ApiClient.streamChatCompletion(callToExecute) { chunk ->
                    currentText += chunk
                    SwingUtilities.invokeLater {
                        // FIX: Smart Stick-to-Bottom Scrolling
                        // 1. Check if user is ALREADY at the bottom (with some tolerance)
                        val verticalBar = scrollPane.verticalScrollBar
                        val wasAtBottom = (verticalBar.value + verticalBar.visibleAmount) >= (verticalBar.maximum - 60)

                        // 2. Update content
                        ChatComponents.updateMessageBubble(targetBubble, currentText)

                        // 3. Only scroll if we were already following the stream
                        // This prevents jumping if the user scrolls up to read history
                        if (wasAtBottom) {
                            // Validate ensures the scrollbar maximum is updated immediately before we scroll
                            chatContentPanel.validate()
                            verticalBar.value = verticalBar.maximum
                        }
                    }
                }
                SwingUtilities.invokeLater { handleFinalResponse(fullResponse, chat) }
            } catch (e: Exception) {
                if (e.message != "Socket closed" && e.message != "Canceled") {
                    SwingUtilities.invokeLater { ChatComponents.updateMessageBubble(targetBubble, "Error: ${e.message}") }
                }
            } finally {
                SwingUtilities.invokeLater { if (currentApiCall == callToExecute) { currentApiCall = null; updateSendButtonState(false) } }
            }
        }
    }

    private fun isIgnored(file: VirtualFile): Boolean {
        val ignoredDirs = appSettings.ignoredDirectories.split(",").map { it.trim() }.toSet()
        val ignoredExts = appSettings.ignoredExtensions.split(",").map { it.trim() }.toSet()
        if (file.isDirectory && ignoredDirs.contains(file.name)) return true
        if (!file.isDirectory && (ignoredDirs.contains(file.name) || ignoredExts.contains(file.extension))) return true
        return false
    }

    private fun buildFileTree(file: VirtualFile, indent: String, sb: StringBuilder, depth: Int) {
        if (depth > 8) return
        sb.append("$indent- ${file.name}\n")
        if (file.isDirectory) {
            file.children.filter { !it.name.startsWith(".") && !isIgnored(it) }.sortedBy { if (it.isDirectory) 0 else 1 }.take(50)
                .forEach { buildFileTree(it, "$indent  ", sb, depth + 1) }
        }
    }

    private fun createIconButton(icon: Icon, tooltip: String, action: (ActionEvent) -> Unit): JButton {
        val btn = JButton(icon).apply {
            toolTipText = tooltip; preferredSize = Dimension(28, 28); isBorderPainted = false; isContentAreaFilled = false
            isFocusPainted = false; isOpaque = false; cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            addActionListener { action(it) }
        }
        return btn
    }

    private fun handleFinalResponse(response: String, chat: Conversation) {
        var textPart = response.trim()
        var changes: List<FileChange>? = null

        val startMarkerPattern = Pattern.compile("```json\\s*")
        val matcher = startMarkerPattern.matcher(response)

        if (matcher.find()) {
            val contentStart = matcher.end()
            val endMarker = "```"
            val endIndex = response.indexOf(endMarker, contentStart)

            if (endIndex != -1) {
                val jsonContent = response.substring(contentStart, endIndex).trim()
                try {
                    val request = gson.fromJson(jsonContent, ChangeRequest::class.java)
                    if (request.action == "propose_changes" && !request.changes.isNullOrEmpty()) {
                        changes = request.changes
                        textPart = (response.substring(0, matcher.start()) + response.substring(endIndex + endMarker.length)).trim()
                    }
                } catch (e: Exception) { }
            }
        }

        if (changes == null) {
            val jsonStart = response.indexOf("{")
            val jsonEnd = response.lastIndexOf("}")
            if (jsonStart != -1 && jsonEnd > jsonStart) {
                 val potentialJson = response.substring(jsonStart, jsonEnd + 1)
                 if (potentialJson.contains("\"propose_changes\"")) {
                     try {
                         val request = gson.fromJson(potentialJson, ChangeRequest::class.java)
                         if (request.action == "propose_changes" && !request.changes.isNullOrEmpty()) {
                             changes = request.changes
                             textPart = response.replace(potentialJson, "").trim()
                         }
                     } catch (e: Exception) { }
                 }
            }
        }

        val lastMsg = chat.messages.lastOrNull()
        if (lastMsg != null && lastMsg.role == "assistant") {
             chat.messages[chat.messages.size - 1] = ChatMessage("assistant", textPart, changes)
             val bubblePanel = chatContentPanel.getComponent(chatContentPanel.componentCount - 2) as JPanel
             ChatComponents.updateMessageBubble(bubblePanel, textPart)

             if (changes != null && changes.isNotEmpty()) {
                var widgetPanel: JPanel? = null
                widgetPanel = ChatComponents.createChangeWidget(project, changes) {
                    val idx = chat.messages.size - 1
                    if (idx >= 0) {
                         chat.messages[idx] = chat.messages[idx].copy(changes = null)

                         val conversationsToSave = chatListModel.elements().toList()
                         ApplicationManager.getApplication().executeOnPooledThread {
                              PersistenceService.save(project, conversationsToSave, appSettings)
                         }

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

        val conversationsToSave = chatListModel.elements().toList()
        ApplicationManager.getApplication().executeOnPooledThread {
             PersistenceService.save(project, conversationsToSave, appSettings)
        }
        scrollToBottom()
    }

    private fun stopSending() { currentApiCall?.cancel() }

    private fun refreshModels() {
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                ApiClient.fetchSystemPrompts(appSettings.baseUrl)
                val modelIds = ApiClient.getModels(appSettings.baseUrl)
                SwingUtilities.invokeLater {
                    availableModels.clear()
                    if (modelIds.isNotEmpty()) availableModels.addAll(modelIds)
                    else availableModels.add("gemini-2.5-flash")

                    val targetModel = if (currentMode == "Chat") lastChatModel else lastQuickEditModel
                    setModel(targetModel)
                }
            } catch (e: Exception) { }
        }
    }

    private fun openSettings() {
        ApplicationManager.getApplication().executeOnPooledThread {
             ApiClient.fetchSystemPrompts(appSettings.baseUrl)
             SwingUtilities.invokeLater {
                 val dialog = SettingsDialog(project, appSettings, availableModels)
                 if (dialog.showAndGet()) {
                     val conversationsToSave = chatListModel.elements().toList()
                     ApplicationManager.getApplication().executeOnPooledThread {
                          PersistenceService.save(project, conversationsToSave, appSettings)
                     }
                     refreshModels()
                 }
             }
        }
    }

    private fun updateSendButtonState(isSending: Boolean) {
        if (sendBtn == null) return
        if (isSending) {
            sendBtn?.icon = AllIcons.Actions.Suspend
            sendBtn?.toolTipText = "Stop Sending"
            sendBtn?.actionListeners?.forEach { sendBtn?.removeActionListener(it) }
            sendBtn?.addActionListener { stopSending() }
            inputArea.isEnabled = false; modeButton.isEnabled = false; modelButton.isEnabled = false
        } else {
            sendBtn?.icon = AllIcons.Actions.Execute
            sendBtn?.toolTipText = "Send"
            sendBtn?.actionListeners?.forEach { sendBtn?.removeActionListener(it) }
            sendBtn?.addActionListener { sendMessage() }
            inputArea.isEnabled = true; modeButton.isEnabled = true; modelButton.isEnabled = true
        }
    }

    private fun setupDragAndDrop(component: Component) {
        val target = object : DropTargetAdapter() {
            override fun drop(dtde: DropTargetDropEvent) {
                try {
                    if (dtde.isDataFlavorSupported(DataFlavor.javaFileListFlavor)) {
                        dtde.acceptDrop(DnDConstants.ACTION_COPY)
                        val transferable = dtde.transferable
                        val files = transferable.getTransferData(DataFlavor.javaFileListFlavor) as List<File>
                        files.forEach { addAttachment(FileContext(it)) }
                        dtde.dropComplete(true)
                    } else {
                        dtde.rejectDrop()
                    }
                } catch (e: Exception) {
                    try { dtde.dropComplete(false) } catch(ignore: Exception) {}
                }
            }
        }
        DropTarget(component, target)
    }

    private fun showHistory() {
        cardLayout.show(centerPanel, "HISTORY")
        refreshHistoryList()
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
                        if (index < chat.messages.size) {
                             chat.messages[index] = chat.messages[index].copy(changes = null)

                             val conversationsToSave = chatListModel.elements().toList()
                             ApplicationManager.getApplication().executeOnPooledThread {
                                  PersistenceService.save(project, conversationsToSave, appSettings)
                             }

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
        chatContentPanel.revalidate(); chatContentPanel.repaint()
        cardLayout.show(centerPanel, "CHAT")
        scrollToBottom()
        updateHeaderInfo()
    }

    private fun createNewChat() {
        val chat = Conversation()
        chatListModel.add(0, chat)

        val conversationsToSave = chatListModel.elements().toList()
        ApplicationManager.getApplication().executeOnPooledThread {
             PersistenceService.save(project, conversationsToSave, appSettings)
        }

        refreshHistoryList()
        loadChat(chat)
    }

    private fun renameSpecificChat(chat: Conversation) {
        val newTitle = Messages.showInputDialog(
            project,
            "Enter new chat title:",
            "Rename Chat",
            AllIcons.Actions.Edit,
            chat.title,
            null
        )

        if (!newTitle.isNullOrBlank() && newTitle != chat.title) {
            chat.title = newTitle

            val conversationsToSave = chatListModel.elements().toList()
            ApplicationManager.getApplication().executeOnPooledThread {
                PersistenceService.save(project, conversationsToSave, appSettings)
            }

            refreshHistoryList()
            if (chat == currentConversation) updateHeaderInfo()
        }
    }

    private fun deleteSpecificChat(chat: Conversation) {
        chatListModel.removeElement(chat)

        val conversationsToSave = chatListModel.elements().toList()
        ApplicationManager.getApplication().executeOnPooledThread {
             PersistenceService.save(project, conversationsToSave, appSettings)
        }

        refreshHistoryList()
        if (chatListModel.isEmpty) createNewChat()
        else if (chat == currentConversation) loadChat(chatListModel.firstElement())
    }

    private fun handleMessageDelete(index: Int) {
        val chat = currentConversation ?: return
        if (index >= 0 && index < chat.messages.size) {
            chat.messages.removeAt(index)

            val conversationsToSave = chatListModel.elements().toList()
            ApplicationManager.getApplication().executeOnPooledThread {
                 PersistenceService.save(project, conversationsToSave, appSettings)
            }

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

    private fun updateHeaderInfo() {
        val title = currentConversation?.title ?: "New Chat"
        val model = currentModel
        val displayTitle = if (title.length > 25) title.substring(0, 22) + "..." else title
        headerInfoLabel.text = "<html><b>$displayTitle</b> <span style='color:gray'>($model)</span></html>"
        headerInfoLabel.toolTipText = "$title using $model"
    }
}