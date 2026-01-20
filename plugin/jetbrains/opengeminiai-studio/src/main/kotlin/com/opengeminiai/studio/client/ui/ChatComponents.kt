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

    fun createMessageBubble(role: String, content: String, messageIndex: Int? = null, onDelete: ((Int) -> Unit)? = null, onRegenerate: ((Int) -> Unit)? = null): JPanel {
        val isUser = role == "user"
        val wrapper = JPanel(BorderLayout())
        wrapper.isOpaque = false
        wrapper.border = JBUI.Borders.empty(6, 12, 6, 12)
        // Tag the wrapper for easy identification during streaming updates
        wrapper.putClientProperty("isBubble", true)

        val bubble = RoundedPanel(isUser)
        bubble.layout = BorderLayout()
        // Internal padding for the bubble
        bubble.border = JBUI.Borders.empty(10, 12, 6, 12)

        // 1. Content Panel (Top/Center)
        val contentPanel = JPanel()
        contentPanel.layout = BoxLayout(contentPanel, BoxLayout.Y_AXIS)
        contentPanel.isOpaque = false
        contentPanel.putClientProperty("isContentPanel", true)

        // --- Content Parsing Logic ---
        val textContentBuilder = StringBuilder()
        val attachedFilesForDisplay = mutableListOf<AttachedFile>()

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

        populateBubbleContent(contentPanel, actualTextContent)

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
            contentPanel.add(attachmentsPanel)
        }

        bubble.add(contentPanel, BorderLayout.CENTER)

        // 2. Footer Status Bar (Bottom)
        val footerPanel = JPanel(BorderLayout())
        footerPanel.isOpaque = false
        
        // Create a separator color that matches the bubble border
        val separatorColor = if (isUser) {
            JBColor(Color(200, 210, 240), Color(85, 65, 105))
        } else {
            // Styled gray color for assistant separator to match user bubble style
            JBColor(Color(230, 230, 230), Color(60, 63, 65))
        }

        // Add visual separator between content and footer
        footerPanel.border = JBUI.Borders.compound(
            JBUI.Borders.emptyTop(6),
            JBUI.Borders.compound(
                JBUI.Borders.customLine(separatorColor, 1, 0, 0, 0),
                JBUI.Borders.emptyTop(6)
            )
        )

        // Left Side: Avatar
        val avatarIcon = if (isUser) AllIcons.General.User else Icons.Logo
        val avatarLabel = JLabel(avatarIcon)
        avatarLabel.toolTipText = if (isUser) "User" else "Gemini AI"
        footerPanel.add(avatarLabel, BorderLayout.WEST)

        // Right Side: Actions
        val actionsPanel = JPanel(FlowLayout(FlowLayout.RIGHT, 4, 0))
        actionsPanel.isOpaque = false

        // Regenerate Button (Only for Assistant)
        if (!isUser && messageIndex != null && onRegenerate != null) {
            val regenBtn = createActionButton(AllIcons.Actions.Refresh, "Regenerate Response") {
                onRegenerate(messageIndex)
            }
            actionsPanel.add(regenBtn)
        }

        // Copy Button
        val copyBtn = createActionButton(AllIcons.Actions.Copy, "Copy raw content") {
            val selection = StringSelection(content)
            Toolkit.getDefaultToolkit().systemClipboard.setContents(selection, null)
        }
        actionsPanel.add(copyBtn)

        // Delete Button
        if (messageIndex != null && onDelete != null) {
            val deleteBtn = createActionButton(AllIcons.Actions.GC, "Delete Message") {
                onDelete(messageIndex)
            }
            deleteBtn.addMouseListener(object : MouseAdapter() {
                 override fun mouseEntered(e: MouseEvent) { deleteBtn.icon = AllIcons.Actions.Cancel }
                 override fun mouseExited(e: MouseEvent) { deleteBtn.icon = AllIcons.Actions.GC }
            })
            actionsPanel.add(deleteBtn)
        }

        footerPanel.add(actionsPanel, BorderLayout.EAST)
        bubble.add(footerPanel, BorderLayout.SOUTH)

        // Layout Wrapper
        val box = Box.createHorizontalBox()
        if (isUser) {
            box.add(Box.createHorizontalGlue())
            box.add(bubble)
        } else {
            box.add(bubble)
            box.add(Box.createHorizontalGlue())
        }

        wrapper.add(box, BorderLayout.CENTER)
        return wrapper
    }

    private fun createActionButton(icon: Icon, tooltip: String, action: () -> Unit): JLabel {
        val btn = JLabel(icon)
        btn.toolTipText = tooltip
        btn.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
        btn.border = JBUI.Borders.empty(2)
        btn.addMouseListener(object : MouseAdapter() {
            override fun mouseClicked(e: MouseEvent) {
                if (SwingUtilities.isLeftMouseButton(e)) action()
            }
        })
        return btn
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
        // Find the content panel specifically by the client property we set
        val contentPanel = bubble?.components?.find { (it as? JComponent)?.getClientProperty("isContentPanel") == true } as? JPanel

        if (contentPanel != null) {
            contentPanel.removeAll()
            populateBubbleContent(contentPanel, content)
            contentPanel.revalidate()
            contentPanel.repaint()
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
                        // Updated to pass language
                        panel.add(createCodePanel(segment.content, segment.language))
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
    // Added language field
    private data class MessageSegment(val content: String, val type: SegmentType, val title: String? = null, val contentType: String? = null, val language: String? = null)

    private fun parseSegments(text: String): List<MessageSegment> {
        val segments = mutableListOf<MessageSegment>()

        // Updated regex to require newline before closing backticks (\n```)
        // This prevents the parser from breaking when the code content itself contains inline triple backticks
        val pattern = Pattern.compile("```(\\w*)\n?([\\s\\S]*?)(?:\n```|(?=\\z))|:::CTX:(.*?):(.*?):::\n([\\s\\S]*?)\n:::END:::")
        val matcher = pattern.matcher(text)
        var lastIndex = 0

        while (matcher.find()) {
            if (matcher.start() > lastIndex) {
                val textPart = text.substring(lastIndex, matcher.start())
                if (textPart.isNotBlank()) segments.add(MessageSegment(textPart, SegmentType.TEXT))
            }

            if (matcher.group(2) != null) {
                val lang = matcher.group(1)?.takeIf { it.isNotBlank() }
                segments.add(MessageSegment(matcher.group(2).trim(), SegmentType.CODE, language = lang))
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

    private fun createCodePanel(code: String, language: String? = null): JComponent {
        val outerPanel = JPanel(BorderLayout())
        // Border for the whole block
        val borderColor = if (UIUtil.isUnderDarcula()) Color(50, 50, 50) else Color(200, 200, 200)
        outerPanel.border = JBUI.Borders.customLine(borderColor)
        outerPanel.alignmentX = Component.LEFT_ALIGNMENT

        // --- Header ---
        val header = JPanel(BorderLayout())
        val headerBg = if (UIUtil.isUnderDarcula()) Color(45, 47, 49) else Color(225, 227, 229)
        header.background = headerBg
        header.border = JBUI.Borders.empty(4, 8)

        val langText = if (!language.isNullOrBlank()) language.uppercase() else "CODE"
        val langLabel = JLabel(langText)
        langLabel.font = JBUI.Fonts.smallFont().deriveFont(Font.BOLD)
        langLabel.foreground = JBColor.GRAY
        header.add(langLabel, BorderLayout.WEST)

        val copyBtn = JLabel(AllIcons.Actions.Copy)
        copyBtn.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
        copyBtn.toolTipText = "Copy content"
        copyBtn.addMouseListener(object : MouseAdapter() {
            override fun mouseClicked(e: MouseEvent) {
                if (SwingUtilities.isLeftMouseButton(e)) {
                    try {
                        val selection = StringSelection(code)
                        Toolkit.getDefaultToolkit().systemClipboard.setContents(selection, null)
                        
                        // Feedback
                        val originalIcon = copyBtn.icon
                        copyBtn.icon = AllIcons.Actions.Checked
                        val timer = Timer(1500) { copyBtn.icon = originalIcon }
                        timer.isRepeats = false
                        timer.start()
                    } catch (ex: Exception) {}
                }
            }
        })
        header.add(copyBtn, BorderLayout.EAST)
        outerPanel.add(header, BorderLayout.NORTH)

        // --- Code Area ---
        val textArea = JTextArea(code)
        textArea.font = JBUI.Fonts.create("JetBrains Mono", 12)
        textArea.isEditable = false
        val codeBg = if (UIUtil.isUnderDarcula()) Color(30, 31, 33) else Color(242, 244, 245)
        textArea.background = codeBg
        textArea.foreground = if (UIUtil.isUnderDarcula()) Color(169, 183, 198) else Color(8, 8, 8)
        textArea.margin = JBUI.insets(8)

        val scroll = JBScrollPane(textArea)
        scroll.border = null
        scroll.viewportBorder = null

        val metrics = textArea.getFontMetrics(textArea.font)
        val lineHeight = metrics.height
        val lines = code.lines().size
        val maxCodeHeight = 300
        val codeHeight = min(maxCodeHeight, (lines * lineHeight) + 24)

        scroll.preferredSize = Dimension(-1, codeHeight)
        
        outerPanel.add(scroll, BorderLayout.CENTER)
        
        // Set layout sizes for the wrapper
        val headerHeight = 28 // Approximate
        outerPanel.preferredSize = Dimension(-1, codeHeight + headerHeight)
        outerPanel.maximumSize = Dimension(Int.MAX_VALUE, codeHeight + headerHeight)

        return outerPanel
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

    fun <T : Component> findChildComponentRecursive(parent: Container, clazz: Class<T>): T? {
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
        // FIX: Adjusted right padding (12) to match left
        wrapper.border = JBUI.Borders.empty(4, 12, 4, 12)

        fun rebuild() {
            wrapper.removeAll()

            val container = RoundedChangeWidgetPanel()
            container.layout = BoxLayout(container, BoxLayout.Y_AXIS)
            // FIX: Padding 12 to match chat bubble padding (Aligns icons vertically)
            container.border = JBUI.Borders.empty(6, 12)
            container.alignmentX = Component.LEFT_ALIGNMENT

            changes.forEachIndexed { index, change ->
                val isApplied = appliedStatus.contains(change.path)

                val row = JPanel(BorderLayout())
                row.isOpaque = false
                row.maximumSize = Dimension(Int.MAX_VALUE, 24)

                // FIX: Gap 0 (handled by struts) to align perfectly with left border
                val leftPanel = JPanel(FlowLayout(FlowLayout.LEFT, 0, 0))
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
                leftPanel.add(Box.createHorizontalStrut(8))

                val nameLabel = JLabel(fileName)
                nameLabel.font = JBUI.Fonts.label().deriveFont(Font.PLAIN)
                leftPanel.add(nameLabel)

                if (isApplied) {
                    leftPanel.add(Box.createHorizontalStrut(8))
                    leftPanel.add(JLabel(AllIcons.Actions.Checked))
                }

                // FIX: Gap 0
                val rightPanel = JPanel(FlowLayout(FlowLayout.RIGHT, 0, 0))
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
                    rightPanel.add(Box.createHorizontalStrut(8))
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

                // FIX: Gap 0 to align with file rows
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

                // FIX: Gap 0
                val dismissPanel = JPanel(FlowLayout(FlowLayout.RIGHT, 0, 0))
                dismissPanel.isOpaque = false

                val dismissBtn = JLabel("Dismiss")
                dismissBtn.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
                dismissBtn.font = JBUI.Fonts.smallFont()
                dismissBtn.foreground = JBColor.RED.darker()
                dismissBtn.addMouseListener(object : MouseAdapter() {
                    override fun mouseClicked(e: MouseEvent) { onDelete() }
                })
                dismissPanel.add(dismissBtn)

                footer.add(dismissPanel, BorderLayout.EAST)

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
            g2.color = if(isUser) JBColor(Color(200, 210, 240), Color(85, 65, 105)) else JBColor(Color(230, 230, 230), Color(60, 63, 65))
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
