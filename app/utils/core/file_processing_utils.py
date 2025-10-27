"""
Utility functions for processing local file paths found in user messages.
"""
import base64
import mimetypes
import os
import re
from app.config import config
from app.utils.core import tools as utils

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

def process_message_for_paths(content: str, processed_paths: set) -> tuple[list | str, str | None]:
    """
    Processes a message content string to find local file paths (e.g.,
    image_path=..., code_path=..., project_path=...), and replaces them with
    appropriate content parts for multimodal input or project context.

    - image_path, pdf_path, audio_path: Embeds files as multimodal data
    - code_path: Recursively loads all code files as text context
    - project_path: Activates tools and provides project structure for agent

    Args:
        content: The message content string.
        processed_paths: A set for tracking already processed file/project paths to avoid duplicates across multiple messages.

    Returns:
        A tuple containing:
        - The processed content (either a list of parts for multimodal input or the original string if no paths are found).
        - The project root path if `project_path=` was found, otherwise None.
    """
    if not isinstance(content, str):
        return content, None

    # Improved regex to handle quoted paths and avoid trailing punctuation
    path_pattern = re.compile(r'(image|pdf|audio|code|project)_path=("[^"]+"|\'[^\']+\'|[^\s,;)]+)')
    matches = list(path_pattern.finditer(content))

    if not matches:
        return content, None

    new_content_parts = []
    last_end = 0
    project_path_found = None
    # processed_paths = set() # Now an argument

    for i, match in enumerate(matches):
        start, end = match.span()
        if start > last_end:
            new_content_parts.append({"type": "text", "text": content[last_end:start]})

        # Parse potential parameters to correctly calculate command_end
        command_end = _parse_ignore_patterns(content, match, matches, i)

        file_type = match.group(1)
        raw_path = match.group(2)

        # Strip quotes if they exist to handle paths with spaces
        if raw_path.startswith(('"', "'")) and raw_path.endswith(raw_path[0]):
            file_path_str = raw_path[1:-1]
        else:
            file_path_str = raw_path

        expanded_path = os.path.realpath(os.path.expanduser(file_path_str))

        if expanded_path in processed_paths:
            utils.log(f"Skipping duplicate path: {expanded_path}")
            last_end = command_end
            continue
        processed_paths.add(expanded_path)

        if file_type == 'project':
            # project_path: Activate tools and provide project structure for agent
            project_path_found = expanded_path

            # Insert detailed context message for the model
            context_text = (
                f"🚀 **PROJECT MODE ACTIVATED** for project root: '{file_path_str}'\n\n"
                f"The project context is set. Start by using `list_files(path='.')` to explore.\n\n"
                f"**Available Tools:**\n"
                f"• Navigation: `list_files`, `get_file_content`, `get_code_snippet`, `search_codebase`\n"
                f"• Analysis: `analyze_file_structure`, `analyze_project_structure`, `get_file_stats`, `find_symbol`, `get_dependencies`\n"
                f"• Modification: `apply_patch`, `create_file`, `write_file`\n"
                f"• Execution: `execute_command`\n"
                f"• Git: `git_status`, `git_log`, `git_diff`, `git_show`, `git_blame`, `list_recent_changes`\n\n"
                f"Your confirmation is required before using any tools.\n"
            )

            # Check if path is valid for proactive feedback
            if not os.path.isdir(expanded_path):
                project_path_found = None # Do not set context if path is invalid
                context_text = f"[Error: Project path '{file_path_str}' not found or is not a directory. All tools remain enabled but the project context is the current working directory.]"

            new_content_parts.append({"type": "text", "text": context_text})

            last_end = command_end
            continue

        if file_type == 'code':
            # code_path: Recursively load all code files as text
            if not os.path.exists(expanded_path):
                utils.log(f"Code path not found: {expanded_path}")
                new_content_parts.append({
                    "type": "text",
                    "text": f"[Error: Path '{file_path_str}' not found]"
                })
                last_end = command_end
                continue

            # Collect code files
            code_files = []
            total_size = 0
            MAX_CODE_SIZE = config.MAX_CODE_INJECTION_SIZE_KB * 1024

            # Default ignore patterns for code
            ignore_patterns = utils.DEFAULT_CODE_IGNORE_PATTERNS

            # Parse ignore patterns from prompt
            param_pattern = re.compile(r'\s+(ignore_type|ignore_file|ignore_dir)=([^\s]+)')
            search_region = content[end:command_end]
            for param_match in param_pattern.finditer(search_region):
                ignore_key = param_match.group(1)
                value = param_match.group(2)
                patterns = value.split('|')
                
                if ignore_key == 'ignore_type':
                    ignore_patterns.extend([f"*.{p}" for p in patterns])
                else:
                    ignore_patterns.extend(patterns)

            if os.path.isfile(expanded_path):
                # Single file
                try:
                    size = os.path.getsize(expanded_path)
                    if size <= MAX_CODE_SIZE:
                        with open(expanded_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content_data = f.read()
                        code_files.append((os.path.basename(expanded_path), content_data))
                        total_size = size
                except Exception as e:
                    utils.log(f"Error reading code file {expanded_path}: {e}")

            elif os.path.isdir(expanded_path):
                # Directory - recursively collect files
                import fnmatch
                
                for root, dirs, files in os.walk(expanded_path):
                    # Filter ignored directories
                    dirs[:] = [d for d in dirs if not any(
                        fnmatch.fnmatch(d, p) for p in ignore_patterns
                    )]

                    for filename in files:
                        if filename.startswith('.'):
                            continue

                        filepath = os.path.join(root, filename)
                        rel_path = os.path.relpath(filepath, expanded_path)

                        # Check ignore patterns
                        if any(fnmatch.fnmatch(rel_path, p) or fnmatch.fnmatch(filename, p) 
                               for p in ignore_patterns):
                            continue

                        try:
                            size = os.path.getsize(filepath)
                            if total_size + size > MAX_CODE_SIZE:
                                utils.log(f"Code injection size limit ({config.MAX_CODE_INJECTION_SIZE_KB} KB) reached. Stopping file collection.")
                                break

                            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                                content_data = f.read()
                            
                            code_files.append((rel_path, content_data))
                            total_size += size

                        except Exception as e:
                            utils.log(f"Error reading {filepath}: {e}")
                            continue

                    if total_size > MAX_CODE_SIZE:
                        break

            if code_files:
                # Format code files for injection
                code_parts = []
                code_parts.append(
                    f"📝 **CODE CONTEXT LOADED** from: '{file_path_str}'\n"
                    f"Total: {len(code_files)} files, {total_size / 1024:.2f} KB\n\n"
                )

                for rel_path, file_content in code_files:
                    ext = os.path.splitext(rel_path)[1].lstrip('.')
                    code_parts.append(
                        f"**File:** `{rel_path}`\n"
                        f"```{ext}\n{file_content}\n```\n\n"
                    )

                new_content_parts.append({
                    "type": "text",
                    "text": "".join(code_parts)
                })
                utils.log(f"Injected {len(code_files)} code files ({total_size / 1024:.2f} KB)")
            else:
                new_content_parts.append({
                    "type": "text",
                    "text": f"[No code files found in '{file_path_str}']"
                })

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

    return new_content_parts, project_path_found