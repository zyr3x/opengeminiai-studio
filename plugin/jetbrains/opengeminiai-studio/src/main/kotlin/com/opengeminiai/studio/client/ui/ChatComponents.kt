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
import com.intellij.openapi.ui.DialogWrapper
import java.awt.*
import java.awt.datatransfer.StringSelection
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent
import java.io.File
import java.util.regex.Pattern
import javax.swing.*
import kotlin.math.min

object ChatComponents {

    private val undoCache = mutableMapOf<String, String>()
    private val appliedStatus = mutableSetOf<String>()

    fun createMessageBubble(role: String, content: String, messageIndex: Int? = null, onDelete: ((Int) -> Unit)? = null): JPanel {
        val isUser = role == "user"
        val wrapper = JPanel(BorderLayout())
        wrapper.isOpaque = false
        wrapper.border = JBUI.Borders.empty(4, 0)

        val avatarIcon = if (isUser) AllIcons.General.User else Icons.Logo
        val avatarLabel = JLabel(avatarIcon)
        avatarLabel.verticalAlignment = SwingConstants.TOP
        avatarLabel.border = JBUI.Borders.empty(0, 8)

        val bubble = RoundedPanel(isUser)
        bubble.layout = BoxLayout(bubble, BoxLayout.Y_AXIS)
        bubble.border = JBUI.Borders.empty(8, 10)

        val textContentBuilder = StringBuilder()
        val attachedFilesForDisplay = mutableListOf<File>()

        // Pre-process markers to extract files and keep other content
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

        populateBubbleContent(bubble, actualTextContent)

        if (attachedFilesForDisplay.isNotEmpty()) {
            val attachmentsPanel = JPanel()
            attachmentsPanel.layout = BoxLayout(attachmentsPanel, BoxLayout.Y_AXIS)
            attachmentsPanel.isOpaque = false

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

        val copyBtn = JLabel(AllIcons.Actions.Copy)
        copyBtn.toolTipText = "Copy raw content"
        copyBtn.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
        copyBtn.border = JBUI.Borders.empty(6)
        copyBtn.addMouseListener(object : MouseAdapter() {
            override fun mouseClicked(e: MouseEvent) {
                val selection = StringSelection(content)
                Toolkit.getDefaultToolkit().systemClipboard.setContents(selection, null)
            }
        })

        val deleteBtn = JLabel(AllIcons.Actions.GC)
        deleteBtn.toolTipText = "Delete Message"
        deleteBtn.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
        deleteBtn.border = JBUI.Borders.empty(6)
        if (messageIndex != null && onDelete != null) {
            deleteBtn.addMouseListener(object : MouseAdapter() {
                override fun mouseClicked(e: MouseEvent) { onDelete(messageIndex) }
                override fun mouseEntered(e: MouseEvent) { deleteBtn.icon = AllIcons.Actions.Cancel }
                override fun mouseExited(e: MouseEvent) { deleteBtn.icon = AllIcons.Actions.GC }
            })
        } else {
            deleteBtn.isVisible = false
        }

        val box = Box.createHorizontalBox()
        if (isUser) {
            box.add(Box.createHorizontalGlue())
            box.add(copyBtn)
            box.add(deleteBtn)
            box.add(bubble)
            box.add(avatarLabel)
        } else {
            box.add(avatarLabel)
            box.add(bubble)
            box.add(copyBtn)
            box.add(deleteBtn)
            box.add(Box.createHorizontalGlue())
        }

        wrapper.add(box, BorderLayout.CENTER)
        return wrapper
    }

    fun updateMessageBubble(bubbleWrapper: JPanel, content: String) {
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
            when (segment.type) {
                SegmentType.CODE -> panel.add(createCodePanel(segment.content))
                SegmentType.CONTEXT -> {
                    val ctxPanel = createContextPanel(segment.title!!, segment.contentType!!, segment.content)
                    panel.add(ctxPanel)
                    // Add small spacing after context item
                    panel.add(Box.createVerticalStrut(4))
                }
                SegmentType.TEXT -> {
                    if (segment.content.isNotBlank()) {
                        panel.add(createTextPanel(segment.content))
                    }
                }
            }
        }
    }

    enum class SegmentType { TEXT, CODE, CONTEXT }
    private data class MessageSegment(val content: String, val type: SegmentType, val title: String? = null, val contentType: String? = null)

    private fun parseSegments(text: String): List<MessageSegment> {
        val segments = mutableListOf<MessageSegment>()

        // Group 1: Code block content
        // Group 2: Context title, Group 3: Context type, Group 4: Context content
        val pattern = Pattern.compile("```(?:\\w*)\\n?([\\s\\S]*?)```|:::CTX:(.*?):(.*?):::\\n([\\s\\S]*?)\\n:::END:::")
        val matcher = pattern.matcher(text)
        var lastIndex = 0

        while (matcher.find()) {
            if (matcher.start() > lastIndex) {
                val textPart = text.substring(lastIndex, matcher.start())
                if (textPart.isNotBlank()) segments.add(MessageSegment(textPart, SegmentType.TEXT))
            }

            if (matcher.group(1) != null) {
                segments.add(MessageSegment(matcher.group(1).trim(), SegmentType.CODE))
            } else {
                val title = matcher.group(2)
                val type = matcher.group(3)
                val content = matcher.group(4)
                segments.add(MessageSegment(content, SegmentType.CONTEXT, title, type))
            }
            lastIndex = matcher.end()
        }

        if (lastIndex < text.length) {
            val tail = text.substring(lastIndex)
            if (tail.isNotEmpty()) segments.add(MessageSegment(tail, SegmentType.TEXT))
        }
        return segments
    }

    private fun createContextPanel(title: String, type: String, content: String): JComponent {
        val icon = when (type) {
            "commit" -> AllIcons.Vcs.CommitNode
            "structure" -> AllIcons.Actions.ListFiles
            else -> AllIcons.FileTypes.Text
        }

        // Limit title length to avoid super wide chips
        val displayTitle = if (title.length > 40) title.take(37) + "..." else title

        val chip = createGenericChip(displayTitle, icon, {}, {
            showContentDialog(title, content)
        }, false)

        chip.alignmentX = Component.LEFT_ALIGNMENT
        // FIX: Ensure it doesn't stretch to full width
        chip.maximumSize = chip.preferredSize

        return chip
    }

    private fun showContentDialog(title: String, content: String) {
        val dialog = object : DialogWrapper(true) {
            init {
                this.title = title
                init()
            }
            override fun createCenterPanel(): JComponent {
                val textArea = JTextArea(content)
                textArea.isEditable = false
                textArea.font = JBUI.Fonts.create("JetBrains Mono", 12)
                val scroll = JBScrollPane(textArea)
                scroll.preferredSize = Dimension(600, 400)
                return scroll
            }
            override fun createActions(): Array<Action> = arrayOf(okAction)
        }
        dialog.show()
    }

    private fun createCodePanel(code: String): JComponent {
        val textArea = JTextArea(code)
        textArea.font = JBUI.Fonts.create("JetBrains Mono", 12)
        textArea.isEditable = false
        textArea.background = if (UIUtil.isUnderDarcula()) Color(30, 31, 33) else Color(242, 244, 245)
        textArea.foreground = if (UIUtil.isUnderDarcula()) Color(169, 183, 198) else Color(8, 8, 8)
        textArea.margin = JBUI.insets(8)

        val scroll = JBScrollPane(textArea)
        scroll.border = JBUI.Borders.customLine(if (UIUtil.isUnderDarcula()) Color(50, 50, 50) else Color(200, 200, 200))
        scroll.viewportBorder = null

        val metrics = textArea.getFontMetrics(textArea.font)
        val lineHeight = metrics.height
        val lines = code.lines().size
        val maxHeight = 300
        val prefHeight = min(maxHeight, (lines * lineHeight) + 24)

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

    fun createGenericChip(text: String, icon: Icon, onClose: () -> Unit, onClick: (() -> Unit)? = null, isRemovable: Boolean = true): JPanel {
        val chip = JPanel(BorderLayout())
        chip.isOpaque = false

        val bg = object : JPanel(BorderLayout()) {
            override fun paintComponent(g: Graphics) {
                val g2 = g as Graphics2D
                g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
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

    fun createAttachmentChip(file: File, onClose: () -> Unit, isRemovable: Boolean = true): JPanel {
        val icon = if (file.isDirectory) AllIcons.Nodes.Folder else AllIcons.FileTypes.Any_type
        return createGenericChip(file.name, icon, onClose, null, isRemovable)
    }

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
