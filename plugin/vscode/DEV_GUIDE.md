# OpenGeminiAI Studio - VS Code Extension Developer Guide

This guide explains how to run, test, and debug the VS Code extension without installing it.

## Prerequisites

1. **VS Code:** Ensure you have the latest version of Visual Studio Code.
2. **Node.js & npm:** Installed on your system.
3. **Proxy Server:** The `gemini-proxy` backend must be running (usually on `http://localhost:8080`).

## Setup

1. Open the `plugin/vscode` directory in VS Code.
2. Open a terminal in that directory and run:

    ```bash
    npm install
    ```

## How to Run & Test (Extension Development Host)

The standard way to test a VS Code extension without "installing" it is to use the **Extension Development Host**.

1. Open `plugin/vscode` in VS Code.
2. Press **F5** (or go to `Run and Debug` sidebar and click the play button next to "Run Extension").
3. A new VS Code window will open. This is the **Extension Development Host**. It has your extension loaded.
4. In this new window:
    - Look for the **OpenGeminiAI** (OG) logo in the Activity Bar (left sidebar).
    - Click it to open the Chat view.
    - Try typing a message (ensure your proxy server is running).
    - Try the context menu: right-click in any code file and look for "OpenGemini AI" submenu.

## How to Debug

### 1. Check Extension Logs (Backend Logic)

1. In the **Extension Development Host**, open the **Output** panel (`Cmd+Shift+U`).
2. Select **OpenGeminiAI** from the dropdown menu (it might be "OG Studio").
3. This is where `ApiClient` errors and `ChatViewProvider` logs appear.

### 2. Check Webview Console (UI/JS Logic)

1. In the **Extension Development Host**, run the command: `Developer: Open Webview Developer Tools`.
2. This opens the Chrome DevTools for the chat sidebar.
3. Check the **Console** tab for JS errors like `TypeError` or `message handler not found`.

## Troubleshooting

- **Models not loading:**
  - Check the Output channel for "Failed to load models".
  - Check if the proxy is reachable: `curl http://localhost:8080/v1/models`.
- **Sidebar button (☰) doesn't work:**
  - Open Webview DevTools. Check if clicking the button triggers a `toggleSidebar` function error.
- **Chats not opening:**
  - If clicking a chat in history does nothing, check the Webview Console for "loadChat" message errors.
- **Drag & Drop not working:**
  - Ensure you are dragging files from the VS Code Explorer into the chat input area.

## Building for Distribution

If you want to create a `.vsix` file to share or install manually, run:

```bash
./build.sh
```

This will create a file like `opengeminiai-studio-1.0.0.vsix` which you can install via `Extensions -> ... -> Install from VSIX...`.
