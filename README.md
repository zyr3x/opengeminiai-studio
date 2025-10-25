# OpenGeminiAI Studio V2.2 (Async Edition)

<!-- TODO: Add a real project logo -->
[![Project Logo](static/img/logo.svg)](http://localhost:8080/)

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](https://github.com/username/repo)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![Async Support](https://img.shields.io/badge/async-enabled-green.svg)](ASYNC_README.md)

An advanced, high-performance proxy that enables seamless integration of Google's Gemini API with any client or tool built for the OpenAI API. Now featuring **async/await architecture** for 3-5x performance improvements on concurrent workloads.

This proxy includes a web interface for easy configuration, chat, and management of MCP (Multi-Tool Communication Protocol) tools for advanced function calling.

## 🚀 What's New in V2.2

**Major Performance Upgrade:**
- ✨ **Async/Await Architecture**: 3-5x faster for concurrent requests
- 🔌 **HTTP Connection Pooling**: Reuse connections for better performance
- ⚡ **Parallel Tool Execution**: Multiple tools run concurrently
- 📦 **Smart Caching**: Tools, prompts, and model info cached efficiently
- 🎯 **Rate Limiting**: Prevents API throttling with async-safe limiter
- 🌊 **Smooth Streaming**: Word-boundary buffering prevents text breaks

**Two Modes Available:**
- **Async Mode** (recommended): `python run_async.py` - High performance
- **Sync Mode** (compatible): `python run.py` - Legacy support

See [ASYNC_README.md](ASYNC_README.md) for details on async features and performance benchmarks.

## ✨ Features

-   **OpenAI API Compatibility:** Seamlessly use Gemini models with tools built for the OpenAI API, including streaming and function calling.
-   **🚀 High Performance (NEW):** Async architecture with connection pooling delivers 3-5x speed improvement for concurrent workloads.
-   **Advanced Web Interface:** A comprehensive UI featuring multi-chat management, file uploads, an image generation playground, and persistent conversation history.
-   **Powerful Prompt Control:** Define system prompts to guide model behavior and create dynamic prompt overrides that trigger on keywords.
-   **Local File & Code Injection:** Automatically embed local images, PDFs, and audio files in your prompts using syntax like `image_path=...`. It also includes a powerful **code injector** (`code_path=...`) to include single source files or entire directories as context—perfect for IDE integration. The directory scanner intelligently ignores common build artifacts, version control directories, and other non-essential files (`.git`, `node_modules`, `__pycache__`, `*.pyc`, etc.) to provide cleaner context to the model. You can also add custom ignore patterns directly in your prompt using `ignore_dir`, `ignore_file`, and `ignore_type` (for file extensions), e.g., `code_path=... ignore_dir=docs ignore_file=*.tmp ignore_type=log`.
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

## 🌐 Web Interface

The proxy includes a comprehensive web interface at `http://localhost:8080` for configuration and testing.

-   **Chat:** An advanced interface to test models. Features include multi-chat management, persistent conversation history, file uploads, a dedicated image generation mode, system prompts, and manual tool selection.
-   **Configuration:** Set your Gemini API Key and Upstream URL. Changes are saved to the `.env` file.
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
    -   `.env`: For `API_KEY`, `UPSTREAM_URL`, `ASYNC_MODE`, and `SECRET_KEY`.
    -   `var/config/mcp.json`: For MCP tool definitions.
    -   `var/config/prompts.json`: For saved user prompts.
    -   `var/config/system_prompts.json`: For system prompt profiles.

### Async Mode Configuration

For production deployments, enable async mode for better performance:

```bash
# In .env file
ASYNC_MODE=true
SECRET_KEY=your-long-random-secret-key-here  # Optional but recommended

# Or via Docker
docker run -e ASYNC_MODE=true -e SECRET_KEY="..." -e API_KEY="..." gemini-proxy
```

See [ASYNC_README.md](ASYNC_README.md) for detailed async configuration options.

## 🚀 Performance

**Async Mode Performance Gains:**
- Single request: 1.05-1.1x faster
- 10 concurrent requests: ~3x faster
- 50 concurrent requests: ~5x faster
- Multi-tool requests (3+ tools): 2-4x faster with parallel execution

**Run Benchmarks:**
```bash
# Start server
python run_async.py

# In another terminal
python benchmark_async.py
```

## 📚 Documentation

- **[ASYNC_README.md](ASYNC_README.md)** - Complete async mode guide
- **[ULTIMATE_MIGRATION_SUMMARY.md](ULTIMATE_MIGRATION_SUMMARY.md)** - Async implementation details
- **[GIT_COMMIT_GUIDE.md](GIT_COMMIT_GUIDE.md)** - Git commit instructions
- Web UI at `http://localhost:8080` - Interactive documentation

## 🔗 Available Endpoints

-   `GET /`: The main web interface.
-   `GET /v1/models`: Lists available Gemini models in OpenAI format.
-   `POST /v1/chat/completions`: The primary endpoint for chat completions, supporting streaming and function calling.

## ⚖️ License

This project is licensed under the MIT License. See the `LICENSE` file for details.

