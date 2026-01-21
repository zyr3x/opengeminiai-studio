package com.opengeminiai.studio.client.utils

import org.commonmark.parser.Parser
import org.commonmark.renderer.html.HtmlRenderer
import com.intellij.util.ui.UIUtil

object MarkdownUtils {
    private val parser = Parser.builder().build()
    private val renderer = HtmlRenderer.builder().build()

    fun renderHtml(markdown: String): String {
        val isDark = UIUtil.isUnderDarcula()

        // Colors configured for better contrast against darker chat bubbles
        val textColor = if (isDark) "#E2E2E2" else "#222222"
        val linkColor = if (isDark) "#589DF6" else "#285CC4"

        val codeBg = if (isDark) "#1E1F22" else "#F2F4F5"
        val borderColor = if (isDark) "#45484A" else "#D1D1D1"

        val document = parser.parse(markdown)
        var html = renderer.render(document)

        // 1. Force wrapping for code blocks by converting <pre><code> to <div>
        // Standard <pre> tags in JEditorPane do not support line wrapping, causing overflow.
        // We replace them with <div> and convert newlines to <br>.
        html = html.replace(Regex("<pre><code(.*?)>(.*?)</code></pre>", setOf(RegexOption.DOT_MATCHES_ALL, RegexOption.IGNORE_CASE))) { matchResult ->
            val attrs = matchResult.groupValues[1] // captures attributes like class="language-kotlin"
            val content = matchResult.groupValues[2]
            // Replace newlines with <br> to preserve formatting in the div
            val wrappedContent = content.replace("\n", "<br>")
            "<div$attrs class=\"code-block\">$wrappedContent</div>"
        }

        // 2. Inject invisible break characters to force wrapping on long paths
        html = injectBreakableChars(html)

        return """
        <html>
        <head>
            <style>
                body {
                    color: $textColor;
                    margin: 0;
                    font-family: sans-serif;
                    word-wrap: break-word;
                    overflow-wrap: break-word;
                }
                /* Replaces the standard pre/code styling */
                .code-block {
                    font-family: "JetBrains Mono", "Consolas", "Monospaced", monospace;
                    font-size: 0.95em;
                    background-color: $codeBg;
                    border: 1px solid $borderColor;
                    padding: 10px;
                    margin-top: 8px;
                    margin-bottom: 8px;
                    white-space: normal; /* Force wrapping inside our div */
                }
                code {
                    font-family: "JetBrains Mono", "Consolas", "Monospaced", monospace;
                    font-size: 0.95em;
                    background-color: $codeBg;
                }
                p { 
                    margin-top: 0; 
                    margin-bottom: 6px; 
                }
                h1 { font-size: 1.2em; font-weight: bold; color: $textColor; margin-top: 8px; margin-bottom: 4px; }
                h2 { font-size: 1.1em; font-weight: bold; color: $textColor; margin-top: 6px; margin-bottom: 4px; }
                h3 { font-size: 1.0em; font-weight: bold; margin-top: 6px; margin-bottom: 2px; }
                a { color: $linkColor; text-decoration: none; }
                ul { margin-top: 0; margin-bottom: 6px; margin-left: 15px; padding-left: 0; }
                li { margin-top: 2px; }
            </style>
        </head>
        <body>
            $html
        </body>
        </html>
        """.trimIndent()
    }

    /**
     * Injects <wbr> after common separators to force Swing's JEditorPane to wrap long strings.
     * This is necessary because JEditorPane's CSS support for 'word-break: break-all' is limited/non-existent.
     */
    private fun injectBreakableChars(html: String): String {
        // Regex matches text content that is NOT inside a tag (between > and <)
        // (?<=^|>) : Lookbehind ensuring we start after a closing tag or start of string
        // [^><]+   : Match one or more characters that are NOT < or > (Greedy match for efficiency)
        // (?=<|$)  : Lookahead ensuring we end before an opening tag or end of string
        return html.replace(Regex("(?<=^|>)[^><]+(?=<|$)")) { match ->
            match.value
                .replace("/", "/<wbr>")
                .replace("\\", "\\<wbr>")
                .replace(".", ".<wbr>")
                .replace("_", "_<wbr>")
                .replace(":", ":<wbr>")
                .replace("-", "-<wbr>")
                .replace("?", "?<wbr>")
                .replace("=", "=<wbr>")
                .replace(",", ",<wbr>")
                .replace(";", ";<wbr>") // Safe for entities (e.g. &amp; -> &amp;<wbr>)
        }
    }
}
