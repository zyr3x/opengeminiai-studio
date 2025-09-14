# Gemini API to OpenAI Proxy

This project provides a simple and efficient Nginx proxy that allows you to use Google's Gemini API (Generative Language API) with clients originally designed for the OpenAI API.

It forwards requests from OpenAI-compatible endpoints (e.g., `/v1beta/openai/chat/completions`) to the corresponding Google API endpoints, automatically injecting your API key.

## ✨ Features

-   **OpenAI Compatibility:** Use your favorite OpenAI-native tools and libraries to access Google Gemini models.
-   **Easy Deployment:** Runs with a single command using Docker and Docker Compose.
-   **Flexible Configuration:** All settings (API key, upstream URL) are managed in a `.env` file.
-   **Rapid Development:** Nginx configuration changes are applied by simply restarting the container, no image rebuild required.
-   **Lightweight:** Uses the official `nginx:alpine` image for a minimal resource footprint.

## ⚙️ Prerequisites

-   [Docker](https://www.docker.com/get-started)
-   [Docker Compose](https://docs.docker.com/compose/install/) (usually included with Docker Desktop)

## 🚀 Getting Started

### 1. Clone the Repository

```bash
git clone <your-repository-url>
cd <repository-name>
```

### 2. Create the Configuration File

Create a `.env` file in the project's root directory. You can copy `.env.example` if it exists, or create a new one with the following content:

**.env**
```dotenv
# Your API key from Google AI
API_KEY=<API_KEY>

# The upstream URL for the Google Gemini API
UPSTREAM_URL=https://generativelanguage.googleapis.com
```

### 3. Get Your API Key

-   Go to [Google AI Studio](https://aistudio.google.com/app/apikey).
-   Log in with your Google account.
-   Click on the **"Create API key in new project"** button.
-   Copy the generated key and paste it as the `API_KEY` value in your `.env` file.

### 4. Run the Proxy

Execute the following command in your terminal:

```bash
docker-compose up -d
```
This command will pull the Nginx image (if you don't have it) and start the container in the background. The proxy will be available at `http://localhost:8080`.

## 💻 How to Use the Proxy

You can now configure your OpenAI clients to point to this proxy.

-   **Base URL:** `http://localhost:8080/v1beta/openai`

### Example with `curl`

```bash
curl http://localhost:8080/v1beta/openai/models 
```

### Example with the OpenAI Python Client

```python
import openai

client = openai.OpenAI(
    base_url="http://localhost:8080/v1beta/openai"
)

# List available models
models = client.models.list()
for model in models:
    print(model.id)

# Example chat request
completion = client.chat.completions.create(
    model="gemini-pro",
    messages=[
        {"role": "user", "content": "Write a short story about a friendly robot."},
    ],
)
print(completion.choices[0].message.content)
```

### Example with JetBrains AI Assistant

To use the proxy with your JetBrains IDE's AI Assistant, you need to configure its base URL. This allows the AI Assistant to send requests to your local Gemini proxy instead of the default OpenAI endpoints.

1.  **Open JetBrains IDE Settings:** Go to `File` > `Settings` (Windows/Linux) or `PhpStorm` > `Settings` (macOS).
2.  **Navigate to AI Assistant Settings:** In the settings dialog, search for `AI Assistant` or find it under `Tools` > `AI Assistant`.
3.  **Configure On-Premise Server:**
    *   Enable the `Use On-Premise Server` option (if available and applicable for your version/plugin).
    *   Set the **"Server URL"** or **"Endpoint URL"** (the exact naming might vary) to:
        ```
        http://localhost:8080/v1beta/openai
        ```

Your JetBrains AI Assistant should now route its requests through your local Gemini API proxy.

## 🛠️ Modifying the Configuration

If you need to change the proxy's behavior (e.g., add new endpoints or headers), you can edit the `nginx.conf.template` file.