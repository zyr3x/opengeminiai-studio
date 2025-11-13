# 📁 Path Syntax Guide - code_path vs project_path

## Overview

OpenGeminiAI Studio V3.0 supports two modes for working with code projects:

1. **`code_path=`** - Simple recursive code loading
2. **`project_path=`** - Full AI agent mode with tools

## 🆕 Two Modes Explained

### Mode 1: `code_path=` - Code Context Loading

**Purpose:** Recursively loads all code files from a directory as text context

**Use When:**
- You want to provide code as context for the AI
- No need for tools or file modification
- Just need the AI to read and understand code
- Working with small to medium codebases (< 4 MB)

**What It Does:**
- Recursively scans directory
- Loads all code files as text
- Formats them with markdown code blocks
- Injects into prompt as context
- **Does NOT activate tools**

**Example:**
```
Please review this code: code_path=/path/to/myproject
```

**Output:**
```
📝 CODE CONTEXT LOADED from: '/path/to/myproject'
Total: 45 files, 234.5 KB

**File:** `src/main.py`
```python
def main():
    ...
```

**File:** `src/utils.py`
```python
def helper():
    ...
```
... (all files loaded)
```

**Features:**
- ✅ Loads all code files recursively
- ✅ Respects ignore patterns (.git, node_modules, etc.)
- ✅ Custom ignores: `code_path=. ignore_type=log|tmp`
- ✅ Up to 4 MB of code
- ❌ No tool activation
- ❌ No file modification

---

### Mode 2: `project_path=` - AI Agent Mode

**Purpose:** Activates full AI agent capabilities with built-in development tools

**Use When:**
- You want AI to analyze, modify, or work with code
- Need tools for navigation, search, modification
- Want to execute commands (tests, builds)
- Working on a real project that needs changes

**What It Does:**
- Sets working directory for all tools
- Provides project structure overview
- **Activates all 19 built-in tools**
- Enables analysis, modification, execution
- AI can create, edit, delete files
- AI can run commands

**Example:**
```
Analyze this project and fix the bugs: project_path=/path/to/myproject
```

**Output:**
```
🚀 PROJECT MODE ACTIVATED for path: '/path/to/myproject'

All built-in development tools are now available with this project as the working directory.

📁 Project Structure (depth=3):
```
myproject/
├── src/
│   ├── main.py
│   ├── utils.py
│   └── ...
├── tests/
├── README.md
└── requirements.txt
```

**Available Tools:**
• Navigation: list_files, get_file_content, get_code_snippet, search_codebase
• Analysis: analyze_file_structure, analyze_project_structure, get_file_stats, find_symbol, get_dependencies
• Modification: apply_patch, create_file, write_file
• Execution: execute_command (run tests, builds, awk/sed, etc.)
• Git: git_status, git_log, git_diff, git_show, git_blame, list_recent_changes

**Usage:** Use these tools to analyze, modify, or work with the project...
```

**Features:**
- ✅ Shows project tree (depth 3)
- ✅ Activates 19 built-in tools
- ✅ AI can read any file
- ✅ AI can modify files
- ✅ AI can create files
- ✅ AI can execute commands
- ✅ AI can use git operations
- ✅ Full development agent

---

## 📊 Comparison Table

| Feature | code_path= | project_path= |
|---------|-----------|---------------|
| **Loads code files** | ✅ All recursively | ❌ On demand via tools |
| **Shows in prompt** | ✅ Full content | ✅ Structure only |
| **Activates tools** | ❌ No | ✅ Yes (19 tools) |
| **Can modify files** | ❌ No | ✅ Yes |
| **Can execute commands** | ❌ No | ✅ Yes |
| **Size limit** | 4 MB | Unlimited (via tools) |
| **Best for** | Reading code | Working with code |
| **Use case** | Code review, Q&A | Development, debugging |

---

## 🎯 Usage Examples

### Example 1: Code Review (use `code_path=`)

**Prompt:**
```
Review this code for security issues: code_path=~/projects/webapp/src
```

**AI receives:**
- All source files as text
- Can analyze and suggest improvements
- Cannot modify files
- Pure review mode

---

### Example 2: Bug Fixing (use `project_path=`)

**Prompt:**
```
Find and fix the authentication bug: project_path=~/projects/webapp
```

**AI can:**
1. Use `analyze_project_structure()` to understand layout
2. Use `search_codebase("authentication")` to find relevant code
3. Use `get_file_content()` to read specific files
4. Use `apply_patch()` or `write_file()` to fix bugs
5. Use `execute_command("pytest")` to run tests
6. Use `git_diff()` to review changes

---

### Example 3: Project Setup (use `project_path=`)

**Prompt:**
```
Setup a FastAPI project with authentication: project_path=~/projects/newapp
```

**AI can:**
1. Use `create_file("requirements.txt", "...")` to add dependencies
2. Use `create_file("main.py", "...")` to create app
3. Use `create_file("auth.py", "...")` to add auth
4. Use `execute_command("pip install -r requirements.txt")`
5. Use `execute_command("pytest")`

---

### Example 4: Mixed Use

You can use both in the same conversation:

```
First, understand this codebase: code_path=~/project/src

Now analyze and add tests: project_path=~/project
```

**First message:** Loads all source files as context
**Second message:** Activates tools for modifications

---

## 🔧 Advanced Options

### Ignore Patterns

Both modes support ignore patterns:

```bash
# Ignore specific types
code_path=. ignore_type=log|tmp|cache

# Ignore specific files
code_path=. ignore_file=*.test.js|*.spec.ts

# Ignore directories
code_path=. ignore_dir=docs|examples|legacy
```

**Default ignores (both modes):**
- `.git`, `__pycache__`, `node_modules`, `venv`, `.venv`
- `build`, `dist`, `target`, `out`, `coverage`
- `*.pyc`, `*.log`, `*.swp`, `*.tmp`, `*.bak`
- `*.zip`, `*.tar.gz`, `*.exe`, `*.dll`
- `*.png`, `*.jpg`, `*.svg` (images)
- `*.min.js`, `*.min.css`, `*.map` (minified)
- `package-lock.json`, `yarn.lock`, `poetry.lock`

---

## 💡 When To Use What

### Use `code_path=` when:
- ✅ Simple code review or Q&A
- ✅ Understanding existing code
- ✅ No modifications needed
- ✅ Small to medium codebase
- ✅ Want everything in context

### Use `project_path=` when:
- ✅ Need to modify code
- ✅ Need to run commands
- ✅ Large codebase (tools fetch on-demand)
- ✅ Complex workflows (test, build, deploy)
- ✅ Git operations needed
- ✅ Full development work

---

## 🚀 Real-World Workflows

### Workflow 1: Code Audit
```
1. Load all code: code_path=~/project/src
2. Ask: "Find all SQL injection vulnerabilities"
3. AI analyzes loaded code
4. Returns findings
```

### Workflow 2: Refactoring
```
1. Activate agent: project_path=~/project
2. Ask: "Refactor to use async/await everywhere"
3. AI uses tools to:
   - search_codebase("def ")
   - get_file_content() for each
   - apply_patch() with changes
   - execute_command("pytest")
```

### Workflow 3: Documentation
```
1. Load code: code_path=~/project/src
2. Ask: "Generate API documentation"
3. Switch modes: project_path=~/project
4. Ask: "Create docs/API.md with that documentation"
5. AI uses create_file()
```

---

## 🔒 Security Notes

**Both modes are sandboxed:**
- Path traversal protection
- Cannot access outside project root
- File size limits enforced
- Command timeouts applied

**`project_path=` additional security:**
- Commands run in project directory only
- 5-minute max execution time
- Read/write restricted to project

---

## 📚 See Also

- `BUILTIN_TOOLS_ENHANCED.md` - Complete tool reference
- `README.md` - Main documentation
- Web UI - Try both modes interactively

---

**Choose wisely between `code_path=` and `project_path=` based on your needs!**

`code_path=` for reading, `project_path=` for working! 🚀
