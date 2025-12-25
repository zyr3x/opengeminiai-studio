package com.opengeminiai.studio.client.ui

import com.opengeminiai.studio.client.model.*
import com.opengeminiai.studio.client.service.ApiClient
import com.opengeminiai.studio.client.service.PersistenceService
import com.opengeminiai.studio.client.Icons
import com.google.gson.Gson
import com.intellij.execution.configurations.GeneralCommandLine
import com.intellij.execution.util.ExecUtil
import com.intellij.openapi.actionSystem.*
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.fileChooser.FileChooser
import com.intellij.openapi.fileChooser.FileChooserDescriptorFactory
import com.intellij.openapi.project.Project
import com.intellij.openapi.roots.ProjectRootManager
import com.intellij.ui.components.* import com.intellij.openapi.ui.ComboBox
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
import com.intellij.ui.dsl.builder.panel
import com.intellij.ui.dsl.builder.Align
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
    private sealed class ContextItem {
        abstract val name: String
        abstract val icon: Icon
    }
    private data class FileContext(val file: File) : ContextItem() {
        override val name: String = file.name
        override val icon: Icon = if (file.isDirectory) AllIcons.Nodes.Folder else AllIcons.FileTypes.Any_type
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

        // -- LOGIC: Persist Model Selection per Mode --
        modeComboBox.addItemListener { e ->
            if (e.stateChange == ItemEvent.SELECTED) {
                val newMode = e.item as String
                // FIX: Use correctly persisted models when switching
                val modelToRestore = if (newMode == "Chat") lastChatModel else lastQuickEditModel

                // Temporarily remove listener to avoid triggering model change logic
                val listeners = modelComboBox.itemListeners
                listeners.forEach { modelComboBox.removeItemListener(it) }
                modelComboBox.selectedItem = modelToRestore
                listeners.forEach { modelComboBox.addItemListener(it) }

                updateHeaderInfo()
            }
        }

        modelComboBox.addItemListener { e ->
            if (e.stateChange == ItemEvent.SELECTED) {
                // FIX: Use selectedItem instead of .item (which doesn't exist on ComboBox)
                val currentMode = modeComboBox.selectedItem as? String
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

        // Removed Refresh Button as requested
        val addContextBtn = createIconButton(AllIcons.General.Add, "Add Context (Files, Images, Structure)") { e ->
            showAddContextPopup(e.source as Component)
        }

        leftControls.add(addContextBtn)
        leftControls.add(modeComboBox)
        leftControls.add(modelComboBox)

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

    private data class CommitItem(val hash: String, val message: String, val time: String)

    private fun getRecentCommits(project: Project): List<CommitItem> {
        val list = mutableListOf<CommitItem>()
        val basePath = project.basePath ?: return list
        try {
            val cmd = GeneralCommandLine("git", "log", "-n", "30", "--pretty=format:%h|%s|%ar")
            cmd.workDirectory = File(basePath)

            val output = ExecUtil.execAndGetOutput(cmd)
            if (output.exitCode == 0) {
                output.stdout.lines().forEach { line ->
                    if (line.isNotBlank()) {
                        val parts = line.split("|", limit = 3)
                        if (parts.size == 3) {
                            list.add(CommitItem(parts[0], parts[1], parts[2]))
                        }
                    }
                }
            }
        } catch (e: Exception) {
            // Silently fail if git not found or error
        }
        return list
    }

    private fun showAddContextPopup(component: Component) {
        val actions = DefaultActionGroup()

        // 1. Files and Folders
        actions.add(object : AnAction("Files and Folders", "Attach specific files or folders to context", AllIcons.Nodes.Folder) {
            override fun actionPerformed(e: AnActionEvent) {
                val descriptor = FileChooserDescriptorFactory.createMultipleFilesNoJarsDescriptor()
                FileChooser.chooseFiles(descriptor, project, null) { files ->
                    files.forEach { file -> File(file.path).let { addAttachment(FileContext(it)) } }
                }
            }
        })

        // 2. Add Image
        actions.add(object : AnAction("Add Image...", "Attach an image for multimodal analysis", AllIcons.FileTypes.Image) {
            override fun actionPerformed(e: AnActionEvent) {
                val descriptor = FileChooserDescriptorFactory.createSingleFileDescriptor()
                    .withFileFilter { it.extension?.lowercase() in listOf("jpg", "jpeg", "png", "webp") }
                FileChooser.chooseFiles(descriptor, project, null) { files ->
                    files.firstOrNull()?.let { addAttachment(FileContext(File(it.path))) }
                }
            }
        })

        actions.addSeparator()

        // 3. Project Structure
        actions.add(object : AnAction("Project Structure", "Paste current project directory tree into chat", AllIcons.Actions.ListFiles) {
            override fun actionPerformed(e: AnActionEvent) {
                val sb = StringBuilder("Project Structure:\n")
                val roots = ProjectRootManager.getInstance(project).contentRoots
                roots.forEach { root ->
                    buildFileTree(root, "", sb, 0)
                }

                addAttachment(TextContext("Project Structure", sb.toString(), AllIcons.Actions.ListFiles))
            }
        })

        // 4. Commits (Multi-select)
        actions.add(object : AnAction("Commits", "Reference recent git commits", AllIcons.Vcs.CommitNode) {
            override fun actionPerformed(e: AnActionEvent) {
                val commits = getRecentCommits(project)
                if (commits.isEmpty()) {
                    Messages.showInfoMessage(project, "No recent commits found (or git not configured).", "Commits")
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

                val popup = JBPopupFactory.getInstance().createListPopupBuilder(list)
                    .setTitle("Select Commits")
                    .setResizable(true)
                    .setMovable(true)
                    .setItemChoosenCallback {
                        ApplicationManager.getApplication().executeOnPooledThread {
                            val selected = list.selectedValuesList
                            if (selected.isEmpty()) return@executeOnPooledThread

                            selected.forEach { commit ->
                                val sb = StringBuilder()
                                sb.append("Commit: ${commit.hash} - ${commit.message}\n")
                                try {
                                    val cmd = GeneralCommandLine("git", "show", commit.hash)
                                    cmd.workDirectory = File(project.basePath ?: "")
                                    val out = ExecUtil.execAndGetOutput(cmd)
                                    if (out.exitCode == 0) {
                                        val content = out.stdout
                                        val maxLen = 5000
                                        if (content.length > maxLen) {
                                            sb.append(content.take(maxLen)).append("\n...(truncated)...\n")
                                        } else {
                                            sb.append(content).append("\n")
                                        }
                                    }
                                } catch (ex: Exception) {}

                                val commitText = sb.toString()
                                SwingUtilities.invokeLater {
                                    addAttachment(TextContext("Commit ${commit.hash.take(7)}", commitText, AllIcons.Vcs.CommitNode))
                                }
                            }
                        }
                    }
                    .createPopup()

                popup.showUnderneathOf(component)
            }
        })

        val popup = JBPopupFactory.getInstance().createActionGroupPopup(
            "Add Context",
            actions,
            DataManager.getInstance().getDataContext(component),
            JBPopupFactory.ActionSelectionAid.SPEEDSEARCH,
            true
        )
        popup.showUnderneathOf(component)
    }

    private fun buildFileTree(file: com.intellij.openapi.vfs.VirtualFile, indent: String, sb: StringBuilder, depth: Int) {
        if (depth > 5) return // Safety cap
        sb.append("$indent- ${file.name}\n")
        if (file.isDirectory) {
            file.children.take(20).forEach { child -> // Limit children per node
                if (!child.name.startsWith(".")) { // Skip dotfiles
                    buildFileTree(child, "$indent  ", sb, depth + 1)
                }
            }
        }
    }

    private fun updateHeaderInfo() {
        val title = currentConversation?.title ?: "New Chat"
        // FIX: Use selectedItem
        val model = modelComboBox.selectedItem as? String ?: "gemini-2.5-flash"
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
                        files.forEach { addAttachment(FileContext(it)) }
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

    private fun addAttachment(item: ContextItem) {
        if (item is FileContext && attachments.filterIsInstance<FileContext>().any { it.file.absolutePath == item.file.absolutePath }) return
        attachments.add(item)
        refreshAttachmentsPanel()
    }

    private fun removeAttachment(item: ContextItem) {
        attachments.remove(item)
        refreshAttachmentsPanel()
    }

    private fun refreshAttachmentsPanel() {
        attachmentsPanel.removeAll()
        if (attachments.isEmpty()) {
            attachmentsPanel.isVisible = false
        } else {
            attachmentsPanel.isVisible = true

            val count = attachments.size
            val labelText = "$count item${if (count > 1) "s" else ""} attached"

            val summaryBtn = JButton(labelText, AllIcons.FileTypes.Any_type)
            summaryBtn.isBorderPainted = false
            summaryBtn.isContentAreaFilled = false
            summaryBtn.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            summaryBtn.toolTipText = "Click to view and manage context"
            summaryBtn.addActionListener { showAttachmentsPopup(summaryBtn) }

            attachmentsPanel.add(summaryBtn)
        }
        attachmentsPanel.revalidate()
        attachmentsPanel.repaint()
    }

    private fun showAttachmentsPopup(anchor: Component) {
        val panel = JPanel()
        panel.layout = BoxLayout(panel, BoxLayout.Y_AXIS)
        panel.border = JBUI.Borders.empty(8)
        panel.background = JBColor.background()

        var popup: JBPopup? = null

        fun reload() {
            panel.removeAll()
            if (attachments.isEmpty()) {
                popup?.cancel()
                return
            }

            attachments.forEach { item ->
                val row = JPanel(BorderLayout())
                row.isOpaque = false
                row.alignmentX = Component.LEFT_ALIGNMENT
                row.maximumSize = Dimension(400, 32)
                row.border = JBUI.Borders.empty(2, 0)

                val name = if (item.name.length > 35) item.name.take(32) + "..." else item.name
                val label = JLabel(name, item.icon, SwingConstants.LEFT)
                label.border = JBUI.Borders.emptyRight(12)

                // Allow edit for text context
                if (item is TextContext) {
                    label.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
                    label.toolTipText = "Click to edit"
                    label.addMouseListener(object : MouseAdapter() {
                        override fun mouseClicked(e: MouseEvent) {
                            showEditContextDialog(item) {
                                // Refresh logic if needed, but item is mutable
                            }
                        }
                    })
                }

                val delBtn = JButton(AllIcons.Actions.Close)
                delBtn.preferredSize = Dimension(22, 22)
                delBtn.isBorderPainted = false
                delBtn.isContentAreaFilled = false
                delBtn.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
                delBtn.addActionListener {
                    removeAttachment(item)
                    reload()
                    panel.revalidate()
                    panel.repaint()
                    popup?.pack(true, true)
                }

                row.add(label, BorderLayout.CENTER)
                row.add(delBtn, BorderLayout.EAST)
                panel.add(row)
            }
        }

        reload()

        popup = JBPopupFactory.getInstance()
            .createComponentPopupBuilder(panel, null)
            .setTitle("Attached Context")
            .setResizable(false)
            .setMovable(true)
            .setRequestFocus(true)
            .createPopup()

        popup?.showUnderneathOf(anchor)
    }

    private fun showEditContextDialog(item: TextContext, onClose: () -> Unit) {
        val dialog = object : DialogWrapper(project) {
            val textArea = JTextArea(item.content)
            init {
                title = "Edit ${item.name}"
                init()
            }
            override fun createCenterPanel(): JComponent {
                return JBScrollPane(textArea).apply {
                    preferredSize = Dimension(500, 400)
                }
            }
            override fun doOKAction() {
                item.content = textArea.text
                super.doOKAction()
                onClose()
            }
        }
        dialog.show()
    }

    // Changed signature to pass ActionEvent, fixing 'Unresolved reference: source' in lambda
    private fun createIconButton(icon: Icon, tooltip: String, action: (ActionEvent) -> Unit): JButton {
        val btn = JButton(icon)
        btn.toolTipText = tooltip
        btn.preferredSize = Dimension(28, 28)
        btn.isBorderPainted = false
        btn.isContentAreaFilled = false
        btn.isFocusPainted = false
        btn.isOpaque = false
        btn.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
        btn.addActionListener { action(it) }
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
        if ((textInput.isEmpty() && attachments.isEmpty()) || currentConversation == null) return

        val chat = currentConversation!!
        val sb = StringBuilder(textInput)

        if (attachments.isNotEmpty()) {
            if (sb.isNotEmpty()) sb.append("\n\n")

            // Files logic
            attachments.filterIsInstance<FileContext>().forEach { item ->
                val extension = item.file.extension.lowercase()
                when (extension) {
                    "jpg", "jpeg", "png" -> {
                        sb.append("image_path=")
                        sb.append(item.file.absolutePath)
                    }
                    else -> {
                        sb.append("code_path=")
                        sb.append(item.file.absolutePath)
                    }
                }
                sb.append("\n")
            }

            // Text Context logic (append as pure text)
            attachments.filterIsInstance<TextContext>().forEach { item ->
                sb.append("\n\n--- ${item.name} ---\n")
                sb.append(item.content)
                sb.append("\n--- End of ${item.name} ---\n")
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
        attachments.clear()
        attachmentsPanel.removeAll()
        refreshAttachmentsPanel()
        scrollToBottom()
        PersistenceService.save(project, chatListModel.elements().toList(), appSettings)

        // FIX: Use selectedItem instead of incorrect .item
        val model = modelComboBox.selectedItem as? String ?: "gemini-2.5-flash"
        val mode = modeComboBox.selectedItem as? String ?: "Chat"

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
        var textPart = response.trim()
        var changes: List<FileChange>? = null

        // 1. Try to find JSON inside Markdown code blocks (Robust Index-based parsing)
        // Improved: Support optional space after backticks
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
                } catch (e: Exception) {
                    // JSON parse error, keep text as is
                }
            }
        }

        // 2. Fallback: Try to find raw JSON object if no code block match
        if (changes == null) {
            val jsonStart = response.indexOf("{")
            val jsonEnd = response.lastIndexOf("}")

            if (jsonStart != -1 && jsonEnd > jsonStart) {
                 val potentialJson = response.substring(jsonStart, jsonEnd + 1)
                 // Check if it looks like our schema
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
             // Update model
             chat.messages[chat.messages.size - 1] = ChatMessage("assistant", textPart, changes)

             // Update UI Bubble
             val bubblePanel = chatContentPanel.getComponent(chatContentPanel.componentCount - 2) as JPanel
             ChatComponents.updateMessageBubble(bubblePanel, textPart)

             // Append widget if changes exist
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

                    // FIX: Use selectedItem
                    val currentMode = modeComboBox.selectedItem as? String ?: "Chat"
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