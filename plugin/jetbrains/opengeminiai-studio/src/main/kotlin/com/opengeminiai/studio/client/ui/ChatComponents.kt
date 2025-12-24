package com.opengeminiai.studio.client.ui

import com.opengeminiai.studio.client.model.FileChange
import com.opengeminiai.studio.client.utils.DiffUtils
import com.opengeminiai.studio.client.utils.MarkdownUtils
import com.intellij.openapi.project.Project
import com.intellij.ui.JBColor
import com.intellij.ui.components.JBLabel
import com.intellij.util.ui.JBUI
import com.intellij.icons.AllIcons
import java.awt.*
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent
import java.io.File
import javax.swing.*

object ChatComponents {

    fun createMessageBubble(role: String, content: String): JPanel {
        val isUser = role == "user"

        // Outer wrapper for alignment
        val wrapper = JPanel(BorderLayout())
        wrapper.isOpaque = false
        wrapper.border = JBUI.Borders.empty(2, 5)

        // The Bubble Background
        val bubble = RoundedPanel(isUser)
        bubble.layout = BoxLayout(bubble, BoxLayout.Y_AXIS) // Changed to Y_AXIS to stack header, text, and attachments
        // Compact padding inside bubble (adjusted for native look)
        bubble.border = JBUI.Borders.empty(6, 9)

        // Header
        val headerPanel = JPanel(BorderLayout())
        headerPanel.isOpaque = false
        headerPanel.border = JBUI.Borders.emptyBottom(3)

        val headerText = if (isUser) "You" else "OpenGeminiAI Studio"
        val headerLabel = JBLabel(headerText)
        headerLabel.font = JBUI.Fonts.smallFont().deriveFont(Font.BOLD)
        headerLabel.foreground = if (isUser) JBColor(Color(230, 230, 230), Color(230, 230, 230)) else JBColor.GRAY

        if (isUser) {
            headerPanel.add(headerLabel, BorderLayout.EAST)
        } else {
            headerPanel.add(headerLabel, BorderLayout.WEST)
        }
        bubble.add(headerPanel)

        // --- NEW: Parse content for attachments and text ---
        val textContentBuilder = StringBuilder()
        val attachedFilesForDisplay = mutableListOf<File>()
        val lines = content.lines()

        for (line in lines) {
            val trimmedLine = line.trim()
            if (trimmedLine.startsWith("image_path=")) {
                val path = trimmedLine.substringAfter("image_path=")
                attachedFilesForDisplay.add(File(path))
            } else if (trimmedLine.startsWith("code_path=")) {
                val path = trimmedLine.substringAfter("code_path=")
                attachedFilesForDisplay.add(File(path))
            } else {
                textContentBuilder.append(line).append("\n") // Keep original line breaks for markdown
            }
        }

        val actualTextContent = textContentBuilder.toString().trim()

        // Editor pane for Markdown text
        if (actualTextContent.isNotBlank()) {
            val editorPane = JEditorPane()
            editorPane.contentType = "text/html"
            editorPane.font = JBUI.Fonts.smallFont()
            editorPane.text = MarkdownUtils.renderHtml(actualTextContent)
            editorPane.isEditable = false
            editorPane.isOpaque = false
            editorPane.putClientProperty(JEditorPane.HONOR_DISPLAY_PROPERTIES, true)
            editorPane.addHyperlinkListener { e ->
                if (e.eventType == javax.swing.event.HyperlinkEvent.EventType.ACTIVATED) {
                    try { Desktop.getDesktop().browse(e.url.toURI()) } catch (err: Exception) {}
                }
            }
            bubble.add(editorPane)
        }

        // Panel to display attachment chips
        if (attachedFilesForDisplay.isNotEmpty()) {
            val displayAttachmentsPanel = JPanel(FlowLayout(FlowLayout.LEFT, 4, 4))
            displayAttachmentsPanel.isOpaque = false
            // Add padding above chips only if there was text content too
            if (actualTextContent.isNotBlank()) {
                 displayAttachmentsPanel.border = JBUI.Borders.empty(4, 0, 0, 0)
            }

            // Add attachment chips (not removable in display)
            attachedFilesForDisplay.forEach { file ->
                val chip = ChatComponents.createAttachmentChip(file, {}, isRemovable = false)
                displayAttachmentsPanel.add(chip)
            }
            bubble.add(displayAttachmentsPanel)
        }
        // --- END NEW ---

        val box = Box.createHorizontalBox()
        if (isUser) {
            box.add(Box.createHorizontalGlue())
            box.add(bubble)
        } else {
            box.add(bubble)
            box.add(Box.createHorizontalGlue())
        }

        bubble.maximumSize = Dimension(Int.MAX_VALUE, Int.MAX_VALUE)

        wrapper.add(box, BorderLayout.CENTER)
        return wrapper
    }

    // --- NEW: Attachment Chip UI ---
    fun createAttachmentChip(file: File, onClose: () -> Unit, isRemovable: Boolean = true): JPanel {
        val chip = JPanel(BorderLayout())
        chip.isOpaque = false

        // Chip background panel
        val bg = object : JPanel(BorderLayout()) {
            override fun paintComponent(g: Graphics) {
                val g2 = g as Graphics2D
                g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
                // Darker background for chip
                g2.color = JBColor(Color(230, 230, 230), Color(60, 63, 65))
                g2.fillRoundRect(0, 0, width - 1, height - 1, 10, 10)
                g2.color = JBColor.border()
                g2.drawRoundRect(0, 0, width - 1, height - 1, 10, 10)
                super.paintComponent(g)
            }
        }
        bg.isOpaque = false
        bg.border = JBUI.Borders.empty(2, 6, 2, 4)

        // Determine icon based on folder or file
        val icon = if (file.isDirectory) AllIcons.Nodes.Folder else AllIcons.FileTypes.Any_type

        val label = JBLabel(file.name, icon, SwingConstants.LEFT)
        label.font = JBUI.Fonts.smallFont()
        bg.add(label, BorderLayout.CENTER)

        if (isRemovable) {
            val closeBtn = JButton(AllIcons.Actions.Close)
            closeBtn.isBorderPainted = false
            closeBtn.isContentAreaFilled = false
            closeBtn.isFocusPainted = false
            closeBtn.preferredSize = Dimension(16, 16)
            closeBtn.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            closeBtn.addActionListener { onClose() }

            val btnPanel = JPanel(BorderLayout())
            btnPanel.isOpaque = false
            btnPanel.border = JBUI.Borders.emptyLeft(4)
            btnPanel.add(closeBtn, BorderLayout.CENTER)

            bg.add(btnPanel, BorderLayout.EAST)
        }
        chip.add(bg, BorderLayout.CENTER)
        return chip
    }

    fun createChangeWidget(project: Project, changes: List<FileChange>): JPanel {
        val wrapper = JPanel(BorderLayout())
        wrapper.isOpaque = false
        wrapper.border = JBUI.Borders.empty(2, 5)

        val container = RoundedChangeWidgetPanel().apply { layout = BorderLayout() }

        val header = JPanel(BorderLayout())
        header.isOpaque = false
        header.border = JBUI.Borders.empty(5, 8)

        val title = JBLabel("${changes.size} files updated", AllIcons.Actions.Checked, SwingConstants.LEFT)
        title.font = JBUI.Fonts.smallFont().deriveFont(Font.BOLD)
        header.add(title, BorderLayout.WEST)

        val applyAllBtn = JButton("Apply All").apply {
            isBorderPainted = false
            isContentAreaFilled = false
            cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            font = JBUI.Fonts.smallFont()
            foreground = JBColor.BLUE
            addActionListener {
                changes.forEach { DiffUtils.applyChangeDirectly(project, it.path, it.content) }
                container.removeAll()
                val success = JLabel("  All changes applied ✅")
                success.font = JBUI.Fonts.smallFont()
                success.border = JBUI.Borders.empty(8)
                container.add(success, BorderLayout.CENTER)
                container.revalidate()
                container.repaint()
            }
        }
        header.add(applyAllBtn, BorderLayout.EAST)
        container.add(header, BorderLayout.NORTH)

        val fileList = Box.createVerticalBox()
        changes.forEach { change ->
            val row = JPanel(BorderLayout())
            row.isOpaque = false
            row.border = JBUI.Borders.empty(2, 8)
            row.maximumSize = Dimension(Int.MAX_VALUE, 28)

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

            val btnOk = createIconBtn(AllIcons.Actions.Checked, "Apply") {
                DiffUtils.applyChangeDirectly(project, change.path, change.content)
                row.removeAll()
                val lbl = JLabel("$filename (Applied)", AllIcons.Actions.Checked, SwingConstants.LEFT)
                lbl.font = JBUI.Fonts.smallFont()
                lbl.foreground = JBColor.GRAY
                row.add(lbl, BorderLayout.CENTER)
                row.revalidate()
            }
            val btnNo = createIconBtn(AllIcons.Actions.Cancel, "Discard") {
                row.removeAll()
                val lbl = JLabel("$filename (Discarded)", AllIcons.Actions.Cancel, SwingConstants.LEFT)
                lbl.font = JBUI.Fonts.smallFont()
                lbl.foreground = JBColor.GRAY
                row.add(lbl, BorderLayout.CENTER)
                row.revalidate()
            }

            actions.add(btnOk)
            actions.add(Box.createHorizontalStrut(2))
            actions.add(btnNo)

            row.add(link, BorderLayout.CENTER)
            row.add(actions, BorderLayout.EAST)
            fileList.add(row)
        }

        container.add(fileList, BorderLayout.CENTER)
        wrapper.add(container, BorderLayout.CENTER)
        return wrapper
    }

    private fun createIconBtn(icon: Icon, tip: String, action: () -> Unit): JButton {
        return JButton(icon).apply {
            toolTipText = tip
            preferredSize = Dimension(22, 22)
            isBorderPainted = false
            isContentAreaFilled = false
            cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            addActionListener { action() }
        }
    }

    class RoundedPanel(private val isUser: Boolean) : JPanel() {
        init { isOpaque = false }
        override fun paintComponent(g: Graphics) {
            val g2 = g as Graphics2D
            g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
            if (isUser) {
                g2.color = JBColor(Color(225, 245, 254), Color(45, 55, 65))
            } else {
                g2.color = JBColor(Color(255, 255, 255), Color(60, 63, 65))
            }
            g2.fillRoundRect(0, 0, width - 1, height - 1, 10, 10)

            g2.color = JBColor.border()
            g2.drawRoundRect(0, 0, width - 1, height - 1, 10, 10)
            super.paintComponent(g)
        }
    }

    // New class for the change widget background with rounded corners
    class RoundedChangeWidgetPanel : JPanel() {
        init {
            isOpaque = false // Paint manually
        }
        override fun paintComponent(g: Graphics) {
            val g2 = g as Graphics2D
            g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
            val cornerRadius = 10 // Consistent radius
            g2.color = JBColor(Color(245, 245, 245), Color(40, 42, 44)) // Same background as before
            g2.fillRoundRect(0, 0, width - 1, height - 1, cornerRadius, cornerRadius)
            g2.color = JBColor.border() // Same border color
            g2.drawRoundRect(0, 0, width - 1, height - 1, cornerRadius, cornerRadius)
            super.paintComponent(g) // Paint children
        }
    }
}
