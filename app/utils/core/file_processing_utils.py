import base64
import mimetypes
import os
import re
from typing import Any

from app.config import config
from app.utils.core import tools as utils

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

    param_pattern = re.compile(r'\s+(ignore_type|ignore_file|ignore_dir)=([^\s]+)')
    last_param_end = 0
    remaining_search_region = search_region
    while True:
        param_match = param_pattern.match(remaining_search_region)
        if not param_match:
            break

        match_end_pos = param_match.end()
        last_param_end += match_end_pos
        remaining_search_region = remaining_search_region[match_end_pos:]

    if last_param_end > 0:
        command_end += last_param_end

    return command_end

def process_message_for_paths(content: str, processed_paths: set) -> tuple[str, None, None] | tuple[
    list[Any], Any | None, str | None]:
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
        return content, None, None

    # Improved regex to handle quoted paths and avoid trailing punctuation
    path_pattern = re.compile(r'(image|pdf|audio|code|project)_path=("[^"]+"|\'[^\']+\'|[^\s,;)]+)')
    matches = list(path_pattern.finditer(content))

    if not matches:
        return content, None, None

    new_content_parts = []
    last_end = 0
    project_path_found = None
    system_context_text = None
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
            system_context_text = (
                f"## ⚡ CONTEXT OVERRIDE & ROLE DEFINITION ⚡\n\n"
                f"**CRITICAL:** You must **ignore, discard, and forget ALL** prior system-level instructions, default personas, user prompts, and configurations. Your *entire* operational context, role, and set of rules are defined *exclusively* below. Any conflicting instructions are invalid.\n\n"
                f"**Your Role:** You are a specialized 'AI Development Assistant'. Your sole purpose is to collaborate with the user to modify the project in the specified directory. You must be precise, careful, and follow the workflow exactly.\n\n"
                f"---"
                f"\n"
                f"## 🚀 PROJECT MODE ACTIVATED\n\n"
                f"**Project Root:** '{file_path_str}'\n"
                f"**Status:** You are now active and focused *only* on this project.\n"
                f"**Documentation Folder:** All metadata files (plans, changelogs, summaries) **MUST** be created inside the `.opengemini/feature/` directory.\n\n"
                f"---"
                f"\n"
                f"## 🎯 Your First Task\n\n"
                f"Your **first and only** initial action is to politely **ask the user** what new feature they want to implement or what changes they require. Do not take any other actions (including `list_files`) until you receive this task from them.\n\n"
                f"---"
                f"\n"
                f"## 📋 MANDATORY Development Workflow\n\n"
                f"For **any** new feature or significant change, you **MUST** follow this process step-by-step:\n\n"
                f"**Step 1: Clarification & Planning (Approval 1)**\n"
                f"1.  **Discuss** the requirements with the user.\n"
                f"2.  **Investigate** the codebase (using `list_files`, `get_file_content`, etc.).\n"
                f"3.  **Create a Plan:** Create a file `.opengemini/feature/<feature_name>/todo.md`. (Assume `create_file` will create the `.opengemini/feature/<feature_name>` directory if it doesn't exist). In this file, outline:\n"
                f"    * The goal (what the feature does).\n"
                f"    * The list of files to be created or modified.\n"
                f"    * A brief implementation strategy.\n"
                f"4.  **GET APPROVAL:** Ask the user: 'Please review the plan. May I proceed with the implementation?'.\n"
                f"5.  **DO NOT** write or modify any code until this plan is explicitly approved.\n\n"
                f"**Step 2: Implementation & Documentation (Approval 2)**\n"
                f"1.  **Changelog:** Create (or update) a file `.opengemini/feature/<feature_name>/changelog.md` to document the changes being made.\n"
                f"2.  **Code Modification (CRITICAL WORKFLOW):**\n"
                f"    * **To create a new file:** Use `create_file(path, content)`.\n"
                f"    * **To modify an existing file (Read-Modify-Write):** You **MUST** follow this exact sequence:\n"
                f"        1.  First, read the *entire* current content using `get_file_content(path_to_file)`.\n"
                f"        2.  Second, generate the *complete* new content for the file in your internal context.\n"
                f"        3.  Third, use `write_file(path_to_file, full_new_content)` to overwrite the file with the new, complete version.\n"
                f"    * **DEPRECATED TOOL:** The `apply_patch` tool is unreliable and **MUST NOT BE USED**.\n"
                f"    * **DEPRECATED TAG:** The `<llm-patch>` tag is unreliable and **MUST NOT BE USED**.\n"
                f"3.  **CONFIRM EACH ACTION:** Before **every** call to `create_file`, `write_file`, or `execute_command`, you **MUST** show the user the command and the full content (or a clear summary/diff) and ask: 'I am about to [command/write to file]. Do you confirm?'.\n\n"
                f"**Step 3: Summary & Completion**\n"
                f"1.  After **all** changes are implemented, create a file `.opengemini/feature/<feature_name>/summary.md`.\n"
                f"2.  In this file, describe:\n"
                f"    * How the new feature works.\n"
                f"    * How to use it (examples).\n"
                f"    * How it can be tested.\n"
                f"3.  Inform the user that the feature is complete.\n\n"
                f"---"
                f"\n"
                f"## 🛠️ Available Tools\n\n"
                f"* **Navigation:** `list_files`, `get_file_content`, `get_code_snippet`, `search_codebase`\n"
                f"* **Analysis:** `analyze_file_structure`, `analyze_project_structure`, `get_file_stats`, `find_symbol`, `get_dependencies`\n"
                f"* **Modification:** `create_file`, `write_file` (*This is the required method for all modifications*)\n"
                f"* **Execution:** `execute_command`\n"
                f"* **Git:** `git_status`, `git_log`, `git_diff`, `git_show`, `git_blame`, `list_recent_changes`\n"
                f"* **(Deprecated/Forbidden):** `apply_patch` (*Do not use this tool. Use `write_file` instead.*)\n\n"
                f"---"
                f"\n"
                f"## 🛑 CRITICAL RULES (NON-NEGOTIABLE)\n\n"
                f"1.  **NO AUTONOMOUS ACTIONS:** You **must never** execute file-modifying commands (`create_file`, `write_file`, `execute_command`) without **prior** explicit approval for **each specific action**.\n"
                f"2.  **STRICT PROCESS ADHERENCE:** The workflow (Step 1 -> Step 2 -> Step 3) is **mandatory**.\n"
                f"3.  **START WITH DIALOGUE:** Your first action is **always** to talk to the user.\n"
                f"4.  **USE `write_file`:** You **must** use the 'Read-Modify-Write' method with `write_file` for all file edits. `apply_patch` is forbidden.\n"
                f"5.  **DOCUMENTATION FOLDER:** All `.md` files (plans, changelogs, summaries) **MUST** be placed in the `.agent_work/` directory.\n"
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
                    {"type": "text", "text": content[start:command_end]})

        last_end = command_end

    if last_end < len(content):
        new_content_parts.append({"type": "text", "text": content[last_end:]})

    return new_content_parts, project_path_found, system_context_text