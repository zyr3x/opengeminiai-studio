package com.opengeminiai.studio.client.utils

import org.commonmark.parser.Parser
import org.commonmark.renderer.html.HtmlRenderer
import com.intellij.util.ui.UIUtil
import java.awt.Color

object MarkdownUtils {
    private val parser = Parser.builder().build()
    private val renderer = HtmlRenderer.builder().build()

    fun renderHtml(markdown: String): String {
        val isDark = UIUtil.isUnderDarcula()

        // Цвета
        val textColor = if (isDark) "#BBBBBB" else "#222222"
        val linkColor = if (isDark) "#589DF6" else "#285CC4"
        val codeBg = if (isDark) "#3C3F41" else "#F0F0F0"

        // ВАЖНО: Мы убрали явную установку font-family и font-size в CSS для body.
        // JEditorPane с флагом HONOR_DISPLAY_PROPERTIES (установленным в ChatComponents)
        // сам использует шрифт компонента. Это предотвращает NPE в CSS-парсере Swing,
        // который может падать на некоторых системных именах шрифтов.

        val document = parser.parse(markdown)
        val htmlBody = renderer.render(document)

        return """
        <html>
        <head>
            <style>
                body {
                    color: $textColor;
                    margin: 0;
                    overflow-wrap: break-word; /* Добавлено: перенос длинных слов */
                }
                pre {
                    background-color: $codeBg;
                    padding: 8px;
                    margin-top: 6px;
                    margin-bottom: 6px;
                }
                code {
                    font-family: monospace;
                    background-color: $codeBg;
                }
                p { margin-top: 0; margin-bottom: 6px; }
                h1 { font-size: 1.2em; font-weight: bold; color: $textColor; margin-top: 8px; margin-bottom: 4px; }
                h2 { font-size: 1.1em; font-weight: bold; color: $textColor; margin-top: 6px; margin-bottom: 4px; }
                h3 { font-size: 1.0em; font-weight: bold; margin-top: 6px; margin-bottom: 2px; }
                a { color: $linkColor; text-decoration: none; }
                ul { margin-top: 0; margin-bottom: 6px; margin-left: 15px; padding-left: 0; }
                li { margin-top: 2px; }
            </style>
        </head>
        <body>
            $htmlBody
        </body>
        </html>
        """.trimIndent()
    }
}
