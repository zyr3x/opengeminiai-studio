package com.opengeminiai.studio.client.ui

import com.opengeminiai.studio.client.model.FileChange
import com.opengeminiai.studio.client.utils.DiffUtils
import com.opengeminiai.studio.client.utils.MarkdownUtils
import com.opengeminiai.studio.client.Icons
import com.intellij.openapi.project.Project
import com.intellij.ui.JBColor
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBScrollPane
import com.intellij.util.ui.JBUI
import com.intellij.util.ui.UIUtil
import com.intellij.icons.AllIcons
import java.awt.*
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent
import java.io.File
import java.util.regex.Pattern
import javax.swing.*
import kotlin.math.min

object ChatComponents {

    // Cache to store original file content for Undo functionality (Session based)
    private val undoCache = mutableMapOf<String, String>()
    private val appliedStatus = mutableSetOf<String>()

    fun createMessageBubble(role: String, content: String, messageIndex: Int? = null, onDelete: ((Int) -> Unit)? = null): JPanel {
        val isUser = role == "user"

        // Main Wrapper
        val wrapper = JPanel(BorderLayout())
        wrapper.isOpaque = false
        wrapper.border = JBUI.Borders.empty(4, 0) // Minimal vertical spacing

        // --- AVATAR ---
        // Use Plugin Logo for AI, User Icon for User
        val avatarIcon = if (isUser) AllIcons.General.User else Icons.Logo
        val avatarLabel = JLabel(avatarIcon)
        avatarLabel.verticalAlignment = SwingConstants.TOP
        avatarLabel.border = JBUI.Borders.empty(0, 8) // Spacing around avatar

        // --- BUBBLE CONTENT ---
        val bubble = RoundedPanel(isUser)
        bubble.layout = BoxLayout(bubble, BoxLayout.Y_AXIS)
        // Compact padding inside bubble
        bubble.border = JBUI.Borders.empty(8, 10)

        // Parse content
        val textContentBuilder = StringBuilder()
        val attachedFilesForDisplay = mutableListOf<File>()
        content.lines().forEach { line ->
            val trimmed = line.trim()
            if (trimmed.startsWith("image_path=")) {
                attachedFilesForDisplay.add(File(trimmed.substringAfter("image_path=")))
            } else if (trimmed.startsWith("code_path=")) {
                attachedFilesForDisplay.add(File(trimmed.substringAfter("code_path=")))
            } else {
                textContentBuilder.append(line).append("\n")
            }
        }
        val actualTextContent = textContentBuilder.toString().trim()

        // Populate Bubble with Text and Code segments
        populateBubbleContent(bubble, actualTextContent)

        // Attachments
        if (attachedFilesForDisplay.isNotEmpty()) {
            val attachmentsPanel = JPanel()
            attachmentsPanel.layout = BoxLayout(attachmentsPanel, BoxLayout.Y_AXIS)
            attachmentsPanel.isOpaque = false

            // Add spacing between text and files if text exists
            if (actualTextContent.isNotBlank()) {
                 attachmentsPanel.add(Box.createVerticalStrut(8))
            }

            attachedFilesForDisplay.forEach { file ->
                val chip = createAttachmentChip(file, {}, false)
                chip.alignmentX = Component.LEFT_ALIGNMENT
                chip.maximumSize = chip.preferredSize
                attachmentsPanel.add(chip)
                attachmentsPanel.add(Box.createVerticalStrut(4))
            }
            attachmentsPanel.alignmentX = Component.LEFT_ALIGNMENT
            bubble.add(attachmentsPanel)
        }

        // --- DELETE BUTTON ---
        val deleteBtn = JLabel(AllIcons.Actions.GC)
        deleteBtn.toolTipText = "Delete Message"
        deleteBtn.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
        deleteBtn.border = JBUI.Borders.empty(6) // Easier to click
        if (messageIndex != null && onDelete != null) {
            deleteBtn.addMouseListener(object : MouseAdapter() {
                override fun mouseClicked(e: MouseEvent) {
                    onDelete(messageIndex)
                }
                override fun mouseEntered(e: MouseEvent) {
                    deleteBtn.icon = AllIcons.Actions.Cancel // Change icon on hover for effect
                }
                override fun mouseExited(e: MouseEvent) {
                    deleteBtn.icon = AllIcons.Actions.GC
                }
            })
        } else {
            deleteBtn.isVisible = false
        }

        // --- LAYOUT ASSEMBLY ---
        val box = Box.createHorizontalBox()

        if (isUser) {
            box.add(Box.createHorizontalGlue())
            box.add(deleteBtn)
            box.add(bubble)
            box.add(avatarLabel)
        } else {
            box.add(avatarLabel)
            box.add(bubble)
            box.add(deleteBtn)
            box.add(Box.createHorizontalGlue())
        }

        wrapper.add(box, BorderLayout.CENTER)
        return wrapper
    }

    // --- UTILS ---

    fun updateMessageBubble(bubbleWrapper: JPanel, content: String) {
        // Find the RoundedPanel inside the wrapper
        val bubble = findChildComponentRecursive(bubbleWrapper, RoundedPanel::class.java)
        if (bubble != null) {
            bubble.removeAll()
            populateBubbleContent(bubble, content)
            bubble.revalidate()
            bubble.repaint()
        }
    }

    private fun populateBubbleContent(panel: JPanel, content: String) {
        if (content.isEmpty()) {
            panel.add(createTextPanel("&nbsp;"))
            return
        }

        val segments = parseSegments(content)
        segments.forEach { segment ->
            if (segment.isCode) {
                panel.add(createCodePanel(segment.content))
            } else {
                if (segment.content.isNotBlank()) {
                    panel.add(createTextPanel(segment.content))
                }
            }
        }
    }

    private data class MessageSegment(val content: String, val isCode: Boolean)

    private fun parseSegments(text: String): List<MessageSegment> {
        val segments = mutableListOf<MessageSegment>()
        // Regex matches fenced code blocks: ```lang ... ```
        val matcher = Pattern.compile("```(?:\\w*)\\n?([\\s\\S]*?)```").matcher(text)
        var lastIndex = 0

        while (matcher.find()) {
            if (matcher.start() > lastIndex) {
                val textPart = text.substring(lastIndex, matcher.start())
                if (textPart.isNotBlank()) {
                    segments.add(MessageSegment(textPart, false))
                }
            }
            val code = matcher.group(1) ?: ""
            segments.add(MessageSegment(code.trim(), true))
            lastIndex = matcher.end()
        }

        if (lastIndex < text.length) {
            val tail = text.substring(lastIndex)
            if (tail.isNotEmpty()) {
                segments.add(MessageSegment(tail, false))
            }
        }
        return segments
    }

    private fun createCodePanel(code: String): JComponent {
        val textArea = JTextArea(code)
        textArea.font = JBUI.Fonts.create("JetBrains Mono", 12)
        textArea.isEditable = false
        // Make code blocks significantly darker for better separation
        textArea.background = if (UIUtil.isUnderDarcula()) Color(30, 31, 33) else Color(242, 244, 245)
        textArea.foreground = if (UIUtil.isUnderDarcula()) Color(169, 183, 198) else Color(8, 8, 8)
        textArea.margin = JBUI.insets(8)

        val scroll = JBScrollPane(textArea)
        scroll.border = JBUI.Borders.customLine(if (UIUtil.isUnderDarcula()) Color(50, 50, 50) else Color(200, 200, 200))
        scroll.viewportBorder = null

        // Height Logic: Cap at ~300px to allow vertical scrolling
        val metrics = textArea.getFontMetrics(textArea.font)
        val lineHeight = metrics.height
        val lines = code.lines().size
        val maxHeight = 300
        val prefHeight = min(maxHeight, (lines * lineHeight) + 24) // + padding

        scroll.preferredSize = Dimension(-1, prefHeight)
        scroll.maximumSize = Dimension(Int.MAX_VALUE, prefHeight)
        scroll.alignmentX = Component.LEFT_ALIGNMENT

        return scroll
    }

    private fun createTextPanel(text: String): JComponent {
        val editorPane = JEditorPane()
        editorPane.contentType = "text/html"
        editorPane.text = MarkdownUtils.renderHtml(text)
        editorPane.isEditable = false
        editorPane.isOpaque = false
        editorPane.putClientProperty(JEditorPane.HONOR_DISPLAY_PROPERTIES, true)
        editorPane.addHyperlinkListener { e ->
            if (e.eventType == javax.swing.event.HyperlinkEvent.EventType.ACTIVATED) {
                try { Desktop.getDesktop().browse(e.url.toURI()) } catch (err: Exception) {}
            }
        }
        editorPane.alignmentX = Component.LEFT_ALIGNMENT
        return editorPane
    }

    private inline fun <reified T : Component> findChildComponent(parent: Container): T? {
        return findChildComponentRecursive(parent, T::class.java)
    }

    private fun <T : Component> findChildComponentRecursive(parent: Container, clazz: Class<T>): T? {
        for (comp in parent.components) {
            if (clazz.isInstance(comp)) return clazz.cast(comp)
            if (comp is Container) {
                val found = findChildComponentRecursive(comp, clazz)
                if (found != null) return found
            }
        }
        return null
    }

    // Generalized chip creation
    fun createGenericChip(text: String, icon: Icon, onClose: () -> Unit, onClick: (() -> Unit)? = null, isRemovable: Boolean = true): JPanel {
        val chip = JPanel(BorderLayout())
        chip.isOpaque = false

        val bg = object : JPanel(BorderLayout()) {
            override fun paintComponent(g: Graphics) {
                val g2 = g as Graphics2D
                g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
                // Darker chip background in dark mode
                g2.color = JBColor(Color(230, 230, 230), Color(45, 47, 49))
                g2.fillRoundRect(0, 0, width - 1, height - 1, 8, 8)
                g2.color = JBColor.border()
                g2.drawRoundRect(0, 0, width - 1, height - 1, 8, 8)
                super.paintComponent(g)
            }
        }
        bg.isOpaque = false
        bg.border = JBUI.Borders.empty(2, 6, 2, 4)

        val label = JBLabel(text, icon, SwingConstants.LEFT)
        label.font = JBUI.Fonts.smallFont()

        if (onClick != null) {
            bg.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            val mouseAdapter = object : MouseAdapter() {
                override fun mouseClicked(e: MouseEvent) {
                    if (SwingUtilities.isLeftMouseButton(e)) onClick()
                }
            }
            bg.addMouseListener(mouseAdapter)
            label.addMouseListener(mouseAdapter)
        }

        bg.add(label, BorderLayout.CENTER)

        if (isRemovable) {
            val closeBtn = JButton(AllIcons.Actions.Close)
            closeBtn.isBorderPainted = false
            closeBtn.isContentAreaFilled = false
            closeBtn.preferredSize = Dimension(16, 16)
            closeBtn.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            closeBtn.addActionListener { onClose() }
            bg.add(closeBtn, BorderLayout.EAST)
        }
        chip.add(bg, BorderLayout.CENTER)
        return chip
    }

    // Keep compatibility for File signature, delegating to generic
    fun createAttachmentChip(file: File, onClose: () -> Unit, isRemovable: Boolean = true): JPanel {
        val icon = if (file.isDirectory) AllIcons.Nodes.Folder else AllIcons.FileTypes.Any_type
        return createGenericChip(file.name, icon, onClose, null, isRemovable)
    }

    // MODIFIED: Added onDelete callback
    fun createChangeWidget(project: Project, changes: List<FileChange>, onDelete: () -> Unit): JPanel {
        val wrapper = JPanel(BorderLayout())
        wrapper.isOpaque = false
        wrapper.border = JBUI.Borders.empty(2, 38, 2, 5)

        val container = RoundedChangeWidgetPanel().apply { layout = BorderLayout() }

        val header = JPanel(BorderLayout())
        header.isOpaque = false
        header.border = JBUI.Borders.empty(5, 8)

        val title = JBLabel("${changes.size} files updated", AllIcons.Actions.Checked, SwingConstants.LEFT)
        title.font = JBUI.Fonts.smallFont().deriveFont(Font.BOLD)
        header.add(title, BorderLayout.WEST)

        val headerActions = JPanel(FlowLayout(FlowLayout.RIGHT, 4, 0))
        headerActions.isOpaque = false

        fun refreshUI() {
             wrapper.removeAll()
             wrapper.add(createChangeWidget(project, changes, onDelete), BorderLayout.CENTER)
             wrapper.revalidate()
             wrapper.repaint()
        }

        val allApplied = changes.all { appliedStatus.contains(it.path) }
        val globalActionText = if (allApplied) "Undo All" else "Apply All"
        val globalActionColor = if (allApplied) JBColor.RED else JBColor.BLUE

        val actionAllBtn = JButton(globalActionText).apply {
            isBorderPainted = false
            isContentAreaFilled = false
            cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            font = JBUI.Fonts.smallFont()
            foreground = globalActionColor

            addActionListener {
                changes.forEach { change ->
                    val isApplied = appliedStatus.contains(change.path)

                    if (allApplied && isApplied) {
                        val backup = undoCache[change.path]
                        if (backup != null) {
                            DiffUtils.applyChangeDirectly(project, change.path, backup)
                            appliedStatus.remove(change.path)
                        }
                    } else if (!allApplied && !isApplied) {
                        val previous = DiffUtils.applyChangeDirectly(project, change.path, change.content)
                        if (previous != null) undoCache[change.path] = previous
                        appliedStatus.add(change.path)
                    }
                }
                refreshUI()
            }
        }

        val deleteWidgetBtn = JButton(AllIcons.Actions.GC).apply {
            toolTipText = "Remove this widget"
            preferredSize = Dimension(22, 22)
            isBorderPainted = false
            isContentAreaFilled = false
            cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            addActionListener { onDelete() }
        }

        headerActions.add(actionAllBtn)
        headerActions.add(deleteWidgetBtn)
        header.add(headerActions, BorderLayout.EAST)

        container.add(header, BorderLayout.NORTH)

        val fileList = Box.createVerticalBox()
        changes.forEach { change ->
            val changeRow = JPanel(BorderLayout())
            changeRow.isOpaque = false
            changeRow.border = JBUI.Borders.empty(2, 8)

            val filename = change.path.substringAfterLast("/")
            val link = JLabel(filename, AllIcons.FileTypes.Any_type, SwingConstants.LEFT)
            link.font = JBUI.Fonts.smallFont()
            link.foreground = JBColor.BLUE
            link.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            link.addMouseListener(object: MouseAdapter() {
                override fun mouseClicked(e: MouseEvent) {
                    DiffUtils.showDiff(project, change.path, change.content)
                }
            })

            val actions = JPanel(FlowLayout(FlowLayout.RIGHT, 0, 0))
            actions.isOpaque = false

            val isApplied = appliedStatus.contains(change.path)
            val btnIcon = if (isApplied) AllIcons.Actions.Rollback else AllIcons.Actions.Checked
            val btnToolTip = if (isApplied) "Undo changes" else "Apply changes"

            val btnAction = JButton(btnIcon).apply {
                preferredSize = Dimension(20, 20)
                toolTipText = btnToolTip
                isBorderPainted = false
                isContentAreaFilled = false
                cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)

                addActionListener {
                    if (isApplied) {
                         val backup = undoCache[change.path]
                         if (backup != null) {
                             DiffUtils.applyChangeDirectly(project, change.path, backup)
                             appliedStatus.remove(change.path)
                         }
                    } else {
                        val previous = DiffUtils.applyChangeDirectly(project, change.path, change.content)
                        if (previous != null) undoCache[change.path] = previous
                        appliedStatus.add(change.path)
                    }
                    refreshUI()
                }
            }
            actions.add(btnAction)

            changeRow.add(link, BorderLayout.CENTER)
            changeRow.add(actions, BorderLayout.EAST)
            fileList.add(changeRow)
        }
        container.add(fileList, BorderLayout.CENTER)
        wrapper.add(container, BorderLayout.CENTER)
        return wrapper
    }

    class RoundedPanel(private val isUser: Boolean) : JPanel() {
        init { isOpaque = false }
        override fun paintComponent(g: Graphics) {
            val g2 = g as Graphics2D
            g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
            if (isUser) {
                val lightColor = Color(235, 240, 255)
                val darkColor = Color(70, 50, 90)
                g2.color = JBColor(lightColor, darkColor)
            } else {
                // Modified: Darker background for AI response to improve text readability
                // Light Mode: White, Dark Mode: Color(35, 37, 39) (Darker than standard panel)
                g2.color = JBColor(Color(255, 255, 255), Color(35, 37, 39))
            }
            g2.fillRoundRect(0, 0, width - 1, height - 1, 16, 16)
            g2.color = if(isUser) JBColor(Color(200, 210, 240), Color(85, 65, 105)) else JBColor.border()
            g2.drawRoundRect(0, 0, width - 1, height - 1, 16, 16)
            super.paintComponent(g)
        }
    }

    class RoundedChangeWidgetPanel : JPanel() {
        init { isOpaque = false }
        override fun paintComponent(g: Graphics) {
            val g2 = g as Graphics2D
            g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
            g2.color = JBColor(Color(248, 248, 248), Color(40, 42, 44))
            g2.fillRoundRect(0, 0, width - 1, height - 1, 12, 12)
            g2.color = JBColor.border()
            g2.drawRoundRect(0, 0, width - 1, height - 1, 12, 12)
            super.paintComponent(g)
        }
    }
}