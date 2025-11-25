import base64
import mimetypes
import os
import re
from typing import Any

from app.config import config
from app.utils.core import tools as utils, logging

MAX_MULTIMODAL_FILE_SIZE_MB = 12
MAX_MULTIMODAL_FILE_SIZE = MAX_MULTIMODAL_FILE_SIZE_MB * 1024 * 1024
def _parse_ignore_patterns(content, current_match, all_matches, i) -> int:
    command_end = current_match.end()
    next_match_start = len(content) if (i + 1 >= len(all_matches)) else all_matches[i + 1].start()
    search_region = content[command_end:next_match_start]

    param_pattern = re.compile(r'\s+(ignore_type|ignore_file|ignore_dir|project_mode|project_feature)=([^\s]+)')
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
    if not isinstance(content, str):
        return content, None, None

    path_pattern = re.compile(r'(image|pdf|audio|code|project)_path=("[^"]+"|\'[^\']+\'|[^\s,;)]+)|(system_prompt)=("[^"]+"|\'[^\']+\'|[^\s,;)]+)')
    matches = list(path_pattern.finditer(content))
    if not matches:
        return content, None, None

    new_content_parts = []
    last_end = 0
    project_path_found = None
    system_context_text = None
    for i, match in enumerate(matches):
        start, end = match.span()
        if start > last_end:
            new_content_parts.append({"type": "text", "text": content[last_end:start]})

        command_end = _parse_ignore_patterns(content, match, matches, i)

        if match.group(3) and match.group(3) == 'system_prompt':
            raw_value = match.group(4)
            if raw_value.startswith(('"', "'")) and raw_value.endswith(raw_value[0]):
                prompt_key = raw_value[1:-1]
            else:
                prompt_key = raw_value

            prompt_data = utils.system_prompts.get(prompt_key)
            if not prompt_data:
                for key, data in utils.system_prompts.items():
                    if key.lower().startswith(prompt_key.lower()):
                        prompt_data = data
                        logging.log(f"Found partial match for system prompt '{prompt_key}': using '{key}'")
                        break

            if prompt_data and prompt_data.get('prompt'):
                system_context_text = prompt_data['prompt']
                logging.log(f"Overriding system prompt with '{prompt_key}'")
            else:
                logging.log(f"Warning: system_prompt '{prompt_key}' not found. No system context will be injected.")

            last_end = command_end
            continue

        file_type = match.group(1)
        raw_path = match.group(2)

        if raw_path.startswith(('"', "'")) and raw_path.endswith(raw_path[0]):
            file_path_str = raw_path[1:-1]
        else:
            file_path_str = raw_path

        expanded_path = os.path.realpath(os.path.expanduser(file_path_str))

        if expanded_path in processed_paths:
            logging.log(f"Skipping duplicate path: {expanded_path}")
            last_end = command_end
            continue
        processed_paths.add(expanded_path)
        if file_type == 'project':
            project_path_found = expanded_path
            project_mode = 'feature'
            search_area = content[match.end():command_end]
            mode_match = re.search(r'\s+project_mode=([^\s]+)', search_area)
            if mode_match:
                project_mode = mode_match.group(1).strip("'\"")

            feature_name = None
            feature_context = ""
            feature_match = re.search(r'\s+project_feature=([^\s]+)', search_area)
            if feature_match:
                feature_name = feature_match.group(1).strip("'\"")
                doc_path_mode = project_mode
                feature_docs_path = os.path.join(expanded_path, '.opengemini', doc_path_mode, feature_name)
                if os.path.isdir(feature_docs_path):
                    if project_mode == 'feature':
                        project_mode = 'feature_continue'

                    feature_context += f"\n\n## 📚 CONTEXT: Continuing work on '{feature_name}' in mode '{doc_path_mode}'\n\n"
                    feature_context += "The following documentation for this task already exists. Review it before continuing.\n\n"

                    try:
                        doc_files = sorted(os.listdir(feature_docs_path))
                        for doc_file in doc_files:
                            if doc_file.endswith('.md'):
                                try:
                                    with open(os.path.join(feature_docs_path, doc_file), 'r',
                                              encoding='utf-8') as f:
                                        file_content = f.read()
                                    feature_context += f"### File: `{doc_file}`\n\n```markdown\n{file_content}\n```\n\n"
                                except Exception as e:
                                    logging.log(f"Error reading documentation file {doc_file} for {feature_name}: {e}")
                    except Exception as e:
                        logging.log(
                            f"Error listing documentation files for {feature_name} in {feature_docs_path}: {e}")

            prompt_data = utils.agent_prompts.get(project_mode)
            if not prompt_data:
                logging.log(f"Warning: project_mode '{project_mode}' not found. Defaulting to 'feature'.")
                project_mode = 'feature'
                prompt_data = AGENT_PROMPTS.get(project_mode)
            if prompt_data and prompt_data.get('prompt'):
                prompt_template = prompt_data['prompt']
                if feature_name:
                    prompt_template = prompt_template.replace('<feature_name>', feature_name)
                system_context_text = prompt_template.format(project_root=file_path_str)
                if feature_context:
                    system_context_text = feature_context + system_context_text
            else:
                logging.log(f"Warning: Could not load prompt for mode '{project_mode}'. No system context will be injected.")
                system_context_text = None
            if not os.path.isdir(expanded_path):
                project_path_found = None
                system_context_text = None
                context_text = f"[Error: Project path '{file_path_str}' not found or is not a directory. All tools remain enabled but the project context is the current working directory.]"
                new_content_parts.append({"type": "text", "text": context_text})

            last_end = command_end
            continue
        if file_type == 'code':
            if not os.path.exists(expanded_path):
                logging.log(f"Code path not found: {expanded_path}")
                new_content_parts.append({
                    "type": "text",
                    "text": f"[Error: Path '{file_path_str}' not found]"
                })
                last_end = command_end
                continue
            code_files = []
            total_size = 0
            MAX_CODE_SIZE = config.MAX_CODE_INJECTION_SIZE_KB * 1024
            ignore_patterns = utils.DEFAULT_CODE_IGNORE_PATTERNS
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
                try:
                    size = os.path.getsize(expanded_path)
                    if size <= MAX_CODE_SIZE:
                        with open(expanded_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content_data = f.read()
                        code_files.append((os.path.basename(expanded_path), content_data))
                        total_size = size
                except Exception as e:
                    logging.log(f"Error reading code file {expanded_path}: {e}")
            elif os.path.isdir(expanded_path):
                import fnmatch
                for root, dirs, files in os.walk(expanded_path):
                    dirs[:] = [d for d in dirs if not any(
                        fnmatch.fnmatch(d, p) for p in ignore_patterns
                    )]

                    for filename in files:
                        if filename.startswith('.'):
                            continue
                        filepath = os.path.join(root, filename)
                        rel_path = os.path.relpath(filepath, expanded_path)
                        if any(fnmatch.fnmatch(rel_path, p) or fnmatch.fnmatch(filename, p) 
                               for p in ignore_patterns):
                            continue

                        try:
                            size = os.path.getsize(filepath)
                            if total_size + size > MAX_CODE_SIZE:
                                logging.log(f"Code injection size limit ({config.MAX_CODE_INJECTION_SIZE_KB} KB) reached. Stopping file collection.")
                                break
                            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                                content_data = f.read()
                            code_files.append((rel_path, content_data))
                            total_size += size

                        except Exception as e:
                            logging.log(f"Error reading {filepath}: {e}")
                            continue

                    if total_size > MAX_CODE_SIZE:
                        break
            if code_files:
                code_parts = []
                code_parts.append(
                    f"\n🛑 **CRITICAL**: You *MUST** start path for {expanded_path}...\n"
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
                logging.log(f"Injected {len(code_files)} code files ({total_size / 1024:.2f} KB)")
            else:
                new_content_parts.append({
                    "type": "text",
                    "text": f"[No code files found in '{file_path_str}']"
                })

            last_end = command_end
            continue
        if not os.path.exists(expanded_path):
            logging.log(f"Local file not found: {expanded_path}")
            new_content_parts.append({"type": "text", "text": content[start:command_end]})
        else:
            try:
                file_size = os.path.getsize(expanded_path)
                if file_size > MAX_MULTIMODAL_FILE_SIZE:
                    logging.log(
                        f"Skipping local file {expanded_path}: size ({file_size / (1024 * 1024):.2f} MB) exceeds limit of {MAX_MULTIMODAL_FILE_SIZE_MB} MB.")
                    new_content_parts.append(
                        {"type": "text",
                         "text": f"[File '{file_path_str}' was skipped as it exceeds the {MAX_MULTIMODAL_FILE_SIZE_MB}MB size limit.]"}
                    )
                else:
                    mime_type, _ = mimetypes.guess_type(expanded_path)
                    if not mime_type:
                        mime_type = 'application/octet-stream'
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
                    logging.log(f"Embedded local file: {expanded_path} as {mime_type}")
            except Exception as e:
                logging.log(f"Error processing local file {expanded_path}: {e}")
                new_content_parts.append(
                    {"type": "text", "text": content[start:command_end]})
        last_end = command_end
    if last_end < len(content):
        new_content_parts.append({"type": "text", "text": content[last_end:]})
    return new_content_parts, project_path_found, system_context_text