"""
Utility functions for processing local file paths found in user messages.
"""
import os
import re
import base64
import mimetypes
import fnmatch
from app import utils


def process_message_for_paths(content: str):
    """
    Processes a message content string to find local file paths (e.g., image_path=...),
    and replaces them with appropriate content parts for multimodal input.
    If paths are found, returns a list of parts. Otherwise, returns the original string.
    """
    if not isinstance(content, str):
        return content

    path_pattern = re.compile(r'(image|pdf|audio|code)_path=([^\s]+)')
    matches = list(path_pattern.finditer(content))

    if not matches:
        return content

    new_content_parts = []
    last_end = 0
    for i, match in enumerate(matches):
        start, end = match.span()
        # Add preceding text part
        if start > last_end:
            new_content_parts.append({"type": "text", "text": content[last_end:start]})

        # --- Parse ignore patterns ---
        ignore_patterns_from_prompt = []
        command_end = end  # The end of the whole command defaults to end of path match

        # Define search area for ignore patterns: from end of path to start of next path
        next_match_start = len(content) if (i + 1 >= len(matches)) else matches[i + 1].start()
        search_region = content[end:next_match_start]

        # Find all 'ignore_x=...' parameters immediately following the path.
        param_pattern = re.compile(r'\s+(ignore_type|ignore_file|ignore_dir)=([^\s]+)')
        last_param_end = 0
        remaining_search_region = search_region
        while True:
            param_match = param_pattern.match(remaining_search_region)
            if not param_match:
                break

            ignore_key = param_match.group(1)
            value = param_match.group(2)
            patterns = value.split('|')

            if ignore_key == 'ignore_type':
                # For ignore_type=py|js, create patterns like *.py, *.js
                ignore_patterns_from_prompt.extend([f"*.{p}" for p in patterns])
            else:
                # For ignore_file and ignore_dir, use patterns as-is
                ignore_patterns_from_prompt.extend(patterns)

            match_end_pos = param_match.end()
            last_param_end += match_end_pos
            remaining_search_region = remaining_search_region[match_end_pos:]

        # Update the end of the full command (path + all ignores)
        if last_param_end > 0:
            command_end = end + last_param_end

        file_type = match.group(1)
        file_path_str = match.group(2)
        expanded_path = os.path.expanduser(file_path_str)

        if os.path.exists(expanded_path):
            if file_type == 'code':
                # Handle code import from file or directory, optionally zipping large volumes
                MAX_TEXT_SIZE_KB = 512
                MAX_BINARY_SIZE_KB = 8192  # 8 MB limit for binary parts

                candidate_files = []
                total_raw_size = 0

                # Patterns for files and dirs to ignore. Supports fnmatch.
                ignore_patterns = [
                    # Common ignores for code projects
                    '.git', '__pycache__', 'node_modules', 'venv', '.venv',
                    'build', 'dist', 'target', 'out', 'coverage', '.nyc_output', '*.egg-info', 'bin', 'obj', 'pkg',
                    # pkg for Go modules
                    '.idea', '.vscode', '.cache', '.pytest_cache',
                    '.DS_Store', 'Thumbs.db',  # OS/Editor temporary files
                    '*.log', '*.swp', '*.pyc', '*~', '*.bak', '*.tmp',
                    # Archives and binaries are not useful context
                    '*.zip', '*.tar.gz', '*.rar', '*.7z',
                    '*.o', '*.so', '*.dll', '*.exe', '*.a', '*.lib', '*.dylib',  # Compiled C/C++/Go libraries
                    '*.class', '*.jar', '*.war',
                    '*.pdb', '*.nupkg', '*.deps.json', '*.runtimeconfig.json',  # .NET artifacts
                    # Database files (often large binary structures)
                    '*.db', '*.sqlite', '*.sqlite3', 'data.mdb', 'lock.mdb',
                    # Images are handled by image_path, not code_path
                    '*.png', '*.jpg', '*.jpeg', '*.gif', '*.svg',
                    # Fonts and other binary assets
                    '*.woff', '*.woff2', '*.ttf', '*.otf', '*.eot', '*.ico',
                    '*.mp3', '*.wav', '*.mp4', '*.mov',
                    # Minified assets and source maps
                    '*.min.js', '*.min.css', '*.map',
                    # Lock files can be huge and less useful than manifests
                    'package-lock-v1.json', 'package-lock.json', 'yarn.lock', 'poetry.lock', 'Pipfile.lock',
                ]
                ignore_patterns.extend(ignore_patterns_from_prompt)

                # 1. Collect all files and calculate total size
                if os.path.isfile(expanded_path):
                    filename = os.path.basename(expanded_path)
                    # Check if the single file should be ignored
                    if not (filename.startswith('.') or any(fnmatch.fnmatch(filename, p) for p in ignore_patterns)):
                        try:
                            size = os.path.getsize(expanded_path)
                            if size <= MAX_BINARY_SIZE_KB * 1024:
                                candidate_files.append((expanded_path, filename))
                                total_raw_size += size
                        except Exception as e:
                            utils.log(f"Error checking file size {expanded_path}: {e}")

                elif os.path.isdir(expanded_path):
                    for root, dirs, files in os.walk(expanded_path, topdown=True):
                        # Get relative path for matching against patterns
                        rel_root = os.path.relpath(root, expanded_path)
                        if rel_root == '.':
                            rel_root = ''

                        # Filter out ignored and hidden directories from further traversal
                        dirs[:] = [
                            d for d in dirs if not (
                                    d.startswith('.') or
                                    any(fnmatch.fnmatch(os.path.join(rel_root, d).replace(os.sep, '/'),
                                                        p) or fnmatch.fnmatch(d, p) for p in ignore_patterns)
                            )
                        ]

                        for filename in files:
                            # Skip hidden files
                            if filename.startswith('.'):
                                continue

                            # Check if file path or name matches any ignore pattern
                            rel_filepath = os.path.join(rel_root, filename).replace(os.sep, '/')
                            if any(fnmatch.fnmatch(rel_filepath, p) or fnmatch.fnmatch(filename, p) for p in
                                   ignore_patterns):
                                continue

                            file_path = os.path.join(root, filename)

                            try:
                                size = os.path.getsize(file_path)
                                if total_raw_size + size <= MAX_BINARY_SIZE_KB * 1024:
                                    candidate_files.append((file_path, os.path.relpath(file_path, expanded_path)))
                                    total_raw_size += size
                                elif total_raw_size == 0:
                                    utils.log(
                                        f"Code import skipped: File {file_path} exceeds maximum binary limit of {MAX_BINARY_SIZE_KB} KB.")
                                    candidate_files = []
                                    total_raw_size = 0
                                    break
                                else:
                                    utils.log(
                                        f"Code import stopped: Adding {file_path} would exceed maximum binary limit of {MAX_BINARY_SIZE_KB} KB.")
                                    break  # Stop adding files

                            except Exception as e:
                                utils.log(f"Error checking file size {file_path}: {e}")
                                continue  # Skip problematic file

                        if total_raw_size > MAX_BINARY_SIZE_KB * 1024:
                            break  # Stop os.walk loop

                if not candidate_files:
                    msg = f"[Could not import code from {file_path_str}: No files found, or exceeded {MAX_BINARY_SIZE_KB} KB limit.]"
                    utils.log(msg)
                    if os.path.isfile(expanded_path) or os.path.isdir(expanded_path):
                        new_content_parts.append({"type": "text", "text": msg})
                    else:
                        new_content_parts.append({"type": "text", "text": content[start:command_end]})
                    last_end = command_end
                    continue

                # 2. Text Injection Mode (with multi-part, binary skipping, and dir tree)
                def is_likely_binary(fpath, chunk_size=1024):
                    """
                    Check if a file is likely binary by reading a chunk and checking for null bytes
                    or a high percentage of non-text characters.
                    """
                    text_chars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7f})
                    try:
                        with open(fpath, 'rb') as f:
                            chunk = f.read(chunk_size)
                        if not chunk:
                            return False  # Empty file is not binary
                        if b'\0' in chunk:
                            return True  # Null bytes are a strong indicator
                        non_text_count = sum(1 for byte in chunk if byte not in text_chars)
                        return non_text_count / len(chunk) > 0.3  # Heuristic: >30% non-text chars
                    except Exception:
                        return True  # Assume binary on read error

                def generate_tree(file_paths, root_name):
                    """Generates an ASCII directory tree from a list of relative file paths."""
                    tree_dict = {}
                    for path_str in file_paths:
                        parts = path_str.split(os.sep)
                        current_level = tree_dict
                        for part in parts:
                            if part not in current_level:
                                current_level[part] = {}
                            current_level = current_level[part]

                    def build_tree_lines(d, prefix=''):
                        lines = []
                        entries = sorted(d.keys())
                        for i, entry in enumerate(entries):
                            connector = '├── ' if i < len(entries) - 1 else '└── '
                            lines.append(f"{prefix}{connector}{entry}")
                            if d[entry]:
                                extension = '│   ' if i < len(entries) - 1 else '    '
                                lines.extend(build_tree_lines(d[entry], prefix + extension))
                        return lines

                    tree_lines = [root_name]
                    tree_lines.extend(build_tree_lines(tree_dict))
                    return "\n".join(tree_lines)

                relative_paths = sorted([rel_path for _, rel_path in candidate_files])
                tree_root_name = os.path.basename(os.path.normpath(expanded_path))
                directory_tree_str = generate_tree(relative_paths, tree_root_name)
                tree_header = f"Project structure for '{tree_root_name}':\n```\n{directory_tree_str}\n```\n\n"

                MAX_PART_SIZE = MAX_TEXT_SIZE_KB * 1024
                current_text_part = tree_header
                total_parts = []
                files_processed_count = 0

                for fpath, relative_path in candidate_files:
                    try:
                        if is_likely_binary(fpath):
                            utils.log(f"Skipping likely binary file: {relative_path}")
                            continue

                        file_size_bytes = os.path.getsize(fpath)

                        with open(fpath, 'r', encoding='utf8', errors='ignore') as f:
                            code_content = f.read()

                        _, extension = os.path.splitext(fpath)
                        lang = extension.lstrip('.') if extension else ''

                        injected_code_snippet = (
                            f"\n--- Code File: {relative_path} ({file_size_bytes / 1024:.2f} KB) ---\n"
                            f"```{lang}\n{code_content}\n```\n")

                        snippet_bytes = injected_code_snippet.encode('utf-8')
                        snippet_size = len(snippet_bytes)
                        current_part_bytes_len = len(current_text_part.encode('utf-8'))

                        if current_part_bytes_len > 0 and current_part_bytes_len + snippet_size > MAX_PART_SIZE:
                            total_parts.append(current_text_part)
                            current_text_part = ""  # Start a new part

                        if snippet_size > MAX_PART_SIZE:
                            utils.log(
                                f"Warning: Single file '{relative_path}' formatted size ({snippet_size / 1024:.2f} KB) exceeds part limit. Sending as standalone part.")
                            if current_text_part:  # Flush anything before this large file
                                total_parts.append(current_text_part)
                            total_parts.append(injected_code_snippet)
                            current_text_part = ""
                        else:
                            current_text_part += injected_code_snippet

                        files_processed_count += 1

                    except Exception as e:
                        utils.log(f"Error processing code file {fpath}: {e}")

                if current_text_part:
                    total_parts.append(current_text_part)

                if not total_parts:
                    msg = f"[Code import from '{file_path_str}' failed or all files were binary.]"
                    utils.log(msg)
                    new_content_parts.append({"type": "text", "text": msg})
                else:
                    mode_description = "MULTI-PART TEXT MODE" if len(total_parts) > 1 else "TEXT MODE"
                    initial_header = (f"The following context contains code files from '{file_path_str}' "
                                      f"(Total size: {total_raw_size / 1024:.2f} KB, {mode_description}).\n\n")

                    # Prepend initial header, which might merge with the tree header
                    if total_parts[0].startswith("Project structure"):
                        total_parts[0] = initial_header + total_parts[0]
                    else:  # Case where first part is just code (e.g., single massive file)
                        total_parts[0] = initial_header + "\n" + total_parts[0]

                    for idx, part_text in enumerate(total_parts):
                        if len(total_parts) > 1 and idx > 0:
                            part_header = (f"\n--- Continuation of code context for '{file_path_str}' "
                                           f"(Part {idx + 1}/{len(total_parts)}) ---\n")
                            part_text = part_header + part_text
                        new_content_parts.append({"type": "text", "text": part_text})

                    utils.log(
                        f"Successfully injected {files_processed_count} code files across {len(total_parts)} text parts.")

                last_end = command_end
                continue  # Skip multimodal logic below

        try:
            mime_type, _ = mimetypes.guess_type(expanded_path)
            if not mime_type:
                mime_type = 'application/octet-stream'  # Fallback
                if expanded_path.lower().endswith('.pdf'):
                    mime_type = 'application/pdf'

            with open(expanded_path, 'rb') as f:
                file_bytes = f.read()
            encoded_data = base64.b64encode(file_bytes).decode('utf-8')

            if file_type == 'image':
                # Create a data URI that the existing 'image_url' processing can handle
                data_uri = f"data:{mime_type};base64,{encoded_data}"
                new_content_parts.append({
                    "type": "image_url",  # Treated as an image_url part with a data URI
                    "image_url": {"url": data_uri}
                })
            elif file_type == 'pdf' or file_type == 'audio':
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
    else:
        utils.log(f"Local file not found: {expanded_path}")
        new_content_parts.append(
            {"type": "text", "text": content[start:command_end]})  # Keep original text if not found

    last_end = command_end
    # Add any remaining text after the last match
    if last_end < len(content):
        new_content_parts.append({"type": "text", "text": content[last_end:]})

    return new_content_parts
