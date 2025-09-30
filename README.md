# OpenGeminiAI Studio V1.1

<!-- TODO: Add a real project logo -->
[![Project Logo](static/img/logo.svg)](http://localhost:8080/)

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](https://github.com/username/repo)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)

A simple, efficient Python proxy that allows you to use Google's Gemini API with clients and tools designed for the OpenAI API. Bridge the gap and use your favorite OpenAI-native applications with the power of Gemini models.

This proxy includes a web interface for easy configuration, chat, and management of MCP (Multi-Tool Communication Protocol) tools for advanced function calling.

## ✨ Features

-   **OpenAI API Compatibility:** Seamlessly use Gemini models with tools built for the OpenAI API.
-   **Web Interface:** A user-friendly UI to configure your API key, manage prompts, define MCP tools, and test models in a chat interface.
-   **MCP Tools Support:** Enables powerful, structured function calling capabilities with Gemini.
-   **Easy Deployment:** Get up and running in minutes with a single Docker command.
-   **Flexible Configuration:** Manage settings via the web UI, `.env` file, or environment variables.
-   **Lightweight & Fast:** Built on Flask with a minimal resource footprint using the official Python 3.12 image.

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
    ```
3.  Start the service using Docker Compose:
    ```bash
    docker-compose up -d
    ```

The proxy is now running and accessible at `http://localhost:8080`.

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

-   **Chat:** A simple interface to test models and conversation history.
-   **Configuration:** Set your Gemini API Key and Upstream URL. Changes are saved to the `.env` file.
-   **Prompts:** Create, edit, and manage a library of reusable prompts.
-   **MCP:** Configure MCP (Multi-Tool Communication Protocol) tools for function calling.
-   **Documentation:** View API endpoint details and setup instructions.

*Screenshot of the Web Interface:*
![OpenGeminiAI Studio Web Interface](/static/img/placeholder_web_ui.png)
<!-- TODO: Add screenshot of the web UI -->

## 🛠️ Configuration

The proxy can be configured in three ways (in order of precedence):

1.  **Web Interface:** Settings saved via the UI persist in `.env` and `var/config/mcp.json`.
2.  **Environment Variables:** Set `API_KEY` and `UPSTREAM_URL` when running the container.
3.  **Configuration Files:**
    -   `.env`: For `API_KEY` and `UPSTREAM_URL`.
    -   `var/config/mcp.json`: For MCP tool definitions.
    -   `var/config/prompts.json`: For saved user prompts.

## 🔗 Available Endpoints

-   `GET /`: The main web interface.
-   `GET /v1/models`: Lists available Gemini models in OpenAI format.
-   `POST /v1/chat/completions`: The primary endpoint for chat completions, supporting streaming and function calling.

## ⚖️ License

This project is licensed under the MIT License. See the `LICENSE` file for details.

