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
import javax.swing.*

object ChatComponents {

    fun createMessageBubble(role: String, content: String): JPanel {
        val isUser = role == "user"

        // Outer wrapper for alignment
        val wrapper = JPanel(BorderLayout())
        wrapper.isOpaque = false
        // Compact margin between messages
        wrapper.border = JBUI.Borders.empty(2, 5)

        // The Bubble Background
        val bubble = RoundedPanel(isUser)
        bubble.layout = BorderLayout()
        // Compact padding inside bubble (adjusted for native look)
        bubble.border = JBUI.Borders.empty(6, 9)

        // Header
        val headerText = if (isUser) "You" else "OpenGeminiAI Studio"
        val headerLabel = JBLabel(headerText)
        // Use standard label font for header, maybe bold
        headerLabel.font = JBUI.Fonts.smallFont().deriveFont(Font.BOLD)

        // Subtle header color
        headerLabel.foreground = if (isUser) JBColor(Color(230, 230, 230), Color(230, 230, 230)) else JBColor.GRAY
        headerLabel.border = JBUI.Borders.emptyBottom(3)

        val editorPane = JEditorPane()
        editorPane.contentType = "text/html"
        // Ensure the Swing component itself has the correct native font set
        editorPane.font = JBUI.Fonts.smallFont()
        editorPane.text = MarkdownUtils.renderHtml(content)
        editorPane.isEditable = false
        editorPane.isOpaque = false
        // Key property to respect system fonts
        editorPane.putClientProperty(JEditorPane.HONOR_DISPLAY_PROPERTIES, true)
        editorPane.addHyperlinkListener { e ->
            if (e.eventType == javax.swing.event.HyperlinkEvent.EventType.ACTIVATED) {
                try { Desktop.getDesktop().browse(e.url.toURI()) } catch (err: Exception) {}
            }
        }

        bubble.add(headerLabel, BorderLayout.NORTH)
        bubble.add(editorPane, BorderLayout.CENTER)

        // Layout: Left or Right
        val box = Box.createHorizontalBox()
        if (isUser) {
            box.add(Box.createHorizontalGlue())
            box.add(bubble)
        } else {
            box.add(bubble)
            box.add(Box.createHorizontalGlue())
        }

        // Allow width to stretch
        bubble.maximumSize = Dimension(Int.MAX_VALUE, Int.MAX_VALUE)

        wrapper.add(box, BorderLayout.CENTER)
        return wrapper
    }

    fun createChangeWidget(project: Project, changes: List<FileChange>): JPanel {
        val wrapper = JPanel(BorderLayout())
        wrapper.isOpaque = false
        wrapper.border = JBUI.Borders.empty(2, 5)

        val container = JPanel(BorderLayout())
        // Darker/Lighter background for widget
        container.background = JBColor(Color(245, 245, 245), Color(40, 42, 44))
        container.border = BorderFactory.createLineBorder(JBColor.border(), 1, true)

        // Widget Header
        val header = JPanel(BorderLayout())
        header.isOpaque = false
        header.border = JBUI.Borders.empty(5, 8)

        val title = JBLabel("${changes.size} files updated", AllIcons.Actions.Checked, SwingConstants.LEFT)
        title.font = JBUI.Fonts.smallFont().deriveFont(Font.BOLD) // Consistent native font
        header.add(title, BorderLayout.WEST)

        // Global Apply
        val applyAllBtn = JButton("Apply All").apply {
            isBorderPainted = false
            isContentAreaFilled = false
            cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            font = JBUI.Fonts.smallFont() // Consistent native font
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

        // File Rows
        val fileList = Box.createVerticalBox()
        changes.forEach { change ->
            val row = JPanel(BorderLayout())
            row.isOpaque = false
            row.border = JBUI.Borders.empty(2, 8)
            row.maximumSize = Dimension(Int.MAX_VALUE, 28)

            val filename = change.path.substringAfterLast("/")
            val link = JLabel(filename, AllIcons.FileTypes.Any_type, SwingConstants.LEFT)
            link.font = JBUI.Fonts.smallFont() // Consistent native font
            link.foreground = JBColor.BLUE
            link.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            link.addMouseListener(object: MouseAdapter() {
                override fun mouseClicked(e: MouseEvent) {
                    DiffUtils.showDiff(project, change.path, change.content)
                }
            })

            // Actions
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
                // Subtle blue/green for user
                g2.color = JBColor(Color(225, 245, 254), Color(45, 55, 65))
            } else {
                // Standard panel bg or slightly distinct
                g2.color = JBColor(Color(255, 255, 255), Color(60, 63, 65))
            }
            g2.fillRoundRect(0, 0, width-1, height-1, 10, 10)

            g2.color = JBColor.border()
            g2.drawRoundRect(0, 0, width-1, height-1, 10, 10)
            super.paintComponent(g)
        }
    }
}