"""
Utility functions for processing local file paths found in user messages.
"""
import base64
import mimetypes
import os
import re
from app import utils
from app.mcp_handler import list_files, set_project_root

# --- Constants ---
MAX_MULTIMODAL_FILE_SIZE_MB = 12
MAX_MULTIMODAL_FILE_SIZE = MAX_MULTIMODAL_FILE_SIZE_MB * 1024 * 1024


def _parse_ignore_patterns(content, current_match, all_matches, i) -> int:
    """
    Parses ignore_* parameters following a path command and returns the end index
    of the entire command (path + parameters) for removal/replacement.
    """
    command_end = current_match.end()

    next_match_start = len(content) if (i + 1 >= len(all_matches)) else all_matches[i + 1].start()
    search_region = content[command_end:next_match_start]

    # Pattern captures ignore_*=value parameters
    param_pattern = re.compile(r'\s+(ignore_type|ignore_file|ignore_dir)=([^\s]+)')
    last_param_end = 0
    remaining_search_region = search_region
    while True:
        param_match = param_pattern.match(remaining_search_region)
        if not param_match:
            break

        # We don't need the patterns for agentic navigation, just the length of the match
        match_end_pos = param_match.end()
        last_param_end += match_end_pos
        remaining_search_region = remaining_search_region[match_end_pos:]

    if last_param_end > 0:
        command_end += last_param_end

    return command_end

def process_message_for_paths(content: str) -> tuple[list, bool] | str:
    """
    Processes a message content string to find local file paths (e.g.,
    image_path=...), and replaces them with appropriate content parts for
    multimodal input.

    If paths are found, returns (list of parts, bool code_tools_requested).
    Otherwise, returns the original string.
    """
    if not isinstance(content, str):
        return content

    path_pattern = re.compile(r'(image|pdf|audio|code)_path=([^\s]+)')
    matches = list(path_pattern.finditer(content))

    if not matches:
        return content

    new_content_parts = []
    last_end = 0
    code_path_found = None

    for i, match in enumerate(matches):
        start, end = match.span()
        if start > last_end:
            new_content_parts.append({"type": "text", "text": content[last_end:start]})

        # Parse potential parameters to correctly calculate command_end
        command_end = _parse_ignore_patterns(content, match, matches, i)

        file_type = match.group(1)
        file_path_str = match.group(2)
        # expanded_path is only needed for multimodal file checks
        expanded_path = os.path.expanduser(file_path_str)

        if file_type == 'code':
            # This is the primary path for setting the project context for the agent.
            # We extract the path, which will be used to set the cwd for all subsequent tool calls.
            code_path_found = os.path.expanduser(file_path_str)

            # Proactively get the file tree for the requested path using the new context.
            # We list files from the root of the new path (`.`).
            with set_project_root(code_path_found):
                project_tree = list_files(path=".", max_depth=3)

            # Insert a more detailed context message for the model.
            context_text = (
                f"The user has requested code context for the path '{file_path_str}'. "
                f"Here is the project's file structure (limited to a depth of 3 for brevity):\n\n"
                f"{project_tree}\n\n"
                f"The agent should now analyze this tree. If more detail is needed in a specific subdirectory, use the `list_files` tool again with a deeper path and/or a larger `max_depth`. "
                f"Otherwise, use other tools like `analyze_file_structure` or `get_file_content` to inspect files."
            )
            new_content_parts.append({"type": "text", "text": context_text})

            last_end = command_end
            continue

        # Multimodal file handling (image, pdf, audio)
        if not os.path.exists(expanded_path):
            utils.log(f"Local file not found: {expanded_path}")
            new_content_parts.append({"type": "text", "text": content[start:command_end]})
        else:
            try:
                file_size = os.path.getsize(expanded_path)
                if file_size > MAX_MULTIMODAL_FILE_SIZE:
                    utils.log(
                        f"Skipping local file {expanded_path}: size ({file_size / (1024 * 1024):.2f} MB) exceeds limit of {MAX_MULTIMODAL_FILE_SIZE_MB} MB.")
                    new_content_parts.append(
                        {"type": "text",
                         "text": f"[File '{file_path_str}' was skipped as it exceeds the {MAX_MULTIMODAL_FILE_SIZE_MB}MB size limit.]"}
                    )
                else:
                    mime_type, _ = mimetypes.guess_type(expanded_path)
                    if not mime_type:
                        mime_type = 'application/octet-stream'  # Fallback
                        if expanded_path.lower().endswith('.pdf'):
                            mime_type = 'application/pdf'

                    with open(expanded_path, 'rb') as f:
                        file_bytes = f.read()
                    encoded_data = base64.b64encode(file_bytes).decode('utf-8')

                    if file_type == 'image':
                        data_uri = f"data:{mime_type};base64,{encoded_data}"
                        new_content_parts.append({
                            "type": "image_url",
                            "image_url": {"url": data_uri}
                        })
                    elif file_type in ['pdf', 'audio']:
                        new_content_parts.append({
                            "type": "inline_data",
                            "source": {
                                "media_type": mime_type,
                                "data": encoded_data
                            }
                        })
                    utils.log(f"Embedded local file: {expanded_path} as {mime_type}")
            except Exception as e:
                utils.log(f"Error processing local file {expanded_path}: {e}")
                new_content_parts.append(
                    {"type": "text", "text": content[start:command_end]})  # Keep original text on error

        last_end = command_end

    # Add any remaining text after the last match
    if last_end < len(content):
        new_content_parts.append({"type": "text", "text": content[last_end:]})

    return new_content_parts, code_path_found