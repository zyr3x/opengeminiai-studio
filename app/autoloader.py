import os
import json
import importlib
from pathlib import Path
from flask import Flask
from fastmcp import FastMCP
from app.utils.observer import observer
from app.utils.hooks import hooks, render_hooks_global

MODULES_DIR = Path(__file__).parent / "modules"

class Autoloader:
    def __init__(self, app: Flask, mcp_server: FastMCP):
        self.app = app
        self.mcp_server = mcp_server
        self.loaded_modules = []

        # Register render_hooks globally to Jinja
        self.app.jinja_env.globals['render_hooks'] = render_hooks_global

    def load_all(self):
        """Scans the modules directory and loads all enabled modules."""
        if not MODULES_DIR.exists():
            print(f"Modules directory not found at {MODULES_DIR}")
            return
            
        for module_path in MODULES_DIR.iterdir():
            if module_path.is_dir():
                manifest_path = module_path / "module.json"
                if manifest_path.exists():
                    self._load_module(manifest_path)
                    
        print(f"Loaded {len(self.loaded_modules)} modules successfully.")

    def _load_module(self, manifest_path: Path):
        """Loads a single module based on its manifest."""
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error parsing {manifest_path}: {e}")
            return
            
        if not manifest.get("enabled", False):
            print(f"Module {manifest.get('name', 'Unknown')} is disabled. Skipping.")
            return

        module_name = manifest.get("name")
        print(f"Loading module: {module_name} (v{manifest.get('version', '1.0')})")
        
        # Load Blueprints
        for bp_info in manifest.get("blueprints", []):
            try:
                module = importlib.import_module(bp_info["module_path"])
                blueprint = getattr(module, bp_info["blueprint_name"])
                url_prefix = bp_info.get("url_prefix", "")
                self.app.register_blueprint(blueprint, url_prefix=url_prefix)
                print(f"  -> Registered Blueprint: {bp_info['blueprint_name']} at {url_prefix}")
            except Exception as e:
                print(f"  -> Error loading Blueprint {bp_info.get('blueprint_name')}: {e}")

        # Load MCP Tools
        for tool_path in manifest.get("mcp_tools", []):
            try:
                # Tools are typically decorated and self-register, 
                # but we just need to import the module they live in so the decorator runs
                importlib.import_module(tool_path)
                print(f"  -> Loaded MCP Tool module: {tool_path}")
            except Exception as e:
                print(f"  -> Error loading MCP Tool {tool_path}: {e}")
                
        # Load Events (if configs exist)
        events_path = manifest_path.parent / "events.json"
        if events_path.exists():
            try:
                with open(events_path, 'r', encoding='utf-8') as f:
                    events = json.load(f)
                for event_name, handler_path in events.items():
                    # Parse module path and function name
                    module_path, func_name = handler_path.rsplit('.', 1)
                    module = importlib.import_module(module_path)
                    handler_func = getattr(module, func_name)
                    observer.subscribe(event_name, handler_func)
                    print(f"  -> Subscribed to event '{event_name}' with {handler_path}")
            except Exception as e:
                print(f"  -> Error loading Events config from {events_path}: {e}")

        # Load Hooks (if configs exist)
        hooks_path = manifest_path.parent / "hooks.json"
        if hooks_path.exists():
            try:
                with open(hooks_path, 'r', encoding='utf-8') as f:
                    module_hooks = json.load(f)
                for hook_cfg in module_hooks:
                    hooks.register_hook(
                        hook_name=hook_cfg.get("hook"),
                        template_path=hook_cfg.get("template"),
                        priority=hook_cfg.get("priority", 10)
                    )
                    print(f"  -> Registered UI Hook '{hook_cfg.get('hook')}' (Priority: {hook_cfg.get('priority', 10)})")
            except Exception as e:
                print(f"  -> Error loading Hooks config from {hooks_path}: {e}")

        self.loaded_modules.append(module_name)
