import os
import json
from app.utils.core.logging import log


def _resolve_path(file_path: str) -> str | None:
    """Checks for a file at a given path, then falls back to checking relative to CWD."""
    path_to_check = file_path
    if not os.path.exists(path_to_check):
        path_to_check = os.path.join(os.getcwd(), file_path)

    if not os.path.exists(path_to_check):
        return None
    return path_to_check


def load_json_file(file_path: str, default=None):
    """Loads a JSON file, checking both relative and CWD-based paths."""
    if default is None:
        default = {}

    resolved_path = _resolve_path(file_path)
    if not resolved_path:
        log(f"Warning: File not found at '{file_path}'. Using default.")
        return default

    try:
        with open(resolved_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # Handle potential BOM (Byte Order Mark) at the start of the file
            if content.startswith('\ufeff'):
                content = content.lstrip('\ufeff')
            return json.loads(content)
    except (json.JSONDecodeError, IOError) as e:
        log(f"Error loading JSON from '{resolved_path}': {e}. Using default.")
        return default


def load_text_file_lines(file_path: str, default=None):
    """Loads a text file and returns a list of stripped lines, ignoring comments."""
    if default is None:
        default = []

    resolved_path = _resolve_path(file_path)
    if not resolved_path:
        log(f"Warning: File not found at '{file_path}'. Using default.")
        return default

    try:
        with open(resolved_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except IOError as e:
        log(f"Error reading file '{resolved_path}': {e}. Using default.")
        return default
