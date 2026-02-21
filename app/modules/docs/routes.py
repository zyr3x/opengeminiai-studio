from flask import Blueprint, jsonify
from flask_swagger_ui import get_swaggerui_blueprint
from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin

# Initialize APISpec
spec = APISpec(
    title="GeminiProxy Unified API",
    version="1.0.0",
    openapi_version="3.0.2",
    plugins=[MarshmallowPlugin()],
)

docs_bp = Blueprint('docs', __name__)

@docs_bp.route('/openapi.json')
def openapi_spec():
    """Endpoint serving the OpenAPI JSON specification."""
    # Add minimal paths dynamically or manually here
    # In a full production app, we would parse Pydantic -> JSON Schema
    # For now, we inject a static definition for the chat completions
    spec_dict = spec.to_dict()
    spec_dict["paths"] = {
        "/v1/chat/completions": {
            "post": {
                "summary": "Process an AI Chat Request",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/ChatRequest"
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Successful chat response"
                    }
                }
            }
        }
    }
    spec_dict["components"] = {
        "schemas": {
            "ChatRequest": {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "messages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {"type": "string"},
                                "content": {"type": "string"}
                            }
                        }
                    }
                }
            }
        }
    }
    return jsonify(spec_dict)

# Configure Swagger UI
swagger_url = '/docs'
api_url = '/docs/openapi.json'

swagger_ui_bp = get_swaggerui_blueprint(
    swagger_url,
    api_url,
    config={
        'app_name': "GeminiProxy API"
    }
)
