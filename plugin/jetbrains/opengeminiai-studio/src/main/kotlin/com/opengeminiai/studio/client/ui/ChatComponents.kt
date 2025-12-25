package com.opengeminiai.studio.client.ui

import com.opengeminiai.studio.client.model.FileChange
import com.opengeminiai.studio.client.utils.DiffUtils
import com.opengeminiai.studio.client.utils.MarkdownUtils
import com.opengeminiai.studio.client.Icons
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

        // Markdown Text
        if (actualTextContent.isNotBlank()) {
            val editorPane = JEditorPane()
            editorPane.contentType = "text/html"
            editorPane.text = MarkdownUtils.renderHtml(actualTextContent)
            editorPane.isEditable = false
            editorPane.isOpaque = false
            editorPane.putClientProperty(JEditorPane.HONOR_DISPLAY_PROPERTIES, true)
            // Fix: Text color handling is done in MarkdownUtils, but we ensure component is transparent
            editorPane.addHyperlinkListener { e ->
                if (e.eventType == javax.swing.event.HyperlinkEvent.EventType.ACTIVATED) {
                    try { Desktop.getDesktop().browse(e.url.toURI()) } catch (err: Exception) {}
                }
            }
            bubble.add(editorPane)
        }

        // Attachments
        if (attachedFilesForDisplay.isNotEmpty()) {
            val attachmentsPanel = JPanel(FlowLayout(FlowLayout.LEFT, 4, 4))
            attachmentsPanel.isOpaque = false
            if (actualTextContent.isNotBlank()) attachmentsPanel.border = JBUI.Borders.emptyTop(5)
            attachedFilesForDisplay.forEach { file ->
                attachmentsPanel.add(createAttachmentChip(file, {}, false))
            }
            bubble.add(attachmentsPanel)
        }

        // --- DELETE BUTTON ---
        // Visible small trash icon
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
            // User Layout: [Glue] [Delete] [Bubble] [Avatar]
            box.add(Box.createHorizontalGlue())
            box.add(deleteBtn)
            box.add(bubble)
            box.add(avatarLabel)
        } else {
            // AI Layout: [Avatar] [Bubble] [Delete] [Glue]
            box.add(avatarLabel)
            box.add(bubble)
            box.add(deleteBtn)
            box.add(Box.createHorizontalGlue())
        }

        wrapper.add(box, BorderLayout.CENTER)
        return wrapper
    }

    // --- UTILS ---

    fun createAttachmentChip(file: File, onClose: () -> Unit, isRemovable: Boolean = true): JPanel {
        val chip = JPanel(BorderLayout())
        chip.isOpaque = false

        val bg = object : JPanel(BorderLayout()) {
            override fun paintComponent(g: Graphics) {
                val g2 = g as Graphics2D
                g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
                g2.color = JBColor(Color(230, 230, 230), Color(60, 63, 65))
                g2.fillRoundRect(0, 0, width - 1, height - 1, 8, 8) // Slightly sharper corners
                g2.color = JBColor.border()
                g2.drawRoundRect(0, 0, width - 1, height - 1, 8, 8)
                super.paintComponent(g)
            }
        }
        bg.isOpaque = false
        bg.border = JBUI.Borders.empty(2, 6, 2, 4)

        val icon = if (file.isDirectory) AllIcons.Nodes.Folder else AllIcons.FileTypes.Any_type
        val label = JBLabel(file.name, icon, SwingConstants.LEFT)
        label.font = JBUI.Fonts.smallFont()
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

    fun createChangeWidget(project: Project, changes: List<FileChange>): JPanel {
        // Keeping previous widget logic, just wrapping for safety
        val wrapper = JPanel(BorderLayout())
        wrapper.isOpaque = false
        wrapper.border = JBUI.Borders.empty(2, 38, 2, 5) // Indent to align with text bubbles

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
            val btnOk = JButton(AllIcons.Actions.Checked).apply {
                preferredSize = Dimension(20, 20); isBorderPainted=false; isContentAreaFilled=false; addActionListener { DiffUtils.applyChangeDirectly(project, change.path, change.content) }
            }
            actions.add(btnOk)

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

            // --- COLOR CUSTOMIZATION ---
            if (isUser) {
                // Purple tint for User
                // Light Mode: Very light purple/blue | Dark Mode: Muted Purple
                val lightColor = Color(235, 240, 255)
                val darkColor = Color(70, 50, 90) // Muted purple for dark mode
                g2.color = JBColor(lightColor, darkColor)
            } else {
                // Standard Gray for Assistant
                g2.color = JBColor(Color(255, 255, 255), Color(60, 63, 65))
            }

            g2.fillRoundRect(0, 0, width - 1, height - 1, 16, 16) // More rounded (16px)

            // Subtle Border
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