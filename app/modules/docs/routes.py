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
    from flask import current_app
    import re

    spec_dict = spec.to_dict()
    spec_dict["paths"] = {}
    
    # Static components definitions
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

    # Dynamically generate paths from Flask routing table
    for rule in current_app.url_map.iter_rules():
        if rule.endpoint == 'static':
            continue
            
        path = str(rule)
        
        # Only include actual API endpoints
        if not (path.startswith('/v1') or path.startswith('/api') or path in ['/ping', '/metrics', '/metrics/api']):
            continue

        # Convert Flask path vars like <int:chat_id> to OpenAPI parameter {chat_id}
        openapi_path = re.sub(r'<[^:]+:([^>]+)>', r'{\1}', path)
        openapi_path = re.sub(r'<([^>]+)>', r'{\1}', openapi_path)
        
        view_func = current_app.view_functions[rule.endpoint]
        docstring = view_func.__doc__ or ""
        
        if openapi_path not in spec_dict["paths"]:
            spec_dict["paths"][openapi_path] = {}
            
        methods = [m.lower() for m in rule.methods if m in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']]
        
        for method in methods:
            # Document parameters from URL
            parameters = []
            for arg_name in rule.arguments:
                parameters.append({
                    "name": arg_name,
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"}
                })
                
            summary = docstring.strip().split('\n')[0] if docstring.strip() else f"{method.upper()} {path}"
            
            op_spec = {
                "summary": summary,
                "description": docstring.strip(),
                "parameters": parameters,
                "responses": {
                    "200": {"description": "Successful response"}
                }
            }
            
            # Simple tags logic
            if path.startswith('/v1'):
                op_spec["tags"] = ["Proxy API"]
                if "chat/completions" in path and method == "post":
                    op_spec["requestBody"] = {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/ChatRequest"}}
                        }
                    }
            elif path.startswith('/api/mcp'):
                op_spec["tags"] = ["MCP API"]
            elif path.startswith('/api'):
                op_spec["tags"] = ["Web UI API"]
            else:
                op_spec["tags"] = ["System"]
                
            spec_dict["paths"][openapi_path][method] = op_spec

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
