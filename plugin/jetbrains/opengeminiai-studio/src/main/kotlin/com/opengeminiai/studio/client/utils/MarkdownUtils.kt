package com.opengeminiai.studio.client.utils

import org.commonmark.parser.Parser
import org.commonmark.renderer.html.HtmlRenderer
import com.intellij.util.ui.UIUtil
import com.intellij.util.ui.JBUI
import java.awt.Color

object MarkdownUtils {
    private val parser = Parser.builder().build()
    private val renderer = HtmlRenderer.builder().build()

    fun renderHtml(markdown: String): String {
        val isDark = UIUtil.isUnderDarcula()

        // Цвета
        val textColor = if (isDark) "#BBBBBB" else "#222222" // Чуть мягче белый для dark mode
        val linkColor = if (isDark) "#589DF6" else "#285CC4"
        val codeBg = if (isDark) "#3C3F41" else "#F0F0F0" // Более нативный цвет фона кода

        // НАТИВНЫЙ ШРИФТ:
        // Берем системный "маленький" шрифт IDE (как в подсказках или дереве файлов)
        val font = JBUI.Fonts.smallFont()
        val fontFamily = font.family
        // В CSS размер указываем в pt, чтобы соответствовать Java-размерам
        val fontSize = "${font.size}pt"

        val document = parser.parse(markdown)
        val htmlBody = renderer.render(document)

        return """
        <html>
        <head>
            <style>
                body {
                    font-family: "$fontFamily", sans-serif;
                    font-size: $fontSize;
                    color: $textColor;
                    margin: 0;
                }
                pre {
                    background-color: $codeBg;
                    padding: 8px;
                    border-radius: 4px;
                    margin-top: 6px;
                    margin-bottom: 6px;
                }
                code {
                    font-family: "JetBrains Mono", monospace;
                    background-color: $codeBg;
                    font-size: $fontSize;
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