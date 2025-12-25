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

        // Colors configured for better contrast against darker chat bubbles
        // Changed: Lighter text color in dark mode (#E2E2E2) for readability against #232527
        val textColor = if (isDark) "#E2E2E2" else "#222222"
        val linkColor = if (isDark) "#589DF6" else "#285CC4"

        // Distinct background and border for code blocks
        // Changed: Darker code background to separate from bubble
        val codeBg = if (isDark) "#1E1F22" else "#F2F4F5"
        val borderColor = if (isDark) "#45484A" else "#D1D1D1"

        // IMPORTANT: We keep body font flexible (handled by JEditorPane),
        // but enforce monospace for code blocks.

        val document = parser.parse(markdown)
        val htmlBody = renderer.render(document)

        return """
        <html>
        <head>
            <style>
                body {
                    color: $textColor;
                    margin: 0;
                    overflow-wrap: break-word;
                }
                pre {
                    background-color: $codeBg;
                    border: 1px solid $borderColor;
                    padding: 10px;
                    margin-top: 8px;
                    margin-bottom: 8px;
                }
                code {
                    font-family: "JetBrains Mono", "Consolas", "Monospaced", monospace;
                    font-size: 0.95em;
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