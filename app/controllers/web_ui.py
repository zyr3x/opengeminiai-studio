"""
Flask routes for the web UI, including the main page and direct chat API.
Compatible with both Flask and Quart.
"""
import json
from datetime import datetime
import os

try:
    from quart import Blueprint, Response, render_template
except ImportError:
    from flask import Blueprint, Response, render_template

from app.config import config
from app import mcp_handler
from app import utils
from .metrics import get_metrics

web_ui_bp = Blueprint('web_ui', __name__)

@web_ui_bp.route('/', methods=['GET'])
async def index():
    """
    Serves the main documentation and configuration page.
    Compatible with both Flask and Quart (async).
    """
    api_key_status = "Set" if config.API_KEY else "Not Set"
    current_mcp_config_str = ""
    if os.path.exists(mcp_handler.MCP_CONFIG_FILE):
        with open(mcp_handler.MCP_CONFIG_FILE, 'r') as f: current_mcp_config_str = f.read()

    current_prompt_overrides_str = ""
    if os.path.exists(utils.PROMPT_OVERRIDES_FILE):
        with open(utils.PROMPT_OVERRIDES_FILE, 'r') as f: current_prompt_overrides_str = f.read()

    current_system_prompts_str = ""
    if os.path.exists(utils.SYSTEM_PROMPTS_FILE):
        with open(utils.SYSTEM_PROMPTS_FILE, 'r') as f: current_system_prompts_str = f.read()

    default_prompt_overrides = {
      "default_chat": {"triggers": ["You are a JetBrains AI Assistant for code development."], "overrides": {"Follow the user's requirements carefully & to the letter.": ""}, "enable_native_tools": False},
      "commit_message": {"triggers": ["[Diff]"], "overrides": {}, "disable_tools": True, "enable_native_tools": False}
    }
    prompt_profiles = default_prompt_overrides
    if current_prompt_overrides_str.strip():
        try: prompt_profiles = json.loads(current_prompt_overrides_str)
        except json.JSONDecodeError: pass

    default_system_prompts = {
      "Professional Assistant": {"enabled": True, "prompt": "You are a professional software development assistant and coding expert. Provide concise, accurate, and actionable code solutions, technical advice, or explanations focusing on best practices and idiomatic language use.", "disable_tools": False, "enable_native_tools": False},
      "Frontend Web Developer": {"enabled": True, "prompt": "You are an expert Frontend Web Developer specializing in JavaScript, HTML, and CSS. Focus on responsive design, performance optimization, accessibility, and modern framework practices (e.g., React, Vue, Angular). Provide idiomatic solutions for UI/UX implementation.", "disable_tools": False, "enable_native_tools": False},
      "Backend Web Developer": {"enabled": True, "prompt": "You are an expert Backend Web Developer specializing in server-side logic, APIs, and database interactions (e.g., Python/Flask, PHP, Node.js/Express). Focus on security, scalability, efficient data handling, and robust API design.", "disable_tools": False, "enable_native_tools": False},
      "Creative Writer": {"enabled": True, "prompt": "You are a creative writer and storyteller. Generate imaginative prose, compelling narratives, or engaging fictional responses for any request, ignoring technical constraints.", "disable_tools": True, "enable_native_tools": False},
      "Technical Reviewer": {"enabled": True, "prompt": "You are an expert software architect and security analyst. Provide critical, high-level analysis and feedback on technical specifications, system designs, code structure, and potential architectural pitfalls or security vulnerabilities.", "disable_tools": False, "enable_native_tools": True},
      "Code Refactorer": {"enabled": True, "prompt": "You are an expert in code quality, clean code principles, and optimization. Your focus is strictly on refactoring existing code to improve readability, performance, modularity, and adherence to language-specific best practices without altering external functionality.", "disable_tools": False, "enable_native_tools": False},
      "Documentation Specialist": {"enabled": True, "prompt": "You are a documentation expert and technical author. Your primary goal is to generate clear, precise, and highly structured documentation, including Javadocs/docstrings, user guides, architectural summaries, or detailed API reference material based on the provided code or context.", "disable_tools": True, "enable_native_tools": False},
      "Bug Investigator": {"enabled": True, "prompt": "You are a forensic software investigator and debugger. Analyze provided code, error messages, and context to precisely locate the root cause of reported bugs. When suggesting a fix, it must be the minimal viable change required to resolve the issue.", "disable_tools": False, "enable_native_tools": True}
    }
    system_prompt_profiles = default_system_prompts
    if current_system_prompts_str.strip():
        try: system_prompt_profiles = json.loads(current_system_prompts_str)
        except json.JSONDecodeError: pass

    default_mcp_config = {
      "mcpServers": {"youtrack": {"command": "docker", "args": ["run", "--rm", "-i", "-e", "YOUTRACK_API_TOKEN", "-e", "YOUTRACK_URL", "tonyzorin/youtrack-mcp:latest"], "env": {"YOUTRACK_API_TOKEN": "perm-your-token-here", "YOUTRACK_URL": "https://youtrack.example.com/"}}},
      "maxFunctionDeclarations": mcp_handler.MAX_FUNCTION_DECLARATIONS_DEFAULT,
      "disableAllTools": mcp_handler.DISABLE_ALL_MCP_TOOLS_DEFAULT # Include default global disable setting
    }
    mcp_config_data = default_mcp_config
    if current_mcp_config_str.strip():
        try:
            loaded_mcp_config = json.loads(current_mcp_config_str)
            if "mcpServers" in loaded_mcp_config and isinstance(loaded_mcp_config.get("mcpServers"), dict):
                mcp_config_data = loaded_mcp_config
            # Also load the disableAllTools setting if present in the saved config
            mcp_config_data["disableAllTools"] = loaded_mcp_config.get("disableAllTools", mcp_handler.DISABLE_ALL_MCP_TOOLS_DEFAULT)
        except json.JSONDecodeError: pass

    mcp_functions_by_tool = {}
    for func_decl in mcp_handler.mcp_function_declarations:
        tool_name = mcp_handler.mcp_function_to_tool_map.get(func_decl['name'])
        if tool_name:
            if tool_name not in mcp_functions_by_tool:
                mcp_functions_by_tool[tool_name] = []
            mcp_functions_by_tool[tool_name].append(func_decl)

    return await render_template(
        'index.html',
        API_KEY=config.API_KEY, api_key_status=api_key_status,
        current_mcp_config_str=current_mcp_config_str, mcp_config=mcp_config_data,
        default_mcp_config_json=utils.pretty_json(default_mcp_config),
        prompt_profiles=prompt_profiles, current_prompt_overrides_str=current_prompt_overrides_str,
        default_prompt_overrides_json=utils.pretty_json(default_prompt_overrides),
        system_prompt_profiles=system_prompt_profiles, current_system_prompts_str=current_system_prompts_str,
        default_system_prompts_json=utils.pretty_json(default_system_prompts),
        verbose_logging_status=utils.VERBOSE_LOGGING,
        current_max_function_declarations=mcp_config_data.get("maxFunctionDeclarations", mcp_handler.max_function_declarations_limit),
        current_disable_all_mcp_tools=mcp_handler.disable_all_mcp_tools, # Pass current status of global disable
        current_year=datetime.now().year,
        mcp_functions_by_tool=mcp_functions_by_tool, # Pass available MCP functions grouped by tool
        metrics=get_metrics()
    )

@web_ui_bp.route('/favicon.ico')
async def favicon():
    """Serves the favicon for the web interface."""
    favicon_svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">⚙️</text></svg>'
    return Response(favicon_svg, mimetype='image/svg+xml')
