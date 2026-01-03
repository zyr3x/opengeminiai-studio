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
import com.intellij.openapi.ui.popup.JBPopupFactory
import com.intellij.openapi.ui.MessageType
import com.intellij.openapi.ui.popup.Balloon
import java.awt.*
import java.awt.datatransfer.StringSelection
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent
import java.io.File
import java.util.regex.Pattern
import java.util.Locale
import javax.swing.*
import kotlin.math.min

object ChatComponents {

    private data class AttachedFile(val file: File, val params: String?)

    fun createMessageBubble(role: String, content: String, messageIndex: Int? = null, onDelete: ((Int) -> Unit)? = null): JPanel {
        val isUser = role == "user"
        val wrapper = JPanel(BorderLayout())
        wrapper.isOpaque = false
        // FIX: Increased right padding (24) to prevent content from being covered by the tool window scrollbar
        wrapper.border = JBUI.Borders.empty(6, 12, 6, 24)

        val avatarIcon = if (isUser) AllIcons.General.User else Icons.Logo
        val avatarLabel = JLabel(avatarIcon)
        avatarLabel.verticalAlignment = SwingConstants.TOP
        avatarLabel.border = JBUI.Borders.empty(0, 8)

        val bubble = RoundedPanel(isUser)
        bubble.layout = BoxLayout(bubble, BoxLayout.Y_AXIS)
        // FIX: Increased internal padding for better readability
        bubble.border = JBUI.Borders.empty(10, 12)

        val textContentBuilder = StringBuilder()
        val attachedFilesForDisplay = mutableListOf<AttachedFile>()

        // Pre-process markers to extract files and keep other content
        content.lines().forEach { line ->
            val trimmed = line.trim()
            if (trimmed.startsWith("image_path=") || trimmed.startsWith("code_path=") || trimmed.startsWith("pdf_path=")) {
                val prefix = when {
                    trimmed.startsWith("image_path=") -> "image_path="
                    trimmed.startsWith("pdf_path=") -> "pdf_path="
                    else -> "code_path="
                }
                val rawPath = trimmed.substringAfter(prefix)
                val (path, params) = parsePathAndParams(rawPath)
                attachedFilesForDisplay.add(AttachedFile(File(path), params))
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

            attachedFilesForDisplay.forEach { (file, params) ->
                val chip = createAttachmentChip(file, params, {}, false)
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

    private fun parsePathAndParams(fullLine: String): Pair<String, String?> {
        // Look for the start of parameters
        val triggers = listOf(" ignore_type=", " ignore_file=", " ignore_dir=")
        var firstTriggerIndex = -1

        for (trigger in triggers) {
            val index = fullLine.indexOf(trigger)
            if (index != -1 && (firstTriggerIndex == -1 || index < firstTriggerIndex)) {
                firstTriggerIndex = index
            }
        }

        return if (firstTriggerIndex != -1) {
            Pair(fullLine.substring(0, firstTriggerIndex).trim(), fullLine.substring(firstTriggerIndex).trim())
        } else {
            Pair(fullLine.trim(), null)
        }
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
        val segments = parseSegments(content)
        segments.forEach { segment ->
            when (segment.type) {
                SegmentType.CODE -> {
                    // FIX: Stricter check for JSON actions (must start with {) to avoid false positives in source code
                    if (segment.content.trim().startsWith("{") && segment.content.contains("\"action\": \"propose_changes\"")) {
                        val pathPattern = Pattern.compile("\"path\"\\s*:\\s*\"(.*?)\"")
                        val pathMatcher = pathPattern.matcher(segment.content)
                        var lastFileName: String? = null
                        while (pathMatcher.find()) {
                            lastFileName = pathMatcher.group(1).substringAfterLast('/')
                        }
                        panel.add(createGeneratingPlaceholder(lastFileName))
                    } else {
                        panel.add(createCodePanel(segment.content))
                    }
                }
                SegmentType.CONTEXT -> {
                    val ctxPanel = createContextPanel(segment.title!!, segment.contentType!!, segment.content)
                    panel.add(ctxPanel)
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

        // FIX: Updated regex to require newline before closing backticks (\n```)
        // This prevents the parser from breaking when the code content itself contains inline triple backticks (e.g. inside strings)
        val pattern = Pattern.compile("```(\\w*)\\n?([\\s\\S]*?)(?:\\n```|(?=\\z))|:::CTX:(.*?):(.*?):::\\n([\\s\\S]*?)\\n:::END:::")
        val matcher = pattern.matcher(text)
        var lastIndex = 0

        while (matcher.find()) {
            if (matcher.start() > lastIndex) {
                val textPart = text.substring(lastIndex, matcher.start())
                if (textPart.isNotBlank()) segments.add(MessageSegment(textPart, SegmentType.TEXT))
            }

            if (matcher.group(2) != null) {
                segments.add(MessageSegment(matcher.group(2).trim(), SegmentType.CODE))
            } else if (matcher.group(3) != null) {
                val title = matcher.group(3)
                val type = matcher.group(4)
                val content = matcher.group(5)
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

    private fun createGeneratingPlaceholder(fileName: String?): JComponent {
        val panel = JPanel(FlowLayout(FlowLayout.LEFT, 8, 4))
        panel.isOpaque = false
        panel.alignmentX = Component.LEFT_ALIGNMENT

        val label = JLabel(if (fileName != null) "Generating changes for $fileName..." else "Generating changes...", AllIcons.Process.Step_1, SwingConstants.LEFT)
        label.font = JBUI.Fonts.smallFont().deriveFont(Font.ITALIC)
        label.foreground = JBColor.GRAY

        panel.add(label)
        panel.border = JBUI.Borders.empty(4, 0)

        return panel
    }

    private fun createContextPanel(title: String, type: String, content: String): JComponent {
        val icon = when (type) {
            "commit" -> AllIcons.Vcs.CommitNode
            "structure" -> AllIcons.Actions.ListFiles
            else -> AllIcons.FileTypes.Text
        }

        val displayTitle = if (title.length > 40) title.take(37) + "..." else title

        val chip = createGenericChip(displayTitle, icon, {}, {
            showContentDialog(title, content)
        }, false)

        chip.alignmentX = Component.LEFT_ALIGNMENT
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

    fun createGenericChip(text: String, icon: Icon, onClose: () -> Unit, onClick: (() -> Unit)? = null, isRemovable: Boolean = true, additionalAction: JComponent? = null): JPanel {
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

        val rightPanel = JPanel(FlowLayout(FlowLayout.RIGHT, 2, 0))
        rightPanel.isOpaque = false

        if (additionalAction != null) {
             rightPanel.add(additionalAction)
        }

        if (isRemovable) {
            val closeBtn = JButton(AllIcons.Actions.Close)
            closeBtn.isBorderPainted = false
            closeBtn.isContentAreaFilled = false
            closeBtn.preferredSize = Dimension(16, 16)
            closeBtn.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            closeBtn.addActionListener { onClose() }
            rightPanel.add(closeBtn)
        }

        if (additionalAction != null || isRemovable) {
            bg.add(rightPanel, BorderLayout.EAST)
        }

        chip.add(bg, BorderLayout.CENTER)
        return chip
    }

    fun createAttachmentChip(file: File, params: String? = null, onClose: () -> Unit, isRemovable: Boolean = true): JPanel {
        val icon = if (file.isDirectory) AllIcons.Nodes.Folder else AllIcons.FileTypes.Any_type

        val infoIcon = if (!params.isNullOrBlank()) {
            val label = JLabel(AllIcons.General.Information)
            label.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            label.toolTipText = "View Filters"
            label.addMouseListener(object : MouseAdapter() {
                override fun mouseClicked(e: MouseEvent) {
                    showParamsPopup(label, params)
                }
            })
            label
        } else null

        return createGenericChip(file.name, icon, onClose, null, isRemovable, infoIcon)
    }

    private fun showParamsPopup(target: JComponent, params: String) {
        val parts = params.split(" ").map { it.split("=", limit = 2) }
        val sb = StringBuilder("<html><body><b>Applied Filters:</b><ul>")
        parts.forEach { part ->
            if (part.size == 2) {
                val rawKey = part[0].removePrefix("ignore_")
                val key = rawKey.replaceFirstChar { if (it.isLowerCase()) it.titlecase(Locale.getDefault()) else it.toString() }
                val value = part[1]
                sb.append("<li><b>$key:</b> $value</li>")
            } else {
                sb.append("<li>${part[0]}</li>")
            }
        }
        sb.append("</ul></body></html>")

        JBPopupFactory.getInstance()
            .createHtmlTextBalloonBuilder(sb.toString(), MessageType.INFO, null)
            .setFadeoutTime(5000)
            .createBalloon()
            .show(com.intellij.ui.awt.RelativePoint.getCenterOf(target), Balloon.Position.below)
    }

    fun createChangeWidget(project: Project, changes: List<FileChange>, onDelete: () -> Unit): JPanel {
        val undoCache = mutableMapOf<String, String>()
        val appliedStatus = mutableSetOf<String>()

        val wrapper = JPanel(BorderLayout())
        wrapper.isOpaque = false
        wrapper.border = JBUI.Borders.empty(2, 38, 2, 10)

        fun rebuild() {
            wrapper.removeAll()

            val container = RoundedChangeWidgetPanel()
            container.layout = BoxLayout(container, BoxLayout.Y_AXIS)
            container.border = JBUI.Borders.empty(6, 10)
            container.alignmentX = Component.LEFT_ALIGNMENT

            changes.forEachIndexed { index, change ->
                val isApplied = appliedStatus.contains(change.path)

                val row = JPanel(BorderLayout())
                row.isOpaque = false
                row.maximumSize = Dimension(Int.MAX_VALUE, 24)

                val leftPanel = JPanel(FlowLayout(FlowLayout.LEFT, 6, 0))
                leftPanel.isOpaque = false
                leftPanel.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
                leftPanel.toolTipText = "Click to view diff"

                leftPanel.addMouseListener(object : MouseAdapter() {
                    override fun mouseClicked(e: MouseEvent) {
                         if (SwingUtilities.isLeftMouseButton(e)) {
                             DiffUtils.showDiff(project, change.path, change.content)
                         }
                    }
                })

                val fileName = change.path.substringAfterLast("/")
                val icon = if (File(change.path).isDirectory) AllIcons.Nodes.Folder else AllIcons.FileTypes.Any_type

                leftPanel.add(JLabel(icon))

                val nameLabel = JLabel(fileName)
                nameLabel.font = JBUI.Fonts.label().deriveFont(Font.PLAIN)
                leftPanel.add(nameLabel)

                if (isApplied) {
                    leftPanel.add(JLabel(AllIcons.Actions.Checked))
                }

                val rightPanel = JPanel(FlowLayout(FlowLayout.RIGHT, 8, 0))
                rightPanel.isOpaque = false

                val actionLabel = JLabel(if (isApplied) "Undo" else "Apply")
                actionLabel.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
                actionLabel.foreground = if (isApplied) JBColor.GRAY else JBColor.BLUE
                actionLabel.font = JBUI.Fonts.smallFont()

                actionLabel.addMouseListener(object : MouseAdapter() {
                    override fun mouseClicked(e: MouseEvent) {
                        if (SwingUtilities.isLeftMouseButton(e)) {
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
                            rebuild()
                        }
                    }
                })
                rightPanel.add(actionLabel)

                if (changes.size == 1) {
                    val dismissIcon = JLabel(AllIcons.Actions.Close)
                    dismissIcon.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
                    dismissIcon.toolTipText = "Dismiss"
                    dismissIcon.border = JBUI.Borders.emptyLeft(6)
                    dismissIcon.addMouseListener(object : MouseAdapter() {
                        override fun mouseClicked(e: MouseEvent) { onDelete() }
                    })
                    rightPanel.add(dismissIcon)
                }

                row.add(leftPanel, BorderLayout.CENTER)
                row.add(rightPanel, BorderLayout.EAST)

                container.add(row)

                if (index < changes.size - 1) {
                    container.add(Box.createVerticalStrut(4))
                }
            }

            if (changes.size > 1) {
                container.add(Box.createVerticalStrut(8))
                val footer = JPanel(BorderLayout())
                footer.isOpaque = false

                val actionsPanel = JPanel(FlowLayout(FlowLayout.LEFT, 0, 0))
                actionsPanel.isOpaque = false

                fun createLinkBtn(text: String, action: () -> Unit, color: Color? = null): JLabel {
                     val btn = JLabel(text)
                     btn.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
                     btn.font = JBUI.Fonts.smallFont()
                     if (color != null) btn.foreground = color
                     btn.border = JBUI.Borders.emptyRight(12)
                     btn.addMouseListener(object : MouseAdapter() {
                         override fun mouseClicked(e: MouseEvent) { action() }
                     })
                     return btn
                }

                val applyAllBtn = createLinkBtn("Apply All", {
                    changes.forEach { change ->
                        if (!appliedStatus.contains(change.path)) {
                            val previous = DiffUtils.applyChangeDirectly(project, change.path, change.content)
                            if (previous != null) undoCache[change.path] = previous
                            appliedStatus.add(change.path)
                        }
                    }
                    rebuild()
                }, JBColor.BLUE)
                actionsPanel.add(applyAllBtn)

                val undoAllBtn = createLinkBtn("Undo All", {
                    changes.forEach { change ->
                        if (appliedStatus.contains(change.path)) {
                            val backup = undoCache[change.path]
                            if (backup != null) {
                                DiffUtils.applyChangeDirectly(project, change.path, backup)
                                appliedStatus.remove(change.path)
                            }
                        }
                    }
                    rebuild()
                }, JBColor.GRAY)
                actionsPanel.add(undoAllBtn)

                footer.add(actionsPanel, BorderLayout.WEST)

                val dismissBtn = JLabel("Dismiss")
                dismissBtn.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
                dismissBtn.font = JBUI.Fonts.smallFont()
                dismissBtn.foreground = JBColor.RED.darker()
                dismissBtn.addMouseListener(object : MouseAdapter() {
                    override fun mouseClicked(e: MouseEvent) { onDelete() }
                })

                footer.add(dismissBtn, BorderLayout.EAST)

                container.add(footer)
            }

            wrapper.add(container, BorderLayout.CENTER)
            wrapper.revalidate()
            wrapper.repaint()
        }

        rebuild()
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
                g2.color = JBColor(Color(255, 255, 255), Color(40, 42, 44))
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
