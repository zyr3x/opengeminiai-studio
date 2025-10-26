"""
MCP Tool Handling logic for Gemini-Proxy.
"""
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

from app.utils.core.tools import log, load_code_ignore_patterns # Import new utility
from contextlib import contextmanager
from . import optimization
from .optimization import record_tool_call # Explicitly import for clarity

# --- BUILT-IN CODE NAVIGATION TOOL DEFINITIONS ---
BUILTIN_TOOL_NAME = "__builtin_code_navigator"

# Thread-local storage to hold the project root for the current request context
_request_context = threading.local()

def get_project_root() -> str:
    """Gets the project root for the current request. Defaults to CWD if not set."""
    return getattr(_request_context, 'project_root', os.path.realpath(os.getcwd()))

@contextmanager
def set_project_root(path: str | None):
    """A context manager to set the project root for the duration of a request."""
    original_path = getattr(_request_context, 'project_root', None)
    if path and os.path.isdir(os.path.expanduser(path)):
        _request_context.project_root = os.path.realpath(os.path.expanduser(path))
    else:
        _request_context.project_root = os.path.realpath(os.getcwd())
    try:
        yield
    finally:
        _request_context.project_root = original_path


# Cache for ignore patterns, keyed by project root path
_ignore_patterns_cache = {}

def get_code_ignore_patterns() -> list[str]:
    """
    Loads and caches code ignore patterns from the .aiignore file and defaults.
    """
    project_root = get_project_root()
    if project_root not in _ignore_patterns_cache:
        patterns = load_code_ignore_patterns(project_root)
        _ignore_patterns_cache[project_root] = patterns
        return patterns
    return _ignore_patterns_cache[project_root]


def _safe_path_resolve(path: str) -> str | None:
    """Resolves a path relative to the current request's project root and checks if it stays within bounds."""
    from app.config import config
    
    project_root = get_project_root()
    # We always join the relative path to the project_root first
    full_path = os.path.join(project_root, path)
    resolved_path = os.path.realpath(full_path)

    # Crucial safety check: ensure the resolved path remains within the project root
    if not resolved_path.startswith(project_root):
        log(f"Security violation attempt: Path '{path}' resolves outside project root ({resolved_path} vs {project_root}).")
        return None
    
    # Additional check: if ALLOWED_CODE_PATHS is configured, ensure the path is within allowed directories
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
    """Generates an ASCII directory tree from a list of relative file paths."""
    tree_dict = {}
    for path_str in file_paths:
        # Use '/' as separator internally regardless of OS for consistent path parts splitting
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
    """
    Lists files and directories recursively for code context.
    Respects common ignore patterns. Returns an ASCII tree structure.
    An optional max_depth can be specified to limit traversal depth (e.g., max_depth=3).

    PHASE 3 - STAGE 2: Now with progress feedback for better UX.
    """
    from app.config import config
    
    resolved_path = _safe_path_resolve(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return f"Error: Path '{path}' not found or inaccessible."

    if os.path.isfile(resolved_path):
        return f"Path '{path}' is a file, not a directory. Use get_file_content."

    # Progress feedback (if enabled)
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

            # Filter directories in place first
            dirs[:] = [d for d in dirs if not (
                    d.startswith('.') or
                    any(fnmatch.fnmatch(os.path.join(rel_root, d).replace(os.sep, '/'), p) or fnmatch.fnmatch(d, p) for p in IGNORE_PATTERNS)
            )]

            # If max_depth is set, stop descending further once reached
            if max_depth != -1 and depth >= max_depth:
                dirs[:] = []

            for filename in files:
                if file_count >= MAX_FILES_LISTED:
                    dirs[:] = []  # Stop traversing deeper
                    break

                rel_filepath_fs = os.path.join(rel_root, filename)
                rel_filepath_norm = rel_filepath_fs.replace(os.sep, '/')

                if filename.startswith('.'): continue

                if any(fnmatch.fnmatch(rel_filepath_norm, p) or fnmatch.fnmatch(filename, p) for p in IGNORE_PATTERNS):
                    continue

                relative_paths.append(rel_filepath_fs)
                file_count += 1
                
                # Progress feedback every 50 files
                if config.STREAMING_PROGRESS_ENABLED and file_count - last_progress_report >= 50:
                    log(f"  📂 Found {file_count} files so far...")
                    last_progress_report = file_count

            if file_count >= MAX_FILES_LISTED:
                log(f"⚠️  Stopped at {MAX_FILES_LISTED} files to prevent large context.")
                break
    except Exception as e:
        log(f"Error during file listing for path '{path}': {e}")
        return f"Error: Failed to list directory contents due to system error."

    # Final progress
    if config.STREAMING_PROGRESS_ENABLED:
        log(f"✅ Scan complete: {file_count} files found")

    # Determine the name to display as the root of the tree
    tree_root_name = path if path != "." else os.path.basename(get_project_root())

    if not relative_paths:
        return f"Directory '{path}' is empty or contains only ignored files."

    full_tree_content = "Project structure:\n" + _generate_tree_local(relative_paths, tree_root_name)
    return full_tree_content

def get_file_content(path: str) -> str:
    """
    Reads the content of a single file, respecting safety bounds and size limits.
    Returns the file content formatted as a code snippet.
    """
    resolved_path = _safe_path_resolve(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return f"Error: File '{path}' not found or inaccessible."

    if not os.path.isfile(resolved_path):
        return f"Error: Path '{path}' is a directory, not a file."

    MAX_FILE_SIZE_BYTES = 256 * 1024 # 256 KB

    try:
        file_size = os.path.getsize(resolved_path)
        if file_size > MAX_FILE_SIZE_BYTES:
            return f"Error: File size ({file_size / 1024:.2f} KB) exceeds the maximum allowed limit of 256 KB."

        # Basic binary check (quick heuristic)
        with open(resolved_path, 'rb') as f:
            chunk = f.read(1024)
            if b'\0' in chunk:
                return f"Error: File '{path}' appears to be a binary file. Cannot read."

        _, extension = os.path.splitext(resolved_path)
        lang = extension.lstrip('.') if extension else ''

        # Read the entire file content as a single string
        with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
            file_content = f.read()

        return (
            f"\n--- Code File: {path} ({file_size / 1024:.2f} KB) ---\n"
            f"```{lang}\n"
            f"{file_content}\n"
            f"```\n"
        )

    except Exception as e:
        # Return the error as a string, as no generator was started.
        return f"Error reading file '{path}': {e}"

def get_code_snippet(path: str, symbol_name: str) -> str:
    """
    Extracts the source code of a specific function or class from a Python file.
    Use this after finding a symbol with `list_symbols_in_file`.
    """
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
                # ast.get_source_segment is the most reliable way to get the exact source
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
    """
    Searches the entire project codebase for a specific query string.
    Uses 'ripgrep' (rg) if available for speed and .gitignore support, otherwise falls back to 'grep'.
    Returns a formatted list of matches, including file paths and line numbers.
    
    PHASE 3 - STAGE 2: Now with progress feedback for better UX.
    """
    from app.config import config
    
    MAX_SEARCH_RESULTS = 100
    
    if config.STREAMING_PROGRESS_ENABLED:
        log(f"🔍 Searching codebase for: '{query}'")
    
    try:
        # Check if ripgrep (rg) is installed. We prefer it for its speed and gitignore handling.
        subprocess.run(['rg', '--version'], check=True, capture_output=True)
        # Use ripgrep with vimgrep format (file:line:col:text), which is structured and easy for an LLM to parse.
        command = ['rg', '--vimgrep', '--max-count', str(MAX_SEARCH_RESULTS), '--', query, '.']
        log(f"Using ripgrep for search with command: {' '.join(command)}")
        
        if config.STREAMING_PROGRESS_ENABLED:
            log(f"  📍 Searching with ripgrep...")
        
        result = subprocess.run(
            command, cwd=get_project_root(), capture_output=True, text=True, check=False
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        # Fallback to grep if ripgrep is not available.
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

    if result.returncode not in [0, 1]:  # 0 = success with matches, 1 = success with no matches
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
    """
    Applies a patch to the codebase to modify files.
    The user must provide the patch content in the standard unified diff format (e.g., from `git diff`).
    This tool should be used as the final step when a user asks to fix, refactor, or add code.
    """
    if not patch_content or not isinstance(patch_content, str):
        return "Error: Patch content must be a non-empty string."

    # Clean up potential markdown formatting from the LLM's output
    original_content = patch_content
    patch_content = patch_content.strip()
    
    # Remove markdown code blocks (various formats)
    if patch_content.startswith("```"):
        lines = patch_content.split('\n')
        # Remove first line (```diff or ```patch or just ```)
        lines = lines[1:]
        # Remove last line if it's ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        patch_content = '\n'.join(lines)
        log(f"Cleaned markdown formatting from patch")
    
    # Additional cleanup: remove any remaining stray ```
    patch_content = patch_content.replace('```', '')
    
    # Verify patch format (should start with --- or diff)
    patch_content = patch_content.strip()
    if not patch_content:
        return "Error: Patch content is empty after cleanup."
    
    if not (patch_content.startswith('---') or patch_content.startswith('diff ')):
        log(f"Warning: Patch doesn't start with standard format. First line: {patch_content.split(chr(10))[0][:50]}")

    """
    Applies a git-style patch string to the project codebase using the system's `patch` utility.

    This function securely writes the patch content to a temporary file and executes the
    `patch -p1` command from the project root.

    Args:
        patch_content: A string containing the patch in the standard unified diff format.

    Returns:
        A string indicating the success or failure of the patch application, including
        error messages if applicable.
    """
    log(f"Attempting to apply patch:\n---\n{patch_content}\n---")

    try:
        # Use a secure temporary file to pass the patch to the command
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
            tmp.write(patch_content)
            temp_patch_file = tmp.name

        try:
            # The `patch` command is standard on Linux/macOS. -p1 strips the 'a/' and 'b/' prefixes.
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
            # Build detailed error message
            error_message = f"Error applying patch. Return code: {result.returncode}\n"
            
            # Check for common issues
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
            
            # Add first few lines of the patch for debugging
            patch_preview = '\n'.join(patch_content.split('\n')[:10])
            error_message += f"\nFirst 10 lines of patch:\n{patch_preview}\n"
            
            log(error_message)
            return error_message

    except Exception as e:
        log(f"Failed to execute patch command: {e}")
        return f"Error: An unexpected exception occurred while trying to apply the patch: {e}"


# --- GIT OPERATIONS ---
def git_status() -> str:
    """
    Shows the working tree status including staged, unstaged, and untracked files.
    This is useful for understanding what changes exist before committing.
    """
    try:
        result = subprocess.run(
            ['git', 'status', '--short', '--branch'],
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            check=False,
            timeout=10
        )

        if result.returncode != 0:
            return f"Error: Not a git repository or git command failed.\n{result.stderr}"

        if not result.stdout.strip():
            return "Working tree is clean (no changes)."

        return f"Git Status:\n```\n{result.stdout.strip()}\n```"
    except subprocess.TimeoutExpired:
        return "Error: git status command timed out."
    except FileNotFoundError:
        return "Error: git command not found. Please ensure git is installed."
    except Exception as e:
        return f"Error running git status: {e}"


def git_log(max_count: int = 10, path: str = None) -> str:
    """
    Shows the commit history with author, date, and commit message.
    Optionally filter by a specific file path.
    """
    try:
        max_count = int(max_count) if max_count else 10
        max_count = min(max(1, max_count), 50)  # Limit between 1 and 50

        cmd = ['git', 'log', f'--max-count={max_count}', '--oneline', '--graph', '--decorate']
        if path:
            resolved_path = _safe_path_resolve(path)
            if not resolved_path:
                return f"Error: Invalid or unsafe path '{path}'."
            cmd.extend(['--', resolved_path])

        result = subprocess.run(
            cmd,
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            check=False,
            timeout=15
        )

        if result.returncode != 0:
            return f"Error: git log failed.\n{result.stderr}"

        if not result.stdout.strip():
            return "No commits found." if not path else f"No commits found for path '{path}'."

        header = f"Last {max_count} commits" + (f" for {path}" if path else "") + ":\n"
        return f"{header}```\n{result.stdout.strip()}\n```"
    except Exception as e:
        return f"Error running git log: {e}"


def git_diff(staged: bool = False, path: str = None) -> str:
    """
    Shows changes in the working directory or staged area.
    Use staged=True to see changes in the staging area (git diff --cached).
    """
    try:
        cmd = ['git', 'diff']
        if staged:
            cmd.append('--cached')

        if path:
            resolved_path = _safe_path_resolve(path)
            if not resolved_path:
                return f"Error: Invalid or unsafe path '{path}'."
            cmd.extend(['--', resolved_path])

        result = subprocess.run(
            cmd,
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            check=False,
            timeout=30
        )

        if result.returncode != 0:
            return f"Error: git diff failed.\n{result.stderr}"

        if not result.stdout.strip():
            area = "staged area" if staged else "working directory"
            return f"No changes in {area}." + (f" for path '{path}'." if path else "")

        # Limit output size
        output = result.stdout
        if len(output) > 50000:  # ~50KB limit
            output = output[:50000] + "\n... (output truncated, diff is too large)"

        return f"Git Diff:\n```diff\n{output}\n```"
    except Exception as e:
        return f"Error running git diff: {e}"


def git_show(commit: str = "HEAD", path: str = None) -> str:
    """
    Shows the contents of a specific commit.
    Optionally filter by a specific file path to see only changes to that file.
    """
    try:
        if not commit:
            commit = "HEAD"

        # Security: sanitize commit reference
        if not re.match(r'^[a-zA-Z0-9_\-\.\/]+$', commit):
            return f"Error: Invalid commit reference '{commit}'."

        cmd = ['git', 'show', commit, '--stat']
        if path:
            resolved_path = _safe_path_resolve(path)
            if not resolved_path:
                return f"Error: Invalid or unsafe path '{path}'."
            # For git show, we need relative path from git root
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

        result = subprocess.run(
            cmd,
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            check=False,
            timeout=15
        )

        if result.returncode != 0:
            return f"Error: git show failed. Commit '{commit}' may not exist.\n{result.stderr}"

        output = result.stdout
        if len(output) > 30000:
            output = output[:30000] + "\n... (output truncated)"

        return f"Commit {commit}:\n```\n{output}\n```"
    except Exception as e:
        return f"Error running git show: {e}"


def git_blame(path: str, start_line: int = None, end_line: int = None) -> str:
    """
    Shows who last modified each line of a file and when.
    Optionally specify line range with start_line and end_line.
    """
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

        # Get relative path from git root
        git_root = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        rel_path = os.path.relpath(resolved_path, git_root)
        cmd.append(rel_path)

        result = subprocess.run(
            cmd,
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            check=False,
            timeout=15
        )

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
    """
    Lists files that were modified in the last N days using git log.
    Useful for understanding recent development activity.
    """
    try:
        days = int(days) if days else 7
        days = min(max(1, days), 90)  # Limit between 1 and 90 days

        max_files = int(max_files) if max_files else 20
        max_files = min(max(1, max_files), 100)

        result = subprocess.run(
            ['git', 'log', f'--since={days} days ago', '--name-only', '--pretty=format:', '--'],
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            check=False,
            timeout=15
        )

        if result.returncode != 0:
            return f"Error: git log failed.\n{result.stderr}"

        # Parse unique files from output
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


# --- FILE ANALYSIS ---
def analyze_file_structure(path: str) -> str:
    """
    Analyzes a Python file to extract comprehensive structural information:
    imports, functions, classes, decorators, and docstrings.
    """
    resolved_path = _safe_path_resolve(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return f"Error: File '{path}' not found or inaccessible."

    if not os.path.isfile(resolved_path):
        return f"Error: Path '{path}' is not a file."

    try:
        with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        tree = ast.parse(content)

        # Extract imports
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

        # Extract top-level definitions
        functions = []
        classes = []

        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                # Extract function signature
                args_str = ", ".join([arg.arg for arg in node.args.args])
                decorators = [d.id if isinstance(d, ast.Name) else ast.unparse(d) for d in node.decorator_list]

                func_info = f"def {node.name}({args_str})"
                if decorators:
                    func_info = f"@{', @'.join(decorators)}\n  {func_info}"

                # Add docstring if present
                docstring = ast.get_docstring(node)
                if docstring:
                    # Truncate long docstrings
                    if len(docstring) > 100:
                        docstring = docstring[:100] + "..."
                    func_info += f"\n    \"\"\"{docstring}\"\"\""

                functions.append(func_info)

            elif isinstance(node, ast.ClassDef):
                # Extract class info
                bases = [ast.unparse(base) for base in node.bases]
                bases_str = f"({', '.join(bases)})" if bases else ""

                class_info = f"class {node.name}{bases_str}"

                # Count methods
                methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
                class_info += f"  # {len(methods)} method(s)"

                # Add docstring
                docstring = ast.get_docstring(node)
                if docstring:
                    if len(docstring) > 80:
                        docstring = docstring[:80] + "..."
                    class_info += f"\n    \"\"\"{docstring}\"\"\""

                classes.append(class_info)

        # Build result
        result = [f"File Structure Analysis: {path}", "=" * 50, ""]

        if imports:
            result.append("IMPORTS:")
            for imp in imports[:20]:  # Limit to first 20
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
    """
    Returns statistics about a file: size, lines, language, last modified date, and git info.
    """
    resolved_path = _safe_path_resolve(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return f"Error: File '{path}' not found or inaccessible."

    if not os.path.isfile(resolved_path):
        return f"Error: Path '{path}' is not a file."

    try:
        stats = os.stat(resolved_path)
        file_size = stats.st_size
        modified_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stats.st_mtime))

        # Detect language by extension
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

        # Count lines
        try:
            with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                total_lines = len(lines)
                code_lines = sum(1 for line in lines if line.strip() and not line.strip().startswith('#'))
                blank_lines = sum(1 for line in lines if not line.strip())
                comment_lines = total_lines - code_lines - blank_lines
        except:
            total_lines = code_lines = blank_lines = comment_lines = 0

        # Git info
        git_info = ""
        try:
            # Get relative path from git root
            git_root = subprocess.run(
                ['git', 'rev-parse', '--show-toplevel'],
                cwd=get_project_root(),
                capture_output=True,
                text=True,
                check=True,
                timeout=5
            ).stdout.strip()
            rel_path = os.path.relpath(resolved_path, git_root)

            # Last commit for this file
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

        # Format output
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
    """
    Creates a new file with the specified content.
    Args:
        path: File path relative to project root
        content: Content to write to the file
        mode: File permissions (default: 644)
    Returns:
        Success message or error
    """
    try:
        resolved_path = _safe_path_resolve(path)
        if not resolved_path:
            return f"Error: Access denied to path '{path}' (outside project root)"
        
        # Check if file already exists
        if os.path.exists(resolved_path):
            return f"Error: File '{path}' already exists. Use write_file to overwrite or choose different name."
        
        # Create parent directories if needed
        os.makedirs(os.path.dirname(resolved_path), exist_ok=True)
        
        # Write content
        with open(resolved_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Set permissions
        try:
            os.chmod(resolved_path, int(mode, 8))
        except:
            pass  # Ignore permission errors on Windows
        
        file_size = len(content.encode('utf-8'))
        lines = content.count('\n') + 1
        
        return f"✅ File created successfully: {path}\nSize: {file_size} bytes, Lines: {lines}\nPermissions: {mode}"
    
    except Exception as e:
        return f"Error creating file: {e}"

def write_file(path: str, content: str) -> str:
    """
    Writes content to an existing file, overwriting it completely.
    Args:
        path: File path relative to project root
        content: New content for the file
    Returns:
        Success message or error
    """
    try:
        resolved_path = _safe_path_resolve(path)
        if not resolved_path:
            return f"Error: Access denied to path '{path}' (outside project root)"
        
        if not os.path.exists(resolved_path):
            return f"Error: File '{path}' does not exist. Use create_file to create new files."
        
        # Backup old content size for reporting
        old_size = os.path.getsize(resolved_path)
        
        # Write new content
        with open(resolved_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        new_size = len(content.encode('utf-8'))
        lines = content.count('\n') + 1
        
        return f"✅ File updated successfully: {path}\nOld size: {old_size} bytes → New size: {new_size} bytes\nLines: {lines}"
    
    except Exception as e:
        return f"Error writing file: {e}"

def execute_command(command: str, timeout: int = 30) -> str:
    """
    Executes a shell command and returns its output.
    Args:
        command: Shell command to execute
        timeout: Maximum execution time in seconds (default: 30, max: 300)
    Returns:
        Command output (stdout + stderr) or error
    """
    try:
        # Security: limit timeout
        timeout = min(max(1, timeout), 300)
        
        log(f"Executing command: {command[:100]}...")
        
        # Execute command
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
    """
    Analyzes the entire project structure and returns a comprehensive overview.
    Returns:
        Project analysis including file types, sizes, dependencies, and structure
    """
    try:
        project_root = get_project_root()
        
        analysis = []
        analysis.append(f"📊 Project Analysis: {os.path.basename(project_root)}")
        analysis.append(f"Root: {project_root}\n")
        
        # Collect file statistics
        file_types = {}
        total_files = 0
        total_size = 0
        language_files = {}
        
        ignore_patterns = get_code_ignore_patterns()
        
        for root, dirs, files in os.walk(project_root):
            # Filter directories
            dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, p) for p in ignore_patterns)]
            
            rel_root = os.path.relpath(root, project_root)
            if rel_root != '.' and any(fnmatch.fnmatch(rel_root, p) or fnmatch.fnmatch(os.path.join(rel_root, ''), p) for p in ignore_patterns):
                continue
            
            for file in files:
                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, project_root)
                
                # Check if file matches ignore patterns
                if any(fnmatch.fnmatch(rel_path, p) or fnmatch.fnmatch(file, p) for p in ignore_patterns):
                    continue
                
                try:
                    size = os.path.getsize(filepath)
                    ext = os.path.splitext(file)[1].lower() or '(no extension)'
                    
                    file_types[ext] = file_types.get(ext, 0) + 1
                    total_files += 1
                    total_size += size
                    
                    # Language detection
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
        
        # File types summary
        analysis.append("📁 File Types:")
        sorted_types = sorted(file_types.items(), key=lambda x: x[1], reverse=True)[:15]
        for ext, count in sorted_types:
            analysis.append(f"  {ext}: {count} files")
        
        # Language summary
        if language_files:
            analysis.append("\n💻 Programming Languages:")
            sorted_langs = sorted(language_files.items(), key=lambda x: x[1], reverse=True)
            for lang, count in sorted_langs:
                analysis.append(f"  {lang}: {count} files")
        
        # Size summary
        size_mb = total_size / (1024 * 1024)
        analysis.append(f"\n📦 Total: {total_files} files, {size_mb:.2f} MB")
        
        # Check for common project files
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
        
        # Git status if available
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
    """
    Searches for a symbol (function, class, variable) across the entire project.
    Args:
        symbol_name: Name of the symbol to find
    Returns:
        List of files and locations where the symbol is defined or used
    """
    try:
        project_root = get_project_root()
        ignore_patterns = get_code_ignore_patterns()
        
        results = []
        results.append(f"🔍 Searching for symbol: '{symbol_name}'\n")
        
        # Patterns to search for
        patterns = [
            f"def {symbol_name}",      # Python function
            f"class {symbol_name}",    # Python/Java class
            f"function {symbol_name}", # JavaScript function
            f"const {symbol_name}",    # JavaScript/TypeScript const
            f"let {symbol_name}",      # JavaScript/TypeScript let
            f"var {symbol_name}",      # JavaScript var
            f"{symbol_name} =",        # Assignment
            f"{symbol_name}(",         # Function call
        ]
        
        found_items = []
        
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, p) for p in ignore_patterns)]
            
            rel_root = os.path.relpath(root, project_root)
            if rel_root != '.' and any(fnmatch.fnmatch(rel_root, p) for p in ignore_patterns):
                continue
            
            for file in files:
                # Only search in code files
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
                                    break  # One match per line
                except:
                    pass
        
        if not found_items:
            return f"❌ Symbol '{symbol_name}' not found in the project."
        
        # Group by file
        from collections import defaultdict
        by_file = defaultdict(list)
        for item in found_items:
            by_file[item['file']].append(item)
        
        results.append(f"✅ Found {len(found_items)} occurrences in {len(by_file)} files:\n")
        
        for file, items in sorted(by_file.items()):
            results.append(f"📄 {file}:")
            for item in items[:5]:  # Limit to first 5 per file
                results.append(f"  Line {item['line']}: {item['content'][:80]}")
            if len(items) > 5:
                results.append(f"  ... and {len(items) - 5} more occurrences")
            results.append("")
        
        return "\n".join(results)
    
    except Exception as e:
        return f"Error finding symbol: {e}"

def get_dependencies() -> str:
    """
    Detects and lists project dependencies from common dependency files.
    Returns:
        List of dependencies found in the project
    """
    try:
        project_root = get_project_root()
        
        results = []
        results.append("📦 Project Dependencies\n")
        
        # Python - requirements.txt
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
        
        # Python - pyproject.toml
        pyproject = os.path.join(project_root, 'pyproject.toml')
        if os.path.exists(pyproject):
            results.append("🐍 Python (pyproject.toml): (file exists)")
        
        # Node.js - package.json
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
        
        # Go - go.mod
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
        
        # Rust - Cargo.toml
        cargo_toml = os.path.join(project_root, 'Cargo.toml')
        if os.path.exists(cargo_toml):
            results.append("🦀 Rust (Cargo.toml): (file exists)")
        
        if len(results) == 2:  # Only header
            return "❌ No dependency files found (requirements.txt, package.json, go.mod, Cargo.toml, etc.)"
        
        return "\n".join(results)
    
    except Exception as e:
        return f"Error getting dependencies: {e}"

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
    "get_file_stats": get_file_stats
}

BUILTIN_DECLARATIONS = [
    {
        "name": "list_files",
        "description": "Lists files and directories recursively from a starting path, returning an ASCII directory tree structure. This is the first step to understand the project layout before fetching file content. Use '.' to list the current project root. Results are filtered by standard ignore rules (e.g., .git, venv, build artifacts).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "The starting path relative to the current working directory. Use '.' for the project root."
                },
                "max_depth": {
                    "type": "INTEGER",
                    "description": "Optional. The maximum depth of directories to traverse. `max_depth=1` lists the current directory."
                }
            }
        }
    },
    {
        "name": "get_code_snippet",
        "description": "Extracts the source code of a specific function or class from a Python file. Use this after finding a symbol with analyze_file_structure.",
        "parameters": {
            "type": "OBJECT",
            "required": ["path", "symbol_name"],
            "properties": {
                "path": {
                    "type":  "STRING",
                    "description": "The path to the file relative to the current working directory."
                },
                "symbol_name": {
                    "type": "STRING",
                    "description": "The name  of the function or class to extract."
                }
            }
        }
    },
    {
        "name": "get_file_content",
        "description": "Reads and returns the content of a single specified text file. Use this after identifying the file via list_files. Limited to 256 KB per file.",
        "parameters": {
            "type": "OBJECT",
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "The path to the file relative to the current working directory."
                }
            }
        }
    },
    {
        "name": "search_codebase",
        "description": "Performs a fast, line-based search for a string query across all files in the project, returning matching lines with their file paths and line numbers. Ideal for finding where functions are called or variables are defined.",
        "parameters": {
            "type": "OBJECT",
            "required": ["query"],
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "The string or regular expression to search for."
                }
            }
        }
    },
    {
        "name": "apply_patch",
        "description": "Applies a code patch (in unified diff format) to the codebase. Use this for making code changes.",
        "parameters": {
            "type": "object",
            "properties": {
                "patch_content": {
                    "type": "string",
                    "description": "The patch content in unified diff format (e.g., as generated by 'git diff')."
                }
            },
            "required": ["patch_content"]
        }
    },
    {
        "name": "git_status",
        "description": "Shows the working tree status including staged, unstaged, and untracked files. Essential for understanding current changes before committing.",
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    },
    {
        "name": "git_log",
        "description": "Shows commit history with messages and metadata. Optionally filter by file path to see commits affecting a specific file.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "max_count": {
                    "type": "INTEGER",
                    "description": "Maximum number of commits to show (1-50, default 10)."
                },
                "path": {
                    "type": "STRING",
                    "description": "Optional file path to filter commits that modified this file."
                }
            }
        }
    },
    {
        "name": "git_diff",
        "description": "Shows changes in the working directory or staging area. Use staged=True to see what will be committed.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "staged": {
                    "type": "BOOLEAN",
                    "description": "If true, shows staged changes (git diff --cached). If false or omitted, shows unstaged changes."
                },
                "path": {
                    "type": "STRING",
                    "description": "Optional file path to show diff only for this file."
                }
            }
        }
    },
    {
        "name": "git_show",
        "description": "Shows the content and metadata of a specific commit. Use this to inspect what changed in a commit.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "commit": {
                    "type": "STRING",
                    "description": "Commit reference (hash, branch name, or 'HEAD'). Default is 'HEAD'."
                },
                "path": {
                    "type": "STRING",
                    "description": "Optional file path to show changes only for this file in the commit."
                }
            }
        }
    },
    {
        "name": "git_blame",
        "description": "Shows who last modified each line of a file and when. Useful for understanding code history and authorship.",
        "parameters": {
            "type": "OBJECT",
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "Path to the file to blame."
                },
                "start_line": {
                    "type": "INTEGER",
                    "description": "Optional starting line number for blame range."
                },
                "end_line": {
                    "type": "INTEGER",
                    "description": "Optional ending line number for blame range."
                }
            }
        }
    },
    {
        "name": "list_recent_changes",
        "description": "Lists files modified in the last N days based on git history. Useful for understanding recent development activity.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "days": {
                    "type": "INTEGER",
                    "description": "Number of days to look back (1-90, default 7)."
                },
                "max_files": {
                    "type": "INTEGER",
                    "description": "Maximum number of files to return (1-100, default 20)."
                }
            }
        }
    },
    {
        "name": "analyze_file_structure",
        "description": "Analyzes a Python file's structure: imports, classes, functions, decorators, and docstrings.",
        "parameters": {
            "type": "OBJECT",
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "Path to the Python file to analyze."
                }
            }
        }
    },
    {
        "name": "get_file_stats",
        "description": "Returns comprehensive file statistics: size, lines of code, language, modification date, and git history.",
        "parameters": {
            "type": "OBJECT",
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "Path to the file to analyze."
                }
            }
        }
    },
    {
        "name": "create_file",
        "description": "Creates a new file with specified content. Perfect for creating scripts, config files, or any new files. Use write_file to modify existing files.",
        "parameters": {
            "type": "OBJECT",
            "required": ["path", "content"],
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "Path for the new file relative to project root."
                },
                "content": {
                    "type": "STRING",
                    "description": "Content to write to the file."
                },
                "mode": {
                    "type": "STRING",
                    "description": "Optional file permissions in octal format (default: '644', executable: '755')."
                }
            }
        }
    },
    {
        "name": "write_file",
        "description": "Writes content to an existing file, completely overwriting it. File must already exist (use create_file for new files).",
        "parameters": {
            "type": "OBJECT",
            "required": ["path", "content"],
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "Path to the existing file."
                },
                "content": {
                    "type": "STRING",
                    "description": "New content for the file."
                }
            }
        }
    },
    {
        "name": "execute_command",
        "description": "Executes a shell command and returns its output. Useful for running builds, tests, awk/sed scripts, or any shell commands. Commands run in project root directory.",
        "parameters": {
            "type": "OBJECT",
            "required": ["command"],
            "properties": {
                "command": {
                    "type": "STRING",
                    "description": "Shell command to execute (e.g., 'npm test', 'python script.py', 'awk ...')."
                },
                "timeout": {
                    "type": "INTEGER",
                    "description": "Maximum execution time in seconds (default: 30, max: 300)."
                }
            }
        }
    },
    {
        "name": "analyze_project_structure",
        "description": "Analyzes the entire project and returns a comprehensive overview: file types, programming languages, dependencies files found, total size, and structure. Great for understanding a new project quickly.",
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    },
    {
        "name": "find_symbol",
        "description": "Searches for a symbol (function, class, variable, constant) across the entire project. Returns all files and line numbers where the symbol is defined or used.",
        "parameters": {
            "type": "OBJECT",
            "required": ["symbol_name"],
            "properties": {
                "symbol_name": {
                    "type": "STRING",
                    "description": "Name of the symbol to find (e.g., 'myFunction', 'MyClass')."
                }
            }
        }
    },
    {
        "name": "get_dependencies",
        "description": "Detects and lists project dependencies from common dependency files (requirements.txt, package.json, go.mod, Cargo.toml, etc.). Shows all dependencies with versions.",
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    }
]
# --- END BUILT-IN CODE NAVIGATION TOOL DEFINITIONS ---


# --- MCP Tool Configuration ---
MCP_CONFIG_FILE = 'var/config/mcp.json'
mcp_function_declarations = []  # A flat list of all function declarations from all tools
mcp_function_to_tool_map = {}   # Maps a function name to its parent tool name (from mcpServers)
mcp_function_input_schema_map = {}  # Maps a function name to its inputSchema from MCP
mcp_tool_processes = {}  # Cache for running tool subprocesses
mcp_request_id_counter = 1  # Counter for unique JSON-RPC request IDs
mcp_request_id_lock = threading.Lock() # Lock to ensure thread-safe request ID generation
_mcp_tool_locks = {} # Cache for tool-specific locks to prevent race conditions
_mcp_tool_locks_lock = threading.Lock() # Lock to manage access to the locks dictionary

MAX_FUNCTION_DECLARATIONS_DEFAULT = 64 # Default documented limit
max_function_declarations_limit = MAX_FUNCTION_DECLARATIONS_DEFAULT # Configurable limit

DISABLE_ALL_MCP_TOOLS_DEFAULT = False
disable_all_mcp_tools = DISABLE_ALL_MCP_TOOLS_DEFAULT # Global flag to disable all MCP tools

def set_disable_all_mcp_tools(status: bool):
    """Sets the global status for disabling all MCP tools and saves it to config."""
    global disable_all_mcp_tools, mcp_config
    disable_all_mcp_tools = status
    # Update the in-memory config and save it
    mcp_config["disableAllTools"] = status
    try:
        with open(MCP_CONFIG_FILE, 'w') as f:
            json.dump(mcp_config, f, indent=2)
        log(f"MCP general settings updated and saved to {MCP_CONFIG_FILE}. Disable all tools: {status}")
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error saving MCP config: {e}")


def get_declarations_from_tool(tool_name, tool_info):
    """Fetches function declaration schema(s) from an MCP tool using MCP protocol."""
    global mcp_function_input_schema_map
    command = [tool_info["command"]] + tool_info.get("args", [])
    env = os.environ.copy()
    if "env" in tool_info:
        env.update(tool_info["env"])

    try:
        log(f"Fetching schema for tool '{tool_name}'...")

        # Send MCP initialization and tools/list request
        mcp_init_request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "gemini-proxy", "version": "2.2.0"}
            }
        }

        tools_list_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }

        # Send initialize -> notifications/initialized -> tools/list in a single stdio session
        initialized_notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        input_data = (
            json.dumps(mcp_init_request) + "\n" +
            json.dumps(initialized_notification) + "\n" +
            json.dumps(tools_list_request) + "\n"
        )

        process = subprocess.run(
            command,
            input=input_data,
            text=True,
            capture_output=True,
            check=False,
            env=env,
            timeout=30
        )

        if process.returncode != 0:
            print(f"MCP tool '{tool_name}' failed with exit code {process.returncode}")
            if process.stderr:
                print(f"Stderr: {process.stderr}")
            return []

        # Parse MCP response - look for tools/list response (id == 1)
        lines = process.stdout.strip().split('\n')
        tools = []

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
                    mcp_tools = response["result"]["tools"]

                    # Convert MCP tool format to Gemini function declarations
                    for tool in mcp_tools:
                        declaration = {
                            "name": tool["name"],
                            "description": tool.get("description", f"Execute {tool['name']} tool")
                        }
                        # Cache original inputSchema for later argument coercion
                        mcp_function_input_schema_map[tool["name"]] = tool.get("inputSchema")

                        # Convert MCP input schema to Gemini parameters format
                        if "inputSchema" in tool:
                            schema = tool["inputSchema"]
                            if schema.get("type") == "object":
                                # Use Gemini function schema types (uppercase)
                                declaration["parameters"] = {
                                    "type": "OBJECT",
                                    "properties": {}
                                }

                                def convert_property_to_gemini(prop_def):
                                    """Convert a JSON Schema property to Gemini function parameter format."""
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
                                        # Handle array items - required for Gemini API
                                        items = prop_def.get("items", {})
                                        if items:
                                            param["items"] = convert_property_to_gemini(items)
                                        else:
                                            # Default to string items if not specified
                                            param["items"] = {"type": "STRING"}
                                        return param
                                    elif t == "object":
                                        param = {
                                            "type": "OBJECT",
                                            "description": prop_def.get("description", "Object parameter")
                                        }
                                        # Handle nested object properties
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
                    break
            except json.JSONDecodeError:
                continue

        if process.stderr:
            print(f"Stderr: {process.stderr}")

        log(f"Successfully fetched {len(tools)} function declaration(s) for tool '{tool_name}'.")
        return tools

    except subprocess.TimeoutExpired:
        print(f"Error: Timeout while fetching schema for tool '{tool_name}'.")
    except Exception as e:
        print(f"An unexpected error occurred while fetching schema for tool '{tool_name}': {e}")

    return []

def fetch_mcp_tool_list(tool_info):
    """Fetches the raw list of tools from an MCP server based on its config."""
    command_str = tool_info.get("command")
    if not command_str:
        return {"error": "Command not provided."}

    command = [command_str] + tool_info.get("args", [])
    env = os.environ.copy()
    if "env" in tool_info:
        env.update(tool_info["env"])

    try:
        log(f"Fetching tool list for command: '{command_str}'")

        mcp_init_request = {
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "gemini-proxy", "version": "1.0.0"}}
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
            return {"error": f"Tool failed with exit code {process.returncode}", "stderr": process.stderr.strip()}

        lines = process.stdout.strip().split('\n')
        for line in lines:
            if not line.strip():
                continue
            try:
                if line.startswith('\ufeff'):
                    line = line.lstrip('\ufeff')
                response = json.loads(line)
                if response.get("id") == 1 and "result" in response and "tools" in response["result"]:
                    return {"tools": response["result"]["tools"]}
            except json.JSONDecodeError:
                continue

        return {"error": "Did not receive a valid tools/list response.", "stdout": process.stdout.strip(), "stderr": process.stderr.strip()}

    except subprocess.TimeoutExpired:
        return {"error": "Timeout while fetching tool list."}
    except FileNotFoundError:
        return {"error": f"Command not found: '{command_str}'."}
    except Exception as e:
        return {"error": f"An unexpected error occurred: {e}"}

def load_mcp_config():
    """Loads MCP tool configuration from file and fetches schemas for all configured tools."""
    global mcp_config, mcp_function_declarations, mcp_function_to_tool_map, mcp_function_input_schema_map, mcp_tool_processes, max_function_declarations_limit, disable_all_mcp_tools

    # Terminate any existing tool processes before reloading config
    for tool_name, process in mcp_tool_processes.items():
        if process.poll() is None:  # Check if the process is running
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

    # 1. Load Declarations from External MCP Servers
    if mcp_config.get("mcpServers"):
        # Sort servers by priority (higher first), default 0
        sorted_servers = sorted(
            mcp_config["mcpServers"].items(),
            key=lambda item: item[1].get('priority', 0),
            reverse=True
        )

        for tool_name, tool_info in sorted_servers:
            # Skip disabled tools (defaults to enabled if 'enabled' key is missing)
            if not tool_info.get('enabled', True):
                log(f"Skipping disabled tool: '{tool_name}'.")
                continue

            declarations = get_declarations_from_tool(tool_name, tool_info)
            mcp_function_declarations.extend(declarations)
            for decl in declarations:
                if 'name' in decl:
                    mcp_function_to_tool_map[decl['name']] = tool_name

    # 2. Add Built-in Code Navigation Tool (always registered)
    mcp_function_declarations.extend(BUILTIN_DECLARATIONS)
    for decl in BUILTIN_DECLARATIONS:
        if 'name' in decl:
            mcp_function_to_tool_map[decl['name']] = BUILTIN_TOOL_NAME
            # Built-in tools have no external schema, use empty dict for input coercion logic safety
            mcp_function_input_schema_map[decl['name']] = {}

    log(f"Total function declarations loaded: {len(mcp_function_declarations)}")

def create_tool_declarations(prompt_text: str = ""):
    """
    Returns tool declarations for the Gemini API, intelligently selecting them based on the prompt.
    If a tool's name (e.g., 'youtrack') or a function's name (e.g., 'get_issue') is mentioned in the prompt,
    only the functions from the relevant tool(s) are sent. Otherwise, it sends all available functions
    up to the API limit.
    """
    if disable_all_mcp_tools:
        log("All MCP tools are globally disabled. Returning no declarations.")
        return None

    if not mcp_function_declarations:
        return None

    selected_tool_names = set()
    padded_prompt = f' {prompt_text.lower()} '

    # Context-aware tool selection
    if prompt_text:
        # 1. Check for tool server names (e.g., 'youtrack')
        if mcp_config.get("mcpServers"):
            for tool_name in mcp_config["mcpServers"].keys():
                if f' {tool_name.lower()} ' in padded_prompt:
                    log(f"Detected keyword for tool server '{tool_name}'.")
                    selected_tool_names.add(tool_name)

        # 2. Check for individual function names (e.g., 'get_issue')
        for func_decl in mcp_function_declarations:
            func_name = func_decl['name']
            if f' {func_name.lower()} ' in padded_prompt:
                parent_tool_name = mcp_function_to_tool_map.get(func_name)
                if parent_tool_name and parent_tool_name not in selected_tool_names:
                    log(f"Detected keyword for function '{func_name}'. Selecting parent tool '{parent_tool_name}'.")
                    selected_tool_names.add(parent_tool_name)

    # If specific tools were selected, build the declaration list from them
    if selected_tool_names:
        log(f"Final selected tools: {list(selected_tool_names)}")
        selected_declarations = []
        for func_decl in mcp_function_declarations:
            if mcp_function_to_tool_map.get(func_decl['name']) in selected_tool_names:
                selected_declarations.append(func_decl)
        final_declarations = selected_declarations
    else:
        # Fallback: use all declarations
        final_declarations = []

    if len(final_declarations) > max_function_declarations_limit:
        log(f"Warning: Number of function declarations ({len(final_declarations)}) exceeds the limit of {max_function_declarations_limit}. Truncating list.")
        final_declarations = final_declarations[:max_function_declarations_limit]

    if not final_declarations:
        return None

    return [{"functionDeclarations": final_declarations}]

def create_tool_declarations_from_list(function_names: list[str]):
    """
    Returns tool declarations for the Gemini API, selecting only those from the specified list of function names.
    This bypasses context-aware selection and respects the max_function_declarations_limit.
    """
    if disable_all_mcp_tools:
        log("All MCP tools are globally disabled. Returning no declarations.")
        return None

    if not mcp_function_declarations or not function_names:
        return None

    selected_declarations = []
    # Handle sentinel for "all functions"
    if function_names == ["*"]:
        log("Selecting all available MCP functions due to '*' sentinel.")
        selected_declarations = mcp_function_declarations[:]  # Make a copy
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
    """
    Parses a simple key=value string (supports quoted values) into a dict.
    Example: 'issue_id="ACS-611" limit=10' -> {'issue_id': 'ACS-611', 'limit': '10'}
    """
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

def _normalize_mcp_args(args) -> dict:
    """
    Normalizes functionCall args from Gemini into a JSON object suitable for MCP tools/call.
    Handles:
      - dict with 'kwargs' field containing string or dict
      - plain string (JSON or key=value pairs)
      - already-correct dict
    """
    if args is None:
        return {}
    # If already a dict without wrapper keys
    if isinstance(args, dict) and "kwargs" not in args and "args" not in args:
        return args
    # If dict with kwargs wrapper
    if isinstance(args, dict):
        kwargs_val = args.get("kwargs")
        if isinstance(kwargs_val, dict):
            return kwargs_val
        if isinstance(kwargs_val, str):
            # Try JSON first
            try:
                parsed = json.loads(kwargs_val)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
            # Fallback to key=value parsing
            parsed_kv = _parse_kwargs_string(kwargs_val)
            if parsed_kv:
                return parsed_kv
        # If 'args' is a JSON string with object, try it
        args_val = args.get("args")
        if isinstance(args_val, str):
            try:
                parsed_args = json.loads(args_val)
                if isinstance(parsed_args, dict):
                    return parsed_args
            except json.JSONDecodeError:
                pass
        return {}
    # If a raw string
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return _parse_kwargs_string(args)
    # Unknown type
    return {}

def _ensure_dict(value):
    """
    Ensures the value is a dict. If a string, try JSON then key=value parsing.
    """
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
    """
    Coerces normalized arguments into the structure required by input_schema.
    If schema expects 'args'/'kwargs', wrap values accordingly.
    """
    if not isinstance(input_schema, dict):
        return normalized_args

    props = input_schema.get("properties", {}) or {}
    required = set(input_schema.get("required", []) or [])

    expects_wrapped = ("args" in props) or ("kwargs" in props) or ("args" in required) or ("kwargs" in required)

    if not expects_wrapped:
        # Pass through normalized args as the flat parameter object
        return normalized_args

    # Build wrapped structure
    result = {}

    # Handle kwargs
    if "kwargs" in props or "kwargs" in required:
        if "kwargs" in normalized_args:
            result["kwargs"] = _ensure_dict(normalized_args.get("kwargs"))
        else:
            # Use entire flat normalized_args as kwargs
            result["kwargs"] = normalized_args

    # Handle args
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
    """
    Executes an MCP tool function using MCP protocol and returns its output.
    This function maintains a pool of long-running tool processes and reuses them for subsequent calls.
    If a process for a tool is not running, it will be started and initialized.
    Includes caching and optimization for performance.

    Args:
        function_name: The name of the function to call.
        tool_args: Dictionary of arguments for the tool function.
        project_root_override: Optional path to set as the project root for built-in tools.
    """
    global mcp_tool_processes, mcp_request_id_counter

    log(f"Executing MCP function: {function_name} with args: {tool_args}")
    function_name = function_name.replace("default_api:", "")
    tool_name = mcp_function_to_tool_map.get(function_name)

    # Record the tool execution
    is_builtin = (tool_name == BUILTIN_TOOL_NAME)
    record_tool_call(is_builtin=is_builtin)

    if not tool_name:
        return f"Error: Function '{function_name}' not found in any configured MCP tool."

    # --- OPTIMIZATION: Check cache first ---
    if optimization.should_cache_tool(function_name):
        cached_output = optimization.get_cached_tool_output(function_name, tool_args)
        if cached_output is not None:
            log(f"✓ Cache HIT for {function_name}")
            optimization.record_cache_hit()
            return cached_output
        else:
            log(f"✗ Cache MISS for {function_name}")
            optimization.record_cache_miss()

    # Handle built-in tools (executed locally)
    if tool_name == BUILTIN_TOOL_NAME:
        builtin_func = BUILTIN_FUNCTIONS.get(function_name)
        if not builtin_func:
            return f"Error: Built-in function '{function_name}' not implemented."

        normalized_args = _normalize_mcp_args(tool_args)
        log(f"Normalized args for {function_name}: {normalized_args}")

        # Use set_project_root to ensure the context is set correctly in the current thread (the executor thread)
        with set_project_root(project_root_override):

            # Prepare args for the specific built-in function call
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
                    if content is None: # Can be empty string
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

                # Git operations
                elif function_name == 'git_status':
                    pass # No arguments needed

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

                # File analysis
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

                # No-arg functions don't need an entry:
                # analyze_project_structure, get_dependencies

            except KeyError as e:
                log(f"Error: Missing required argument '{e.args[0]}' for function '{function_name}'. Normalized args: {normalized_args}")
                return f"Error: Missing required argument '{e.args[0]}' for function '{function_name}'."
            except (ValueError, TypeError) as e:
                log(f"Error: Invalid argument type or null value provided for function '{function_name}'. Details: {e}. Normalized args: {normalized_args}")
                return f"Error: Invalid argument type provided for function '{function_name}': {e}"

        try:
            result = builtin_func(**func_args)
            
            # Check if the result is a generator (a streaming result).
            # We check for a generator type object.
            if hasattr(result, '__iter__') and not isinstance(result, (str, dict, list)):
                log(f"Returning streaming result for built-in function: {function_name}")
                return result

            # --- OPTIMIZATION: Optimize output and cache it (only for non-streaming results) ---
            optimized_result = optimization.optimize_tool_output(result, function_name)
            
            # Record tokens saved
            if len(optimized_result) < len(result):
                tokens_saved = optimization.estimate_tokens(result) - optimization.estimate_tokens(optimized_result)
                optimization.record_tokens_saved(tokens_saved)
                log(f"✓ Optimized output: saved ~{tokens_saved} tokens")
            
            # Cache the result if appropriate
            if optimization.should_cache_tool(function_name):
                optimization.cache_tool_output(function_name, tool_args, optimized_result)
            
            optimization.record_optimization()
            return optimized_result
        except Exception as e:
            log(f"Error executing built-in tool {function_name} with args {func_args}: {type(e).__name__}: {e}")
            return f"Error executing built-in function '{function_name}': {e}"


    tool_info = mcp_config.get("mcpServers", {}).get(tool_name)
    if not tool_info:
        return f"Error: Tool '{tool_name}' for function '{function_name}' not found in mcpServers config."

    # --- THREAD SAFETY: Acquire lock for this specific tool ---
    with _mcp_tool_locks_lock:
        if tool_name not in _mcp_tool_locks:
            _mcp_tool_locks[tool_name] = threading.Lock()
    tool_lock = _mcp_tool_locks[tool_name]

    with tool_lock:
        process = mcp_tool_processes.get(tool_name)

        # If process doesn't exist or has terminated, start a new one
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

                # Perform MCP handshake
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

        # At this point, `process` should be a valid, running Popen object
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

            # Read stdout/stderr until we get a response with the matching ID or timeout
            deadline = time.time() + 120
            while time.time() < deadline:
                # Watch both stdout and stderr to prevent stderr buffer from filling up and causing a deadlock
                ready_to_read, _, _ = select.select([process.stdout, process.stderr], [], [], 0.5)

                if not ready_to_read:
                    # If select times out, check if the process has terminated
                    if process.poll() is not None:
                        print(f"Tool '{tool_name}' process terminated while waiting for response.")
                        stderr_output = process.stderr.read()
                        if stderr_output:
                            print(f"Stderr from '{tool_name}': {stderr_output.strip()}")
                        if tool_name in mcp_tool_processes:
                            del mcp_tool_processes[tool_name]
                        return f"Error: Tool '{tool_name}' terminated unexpectedly."
                    continue  # Continue waiting for I/O

                # Drain stderr to prevent blocking
                if process.stderr in ready_to_read:
                    err_line = process.stderr.readline()
                    if err_line:
                        print(f"Warning (stderr from '{tool_name}'): {err_line.strip()}")

                # Process stdout for the response
                if process.stdout in ready_to_read:
                    line = process.stdout.readline()
                    if not line:  # EOF
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
                                # If the content is purely text, concatenate it and return a single string.
                                is_all_text = content and all(item.get("type") == "text" for item in content)
                                if is_all_text:
                                    result_text = "".join(item.get("text", "") for item in content)
                                    return result_text

                                # For all other cases (mixed content, structured data), return the entire result object as a JSON string.
                                return json.dumps(response["result"])
                            elif "error" in response:
                                return f"MCP Error: {response['error'].get('message', 'Unknown error')}"
                            return "Tool returned a response with no result or error."

                    except json.JSONDecodeError:
                        print(f"Warning: Could not decode JSON from tool '{tool_name}': {line}")
                        continue

            # Timeout occurred
            return f"Error: Function '{function_name}' timed out after 120 seconds."

        except Exception as e:
            error_message = f"An unexpected error occurred while executing function '{function_name}': {e}"
            print(error_message)
            # If a major error occurs, it's safer to terminate the process
            try:
                if process.poll() is None:
                    process.terminate()
            except Exception:
                pass
            if tool_name in mcp_tool_processes:
                del mcp_tool_processes[tool_name]
            return error_message

def cleanup_orig_files():
    """
    Recursively searches and removes *.orig files created during patch application.
    """
    project_root = get_project_root()
    # Use os .walk for robustness across platforms
    for root, _, files in os.walk(project_root):
        for filename in files:
            if filename.endswith('.orig'):
                filepath = os.path.join( root, filename)
                try:
                    os.remove(filepath)
                    log(f"Cleaned up temporary file: {filepath}")
                except OSError as e:
                    log(f"Error cleaning up { filepath}: {e}")