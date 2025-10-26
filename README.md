# OpenGeminiAI Studio V2.3 (Async Edition)

<!-- TODO: Add a real project logo -->
[![Project Logo](static/img/logo.svg)](http://localhost:8080/)

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](https://github.com/zyr3x/opengeminiai-studio)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)

An advanced, high-performance proxy that enables seamless integration of Google's Gemini API with any client or tool built for the OpenAI API. Now featuring **async/await architecture** for 3-5x performance improvements on concurrent workloads.

This proxy includes a web interface for easy configuration, chat, and management of MCP (Multi-Tool Communication Protocol) tools for advanced function calling.

## 🤔 Why OpenGeminiAI Studio?

In a world of AI coding assistants, OpenGeminiAI Studio stands out by combining the power of Google's state-of-the-art Gemini models with a robust, locally-hosted toolkit designed for professional developers. It's more than just a proxy; it's a complete, extensible, and secure development environment.

-   **Go Beyond Chat:** While other tools stop at generating code snippets, OpenGeminiAI Studio acts as an **autonomous agent**. It can understand your project structure, read and write files, execute tests, manage git history, and apply patches. It doesn't just suggest code; it *implements* it.
-   **Your Tools, Your Workflow:** Seamlessly integrate with any OpenAI-compatible client, including the JetBrains AI Assistant, VS Code, or your own scripts. Keep your preferred development environment without sacrificing power.
-   **Total Control & Privacy:** Host it on your own machine or private network. Your code and API keys never leave your control. Sandbox the AI's access to specific project directories for complete peace of mind.
-   **Extensible & Open:** Built with a modular MCP architecture, you can easily add your own custom tools to extend its capabilities. The project is open and transparent.
-   **Cost-Effective:** Leverage powerful optimization features like selective context, prompt caching, and tool output summarization to significantly reduce token usage and lower your API costs.

## 🚀 What's New in V2.3 - The Agentic Developer Update

Version 2.3 transforms OpenGeminiAI Studio into a powerful **AI-driven software developer**. With an expanded toolkit and deeper project understanding, it can now take on complex development tasks autonomously.

-   **🤖 Full Agentic Capabilities**: With `project_path=`, the AI can now **write, modify, and create files** (`apply_patch`, `create_file`, `write_file`), **execute shell commands** (`execute_command` for tests, builds, and scripts), and perform **full git operations** (`git_diff`, `git_status`, etc.). It's not just a code assistant; it's an active development partner.
-   **🔬 Advanced Code Analysis**: New tools like `analyze_project_structure`, `find_symbol`, and `get_dependencies` give the AI a comprehensive understanding of your entire codebase, enabling more accurate and context-aware responses.
-   **✍️ Better Streaming & UI**: Text streaming is now more robust, preventing broken words and improving readability in the chat UI.
-   **🔐 Enhanced Security & Control**: The `ALLOWED_CODE_PATHS` setting allows you to sandbox the AI's file system access to specific project directories, providing crucial security for your development environment.
-   **🐛 Stability Fixes**: Resolved several async compatibility issues, improved session management, and streamlined tool execution logic for a more reliable experience.

## ⚡ What's New in V2.2

**Major Performance Upgrade:**
- ✨ **Async/Await Architecture**: 3-5x faster for concurrent requests
- 🔌 **HTTP Connection Pooling**: Reuse connections for better performance
- ⚡ **Parallel Tool Execution**: Multiple tools run concurrently
- 📦 **Smart Caching**: Tools, prompts, and model info cached efficiently
- 🎯 **Rate Limiting**: Prevents API throttling with async-safe limiter
- 🌊 **Smooth Streaming**: Word-boundary buffering prevents text breaks

**Two Modes Available:**
- **Async Mode** (recommended): - High performance
- **Sync Mode** (compatible): - Legacy support


## ✨ Features

-   **OpenAI API Compatibility:** Seamlessly use Gemini models with tools built for the OpenAI API, including streaming and function calling.
-   **🚀 High Performance (NEW):** Async architecture with connection pooling delivers 3-5x speed improvement for concurrent workloads.
-   **Advanced Web Interface:** A comprehensive UI featuring multi-chat management, file uploads, an image generation playground, and persistent conversation history.
-   **Powerful Prompt Control:** Define system prompts to guide model behavior and create dynamic prompt overrides that trigger on keywords.
-   **🆕 Dual Path Mode (NEW):**
    -   **`code_path=`**: Recursively loads all code files from a directory as text context—perfect for code review, Q&A, and understanding codebases. No tools activated, just pure code context (up to 4MB).
    -   **`project_path=`**: Activates full AI agent mode with 19 built-in development tools for navigation, analysis, modification, and execution. AI can read, write, create files, run commands (tests, builds, awk/sed/grep), and perform git operations. Perfect for actual development work.
    -   Both modes support custom ignore patterns: `ignore_dir=`, `ignore_file=`, `ignore_type=`
    -   See **[PATH_SYNTAX_GUIDE.md](PATH_SYNTAX_GUIDE.md)** for complete guide and examples.
-   **Local File Injection:** Automatically embed local images, PDFs, and audio files in your prompts using syntax like `image_path=...`, `pdf_path=...`, `audio_path=...`.
-   **Built-in Development Tools (19 tools):** When using `project_path=`, AI gets access to a comprehensive toolkit:
    -   **Navigation**: `list_files`, `get_file_content`, `get_code_snippet`, `search_codebase`
    -   **Analysis**: `analyze_file_structure`, `analyze_project_structure`, `get_file_stats`, `find_symbol`, `get_dependencies`
    -   **Modification**: `apply_patch`, `create_file`, `write_file`
    -   **Execution**: `execute_command` (run tests, builds, awk/sed/grep, any shell command with 5-min timeout)
    -   **Git Operations**: `git_status`, `git_log`, `git_diff`, `git_show`, `git_blame`, `list_recent_changes`
-   **MCP Tools Support:** Integrates with external tools via the Multi-Tool Communication Protocol (MCP) for advanced, structured function calling. **Tools/functions can be explicitly selected or disabled via System Prompt and Prompt Override profiles.**
-   **Native Google Tools:** Enable built-in Google tools like Search directly within your prompts for enhanced, real-time data retrieval.
-   **Integrated Developer Toolkit:** The container comes with a pre-configured development environment, including **Node.js 22+** and the **Docker CLI**. This allows you to run `npx mcp-tools` directly and manage host Docker containers from within the proxy, streamlining development and automation tasks.
-   **Easy Deployment:** Get up and running in minutes with Docker or standard Python setup.
-   **Flexible Configuration:** Manage settings via the web UI, `.env` file, or environment variables.
-   **Optimized Performance:** Built on Quart (async) or Flask (sync) with minimal resource footprint.

## 🚀 Quick Start with Docker

Get the proxy running in just a few steps.

### Prerequisites

-   [Docker](https://www.docker.com/get-started)
-   [Docker Compose](https://docs.docker.com/compose/install/) (included with Docker Desktop)

### 1. Clone the Repository

```
bash git clone <your-repository-url> cd <repository-name>
```


### 2. Get Your Gemini API Key

1.  Navigate to [Google AI Studio](https://aistudio.google.com/app/apikey).
2.  Click **"Create API key in new project"**.
3.  Copy the generated key.

### 3. Configure and Run

1.  Create a `.env` file in the project root (you can copy `.env.example`).
2.  Add your API key to the `.env` file:
    ```dotenv
    # .env
    API_KEY=<PASTE_YOUR_GEMINI_API_KEY_HERE>
    UPSTREAM_URL=https://generativelanguage.googleapis.com
    SERVER_HOST=0.0.0.0
    SERVER_PORT=8080
    
    # Optional: Enable async mode for better performance (recommended)
    ASYNC_MODE=true
    
    # Optional: Set a secret key for sessions (auto-generated if not set)
    # SECRET_KEY=your-random-secret-key-here
    
    # Context Management Settings (configurable via Web UI)
    SELECTIVE_CONTEXT_ENABLED=true
    CONTEXT_MIN_RELEVANCE_SCORE=0.3
    CONTEXT_ALWAYS_KEEP_RECENT=15
    
    # Security Settings (configurable via Web UI)
    # Comma-separated allowed root directories for builtin tools
    # Leave empty to allow all paths
    ALLOWED_CODE_PATHS=
    ```
3.  Start the service using Docker Compose:
    ```bash
    docker-compose up -d
    ```

The proxy is now running and accessible at `http://localhost:8080`.

**Performance Tip:** Set `ASYNC_MODE=true` for 3-5x better performance with concurrent requests!

## 💻 How to Use the Proxy

Point your OpenAI-compatible client to the proxy's base URL: `http://localhost:8080/v1`

### Example: `curl`

Fetch the list of available models:

```
bash curl http://localhost:8080/v1/models
```


### Example: OpenAI Python Client
```python

import openai
client = openai.OpenAI
# List models
for model in client.models.list(): print(model.id)
# Chat request
completion = client.chat.completions.create( model='gemini-2.5-flash-lite', messages= {'role':'user','content':'Tell me joe about AI.'})
print(completion.choices[0].message.content)
```


### Example: JetBrains AI Assistant

Integrate the proxy with your JetBrains IDE's AI Assistant.

1.  In your IDE, go to `Settings` > `Tools` > `AI Assistant`.
2.  Select the **"OpenAI API"** service.
3.  Set the **Server URL** to: `http://localhost:8080/v1/`
4.  The API Key field can be left blank or filled with any text, as the proxy manages authentication.

The IDE will automatically fetch the model list and route AI Assistant features through your local proxy.

*Screenshot of JetBrains AI Assistant settings:*
![JetBrains AI Assistant Configuration](/static/img/placeholder_jetbrains_config.png)
<!-- TODO: Add screenshot of JetBrains AI Assistant configuration -->

## 🎯 Dual Path Mode: Two Ways to Work with Code

OpenGeminiAI Studio V2.2 introduces two distinct modes for working with code projects:

### 🔷 Mode 1: `code_path=` - Code Context Loading

**Purpose:** Recursively loads all code files as text context for review and analysis.

**Features:**
- ✅ Loads ALL code files recursively from directory
- ✅ Formats with markdown code blocks
- ✅ Supports ignore patterns
- ❌ NO tools activated (read-only mode)
- 📦 Up to 4 MB code limit

**Usage Example:**
```
Review this code for security issues: code_path=~/myproject/src
```

**Perfect For:**
- Code review and auditing
- Q&A about code
- Understanding existing codebases
- Static analysis

### 🔶 Mode 2: `project_path=` - AI Agent Mode

**Purpose:** Activates full AI agent with 19 development tools for comprehensive project work.

**Features:**
- ✅ Shows project structure (tree view, depth 3)
- ✅ Activates ALL 19 built-in development tools
- ✅ Can read files on-demand
- ✅ Can modify and create files
- ✅ Can execute commands (tests, builds, awk/sed/grep)
- ✅ Full git operations
- 📦 Unlimited size (tools fetch on-demand)

**Usage Example:**
```
Find and fix the authentication bug: project_path=~/myproject
```

**Perfect For:**
- Bug fixing and debugging
- Feature development
- Refactoring code
- Running tests and builds
- Full development workflows

### 📊 Quick Comparison

| Feature | `code_path=` | `project_path=` |
|---------|--------------|-----------------|
| Loads code files | ✅ All at once | ❌ On-demand via tools |
| In prompt context | ✅ Full text | ✅ Structure only |
| Activates tools | ❌ No | ✅ Yes (19 tools) |
| Can modify files | ❌ No | ✅ Yes |
| Can execute commands | ❌ No | ✅ Yes |
| Size limit | 4 MB | Unlimited |
| Best for | **Reading** code | **Working** with code |

### 🔧 Both Support Ignore Patterns

```bash
# Ignore specific file types
code_path=. ignore_type=log|tmp|cache

# Ignore specific files
code_path=. ignore_file=*.test.js|*.spec.ts

# Ignore directories
code_path=. ignore_dir=docs|examples|legacy

# Same works for project_path
project_path=. ignore_type=cache
```

**Default Ignores:** `.git`, `node_modules`, `__pycache__`, `venv`, `build`, `dist`, `*.pyc`, `*.log`, minified files, lock files, and more.

### 💡 Real-World Examples

**Example 1: Code Review**
```
Prompt: "Review for security vulnerabilities: code_path=~/webapp/src"
```
→ AI receives all source files and analyzes them (no modifications)

**Example 2: Bug Fixing**
```
Prompt: "Fix the SQL injection in user login: project_path=~/webapp"
```
→ AI uses tools to search, analyze, patch files, and run tests

**Example 3: New Feature**
```
Prompt: "Add /api/users endpoint with authentication: project_path=~/api-server"
```
→ AI creates files, modifies routes, writes tests, runs pytest

**Example 4: Mixed Workflow**
```
First: "Understand this codebase: code_path=~/project/src"
Then: "Now refactor to use async/await: project_path=~/project"
```

See **[PATH_SYNTAX_GUIDE.md](PATH_SYNTAX_GUIDE.md)** for complete documentation and more examples.

## 🌐 Web Interface

The proxy includes a comprehensive web interface at `http://localhost:8080` for configuration and testing.

-   **Chat:** An advanced interface to test models. Features include multi-chat management, persistent conversation history, file uploads, a dedicated image generation mode, system prompts, and manual tool selection.
-   **Configuration:** Set your Gemini API Key and Upstream URL. Manage context settings including selective context filtering, relevance scoring thresholds, and recent message retention. Configure security restrictions for builtin tools. Configure debugging options. Changes are saved to the `.env` file.
-   **Prompts:** Create, edit, and manage libraries of reusable system prompts and keyword-based prompt overrides.
-   **MCP:** Configure MCP (Multi-Tool Communication Protocol) tools for function calling and test their responses.
-   **Documentation:** View API endpoint details and setup instructions.

*Screenshot of the Web Interface:*
![OpenGeminiAI Studio Web Interface](/static/img/placeholder_web_ui.png)
<!-- TODO: Add screenshot of the web UI -->

## 🛠️ Configuration

The proxy can be configured in three ways (in order of precedence):

1.  **Web Interface:** Settings saved via the UI persist in `.env` and `var/config/mcp.json`.
2.  **Environment Variables:** Set `API_KEY`, `UPSTREAM_URL`, and `ASYNC_MODE` when running the container.
3.  **Configuration Files:**
    -   `.env`: For `API_KEY`, `UPSTREAM_URL`, `ASYNC_MODE`, `SECRET_KEY`, and context management settings.
    -   `var/config/mcp.json`: For MCP tool definitions.
    -   `var/config/prompts.json`: For saved user prompts.
    -   `var/config/system_prompts.json`: For system prompt profiles.

### Context Management Settings

Control how the proxy handles conversation history and context selection:

-   **`SELECTIVE_CONTEXT_ENABLED`** (default: `true`): When enabled, uses relevance scoring to select the most pertinent context from conversation history instead of sending all messages.
-   **`CONTEXT_MIN_RELEVANCE_SCORE`** (default: `0.3`): Minimum relevance threshold (0.0-1.0) for including context. Higher values mean stricter filtering.
-   **`CONTEXT_ALWAYS_KEEP_RECENT`** (default: `15`): Number of most recent messages to always include, regardless of relevance score.

These settings can be easily adjusted through the **Configuration** page in the Web UI under the "Context Management" section.

### Security Settings

Control access restrictions for builtin development tools:

-   **`ALLOWED_CODE_PATHS`** (default: empty/unrestricted): Comma-separated list of root directories that builtin tools can access. When set, tools like `list_files`, `get_file_content`, `create_file`, etc., will only work within these directories. Leave empty to allow access to all paths.
    
    **Example:** `ALLOWED_CODE_PATHS=/home/user/projects,/opt/workspace,/var/www`
    
    **Use cases:**
    - Restrict AI access to specific project directories
    - Prevent accidental access to system files
    - Create sandboxed development environments
    - Multi-user scenarios where isolation is needed

This setting can be configured through the **Configuration** page in the Web UI under the "Security Settings" section.

### Async Mode Configuration

For production deployments, enable async mode for better performance:

```bash
# In .env file
ASYNC_MODE=true
SECRET_KEY=your-long-random-secret-key-here  # Optional but recommended

# Or via Docker
docker run -e ASYNC_MODE=true -e SECRET_KEY="..." -e API_KEY="..." gemini-proxy
```

## 🚀 Performance

**Async Mode Performance Gains:**
- Single request: 1.05-1.1x faster
- 10 concurrent requests: ~3x faster
- 50 concurrent requests: ~5x faster
- Multi-tool requests (3+ tools): 2-4x faster with parallel execution

## 📚 Documentation

- **[PATH_SYNTAX_GUIDE.md](PATH_SYNTAX_GUIDE.md)** - 🆕 Guide to `code_path=` vs `project_path=` modes
- Web UI at `http://localhost:8080` - Interactive documentation

## 🔗 Available Endpoints

-   `GET /`: The main web interface.
-   `GET /v1/models`: Lists available Gemini models in OpenAI format.
-   `POST /v1/chat/completions`: The primary endpoint for chat completions, supporting streaming and function calling.

## ⚖️ License

This project is licensed under the MIT License. See the `LICENSE` file for details.

