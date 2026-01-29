import * as vscode from 'vscode';

export class WebPanelProvider implements vscode.WebviewViewProvider {
    resolveWebviewView(webviewView: vscode.WebviewView) {
        webviewView.webview.options = { enableScripts: true };
        webviewView.webview.html = `
            <iframe src="https://gemini.google.com/" 
                    style="width:100%; height:100%; border:none;" 
                    allow="clipboard-read; clipboard-write;">
            </iframe>`;
    }
}