import os
import tempfile
import json
import subprocess
import shlex
import select
import threading
import time
import fnmatch
import ast
import re
from app.utils.core.logging import log
from app.utils.core.tools import load_code_ignore_patterns
from contextlib import contextmanager
from app.utils.core import optimization
from app.utils.core.optimization import record_tool_call
from app.utils.core import optimization_utils
BUILTIN_TOOL_NAME = "__builtin_code_navigator"
_request_context = threading.local()
def get_project_root() -> str:
    return getattr(_request_context, 'project_root', os.path.realpath(os.getcwd()))
@contextmanager
def set_project_root(path: str | None):
    original_path = getattr(_request_context, 'project_root', None)
    if path and os.path.isdir(os.path.expanduser(path)):
        _request_context.project_root = os.path.realpath(os.path.expanduser(path))
    else:
        _request_context.project_root = os.path.realpath(os.getcwd())
    try:
        yield
    except Exception:
        _request_context.project_root = None
        raise
_ignore_patterns_cache = {}
def get_code_ignore_patterns() -> list[str]:
    project_root = get_project_root()
    if project_root not in _ignore_patterns_cache:
        patterns = load_code_ignore_patterns(project_root)
        _ignore_patterns_cache[project_root] = patterns
        return patterns
    return _ignore_patterns_cache[project_root]
def _safe_path_resolve(path: str) -> str | None:
    from app.config import config
    project_root = get_project_root()
    full_path = os.path.join(project_root, path)
    resolved_path = os.path.realpath(full_path)
    if not resolved_path.startswith(project_root):
        log(f"Security violation attempt: Path '{path}' resolves outside project root ({resolved_path} vs {project_root}).")
        return None
    if config.ALLOWED_CODE_PATHS:
        is_allowed = False
        for allowed_path in config.ALLOWED_CODE_PATHS:
            if resolved_path.startswith(allowed_path):
                is_allowed = True
                break
        if not is_allowed:
            log(f"Access denied: Path '{path}' ({resolved_path}) is not within allowed directories: {config.ALLOWED_CODE_PATHS}")
            return None
    return resolved_path
def _generate_tree_local(file_paths, root_name):
    tree_dict = {}
    for path_str in file_paths:
        path_str = path_str.replace(os.sep, '/')
        parts = path_str.split('/')
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
def list_files(path: str = ".", max_depth: int = -1) -> str:
    from app.config import config
    resolved_path = _safe_path_resolve(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return f"Error: Path '{path}' not found or inaccessible."
    if os.path.isfile(resolved_path):
        return f"Path '{path}' is a file, not a directory. Use get_file_content."
    if config.STREAMING_PROGRESS_ENABLED:
        log(f"🔍 Scanning directory: {path}")
    relative_paths = []
    MAX_FILES_LISTED = 500
    file_count = 0
    start_level = resolved_path.count(os.sep)
    last_progress_report = 0
    try:
        IGNORE_PATTERNS = get_code_ignore_patterns()
        for root, dirs, files in os.walk(resolved_path, topdown=True):
            current_level = root.count(os.sep)
            depth = current_level - start_level
            rel_root_abs = os.path.relpath(root, resolved_path)
            rel_root = '' if rel_root_abs == '.' else rel_root_abs
            dirs[:] = [d for d in dirs if not (
                    d.startswith('.') or
                    any(fnmatch.fnmatch(os.path.join(rel_root, d).replace(os.sep, '/'), p) or fnmatch.fnmatch(d, p) for p in IGNORE_PATTERNS)
            )]
            if max_depth != -1 and depth >= max_depth:
                dirs[:] = []
            for filename in files:
                if file_count >= MAX_FILES_LISTED:
                    dirs[:] = []
                    break
                rel_filepath_fs = os.path.join(rel_root, filename)
                rel_filepath_norm = rel_filepath_fs.replace(os.sep, '/')
                if filename.startswith('.'): continue
                if any(fnmatch.fnmatch(rel_filepath_norm, p) or fnmatch.fnmatch(filename, p) for p in IGNORE_PATTERNS):
                    continue
                relative_paths.append(rel_filepath_fs)
                file_count += 1
                if config.STREAMING_PROGRESS_ENABLED and file_count - last_progress_report >= 50:
                    log(f"  📂 Found {file_count} files so far...")
                    last_progress_report = file_count
            if file_count >= MAX_FILES_LISTED:
                log(f"⚠️  Stopped at {MAX_FILES_LISTED} files to prevent large context.")
                break
    except Exception as e:
        log(f"Error during file listing for path '{path}': {e}")
        return f"Error: Failed to list directory contents due to system error."
    if config.STREAMING_PROGRESS_ENABLED:
        log(f"✅ Scan complete: {file_count} files found")
    tree_root_name = path if path != "." else os.path.basename(get_project_root())
    if not relative_paths:
        return f"Directory '{path}' is empty or contains only ignored files."
    full_tree_content = "Project structure:\n" + _generate_tree_local(relative_paths, tree_root_name)
    return full_tree_content
def get_file_content(path: str) -> str:
    resolved_path = _safe_path_resolve(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return f"Error: File '{path}' not found or inaccessible."
    if not os.path.isfile(resolved_path):
        return f"Error: Path '{path}' is a directory, not a file."
    MAX_FILE_SIZE_BYTES = 256 * 1024
    try:
        file_size = os.path.getsize(resolved_path)
        if file_size > MAX_FILE_SIZE_BYTES:
            return f"Error: File size ({file_size / 1024:.2f} KB) exceeds the maximum allowed limit of 256 KB."
        with open(resolved_path, 'rb') as f:
            chunk = f.read(1024)
            if b'\0' in chunk:
                return f"Error: File '{path}' appears to be a binary file. Cannot read."
        _, extension = os.path.splitext(resolved_path)
        lang = extension.lstrip('.') if extension else ''
        with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
            file_content = f.read()
        return (
            f"\n--- Code File: {path} ({file_size / 1024:.2f} KB) ---\n"
            f"```{lang}\n"
            f"{file_content}\n"
            f"```\n"
        )
    except Exception as e:
        return f"Error reading file '{path}': {e}"
def get_code_snippet(path: str, symbol_name: str) -> str:
    resolved_path = _safe_path_resolve(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return f"Error: File '{path}' not found or inaccessible."
    if not os.path.isfile(resolved_path):
        return f"Error: Path '{path}' is a directory, not a file."
    try:
        with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == symbol_name:
                snippet = ast.get_source_segment(content, node)
                if snippet:
                    lang = "python"
                    return (
                        f"\n--- Code Snippet: {symbol_name} from {path} ---\n"
                        f"```{lang}\n{snippet}\n```\n"
                    )
        return f"Error: Symbol '{symbol_name}' not found in file '{path}'."
    except Exception as e:
        return f"Error processing file '{path}' for symbol '{symbol_name}': {e}"
def search_codebase(query: str) -> str:
    from app.config import config
    MAX_SEARCH_RESULTS = 100
    if config.STREAMING_PROGRESS_ENABLED:
        log(f"🔍 Searching codebase for: '{query}'")
    try:
        subprocess.run(['rg', '--version'], check=True, capture_output=True)
        command = ['rg', '--vimgrep', '--max-count', str(MAX_SEARCH_RESULTS), '--', query, '.']
        log(f"Using ripgrep for search with command: {' '.join(command)}")
        if config.STREAMING_PROGRESS_ENABLED:
            log(f"  📍 Searching with ripgrep...")
        result = subprocess.run(
            command, cwd=get_project_root(), capture_output=True, text=True, check=False
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        log("ripgrep not found, falling back to grep. For better performance, install ripgrep.")
        exclude_dirs = [f'--exclude-dir={pattern}' for pattern in [
            '.git', '__pycache__', 'node_modules', 'venv', '.venv', 'build', 'dist', 'target', '.idea', '.vscode'
        ]]
        command = ['grep', '-r', '-n', '-I'] + exclude_dirs + ['-e', query, '.']
        log(f"Using grep for search with command: {' '.join(command)}")
        if config.STREAMING_PROGRESS_ENABLED:
            log(f"  📍 Searching with grep...")
        result = subprocess.run(
            command, cwd=get_project_root(), capture_output=True, text=True, check=False
        )
    if result.returncode not in [0, 1]:
        return f"Error executing search command. Return code: {result.returncode}\nStderr: {result.stderr}"
    output = result.stdout.strip()
    if not output:
        if config.STREAMING_PROGRESS_ENABLED:
            log(f"  📭 No results found")
        return f"No results found for query: '{query}'"
    lines = output.split('\n')
    match_count = len(lines)
    if config.STREAMING_PROGRESS_ENABLED:
        log(f"  ✅ Found {match_count} matches")
    if len(lines) > MAX_SEARCH_RESULTS:
        output = "\n".join(lines[:MAX_SEARCH_RESULTS])
        output += f"\n... (truncated to {MAX_SEARCH_RESULTS} results)"
    return f"Search results for '{query}':\n```\n{output}\n```"
def apply_patch(patch_content: str) -> str:
    if not patch_content or not isinstance(patch_content, str):
        return "Error: Patch content must be a non-empty string."
    original_content = patch_content
    patch_content = patch_content.strip()
    if patch_content.startswith("```"):
        lines = patch_content.split('\n')
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        patch_content = '\n'.join(lines)
        log(f"Cleaned markdown formatting from patch")
    patch_content = patch_content.strip()
    if not patch_content:
        return "Error: Patch content is empty after cleanup."
    if not (patch_content.startswith('---') or patch_content.startswith('diff ')):
        log(f"Warning: Patch doesn't start with standard format. First line: {patch_content.split(chr(10))[0][:50]}")
    log(f"Attempting to apply patch:\n---\n{patch_content}\n---")
    try:
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
            tmp.write(patch_content)
            temp_patch_file = tmp.name
        try:
            command = ['patch', '-p1', f'--input={temp_patch_file}']
            result = subprocess.run(
                command, cwd=get_project_root(), capture_output=True, text=True, check=False
            )
        finally:
            if os.path.exists(temp_patch_file):
                os.remove(temp_patch_file)
        cleanup_orig_files()
        if result.returncode == 0:
            success_message = "Patch applied successfully."
            if result.stdout:
                success_message += f"\nOutput:\n{result.stdout}"
            log(success_message)
            return success_message
        else:
            error_message = f"Error applying patch. Return code: {result.returncode}\n"
            if "malformed patch" in result.stderr.lower():
                error_message += "\n⚠️  MALFORMED PATCH: The patch format is incorrect.\n"
                error_message += "Please ensure:\n"
                error_message += "  1. Remove all markdown formatting (```, ```diff, etc.)\n"
                error_message += "  2. Use proper unified diff format (from 'git diff')\n"
                error_message += "  3. Include file paths with 'a/' and 'b/' prefixes\n"
                error_message += "  4. Each file change should start with '--- a/file' and '+++ b/file'\n\n"
            if result.stderr:
                error_message += f"Stderr:\n{result.stderr}\n"
            if result.stdout:
                error_message += f"Stdout:\n{result.stdout}\n"
            patch_preview = '\n'.join(patch_content.split('\n')[:10])
            error_message += f"\nFirst 10 lines of patch:\n{patch_preview}\n"
            log(error_message)
            return error_message
    except Exception as e:
        log(f"Failed to execute patch command: {e}")
        return f"Error: An unexpected exception occurred while trying to apply the patch: {e}"
def _run_git_command(cmd: list, timeout: int) -> tuple[subprocess.CompletedProcess | None, str | None]:
    try:
        result = subprocess.run(
            cmd,
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout
        )
        return result, None
    except subprocess.TimeoutExpired:
        return None, f"Error: git command timed out after {timeout}s."
    except FileNotFoundError:
        return None, "Error: git command not found. Please ensure git is installed."
    except Exception as e:
        return None, f"Error running git command: {e}"
def git_status() -> str:
    cmd = ['git', 'status', '--short', '--branch']
    result, error = _run_git_command(cmd, 10)
    if error:
        return error
    if result.returncode != 0:
        return f"Error: Not a git repository or git command failed.\n{result.stderr}"
    output = result.stdout.strip()
    if not output:
        return "Working tree is clean (no changes)."
    lines = output.split('\n')
    if len(lines) == 1 and lines[0].startswith("##"):
        return "Working tree is clean (no changes)."
    return f"Git Status:\n```\n{output}\n```"
def git_log(max_count: int = 10, path: str = None) -> str:
    try:
        max_count = int(max_count) if max_count else 10
        max_count = min(max(1, max_count), 50)
        cmd = ['git', 'log', f'--max-count={max_count}', '--oneline', '--graph', '--decorate']
        if path:
            resolved_path = _safe_path_resolve(path)
            if not resolved_path:
                return f"Error: Invalid or unsafe path '{path}'."
            cmd.extend(['--', resolved_path])
        result, error = _run_git_command(cmd, 15)
        if error:
            return error
        if result.returncode != 0:
            return f"Error: git log failed.\n{result.stderr}"
        if not result.stdout.strip():
            return "No commits found." if not path else f"No commits found for path '{path}'."
        header = f"Last {max_count} commits" + (f" for {path}" if path else "") + ":\n"
        return f"{header}```\n{result.stdout.strip()}\n```"
    except Exception as e:
        return f"Error running git log: {e}"
def git_diff(staged: bool = False, path: str = None) -> str:
    try:
        cmd = ['git', 'diff']
        if staged:
            cmd.append('--cached')
        if path:
            resolved_path = _safe_path_resolve(path)
            if not resolved_path:
                return f"Error: Invalid or unsafe path '{path}'."
            cmd.extend(['--', resolved_path])
        result, error = _run_git_command(cmd, 30)
        if error:
            return error
        if result.returncode != 0:
            return f"Error: git diff failed.\n{result.stderr}"
        if not result.stdout.strip():
            area = "staged area" if staged else "working directory"
            return f"No changes in {area}." + (f" for path '{path}'." if path else "")
        output = result.stdout
        if len(output) > 50000:
            output = output[:50000] + "\n... (output truncated, diff is too large)"
        return f"Git Diff:\n```diff\n{output}\n```"
    except Exception as e:
        return f"Error running git diff: {e}"
def git_show(commit: str = "HEAD", path: str = None) -> str:
    try:
        if not commit:
            commit = "HEAD"
        if not re.match(r'^[a-zA-Z0-9_\-\.\/]+$', commit):
            return f"Error: Invalid commit reference '{commit}'."
        cmd = ['git', 'show', commit, '--stat']
        if path:
            resolved_path = _safe_path_resolve(path)
            if not resolved_path:
                return f"Error: Invalid or unsafe path '{path}'."
            try:
                git_root = subprocess.run(
                    ['git', 'rev-parse', '--show-toplevel'],
                    cwd=get_project_root(),
                    capture_output=True,
                    text=True,
                    check=True
                ).stdout.strip()
                rel_path = os.path.relpath(resolved_path, git_root)
                cmd.extend(['--', rel_path])
            except Exception:
                return f"Error: Could not determine git root for path '{path}'."
        result, error = _run_git_command(cmd, 15)
        if error:
            return error
        if result.returncode != 0:
            return f"Error: git show failed. Commit '{commit}' may not exist.\n{result.stderr}"
        output = result.stdout
        if len(output) > 30000:
            output = output[:30000] + "\n... (output truncated)"
        return f"Commit {commit}:\n```\n{output}\n```"
    except Exception as e:
        return f"Error running git show: {e}"
def git_blame(path: str, start_line: int = None, end_line: int = None) -> str:
    resolved_path = _safe_path_resolve(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return f"Error: File '{path}' not found or inaccessible."
    if not os.path.isfile(resolved_path):
        return f"Error: Path '{path}' is not a file."
    try:
        cmd = ['git', 'blame', '--date=short']
        if start_line is not None and end_line is not None:
            start_line = int(start_line)
            end_line = int(end_line)
            if start_line > 0 and end_line >= start_line:
                cmd.extend(['-L', f'{start_line},{end_line}'])
        git_root = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        rel_path = os.path.relpath(resolved_path, git_root)
        cmd.append(rel_path)
        result, error = _run_git_command(cmd, 15)
        if error:
            return error
        if result.returncode != 0:
            if "not a git repository" in result.stderr.lower():
                return f"Error: '{path}' is not in a git repository."
            return f"Error: git blame failed.\n{result.stderr}"
        output = result.stdout
        if len(output) > 20000:
            lines = output.split('\n')
            output = '\n'.join(lines[:200]) + f"\n... (showing first 200 lines, total {len(lines)} lines)"
        return f"Git Blame for {path}:\n```\n{output}\n```"
    except Exception as e:
        return f"Error running git blame: {e}"
def list_recent_changes(days: int = 7, max_files: int = 20) -> str:
    try:
        days = int(days) if days else 7
        days = min(max(1, days), 90)
        max_files = int(max_files) if max_files else 20
        max_files = min(max(1, max_files), 100)
        cmd = ['git', 'log', f'--since={days} days ago', '--name-only', '--pretty=format:', '--']
        result, error = _run_git_command(cmd, 15)
        if error:
            return error
        if result.returncode != 0:
            return f"Error: git log failed.\n{result.stderr}"
        files = set()
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                files.add(line)
        if not files:
            return f"No files modified in the last {days} days."
        files_list = sorted(files)[:max_files]
        count_str = f" (showing {len(files_list)} of {len(files)})" if len(files) > max_files else ""
        return f"Files modified in the last {days} days{count_str}:\n```\n" + '\n'.join(files_list) + "\n```"
    except Exception as e:
        return f"Error listing recent changes: {e}"
def analyze_file_structure(path: str) -> str:
    resolved_path = _safe_path_resolve(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return f"Error: File '{path}' not found or inaccessible."
    if not os.path.isfile(resolved_path):
        return f"Error: Path '{path}' is not a file."
    try:
        with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        tree = ast.parse(content)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else ""))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(
                        f"from {module} import {alias.name}" + (f" as {alias.asname}" if alias.asname else ""))
        functions = []
        classes = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                args_str = ", ".join([arg.arg for arg in node.args.args])
                decorators = [d.id if isinstance(d, ast.Name) else ast.unparse(d) for d in node.decorator_list]
                func_info = f"def {node.name}({args_str})"
                if decorators:
                    func_info = f"@{', @'.join(decorators)}\n  {func_info}"
                docstring = ast.get_docstring(node)
                if docstring:
                    if len(docstring) > 100:
                        docstring = docstring[:100] + "..."
                    func_info += f"\n    \"\"\"{docstring}\"\"\""
                functions.append(func_info)
            elif isinstance(node, ast.ClassDef):
                bases = [ast.unparse(base) for base in node.bases]
                bases_str = f"({', '.join(bases)})" if bases else ""
                class_info = f"class {node.name}{bases_str}"
                methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
                class_info += f"  # {len(methods)} method(s)"
                docstring = ast.get_docstring(node)
                if docstring:
                    if len(docstring) > 80:
                        docstring = docstring[:80] + "..."
                    class_info += f"\n    \"\"\"{docstring}\"\"\""
                classes.append(class_info)
        result = [f"File Structure Analysis: {path}", "=" * 50, ""]
        if imports:
            result.append("IMPORTS:")
            for imp in imports[:20]:
                result.append(f"  {imp}")
            if len(imports) > 20:
                result.append(f"  ... and {len(imports) - 20} more")
            result.append("")
        if classes:
            result.append(f"CLASSES ({len(classes)}):")
            for cls in classes:
                result.append(f"  {cls}")
            result.append("")
        if functions:
            result.append(f"FUNCTIONS ({len(functions)}):")
            for func in functions:
                result.append(f"  {func}")
            result.append("")
        if not imports and not classes and not functions:
            result.append("No top-level imports, classes, or functions found.")
        return "\n".join(result)
    except SyntaxError as e:
        return f"Error: File '{path}' has syntax errors and cannot be parsed.\nLine {e.lineno}: {e.msg}"
    except Exception as e:
        return f"Error analyzing file structure: {e}"
def get_file_stats(path: str) -> str:
    resolved_path = _safe_path_resolve(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return f"Error: File '{path}' not found or inaccessible."
    if not os.path.isfile(resolved_path):
        return f"Error: Path '{path}' is not a file."
    try:
        stats = os.stat(resolved_path)
        file_size = stats.st_size
        modified_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stats.st_mtime))
        _, ext = os.path.splitext(resolved_path)
        lang_map = {
            '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript',
            '.java': 'Java', '.cpp': 'C++', '.c': 'C', '.go': 'Go',
            '.rs': 'Rust', '.rb': 'Ruby', '.php': 'PHP', '.swift': 'Swift',
            '.kt': 'Kotlin', '.cs': 'C#', '.html': 'HTML', '.css': 'CSS',
            '.md': 'Markdown', '.json': 'JSON', '.xml': 'XML', '.yaml': 'YAML',
            '.sh': 'Shell', '.sql': 'SQL', '.r': 'R', '.m': 'MATLAB'
        }
        language = lang_map.get(ext.lower(), 'Unknown')
        try:
            with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                total_lines = len(lines)
                code_lines = sum(1 for line in lines if line.strip() and not line.strip().startswith('#'))
                blank_lines = sum(1 for line in lines if not line.strip())
                comment_lines = total_lines - code_lines - blank_lines
        except:
            total_lines = code_lines = blank_lines = comment_lines = 0
        git_info = ""
        try:
            git_root = subprocess.run(
                ['git', 'rev-parse', '--show-toplevel'],
                cwd=get_project_root(),
                capture_output=True,
                text=True,
                check=True,
                timeout=5
            ).stdout.strip()
            rel_path = os.path.relpath(resolved_path, git_root)
            last_commit = subprocess.run(
                ['git', 'log', '-1', '--pretty=format:%h - %an, %ar: %s', '--', rel_path],
                cwd=get_project_root(),
                capture_output=True,
                text=True,
                check=False,
                timeout=5
            )
            if last_commit.returncode == 0 and last_commit.stdout.strip():
                git_info = f"Last Commit:     {last_commit.stdout.strip()}"
        except:
            git_info = "Git Info:        Not in a git repository or git not available"
        result = [
            f"File Statistics: {path}",
            "=" * 60,
            f"Language:        {language}",
            f"Size:            {file_size:,} bytes ({file_size / 1024:.2f} KB)",
            f"Last Modified:   {modified_time}",
            f"Total Lines:     {total_lines:,}",
            f"Code Lines:      {code_lines:,}",
            f"Blank Lines:     {blank_lines:,}",
            f"Comment Lines:   {comment_lines:,}",
        ]
        if git_info:
            result.append(git_info)
        return "\n".join(result)
    except Exception as e:
        return f"Error getting file stats: {e}"
def create_file(path: str, content: str, mode: str = "644") -> str:
    try:
        resolved_path = _safe_path_resolve(path)
        if not resolved_path:
            return f"Error: Access denied to path '{path}' (outside project root)"
        if os.path.exists(resolved_path):
            return f"Error: File '{path}' already exists. Use write_file to overwrite or choose different name."
        os.makedirs(os.path.dirname(resolved_path), exist_ok=True)
        with open(resolved_path, 'w', encoding='utf-8') as f:
            f.write(content)
        try:
            os.chmod(resolved_path, int(mode, 8))
        except:
            pass
        file_size = len(content.encode('utf-8'))
        lines = content.count('\n') + 1
        return f"✅ File created successfully: {path}\nSize: {file_size} bytes, Lines: {lines}\nPermissions: {mode}"
    except Exception as e:
        return f"Error creating file: {e}"
def write_file(path: str, content: str) -> str:
    try:
        resolved_path = _safe_path_resolve(path)
        if not resolved_path:
            return f"Error: Access denied to path '{path}' (outside project root)"
        if not os.path.exists(resolved_path):
            return f"Error: File '{path}' does not exist. Use create_file to create new files."
        old_size = os.path.getsize(resolved_path)
        with open(resolved_path, 'w', encoding='utf-8') as f:
            f.write(content)
        new_size = len(content.encode('utf-8'))
        lines = content.count('\n') + 1
        return f"✅ File updated successfully: {path}\nOld size: {old_size} bytes → New size: {new_size} bytes\nLines: {lines}"
    except Exception as e:
        return f"Error writing file: {e}"
def execute_command(command: str, timeout: int = 30) -> str:
    try:
        timeout = min(max(1, timeout), 300)
        log(f"Executing command: {command[:100]}...")
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=get_project_root()
        )
        output_parts = []
        if result.stdout:
            output_parts.append(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            output_parts.append(f"STDERR:\n{result.stderr}")
        output = "\n\n".join(output_parts) if output_parts else "(no output)"
        status = "✅ Success" if result.returncode == 0 else f"❌ Failed (exit code: {result.returncode})"
        return f"{status}\nCommand: {command}\n\n{output}"
    except subprocess.TimeoutExpired:
        return f"❌ Command timed out after {timeout} seconds: {command}"
    except Exception as e:
        return f"Error executing command: {e}"
def analyze_project_structure() -> str:
    try:
        project_root = get_project_root()
        analysis = []
        analysis.append(f"📊 Project Analysis: {os.path.basename(project_root)}")
        analysis.append(f"Root: {project_root}\n")
        file_types = {}
        total_files = 0
        total_size = 0
        language_files = {}
        ignore_patterns = get_code_ignore_patterns()
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, p) for p in ignore_patterns)]
            rel_root = os.path.relpath(root, project_root)
            if rel_root != '.' and any(fnmatch.fnmatch(rel_root, p) or fnmatch.fnmatch(os.path.join(rel_root, ''), p) for p in ignore_patterns):
                continue
            for file in files:
                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, project_root)
                if any(fnmatch.fnmatch(rel_path, p) or fnmatch.fnmatch(file, p) for p in ignore_patterns):
                    continue
                try:
                    size = os.path.getsize(filepath)
                    ext = os.path.splitext(file)[1].lower() or '(no extension)'
                    file_types[ext] = file_types.get(ext, 0) + 1
                    total_files += 1
                    total_size += size
                    lang_map = {
                        '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript',
                        '.java': 'Java', '.cpp': 'C++', '.c': 'C', '.h': 'C/C++',
                        '.go': 'Go', '.rs': 'Rust', '.rb': 'Ruby', '.php': 'PHP',
                        '.html': 'HTML', '.css': 'CSS', '.scss': 'SCSS',
                        '.json': 'JSON', '.xml': 'XML', '.yaml': 'YAML', '.yml': 'YAML',
                        '.md': 'Markdown', '.txt': 'Text', '.sh': 'Shell',
                        '.sql': 'SQL', '.kt': 'Kotlin', '.swift': 'Swift'
                    }
                    if ext in lang_map:
                        lang = lang_map[ext]
                        language_files[lang] = language_files.get(lang, 0) + 1
                except:
                    pass
        analysis.append("📁 File Types:")
        sorted_types = sorted(file_types.items(), key=lambda x: x[1], reverse=True)[:15]
        for ext, count in sorted_types:
            analysis.append(f"  {ext}: {count} files")
        if language_files:
            analysis.append("\n💻 Programming Languages:")
            sorted_langs = sorted(language_files.items(), key=lambda x: x[1], reverse=True)
            for lang, count in sorted_langs:
                analysis.append(f"  {lang}: {count} files")
        size_mb = total_size / (1024 * 1024)
        analysis.append(f"\n📦 Total: {total_files} files, {size_mb:.2f} MB")
        analysis.append("\n📋 Project Configuration:")
        config_files = [
            'package.json', 'requirements.txt', 'Cargo.toml', 'go.mod',
            'pom.xml', 'build.gradle', 'Gemfile', 'composer.json',
            'Dockerfile', 'docker-compose.yml', '.env', '.gitignore',
            'README.md', 'LICENSE', 'Makefile', 'CMakeLists.txt'
        ]
        found_configs = []
        for cf in config_files:
            if os.path.exists(os.path.join(project_root, cf)):
                found_configs.append(f"  ✓ {cf}")
        if found_configs:
            analysis.extend(found_configs)
        else:
            analysis.append("  (no standard config files found)")
        git_dir = os.path.join(project_root, '.git')
        if os.path.isdir(git_dir):
            try:
                result = subprocess.run(
                    ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                    capture_output=True, text=True, cwd=project_root, timeout=5
                )
                if result.returncode == 0:
                    branch = result.stdout.strip()
                    analysis.append(f"\n🔀 Git: On branch '{branch}'")
            except:
                pass
        return "\n".join(analysis)
    except Exception as e:
        return f"Error analyzing project: {e}"
def find_symbol(symbol_name: str) -> str:
    try:
        project_root = get_project_root()
        ignore_patterns = get_code_ignore_patterns()
        results = []
        results.append(f"🔍 Searching for symbol: '{symbol_name}'\n")
        patterns = [
            f"def {symbol_name}",
            f"class {symbol_name}",
            f"function {symbol_name}",
            f"const {symbol_name}",
            f"let {symbol_name}",
            f"var {symbol_name}",
            f"{symbol_name} =",
            f"{symbol_name}(",
        ]
        found_items = []
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, p) for p in ignore_patterns)]
            rel_root = os.path.relpath(root, project_root)
            if rel_root != '.' and any(fnmatch.fnmatch(rel_root, p) for p in ignore_patterns):
                continue
            for file in files:
                if not any(file.endswith(ext) for ext in ['.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.rb', '.php', '.kt', '.swift']):
                    continue
                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, project_root)
                if any(fnmatch.fnmatch(rel_path, p) for p in ignore_patterns):
                    continue
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()
                        for line_num, line in enumerate(lines, 1):
                            for pattern in patterns:
                                if pattern in line:
                                    found_items.append({
                                        'file': rel_path,
                                        'line': line_num,
                                        'content': line.strip(),
                                        'type': pattern.split()[0] if ' ' in pattern else 'usage'
                                    })
                                    break
                except:
                    pass
        if not found_items:
            return f"❌ Symbol '{symbol_name}' not found in the project."
        from collections import defaultdict
        by_file = defaultdict(list)
        for item in found_items:
            by_file[item['file']].append(item)
        results.append(f"✅ Found {len(found_items)} occurrences in {len(by_file)} files:\n")
        for file, items in sorted(by_file.items()):
            results.append(f"📄 {file}:")
            for item in items[:5]:
                results.append(f"  Line {item['line']}: {item['content'][:80]}")
            if len(items) > 5:
                results.append(f"  ... and {len(items) - 5} more occurrences")
            results.append("")
        return "\n".join(results)
    except Exception as e:
        return f"Error finding symbol: {e}"
def get_dependencies() -> str:
    try:
        project_root = get_project_root()
        results = []
        results.append("📦 Project Dependencies\n")
        req_file = os.path.join(project_root, 'requirements.txt')
        if os.path.exists(req_file):
            results.append("🐍 Python (requirements.txt):")
            with open(req_file, 'r') as f:
                deps = [line.strip() for line in f if line.strip() and not line.startswith('#')]
                for dep in deps[:20]:
                    results.append(f"  • {dep}")
                if len(deps) > 20:
                    results.append(f"  ... and {len(deps) - 20} more")
            results.append("")
        pyproject = os.path.join(project_root, 'pyproject.toml')
        if os.path.exists(pyproject):
            results.append("🐍 Python (pyproject.toml): (file exists)")
        package_json = os.path.join(project_root, 'package.json')
        if os.path.exists(package_json):
            try:
                with open(package_json, 'r') as f:
                    data = json.load(f)
                    deps = data.get('dependencies', {})
                    dev_deps = data.get('devDependencies', {})
                    if deps:
                        results.append("📦 Node.js Dependencies:")
                        for name, version in list(deps.items())[:15]:
                            results.append(f"  • {name}: {version}")
                        if len(deps) > 15:
                            results.append(f"  ... and {len(deps) - 15} more")
                        results.append("")
                    if dev_deps:
                        results.append("🛠️  Node.js Dev Dependencies:")
                        for name, version in list(dev_deps.items())[:10]:
                            results.append(f"  • {name}: {version}")
                        if len(dev_deps) > 10:
                            results.append(f"  ... and {len(dev_deps) - 10} more")
                        results.append("")
            except:
                results.append("📦 Node.js (package.json): (file exists but couldn't parse)")
        go_mod = os.path.join(project_root, 'go.mod')
        if os.path.exists(go_mod):
            results.append("🔷 Go (go.mod):")
            with open(go_mod, 'r') as f:
                lines = f.readlines()
                in_require = False
                count = 0
                for line in lines:
                    if 'require' in line:
                        in_require = True
                    if in_require and count < 15:
                        stripped = line.strip()
                        if stripped and not stripped.startswith('//'):
                            results.append(f"  • {stripped}")
                            count += 1
                    if in_require and ')' in line:
                        break
            results.append("")
        cargo_toml = os.path.join(project_root, 'Cargo.toml')
        if os.path.exists(cargo_toml):
            results.append("🦀 Rust (Cargo.toml): (file exists)")
        if len(results) == 2:
            return "❌ No dependency files found (requirements.txt, package.json, go.mod, Cargo.toml, etc.)"
        return "\n".join(results)
    except Exception as e:
        return f"Error getting dependencies: {e}"

def read_file_lines(path: str, start_line: int = 1, end_line: int = None) -> str:
    """Read specific lines from a file (inclusive range)"""
    resolved_path = _safe_path_resolve(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return f"Error: File '{path}' not found or inaccessible."
    if not os.path.isfile(resolved_path):
        return f"Error: Path '{path}' is not a file."
    
    try:
        start_line = max(1, int(start_line))
        with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        total_lines = len(lines)
        if end_line is None:
            end_line = total_lines
        else:
            end_line = min(int(end_line), total_lines)
        
        if start_line > total_lines:
            return f"Error: Start line {start_line} exceeds file length ({total_lines} lines)."
        
        selected_lines = lines[start_line-1:end_line]
        _, extension = os.path.splitext(resolved_path)
        lang = extension.lstrip('.') if extension else ''
        
        result = [
            f"File: {path} (lines {start_line}-{end_line} of {total_lines})",
            "=" * 60,
            f"```{lang}"
        ]
        
        for i, line in enumerate(selected_lines, start=start_line):
            result.append(f"{i:4d} | {line.rstrip()}")
        
        result.append("```")
        return "\n".join(result)
    except Exception as e:
        return f"Error reading file lines: {e}"

def find_references(symbol: str, file_types: str = None) -> str:
    """Find all references to a symbol (function, class, variable) across the codebase"""
    try:
        project_root = get_project_root()
        ignore_patterns = get_code_ignore_patterns()
        
        if file_types:
            allowed_extensions = [ext.strip() for ext in file_types.split(',')]
        else:
            allowed_extensions = ['.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.rb', '.php', '.kt', '.swift', '.jsx', '.tsx']
        
        results = []
        results.append(f"🔍 Finding references to: '{symbol}'\n")
        
        found_items = []
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, p) for p in ignore_patterns)]
            
            for file in files:
                ext = os.path.splitext(file)[1]
                if ext not in allowed_extensions:
                    continue
                
                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, project_root)
                
                if any(fnmatch.fnmatch(rel_path, p) for p in ignore_patterns):
                    continue
                
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()
                        for line_num, line in enumerate(lines, 1):
                            if symbol in line:
                                found_items.append({
                                    'file': rel_path,
                                    'line': line_num,
                                    'content': line.strip()
                                })
                except:
                    pass
        
        if not found_items:
            return f"❌ No references to '{symbol}' found in the project."
        
        from collections import defaultdict
        by_file = defaultdict(list)
        for item in found_items:
            by_file[item['file']].append(item)
        
        results.append(f"✅ Found {len(found_items)} references in {len(by_file)} files:\n")
        
        for file, items in sorted(by_file.items())[:20]:
            results.append(f"📄 {file} ({len(items)} references):")
            for item in items[:3]:
                results.append(f"  Line {item['line']}: {item['content'][:80]}")
            if len(items) > 3:
                results.append(f"  ... and {len(items) - 3} more in this file")
            results.append("")
        
        if len(by_file) > 20:
            results.append(f"... and {len(by_file) - 20} more files")
        
        return "\n".join(results)
    except Exception as e:
        return f"Error finding references: {e}"

def run_tests(test_path: str = None, pattern: str = None, verbose: bool = False) -> str:
    """Run tests using common test frameworks (pytest, jest, go test, cargo test, etc.)"""
    try:
        project_root = get_project_root()
        
        # Detect test framework
        if os.path.exists(os.path.join(project_root, 'pytest.ini')) or \
           os.path.exists(os.path.join(project_root, 'setup.py')) or \
           os.path.exists(os.path.join(project_root, 'pyproject.toml')):
            # Python pytest
            cmd = ['pytest']
            if verbose:
                cmd.append('-v')
            if test_path:
                cmd.append(test_path)
            if pattern:
                cmd.extend(['-k', pattern])
            framework = 'pytest'
        
        elif os.path.exists(os.path.join(project_root, 'package.json')):
            # Node.js jest or npm test
            try:
                with open(os.path.join(project_root, 'package.json'), 'r') as f:
                    pkg = json.load(f)
                    if 'jest' in pkg.get('devDependencies', {}) or 'jest' in pkg.get('dependencies', {}):
                        cmd = ['npm', 'run', 'test']
                        framework = 'jest'
                    else:
                        cmd = ['npm', 'test']
                        framework = 'npm test'
            except:
                cmd = ['npm', 'test']
                framework = 'npm test'
        
        elif os.path.exists(os.path.join(project_root, 'go.mod')):
            # Go tests
            cmd = ['go', 'test']
            if verbose:
                cmd.append('-v')
            if test_path:
                cmd.append(test_path)
            else:
                cmd.append('./...')
            framework = 'go test'
        
        elif os.path.exists(os.path.join(project_root, 'Cargo.toml')):
            # Rust cargo test
            cmd = ['cargo', 'test']
            if verbose:
                cmd.append('--verbose')
            if pattern:
                cmd.append(pattern)
            framework = 'cargo test'
        
        else:
            return "❌ No recognized test framework found (pytest, jest, go test, cargo test, etc.)"
        
        log(f"Running tests with {framework}: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes timeout
        )
        
        output_parts = [f"🧪 Test Results ({framework})", "=" * 60, ""]
        
        if result.returncode == 0:
            output_parts.append("✅ All tests passed!")
        else:
            output_parts.append(f"❌ Tests failed (exit code: {result.returncode})")
        
        output_parts.append("")
        
        if result.stdout:
            output_parts.append("STDOUT:")
            output_parts.append(result.stdout)
        
        if result.stderr:
            output_parts.append("\nSTDERR:")
            output_parts.append(result.stderr)
        
        return "\n".join(output_parts)
    
    except subprocess.TimeoutExpired:
        return f"❌ Tests timed out after 300 seconds"
    except FileNotFoundError as e:
        return f"❌ Test command not found: {e}. Please ensure the test framework is installed."
    except Exception as e:
        return f"Error running tests: {e}"

def compare_files(path1: str, path2: str) -> str:
    """Compare two files and show differences"""
    resolved_path1 = _safe_path_resolve(path1)
    resolved_path2 = _safe_path_resolve(path2)
    
    if not resolved_path1 or not os.path.exists(resolved_path1):
        return f"Error: File '{path1}' not found or inaccessible."
    if not resolved_path2 or not os.path.exists(resolved_path2):
        return f"Error: File '{path2}' not found or inaccessible."
    
    try:
        with open(resolved_path1, 'r', encoding='utf-8', errors='ignore') as f:
            lines1 = f.readlines()
        with open(resolved_path2, 'r', encoding='utf-8', errors='ignore') as f:
            lines2 = f.readlines()
        
        import difflib
        diff = difflib.unified_diff(
            lines1, lines2,
            fromfile=path1,
            tofile=path2,
            lineterm=''
        )
        
        diff_text = '\n'.join(diff)
        
        if not diff_text:
            return f"✅ Files are identical:\n  {path1}\n  {path2}"
        
        return f"📊 File Comparison:\n```diff\n{diff_text}\n```"
    
    except Exception as e:
        return f"Error comparing files: {e}"

def get_file_outline(path: str) -> str:
    """Get a structured outline/table of contents for a file showing all top-level definitions"""
    resolved_path = _safe_path_resolve(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return f"Error: File '{path}' not found or inaccessible."
    if not os.path.isfile(resolved_path):
        return f"Error: Path '{path}' is not a file."
    
    try:
        _, ext = os.path.splitext(resolved_path)
        
        if ext == '.py':
            # Python outline
            with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            tree = ast.parse(content)
            outline = []
            outline.append(f"📋 File Outline: {path}")
            outline.append("=" * 60)
            outline.append("")
            
            for node in tree.body:
                if isinstance(node, ast.FunctionDef):
                    args = ", ".join(arg.arg for arg in node.args.args)
                    decorators = ""
                    if node.decorator_list:
                        dec_names = [d.id if isinstance(d, ast.Name) else ast.unparse(d) for d in node.decorator_list]
                        decorators = f"@{', @'.join(dec_names)} "
                    outline.append(f"  📌 {decorators}def {node.name}({args})  [Line {node.lineno}]")
                    docstring = ast.get_docstring(node)
                    if docstring:
                        first_line = docstring.split('\n')[0][:60]
                        outline.append(f"     💬 {first_line}")
                
                elif isinstance(node, ast.ClassDef):
                    bases = ", ".join(ast.unparse(base) for base in node.bases) if node.bases else ""
                    outline.append(f"  🏗️  class {node.name}({bases})  [Line {node.lineno}]")
                    docstring = ast.get_docstring(node)
                    if docstring:
                        first_line = docstring.split('\n')[0][:60]
                        outline.append(f"     💬 {first_line}")
                    
                    # Show methods
                    methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
                    for method in methods[:10]:
                        args = ", ".join(arg.arg for arg in method.args.args)
                        outline.append(f"       • {method.name}({args})  [Line {method.lineno}]")
                    if len(methods) > 10:
                        outline.append(f"       ... and {len(methods) - 10} more methods")
                
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            outline.append(f"  📝 {target.id} = ...  [Line {node.lineno}]")
            
            return "\n".join(outline)
        
        else:
            # Generic outline for other languages
            with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            outline = []
            outline.append(f"📋 File Outline: {path}")
            outline.append("=" * 60)
            outline.append("")
            
            patterns = [
                (r'^\s*def\s+(\w+)', '  📌 def'),
                (r'^\s*function\s+(\w+)', '  📌 function'),
                (r'^\s*class\s+(\w+)', '  🏗️  class'),
                (r'^\s*const\s+(\w+)', '  📝 const'),
                (r'^\s*let\s+(\w+)', '  📝 let'),
                (r'^\s*var\s+(\w+)', '  📝 var'),
            ]
            
            for line_num, line in enumerate(lines, 1):
                for pattern, prefix in patterns:
                    match = re.match(pattern, line)
                    if match:
                        name = match.group(1)
                        outline.append(f"{prefix} {name}  [Line {line_num}]")
            
            if len(outline) == 3:
                outline.append("  (No recognizable structure found)")
            
            return "\n".join(outline)
    
    except SyntaxError as e:
        return f"Error: File has syntax errors.\nLine {e.lineno}: {e.msg}"
    except Exception as e:
        return f"Error generating outline: {e}"
BUILTIN_FUNCTIONS = {
    "list_files": list_files,
    "get_file_content": get_file_content,
    "get_code_snippet": get_code_snippet,
    "search_codebase": search_codebase,
    "apply_patch": apply_patch,
    "create_file": create_file,
    "write_file": write_file,
    "execute_command": execute_command,
    "analyze_project_structure": analyze_project_structure,
    "find_symbol": find_symbol,
    "get_dependencies": get_dependencies,
    "git_status": git_status,
    "git_log": git_log,
    "git_diff": git_diff,
    "git_show": git_show,
    "git_blame": git_blame,
    "list_recent_changes": list_recent_changes,
    "analyze_file_structure": analyze_file_structure,
    "get_file_stats": get_file_stats,
    "read_file_lines": read_file_lines,
    "find_references": find_references,
    "run_tests": run_tests,
    "compare_files": compare_files,
    "get_file_outline": get_file_outline
}
BUILTIN_DECLARATIONS_PATH = 'etc/mcp/declaration/default.json'
def load_builtin_declarations() -> list:
    from app.utils.core.config_loader import load_json_file
    return load_json_file(BUILTIN_DECLARATIONS_PATH, default=[])
BUILTIN_DECLARATIONS = load_builtin_declarations()
MCP_CONFIG_FILE = 'var/config/mcp.json'
mcp_function_declarations = []
mcp_function_to_tool_map = {}
mcp_function_input_schema_map = {}
mcp_tool_processes = {}
mcp_request_id_counter = 1
mcp_request_id_lock = threading.Lock()
_mcp_tool_locks = {}
_mcp_tool_locks_lock = threading.Lock()
MAX_FUNCTION_DECLARATIONS_DEFAULT = 64
max_function_declarations_limit = MAX_FUNCTION_DECLARATIONS_DEFAULT
DISABLE_ALL_MCP_TOOLS_DEFAULT = False
disable_all_mcp_tools = DISABLE_ALL_MCP_TOOLS_DEFAULT
def set_disable_all_mcp_tools(status: bool):
    global disable_all_mcp_tools, mcp_config
    disable_all_mcp_tools = status
    mcp_config["disableAllTools"] = status
    try:
        with open(MCP_CONFIG_FILE, 'w') as f:
            json.dump(mcp_config, f, indent=2)
        log(f"MCP general settings updated and saved to {MCP_CONFIG_FILE}. Disable all tools: {status}")
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error saving MCP config: {e}")


def _parse_headers_from_args(args: list[str]) -> dict:
    headers = {}
    for arg in args:
        if ':' in arg:
            key, value = arg.split(':', 1)
            headers[key.strip()] = value.strip()
    return headers


def _fetch_raw_mcp_tools_http(tool_name: str, tool_info: dict) -> tuple[list | None, str | None]:
    url = tool_info.get("url")
    headers = tool_info.get("headers", {})
    headers['Content-Type'] = 'application/json'

    try:
        from app.utils.core.tools import make_request_with_retry
        log(f"Fetching schema/tool list via HTTP for tool '{tool_name}' from {url}...")

        tools_list_request = {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}
        }

        response = make_request_with_retry(
            url=url,
            headers=headers,
            json_data=tools_list_request,
            stream=False,
            timeout=30
        )
        response_data = response.json()

        if "result" in response_data and "tools" in response_data["result"]:
            return response_data["result"]["tools"], None

        error_details = f"Did not receive a valid tools/list response for tool '{tool_name}' from {url}."
        if response_data:
            error_details += f"\nResponse: {json.dumps(response_data)}"
        return None, error_details
    except Exception as e:
        return None, f"An unexpected error occurred while fetching schema for tool '{tool_name}' via HTTP: {e}"


def _fetch_raw_mcp_tools(tool_name: str, tool_info: dict) -> tuple[list | None, str | None]:
    if "url" in tool_info:
        return _fetch_raw_mcp_tools_http(tool_name, tool_info)
    command_str = tool_info.get("command")
    if not command_str:
        return None, "Command not provided for tool."

    if command_str.startswith(('http://', 'https://')):
        headers = _parse_headers_from_args(tool_info.get("args", []))
        http_tool_info = {"url": command_str, "headers": headers}
        return _fetch_raw_mcp_tools_http(tool_name, http_tool_info)

    command = [command_str] + tool_info.get("args", [])
    env = os.environ.copy()
    if "env" in tool_info:
        env.update(tool_info["env"])
    try:
        log(f"Fetching schema/tool list for tool '{tool_name}'...")
        mcp_init_request = {
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "gemini-proxy", "version": "2.2.0"}}
        }
        tools_list_request = {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}
        }
        initialized_notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        input_data = (
            json.dumps(mcp_init_request) + "\n" +
            json.dumps(initialized_notification) + "\n" +
            json.dumps(tools_list_request) + "\n"
        )
        process = subprocess.run(
            command, input=input_data, text=True, capture_output=True,
            check=False, env=env, timeout=30
        )
        if process.returncode != 0:
            error_details = f"MCP tool '{tool_name}' failed with exit code {process.returncode}."
            if process.stderr:
                error_details += f"\nStderr: {process.stderr.strip()}"
            return None, error_details
        lines = process.stdout.strip().split('\n')
        for line in lines:
            if not line.strip():
                continue
            try:
                if line.startswith('\ufeff'):
                    line = line.lstrip('\ufeff')
                response = json.loads(line)
                if (response.get("id") == 1 and
                    "result" in response and
                    "tools" in response["result"]):
                    return response["result"]["tools"], None
            except json.JSONDecodeError:
                continue
        error_details = f"Did not receive a valid tools/list response for tool '{tool_name}'."
        if process.stdout.strip():
            error_details += f"\nStdout: {process.stdout.strip()}"
        if process.stderr.strip():
            error_details += f"\nStderr: {process.stderr.strip()}"
        return None, error_details
    except subprocess.TimeoutExpired:
        return None, f"Timeout while fetching schema for tool '{tool_name}'."
    except FileNotFoundError:
        return None, f"Command not found: '{command_str}'."
    except Exception as e:
        return None, f"An unexpected error occurred while fetching schema for tool '{tool_name}': {e}"
def get_declarations_from_tool(tool_name, tool_info):
    global mcp_function_input_schema_map
    mcp_tools, error = _fetch_raw_mcp_tools(tool_name, tool_info)
    if error:
        print(f"Error fetching declarations from '{tool_name}': {error}")
        return []
    tools = []
    for tool in mcp_tools:
        declaration = {
            "name": tool["name"],
            "description": tool.get("description", f"Execute {tool['name']} tool")
        }
        mcp_function_input_schema_map[tool["name"]] = tool.get("inputSchema")
        if "inputSchema" in tool:
            schema = tool["inputSchema"]
            if schema.get("type") == "object":
                declaration["parameters"] = {
                    "type": "OBJECT",
                    "properties": {}
                }
                def convert_property_to_gemini(prop_def):
                    t = str(prop_def.get("type", "string")).lower()
                    if t == "string":
                        return {
                            "type": "STRING",
                            "description": prop_def.get("description", "String parameter")
                        }
                    elif t in ("number", "integer"):
                        return {
                            "type": "NUMBER",
                            "description": prop_def.get("description", "Number parameter")
                        }
                    elif t == "boolean":
                        return {
                            "type": "BOOLEAN",
                            "description": prop_def.get("description", "Boolean parameter")
                        }
                    elif t == "array":
                        param = {
                            "type": "ARRAY",
                            "description": prop_def.get("description", "Array parameter")
                        }
                        items = prop_def.get("items", {})
                        if items:
                            param["items"] = convert_property_to_gemini(items)
                        else:
                            param["items"] = {"type": "STRING"}
                        return param
                    elif t == "object":
                        param = {
                            "type": "OBJECT",
                            "description": prop_def.get("description", "Object parameter")
                        }
                        if "properties" in prop_def:
                            param["properties"] = {}
                            for nested_name, nested_def in prop_def["properties"].items():
                                param["properties"][nested_name] = convert_property_to_gemini(nested_def)
                        return param
                    else:
                        return {
                            "type": "STRING",
                            "description": prop_def.get("description", "String parameter")
                        }
                for prop_name, prop_def in schema.get("properties", {}).items():
                    declaration["parameters"]["properties"][prop_name] = convert_property_to_gemini(prop_def)
                if "required" in schema:
                    declaration["parameters"]["required"] = schema["required"]
        tools.append(declaration)
    log(f"Successfully fetched {len(tools)} function declaration(s) for tool '{tool_name}'.")
    return tools
def fetch_mcp_tool_list(tool_info):
    tool_name = tool_info.get("command", "unnamed_tool")
    mcp_tools, error = _fetch_raw_mcp_tools(tool_name, tool_info)
    if error:
        return {"error": error}
    return {"tools": mcp_tools}
def load_mcp_config():
    global mcp_config, mcp_function_declarations, mcp_function_to_tool_map, mcp_function_input_schema_map, mcp_tool_processes, max_function_declarations_limit, disable_all_mcp_tools
    for tool_name, process in mcp_tool_processes.items():
        if process.poll() is None:
            try:
                log(f"Terminating old process for tool '{tool_name}'...")
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print(f"Process for '{tool_name}' did not terminate in time, killing.")
                process.kill()
            except Exception as e:
                print(f"Error terminating process for tool '{tool_name}': {e}")
    mcp_tool_processes.clear()
    mcp_function_declarations = []
    mcp_function_to_tool_map = {}
    mcp_function_input_schema_map = {}
    if os.path.exists(MCP_CONFIG_FILE):
        try:
            with open(MCP_CONFIG_FILE, 'r') as f:
                mcp_config = json.load(f)
            log(f"MCP config loaded from {MCP_CONFIG_FILE}.")
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading MCP config: {e}")
            mcp_config = {}
            max_function_declarations_limit = MAX_FUNCTION_DECLARATIONS_DEFAULT
            return
    else:
        mcp_config = {}
        max_function_declarations_limit = MAX_FUNCTION_DECLARATIONS_DEFAULT
        disable_all_mcp_tools = DISABLE_ALL_MCP_TOOLS_DEFAULT
        log("No MCP config file found, MCP tools disabled.")
        return
    max_function_declarations_limit = mcp_config.get("maxFunctionDeclarations", MAX_FUNCTION_DECLARATIONS_DEFAULT)
    if not isinstance(max_function_declarations_limit, int) or max_function_declarations_limit <= 0:
        log(f"Invalid maxFunctionDeclarations in config ({max_function_declarations_limit}). Using default: {MAX_FUNCTION_DECLARATIONS_DEFAULT}")
        max_function_declarations_limit = MAX_FUNCTION_DECLARATIONS_DEFAULT
    disable_all_mcp_tools = mcp_config.get("disableAllTools", DISABLE_ALL_MCP_TOOLS_DEFAULT)
    if disable_all_mcp_tools:
        log("All MCP tools are globally disabled by configuration.")
    if mcp_config.get("mcpServers"):
        sorted_servers = sorted(
            mcp_config["mcpServers"].items(),
            key=lambda item: item[1].get('priority', 0),
            reverse=True
        )
        for tool_name, tool_info in sorted_servers:
            if not tool_info.get('enabled', True):
                log(f"Skipping disabled tool: '{tool_name}'.")
                continue
            declarations = get_declarations_from_tool(tool_name, tool_info)
            mcp_function_declarations.extend(declarations)
            for decl in declarations:
                if 'name' in decl:
                    mcp_function_to_tool_map[decl['name']] = tool_name
    mcp_function_declarations.extend(BUILTIN_DECLARATIONS)
    for decl in BUILTIN_DECLARATIONS:
        if 'name' in decl:
            mcp_function_to_tool_map[decl['name']] = BUILTIN_TOOL_NAME
            mcp_function_input_schema_map[decl['name']] = {}
    log(f"Total function declarations loaded: {len(mcp_function_declarations)}")
def create_tool_declarations(prompt_text: str = ""):
    if disable_all_mcp_tools:
        log("All MCP tools are globally disabled. Returning no declarations.")
        return None
    if not mcp_function_declarations:
        return None
    selected_tool_names = set()
    padded_prompt = f' {prompt_text.lower()} '
    if prompt_text:
        if mcp_config.get("mcpServers"):
            for tool_name in mcp_config["mcpServers"].keys():
                if f' {tool_name.lower()} ' in padded_prompt:
                    log(f"Detected keyword for tool server '{tool_name}'.")
                    selected_tool_names.add(tool_name)
        for func_decl in mcp_function_declarations:
            func_name = func_decl['name']
            if f' {func_name.lower()} ' in padded_prompt:
                parent_tool_name = mcp_function_to_tool_map.get(func_name)
                if parent_tool_name and parent_tool_name not in selected_tool_names:
                    log(f"Detected keyword for function '{func_name}'. Selecting parent tool '{parent_tool_name}'.")
                    selected_tool_names.add(parent_tool_name)
    if selected_tool_names:
        log(f"Final selected tools: {list(selected_tool_names)}")
        selected_declarations = []
        for func_decl in mcp_function_declarations:
            if mcp_function_to_tool_map.get(func_decl['name']) in selected_tool_names:
                selected_declarations.append(func_decl)
        final_declarations = selected_declarations
    else:
        final_declarations = []
    if len(final_declarations) > max_function_declarations_limit:
        log(f"Warning: Number of function declarations ({len(final_declarations)}) exceeds the limit of {max_function_declarations_limit}. Truncating list.")
        final_declarations = final_declarations[:max_function_declarations_limit]
    if not final_declarations:
        return None
    return [{"functionDeclarations": final_declarations}]
def create_tool_declarations_from_list(function_names: list[str]):
    if disable_all_mcp_tools:
        log("All MCP tools are globally disabled. Returning no declarations.")
        return None
    if not mcp_function_declarations or not function_names:
        return None
    selected_declarations = []
    if function_names == ["*"]:
        log("Selecting all available MCP functions due to '*' sentinel.")
        selected_declarations = mcp_function_declarations[:]
    else:
        for func_decl in mcp_function_declarations:
            if func_decl.get('name') in function_names:
                selected_declarations.append(func_decl)
    if len(selected_declarations) > max_function_declarations_limit:
        log(f"Warning: Number of function declarations ({len(selected_declarations)}) exceeds the limit of {max_function_declarations_limit}. Truncating list.")
        selected_declarations = selected_declarations[:max_function_declarations_limit]
    if not selected_declarations:
        return None
    return [{"functionDeclarations": selected_declarations}]
def _parse_kwargs_string(s: str) -> dict:
    result = {}
    try:
        tokens = shlex.split(s)
        for tok in tokens:
            if '=' in tok:
                k, v = tok.split('=', 1)
                result[k.strip()] = v.strip()
    except Exception as e:
        print(f"Warning: failed to parse kwargs string '{s}': {e}")
    return result


def _execute_mcp_tool_http(function_name: str, tool_args: dict, tool_name: str, tool_info: dict):
    url = tool_info.get("url")
    headers = tool_info.get("headers", {})
    headers['Content-Type'] = 'application/json'

    global mcp_request_id_counter
    with mcp_request_id_lock:
        call_id = mcp_request_id_counter
        mcp_request_id_counter += 1

    normalized_args = _normalize_mcp_args(tool_args)
    input_schema = mcp_function_input_schema_map.get(function_name) or {}
    arguments_for_call = _coerce_args_to_schema(normalized_args, input_schema)

    mcp_call_request = {
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "tools/call",
        "params": {
            "name": function_name,
            "arguments": arguments_for_call
        }
    }

    try:
        from app.utils.core.tools import make_request_with_retry
        response = make_request_with_retry(
            url=url,
            headers=headers,
            json_data=mcp_call_request,
            stream=False,
            timeout=120
        )
        response_data = response.json()

        if "result" in response_data:
            content = response_data["result"].get("content", [])
            is_all_text = content and all(item.get("type") == "text" for item in content)
            if is_all_text:
                result_text = "".join(item.get("text", "") for item in content)
                return result_text
            return json.dumps(response_data["result"])
        elif "error" in response_data:
            return f"MCP Error: {response_data['error'].get('message', 'Unknown error')}"
        return "Tool returned a response with no result or error."

    except Exception as e:
        error_message = f"An unexpected error occurred while executing function '{function_name}' via HTTP: {e}"
        print(error_message)
        return error_message


def _normalize_mcp_args(args) -> dict:
    if args is None:
        return {}
    if isinstance(args, dict) and "kwargs" not in args and "args" not in args:
        return args
    if isinstance(args, dict):
        kwargs_val = args.get("kwargs")
        if isinstance(kwargs_val, dict):
            return kwargs_val
        if isinstance(kwargs_val, str):
            try:
                parsed = json.loads(kwargs_val)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
            parsed_kv = _parse_kwargs_string(kwargs_val)
            if parsed_kv:
                return parsed_kv
        args_val = args.get("args")
        if isinstance(args_val, str):
            try:
                parsed_args = json.loads(args_val)
                if isinstance(parsed_args, dict):
                    return parsed_args
            except json.JSONDecodeError:
                pass
        return {}
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return _parse_kwargs_string(args)
    return {}
def _ensure_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return _parse_kwargs_string(value)
    return {}
def _coerce_args_to_schema(normalized_args: dict, input_schema: dict) -> dict:
    if not isinstance(input_schema, dict):
        return normalized_args
    props = input_schema.get("properties", {}) or {}
    required = set(input_schema.get("required", []) or [])
    expects_wrapped = ("args" in props) or ("kwargs" in props) or ("args" in required) or ("kwargs" in required)
    if not expects_wrapped:
        return normalized_args
    result = {}
    if "kwargs" in props or "kwargs" in required:
        if "kwargs" in normalized_args:
            result["kwargs"] = _ensure_dict(normalized_args.get("kwargs"))
        else:
            result["kwargs"] = normalized_args
    if "args" in props or "args" in required:
        raw_args = normalized_args.get("args") if isinstance(normalized_args, dict) else None
        if isinstance(raw_args, str):
            try:
                parsed = json.loads(raw_args)
                result["args"] = parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                result["args"] = []
        elif isinstance(raw_args, list):
            result["args"] = raw_args
        else:
            result["args"] = []
    return result


def execute_mcp_tool(function_name, tool_args, project_root_override: str | None = None):
    global mcp_tool_processes, mcp_request_id_counter
    log(f"Executing MCP function: {function_name} with args: {tool_args}")
    function_name = function_name.replace("default_api:", "")
    tool_name = mcp_function_to_tool_map.get(function_name)
    is_builtin = (tool_name == BUILTIN_TOOL_NAME)
    record_tool_call(is_builtin=is_builtin)
    
    # Agent Intelligence: Get orchestrator if enabled
    orchestrator = None
    try:
        from app.config import config
        if config.AGENT_INTELLIGENCE_ENABLED and project_root_override:
            from app.utils.core.agent_intelligence import get_agent_orchestrator
            orchestrator = get_agent_orchestrator()
    except Exception as e:
        log(f"Agent intelligence not available: {e}")
    
    if not tool_name:
        return f"Error: Function '{function_name}' not found in any configured MCP tool."
    if optimization_utils.should_cache_tool(function_name):
        cached_output = optimization.get_cached_tool_output(function_name, tool_args)
        if cached_output is not None:
            log(f"✓ Cache HIT for {function_name}")
            optimization.record_cache_hit()
            return cached_output
        else:
            log(f"✗ Cache MISS for {function_name}")
            optimization.record_cache_miss()
    if tool_name == BUILTIN_TOOL_NAME:
        builtin_func = BUILTIN_FUNCTIONS.get(function_name)
        if not builtin_func:
            return f"Error: Built-in function '{function_name}' not implemented."
        normalized_args = _normalize_mcp_args(tool_args)
        log(f"Normalized args for {function_name}: {normalized_args}")
        with set_project_root(project_root_override):
            func_args = {}
            try:
                if function_name == 'list_files':
                    path = normalized_args.get('path')
                    func_args['path'] = path if path is not None else '.'
                    if 'max_depth' in normalized_args:
                        max_depth_val = normalized_args.get('max_depth')
                        if max_depth_val is not None:
                            func_args['max_depth'] = int(max_depth_val)
                elif function_name == 'get_file_content':
                    path = normalized_args.get('path')
                    if not path:
                        raise TypeError("Path argument is required and cannot be null or empty.")
                    func_args['path'] = path
                elif function_name == 'get_code_snippet':
                    path = normalized_args.get('path')
                    symbol_name = normalized_args.get('symbol_name')
                    if not path:
                        raise TypeError("Path argument is required and cannot be null or empty.")
                    if not symbol_name:
                        raise TypeError("Symbol name argument is required and cannot be null or empty.")
                    func_args['path'] = path
                    func_args['symbol_name'] = symbol_name
                elif function_name == 'search_codebase':
                    query = normalized_args.get('query')
                    if not query:
                        raise TypeError("Query argument is required and cannot be null or empty.")
                    func_args['query'] = query
                elif function_name == 'apply_patch':
                    patch_content = normalized_args.get('patch_content')
                    if not patch_content:
                        raise TypeError("Patch content argument is required and cannot be null or empty.")
                    func_args['patch_content'] = patch_content
                elif function_name == 'create_file':
                    path = normalized_args.get('path')
                    content = normalized_args.get('content')
                    if not path:
                        raise TypeError("Path argument is required.")
                    if content is None:
                        raise TypeError("Content argument is required.")
                    func_args['path'] = path
                    func_args['content'] = content
                    if 'mode' in normalized_args:
                        func_args['mode'] = normalized_args.get('mode')
                elif function_name == 'write_file':
                    path = normalized_args.get('path')
                    content = normalized_args.get('content')
                    if not path:
                        raise TypeError("Path argument is required.")
                    if content is None:
                        raise TypeError("Content argument is required.")
                    func_args['path'] = path
                    func_args['content'] = content
                elif function_name == 'execute_command':
                    command = normalized_args.get('command')
                    if not command:
                        raise TypeError("Command argument is required.")
                    func_args['command'] = command
                    if 'timeout' in normalized_args:
                        func_args['timeout'] = normalized_args.get('timeout')
                elif function_name == 'find_symbol':
                    symbol_name = normalized_args.get('symbol_name')
                    if not symbol_name:
                        raise TypeError("Symbol name argument is required.")
                    func_args['symbol_name'] = symbol_name
                elif function_name == 'git_status':
                    pass
                elif function_name == 'git_log':
                    if 'max_count' in normalized_args:
                        func_args['max_count'] = normalized_args.get('max_count')
                    if 'path' in normalized_args:
                        func_args['path'] = normalized_args.get('path')
                elif function_name == 'git_diff':
                    if 'staged' in normalized_args:
                        func_args['staged'] = bool(normalized_args.get('staged'))
                    if 'path' in normalized_args:
                        func_args['path'] = normalized_args.get('path')
                elif function_name == 'git_show':
                    if 'commit' in normalized_args:
                        func_args['commit'] = normalized_args.get('commit')
                    if 'path' in normalized_args:
                        func_args['path'] = normalized_args.get('path')
                elif function_name == 'git_blame':
                    path = normalized_args.get('path')
                    if not path:
                        raise TypeError("Path argument is required.")
                    func_args['path'] = path
                    if 'start_line' in normalized_args:
                        func_args['start_line'] = normalized_args.get('start_line')
                    if 'end_line' in normalized_args:
                        func_args['end_line'] = normalized_args.get('end_line')
                elif function_name == 'list_recent_changes':
                    if 'days' in normalized_args:
                        func_args['days'] = normalized_args.get('days')
                    if 'max_files' in normalized_args:
                        func_args['max_files'] = normalized_args.get('max_files')
                elif function_name == 'analyze_file_structure':
                    path = normalized_args.get('path')
                    if not path:
                        raise TypeError("Path argument is required.")
                    func_args['path'] = path
                elif function_name == 'get_file_stats':
                    path = normalized_args.get('path')
                    if not path:
                        raise TypeError("Path argument is required.")
                    func_args['path'] = path
                elif function_name == 'read_file_lines':
                    path = normalized_args.get('path')
                    if not path:
                        raise TypeError("Path argument is required.")
                    func_args['path'] = path
                    if 'start_line' in normalized_args:
                        func_args['start_line'] = normalized_args.get('start_line')
                    if 'end_line' in normalized_args:
                        func_args['end_line'] = normalized_args.get('end_line')
                elif function_name == 'find_references':
                    symbol = normalized_args.get('symbol')
                    if not symbol:
                        raise TypeError("Symbol argument is required.")
                    func_args['symbol'] = symbol
                    if 'file_types' in normalized_args:
                        func_args['file_types'] = normalized_args.get('file_types')
                elif function_name == 'run_tests':
                    if 'test_path' in normalized_args:
                        func_args['test_path'] = normalized_args.get('test_path')
                    if 'pattern' in normalized_args:
                        func_args['pattern'] = normalized_args.get('pattern')
                    if 'verbose' in normalized_args:
                        func_args['verbose'] = bool(normalized_args.get('verbose'))
                elif function_name == 'compare_files':
                    path1 = normalized_args.get('path1')
                    path2 = normalized_args.get('path2')
                    if not path1 or not path2:
                        raise TypeError("Both path1 and path2 arguments are required.")
                    func_args['path1'] = path1
                    func_args['path2'] = path2
                elif function_name == 'get_file_outline':
                    path = normalized_args.get('path')
                    if not path:
                        raise TypeError("Path argument is required.")
                    func_args['path'] = path
            except KeyError as e:
                log(f"Error: Missing required argument '{e.args[0]}' for function '{function_name}'. Normalized args: {normalized_args}")
                return f"Error: Missing required argument '{e.args[0]}' for function '{function_name}'."
            except (ValueError, TypeError) as e:
                log(f"Error: Invalid argument type or null value provided for function '{function_name}'. Details: {e}. Normalized args: {normalized_args}")
                return f"Error: Invalid argument type provided for function '{function_name}': {e}"
        try:
            result = builtin_func(**func_args)
            if hasattr(result, '__iter__') and not isinstance(result, (str, dict, list)):
                log(f"Returning streaming result for built-in function: {function_name}")
                return result
            
            # Agent Intelligence: Process result with reflection
            if orchestrator:
                try:
                    intelligence_result = orchestrator.after_tool_execution(
                        function_name, func_args, result
                    )
                    
                    if not intelligence_result.get('output_valid'):
                        log(f"⚠️  Agent reflection: {intelligence_result.get('validation_reason')}")
                        if intelligence_result.get('recovery_suggestions'):
                            log(f"💡 Recovery suggestions: {intelligence_result['recovery_suggestions']}")
                    
                    # Add context hints to result if available
                    if intelligence_result.get('suggested_next_tools'):
                        suggested = intelligence_result['suggested_next_tools'][:3]
                        result += f"\n\n💡 Suggested next steps: {', '.join(suggested)}"
                except Exception as e:
                    log(f"Agent intelligence processing error: {e}")
            
            optimized_result = optimization_utils.optimize_tool_output(result, function_name)
            if len(optimized_result) < len(result):
                tokens_saved = optimization_utils.estimate_tokens(result) - optimization_utils.estimate_tokens(optimized_result)
                optimization.record_tokens_saved(tokens_saved)
                log(f"✓ Optimized output: saved ~{tokens_saved} tokens")
            if optimization_utils.should_cache_tool(function_name):
                optimization.cache_tool_output(function_name, tool_args, optimized_result)
            optimization.record_optimization()
            return optimized_result
        except Exception as e:
            log(f"Error executing built-in tool {function_name} with args {func_args}: {type(e).__name__}: {e}")
            error_msg = f"Error executing built-in function '{function_name}': {e}"
            
            # Agent Intelligence: Suggest recovery on error
            if orchestrator:
                try:
                    recovery = orchestrator.reflection.suggest_recovery({
                        'error': str(e),
                        'tool': function_name,
                        'args': func_args
                    })
                    if recovery:
                        error_msg += f"\n\n💡 Suggestions:\n" + "\n".join(f"  • {s}" for s in recovery[:3])
                except:
                    pass
            
            return error_msg
    tool_info = mcp_config.get("mcpServers", {}).get(tool_name)
    if not tool_info:
        return f"Error: Tool '{tool_name}' for function '{function_name}' not found in mcpServers config."

    command_str = tool_info.get("command")
    if command_str and command_str.startswith(('http://', 'https://')):
        headers = _parse_headers_from_args(tool_info.get("args", []))
        http_tool_info = {"url": command_str, "headers": headers}
        return _execute_mcp_tool_http(function_name, tool_args, tool_name, http_tool_info)


    if "url" in tool_info:
        return _execute_mcp_tool_http(function_name, tool_args, tool_name, tool_info)

    with _mcp_tool_locks_lock:
        if tool_name not in _mcp_tool_locks:
            _mcp_tool_locks[tool_name] = threading.Lock()
    tool_lock = _mcp_tool_locks[tool_name]
    with tool_lock:
        process = mcp_tool_processes.get(tool_name)
        if process is None or process.poll() is not None:
            if process is not None:
                log(f"Process for tool '{tool_name}' has terminated. Restarting.")
            else:
                log(f"No active process for tool '{tool_name}'. Starting a new one.")
            command = [tool_info["command"]] + tool_info.get("args", [])
            env = os.environ.copy()
            if "env" in tool_info:
                env.update(tool_info["env"])
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env
                )
                mcp_tool_processes[tool_name] = process
                mcp_init_request = {
                    "jsonrpc": "2.0", "id": 0, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "gemini-proxy", "version": "1.0.0"}}
                }
                process.stdin.write(json.dumps(mcp_init_request) + "\n")
                process.stdin.flush()
                time.sleep(0.1)
                initialized_notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
                process.stdin.write(json.dumps(initialized_notification) + "\n")
                process.stdin.flush()
                time.sleep(0.1)
                log(f"Successfully started and initialized process for tool '{tool_name}'.")
            except Exception as e:
                error_message = f"Failed to start or initialize tool '{tool_name}': {e}"
                print(error_message)
                if tool_name in mcp_tool_processes:
                    del mcp_tool_processes[tool_name]
                return error_message
        try:
            with mcp_request_id_lock:
                call_id = mcp_request_id_counter
                mcp_request_id_counter += 1
            normalized_args = _normalize_mcp_args(tool_args)
            input_schema = mcp_function_input_schema_map.get(function_name) or {}
            arguments_for_call = _coerce_args_to_schema(normalized_args, input_schema)
            mcp_call_request = {
                "jsonrpc": "2.0",
                "id": call_id,
                "method": "tools/call",
                "params": {
                    "name": function_name,
                    "arguments": arguments_for_call
                }
            }
            process.stdin.write(json.dumps(mcp_call_request) + "\n")
            process.stdin.flush()
            deadline = time.time() + 120
            while time.time() < deadline:
                ready_to_read, _, _ = select.select([process.stdout, process.stderr], [], [], 0.5)
                if not ready_to_read:
                    if process.poll() is not None:
                        print(f"Tool '{tool_name}' process terminated while waiting for response.")
                        stderr_output = process.stderr.read()
                        if stderr_output:
                            print(f"Stderr from '{tool_name}': {stderr_output.strip()}")
                        if tool_name in mcp_tool_processes:
                            del mcp_tool_processes[tool_name]
                        return f"Error: Tool '{tool_name}' terminated unexpectedly."
                    continue
                if process.stderr in ready_to_read:
                    err_line = process.stderr.readline()
                    if err_line:
                        print(f"Warning (stderr from '{tool_name}'): {err_line.strip()}")
                if process.stdout in ready_to_read:
                    line = process.stdout.readline()
                    if not line:
                        print(f"Tool '{tool_name}' process closed stdout. Assuming termination.")
                        if tool_name in mcp_tool_processes:
                            del mcp_tool_processes[tool_name]
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        if line.startswith('\ufeff'):
                            line = line.lstrip('\ufeff')
                        response = json.loads(line)
                        if response.get("id") == call_id:
                            if "result" in response:
                                content = response["result"].get("content", [])
                                is_all_text = content and all(item.get("type") == "text" for item in content)
                                if is_all_text:
                                    result_text = "".join(item.get("text", "") for item in content)
                                    return result_text
                                return json.dumps(response["result"])
                            elif "error" in response:
                                return f"MCP Error: {response['error'].get('message', 'Unknown error')}"
                            return "Tool returned a response with no result or error."
                    except json.JSONDecodeError:
                        print(f"Warning: Could not decode JSON from tool '{tool_name}': {line}")
                        continue
            return f"Error: Function '{function_name}' timed out after 120 seconds."
        except Exception as e:
            error_message = f"An unexpected error occurred while executing function '{function_name}': {e}"
            print(error_message)
            try:
                if process.poll() is None:
                    process.terminate()
            except Exception:
                pass
            if tool_name in mcp_tool_processes:
                del mcp_tool_processes[tool_name]
            return error_message
def cleanup_orig_files():
    project_root = get_project_root()
    for root, _, files in os.walk(project_root):
        for filename in files:
            if filename.endswith('.orig'):
                filepath = os.path.join( root, filename)
                try:
                    os.remove(filepath)
                    log(f"Cleaned up temporary file: {filepath}")
                except OSError as e:
                    log(f"Error cleaning up { filepath}: {e}")


def create_agent_plan(task_description: str, available_tools: list[str]) -> dict:
    """
    Create an execution plan for agent task using Agent Intelligence
    
    Args:
        task_description: User's task description
        available_tools: List of available tool names
        
    Returns:
        Plan dictionary with steps, risks, and validation method
    """
    try:
        from app.config import config
        if not config.AGENT_INTELLIGENCE_ENABLED:
            return None
        
        from app.utils.core.agent_intelligence import get_agent_orchestrator
        orchestrator = get_agent_orchestrator()
        plan = orchestrator.start_task(task_description, available_tools)
        
        log(f"🎯 Agent plan created: {len(plan.get('steps', []))} steps")
        return plan
    except Exception as e:
        log(f"Error creating agent plan: {e}")
        return None


def get_agent_context_prompt(project_root: str = None) -> str:
    """
    Get enhanced prompt with agent intelligence context
    
    Returns:
        Enhanced prompt text with planning and memory context
    """
    try:
        from app.config import config
        if not config.AGENT_INTELLIGENCE_ENABLED:
            return ""
        
        from app.utils.core.agent_intelligence import get_agent_orchestrator
        orchestrator = get_agent_orchestrator()
        
        # Get recent context
        context = orchestrator.memory.get_recent_context()
        
        # Get current plan if exists
        plan_prompt = ""
        if orchestrator.current_plan:
            plan = orchestrator.current_plan
            plan_prompt = "\n\n## 🎯 CURRENT TASK PLAN\n\n"
            plan_prompt += f"**Goal:** {plan.get('goal', 'Unknown')}\n\n"
            
            if plan.get('steps'):
                plan_prompt += "**Steps:**\n"
                for i, step in enumerate(plan['steps'], 1):
                    plan_prompt += f"{i}. Use `{step['tool']}` - {step['rationale']}\n"
        
        # Combine context
        if context or plan_prompt:
            return f"\n\n## 📝 AGENT CONTEXT\n\n{context}{plan_prompt}\n"
        
        return ""
    except Exception as e:
        log(f"Error getting agent context: {e}")
        return ""


def get_aux_model_stats() -> dict:
    """
    Get statistics from enhanced aux model
    
    Returns:
        Dictionary with stats (calls, tokens_saved, cache_hit_rate, etc.)
    """
    try:
        from app.utils.core.aux_model_enhanced import get_aux_model
        aux = get_aux_model()
        return aux.get_stats()
    except Exception as e:
        log(f"Error getting aux model stats: {e}")
        return {
            'total_calls': 0,
            'total_tokens_saved': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'cache_hit_rate': 0
        }