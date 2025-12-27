package com.opengeminiai.studio.client.ui

import com.intellij.icons.AllIcons
import com.intellij.openapi.actionSystem.*
import com.intellij.ui.jcef.JBCefApp
import com.intellij.ui.jcef.JBCefBrowser
import com.intellij.ui.components.JBLabel
import org.cef.browser.CefBrowser
import org.cef.browser.CefFrame
import org.cef.handler.CefRequestHandlerAdapter
import org.cef.handler.CefResourceRequestHandler
import org.cef.handler.CefResourceRequestHandlerAdapter
import org.cef.network.CefRequest
import org.cef.misc.BoolRef
import java.awt.BorderLayout
import javax.swing.JPanel
import javax.swing.SwingConstants
import javax.swing.JComponent
import java.util.HashMap

class WebPanel {

    fun getContent(): JComponent {
        val panel = JPanel(BorderLayout())

        // Check if JCEF (Embedded Browser) is supported in this environment
        if (!JBCefApp.isSupported()) {
            val errorPanel = JPanel(BorderLayout())
            errorPanel.add(JBLabel("Web View is not supported in this IDE environment.", SwingConstants.CENTER), BorderLayout.CENTER)
            return errorPanel
        }

        try {
            // Initialize with blank page first to attach request handlers before hitting Google
            val browser = JBCefBrowser("about:blank")

            // Spoof User-Agent to look like a standard Desktop Chrome browser
            // This bypasses the "This browser or app may not be secure" Google login error
            val chromeUserAgent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"

            val resourceHandler = object : CefResourceRequestHandlerAdapter() {
                override fun onBeforeResourceLoad(
                    browser: CefBrowser?,
                    frame: CefFrame?,
                    request: CefRequest?
                ): Boolean {
                    if (request == null) return false

                    // Inject clean User-Agent header
                    val headers = HashMap<String, String>()
                    request.getHeaderMap(headers)
                    headers["User-Agent"] = chromeUserAgent
                    request.setHeaderMap(headers)

                    return false // Continue with request
                }
            }

            browser.jbCefClient.addRequestHandler(object : CefRequestHandlerAdapter() {
                override fun getResourceRequestHandler(
                    browser: CefBrowser?,
                    frame: CefFrame?,
                    request: CefRequest?,
                    isNavigation: Boolean,
                    isDownload: Boolean,
                    requestInitiator: String?,
                    disableDefaultHandling: BoolRef?
                ): CefResourceRequestHandler {
                    return resourceHandler
                }
            }, browser.cefBrowser)

            // Navigation Toolbar
            val toolbarGroup = DefaultActionGroup().apply {
                add(object : AnAction("Reload", "Reload page", AllIcons.Actions.Refresh) {
                    override fun actionPerformed(e: AnActionEvent) { browser.cefBrowser.reload() }
                })
                addSeparator()
                add(object : AnAction("Open Gemini", "Go to Gemini Home", AllIcons.Actions.Back) {
                    override fun actionPerformed(e: AnActionEvent) { browser.loadURL("https://gemini.google.com/") }
                })
            }

            val actionManager = ActionManager.getInstance()
            val toolbar = actionManager.createActionToolbar("GeminiWebToolbar", toolbarGroup, true)
            toolbar.targetComponent = panel

            panel.add(toolbar.component, BorderLayout.NORTH)
            panel.add(browser.component, BorderLayout.CENTER)

            // Now load the actual URL
            browser.loadURL("https://gemini.google.com/")

        } catch (e: Exception) {
             panel.add(JBLabel("Error initializing Web View: ${e.message}", SwingConstants.CENTER), BorderLayout.CENTER)
        }

        return panel
    }
}
