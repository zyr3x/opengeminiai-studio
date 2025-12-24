package com.opengeminiai.studio.client.utils

import org.commonmark.parser.Parser
import org.commonmark.renderer.html.HtmlRenderer
import com.intellij.util.ui.UIUtil
import java.awt.Color

object MarkdownUtils {
    private val parser = Parser.builder().build()
    private val renderer = HtmlRenderer.builder().build()

    // Helper to Convert Color to Hex String safely
    private fun colorToHex(c: Color): String {
        return String.format("#%02x%02x%02x", c.red, c.green, c.blue)
    }

    fun renderHtml(markdown: String): String {
        // Safely determine colors. We use hardcoded defaults if UIUtil is tricky, 
        // but UIUtil is usually standard in Plugins.
        val isDark = UIUtil.isUnderDarcula()

        val textColor = if (isDark) "#C7C7C7" else "#222222"
        val linkColor = if (isDark) "#589DF6" else "#285CC4"
        val codeBg = if (isDark) "#323232" else "#F2F2F2"
        val fontFamily = "Segoe UI, .AppleSystemUIFont, Helvetica, sans-serif"

        val document = parser.parse(markdown)
        val htmlBody = renderer.render(document)

        // Robust CSS without complex shorthands to avoid Swing NPE
        return """
        <html>
        <head>
            <style>
                body { 
                    font-family: $fontFamily; 
                    font-size: 12px; 
                    color: $textColor; 
                    margin: 0;
                    padding: 0;
                }
                pre { 
                    background-color: $codeBg; 
                    padding: 6px; 
                    margin-top: 4px; 
                    margin-bottom: 4px;
                    border-radius: 3px; 
                }
                code { 
                    font-family: JetBrains Mono, monospace; 
                    background-color: $codeBg; 
                    font-size: 12px;
                }
                p { margin-top: 0; margin-bottom: 4px; }
                h1 { font-size: 16px; color: $linkColor; margin-top: 8px; margin-bottom: 4px; }
                h2 { font-size: 14px; color: $linkColor; margin-top: 6px; margin-bottom: 4px; }
                h3 { font-size: 13px; font-weight: bold; margin-top: 6px; margin-bottom: 2px; }
                a { color: $linkColor; text-decoration: none; }
                ul { margin-top: 0; margin-bottom: 4px; margin-left: 15px; padding-left: 0; }
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