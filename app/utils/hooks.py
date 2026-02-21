from typing import List, Dict, Any
from flask import render_template
import traceback

class HookManager:
    """
    Manages UI template injections across the application.
    Modules can register templates to specific string hook points.
    """
    def __init__(self):
        # Dictionary mapping hook_names to a list of dicts: {"template": str, "priority": int}
        self._hooks: Dict[str, List[Dict[str, Any]]] = {}

    def register_hook(self, hook_name: str, template_path: str, priority: int = 10) -> None:
        """
        Register a template to a specific hook point.
        Higher priority numbers are rendered later.
        """
        if hook_name not in self._hooks:
            self._hooks[hook_name] = []
            
        self._hooks[hook_name].append({
            "template": template_path,
            "priority": priority
        })
        
        # Keep the list sorted by priority so it renders in order
        self._hooks[hook_name].sort(key=lambda x: x["priority"])

    def render_hooks(self, hook_name: str, **kwargs: Any) -> str:
        """
        Renders all templates registered to the given hook point.
        This function is intended to be injected into Jinja globals.
        """
        if hook_name not in self._hooks:
            return ""

        rendered_html = []
        for hook_entry in self._hooks[hook_name]:
            try:
                # Render the template with the provided context kwargs
                html = render_template(hook_entry["template"], **kwargs)
                rendered_html.append(html)
            except Exception as e:
                # Log the error but don't break the entire page rendering
                print(f"Error rendering hook '{hook_name}' template '{hook_entry['template']}': {e}")
                traceback.print_exc()

        return "\n".join(rendered_html)

# Global singleton instance
hooks = HookManager()

def render_hooks_global(hook_name: str, **kwargs: Any) -> str:
    """
    Wrapper function to be injected into Flask Jinja globals.
    Allows templates to do: {{ render_hooks('my_hook', context_var=value) | safe }}
    """
    return hooks.render_hooks(hook_name, **kwargs)
