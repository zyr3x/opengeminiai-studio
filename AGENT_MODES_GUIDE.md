# 🎭 Agent Modes Guide - OpenGeminiAI Studio V2.3

## Overview

OpenGeminiAI Studio V2.3 introduces **9 specialized agent modes** that transform the AI into different expert personas, each optimized for specific development tasks. Each mode has its own workflow, tools emphasis, and safety guardrails.

## 🚀 Quick Start

Use agent modes by specifying `project_mode=` parameter:

```
Implement user authentication: project_path=~/myproject project_mode=feature
```

For continuing work on an existing task:

```
Continue auth feature: project_path=~/myproject project_mode=feature_continue project_feature=auth
```

## 📋 Available Modes

### 1. 🔧 feature - Feature Development

**Use When:** Building new functionality from scratch

**Characteristics:**
- Strict plan-implement-test workflow
- Requires approval at each stage
- Full access to all 25 tools
- Creates documentation in `.opengemini/feature/`

**Workflow:**
1. Discusses requirements with you
2. Creates detailed implementation plan
3. Gets your approval
4. Implements changes incrementally
5. Documents everything
6. Provides testing guidance

**Example:**
```
Add API rate limiting: project_path=~/api-server project_mode=feature
```

**Best For:**
- New features
- API endpoints
- New modules/classes
- Database migrations

---

### 2. 🔄 feature_continue - Feature Continuation

**Use When:** Resuming work on a previously started feature

**Characteristics:**
- Loads existing feature documentation
- Continues from where you left off
- Same workflow as `feature` mode
- Accesses `.opengemini/feature/<name>/` for context

**Workflow:**
1. Loads previous plans, changelogs, and progress
2. Confirms understanding of current state
3. Asks for next steps
4. Continues implementation

**Example:**
```
Continue the auth work: project_path=~/myproject project_mode=feature_continue project_feature=user_auth
```

**Requires:** Previous feature work in `.opengemini/feature/<feature_name>/`

---

### 3. 🐛 fix - Bug Fixing

**Use When:** Identifying and fixing bugs

**Characteristics:**
- Focus on root cause analysis
- Minimal, surgical changes
- Emphasizes `search_codebase`, `git_blame`, `find_references`
- Creates documentation in `.opengemini/fix/`

**Workflow:**
1. Asks for bug details (symptoms, errors, steps to reproduce)
2. Investigates using search and analysis tools
3. Creates fix plan with root cause
4. Gets approval
5. Applies minimal fix
6. Verifies with tests

**Example:**
```
Fix the 500 error on user login: project_path=~/webapp project_mode=fix
```

**Best For:**
- Runtime errors
- Logic bugs
- Edge case failures
- Memory leaks

---

### 4. 🏗️ refactor - Code Refactoring

**Use When:** Improving code quality without changing functionality

**Characteristics:**
- Test-driven approach (tests before and after)
- Incremental changes
- Preserves all functionality
- Documents in `.opengemini/refactor/`

**Workflow:**
1. Analyzes current code structure
2. Identifies code smells and issues
3. Creates refactoring plan
4. Runs baseline tests
5. Refactors incrementally
6. Verifies with tests after each change
7. Compares before/after metrics

**Example:**
```
Refactor the authentication module: project_path=~/app project_mode=refactor
```

**Best For:**
- Reducing complexity
- Removing duplication
- Improving naming
- Breaking up large functions
- Restructuring modules

**Key Tools:**
- `run_tests` - Verify functionality preservation
- `compare_files` - Show before/after
- `get_file_outline` - Understand structure

---

### 5. 👁️ review - Code Review

**Use When:** Getting comprehensive code review

**Characteristics:**
- **Read-only mode** (no code modifications)
- Multi-dimensional analysis
- Creates detailed findings report
- Documents in `.opengemini/review/`

**Review Aspects:**
- 🐛 **Bugs** - Logic errors, edge cases
- 🔒 **Security** - Vulnerabilities, exposed secrets
- ⚡ **Performance** - Inefficiencies, bottlenecks
- 📝 **Code Quality** - Naming, complexity, duplication
- 🏗️ **Architecture** - Design patterns, SOLID principles
- ✅ **Testing** - Coverage, quality
- 📚 **Documentation** - Missing or outdated docs

**Example:**
```
Review the payment processing code: project_path=~/ecommerce project_mode=review
```

**Output:**
- `findings.md` - Detailed issues with priorities
- `summary.md` - Executive summary with recommendations

**Best For:**
- Pre-merge reviews
- Security audits
- Architecture evaluation
- Legacy code assessment

---

### 6. 🧪 test - Test Development

**Use When:** Creating comprehensive test suites

**Characteristics:**
- Follows TDD/BDD principles
- Auto-detects test frameworks (pytest, jest, go test, cargo test)
- Creates tests following project conventions
- Documents in `.opengemini/test/`

**Workflow:**
1. Analyzes code to be tested
2. Identifies test framework
3. Creates comprehensive test plan
4. Gets approval
5. Implements tests (unit, integration, edge cases)
6. Runs tests to verify they pass
7. Documents coverage

**Test Coverage:**
- ✅ Happy path (normal operation)
- 🔀 Edge cases (boundaries, limits)
- ❌ Error cases (exceptions, failures)
- 🔗 Integration points

**Example:**
```
Create tests for the user service: project_path=~/api project_mode=test
```

**Best For:**
- Untested legacy code
- New feature test coverage
- Edge case testing
- Integration tests

**Key Tool:**
- `run_tests` - Execute and verify tests

---

### 7. ⚡ optimize - Performance Optimization

**Use When:** Improving performance with measurable results

**Characteristics:**
- Data-driven approach
- Establishes baseline metrics
- One optimization at a time
- Measures impact of each change
- Documents in `.opengemini/optimize/`

**Workflow:**
1. Runs baseline benchmarks/profiling
2. Identifies bottlenecks
3. Creates optimization plan with expected gains
4. Gets approval
5. Applies optimizations incrementally
6. Measures after each change
7. Documents before/after metrics

**Optimization Targets:**
- **Algorithmic** - O(n²) → O(n), better data structures
- **Database** - Indexes, query optimization, N+1 fixes
- **Caching** - Memoization, result caching
- **I/O** - Async operations, batching, streaming
- **Memory** - Generators, leak fixes, efficient structures

**Example:**
```
Optimize the search function: project_path=~/app project_mode=optimize
```

**Best For:**
- Slow endpoints
- High memory usage
- Database query issues
- Algorithm improvements

**Key Tool:**
- `execute_command` - Run profilers and benchmarks

---

### 8. 🔬 research - Codebase Research

**Use When:** Analyzing and understanding code

**Characteristics:**
- **Read-only mode** (no modifications)
- Exploratory analysis
- Creates research documentation
- Documents in `.opengemini/research/`

**Workflow:**
1. Clarifies research question
2. Explores codebase systematically
3. Documents findings with examples
4. Provides comprehensive answer

**Example:**
```
How does the authentication system work? project_path=~/webapp project_mode=research
```

**Best For:**
- Understanding unfamiliar codebases
- Architectural analysis
- Technology stack review
- Finding implementations
- Tracing execution flow

**Key Tools:**
- `find_references` - Trace symbol usage
- `analyze_project_structure` - High-level overview
- `search_codebase` - Find patterns

---

### 9. 📚 documentation - Documentation Writing

**Use When:** Creating technical documentation

**Characteristics:**
- Analyzes code to generate docs
- Follows project documentation standards
- Creates markdown documentation
- Documents in `.opengemini/docs/`

**Workflow:**
1. Discusses documentation scope
2. Creates documentation plan
3. Gets approval
4. Analyzes code thoroughly
5. Writes clear, comprehensive docs
6. Gets user review

**Example:**
```
Document the API endpoints: project_path=~/api-server project_mode=documentation
```

**Best For:**
- API documentation
- Module documentation
- Architecture docs
- Setup guides
- Contributing guidelines

**Key Tools:**
- `get_file_outline` - Structure overview
- `analyze_file_structure` - Detailed analysis

---

## 🛠️ Tool Availability by Mode

| Tool Category | feature | fix | refactor | review | test | optimize | research | docs |
|---------------|---------|-----|----------|--------|------|----------|----------|------|
| **Navigation** (6) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Analysis** (7) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Modification** (3) | ✅ | ✅ | ✅ | ❌ | test files only | ✅ | ❌ | docs only |
| **Testing** (2) | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ |
| **Git** (6) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**Total Tools Available:** 25

## 💡 Best Practices

### 1. Choose the Right Mode
- **New features?** → `feature`
- **Bugs?** → `fix`
- **Code quality?** → `refactor`
- **Need review?** → `review`
- **Missing tests?** → `test`
- **Performance issues?** → `optimize`
- **Understanding code?** → `research`
- **Need docs?** → `documentation`

### 2. Use Feature Names
Always specify `project_feature=name` for better organization:
```
project_path=~/app project_mode=feature project_feature=user_auth
```

This creates organized documentation:
```
.opengemini/
  feature/
    user_auth/
      todo.md
      changelog.md
      summary.md
```

### 3. Review Plans Before Approval
Every modification mode requires approval. Always review:
- What files will be changed
- What the changes accomplish
- Potential risks or side effects

### 4. Use Continuation Mode
For large features, work in sessions:
```
# Session 1
project_path=~/app project_mode=feature project_feature=api_v2

# Session 2 (later)
project_path=~/app project_mode=feature_continue project_feature=api_v2
```

### 5. Combine Modes in Workflow
1. `research` - Understand existing code
2. `review` - Identify issues
3. `feature` or `fix` - Implement changes
4. `test` - Add tests
5. `optimize` - Improve performance
6. `documentation` - Document changes

## 🔒 Safety Features

### Mode-Specific Restrictions
- **review** and **research** - Cannot modify source code
- **test** - Can only create/modify test files
- **documentation** - Can only create/modify docs

### Approval Requirements
All modification modes require explicit approval:
- ✅ Before creating any file
- ✅ Before modifying any file
- ✅ Before executing commands

### Path Sandboxing
Use `ALLOWED_CODE_PATHS` environment variable to restrict access:
```env
ALLOWED_CODE_PATHS=/home/user/projects,/opt/workspace
```

### Documentation Trail
Every mode creates audit trail in `.opengemini/`:
- Plans show what was intended
- Changelogs show what was done
- Summaries explain the results

## 🎯 Advanced Usage

### Custom Ignore Patterns
```
project_path=. project_mode=feature ignore_dir=legacy|vendor ignore_type=log|tmp
```

### Combined with Code Context
```
Here's my auth code: code_path=./auth
Now implement OAuth: project_path=. project_mode=feature project_feature=oauth
```

### Switching Modes Mid-Task
```
# Start with research
project_path=~/app project_mode=research project_feature=auth_system

# Then review the code
project_path=~/app project_mode=review project_feature=auth_system

# Finally implement fixes
project_path=~/app project_mode=fix project_feature=auth_fixes
```

## 📊 Performance Expectations

### Speed
- **research**, **review** - Fast (read-only)
- **fix** - Fast (minimal changes)
- **feature**, **refactor** - Medium (multiple files)
- **test**, **optimize** - Depends on test execution time

### Thoroughness
- **review** - Most comprehensive analysis
- **optimize** - Most data-driven
- **test** - Most coverage-focused
- **feature** - Most structured workflow

## 🐛 Troubleshooting

### "Mode not found" Error
- Check spelling of `project_mode=`
- Available: feature, fix, refactor, review, test, optimize, research, documentation

### Agent Not Following Workflow
- Modes have strict workflows built into prompts
- If skipping steps, regenerate response
- Remind: "Please follow the [mode] workflow"

### Documentation Not Loading
- For `feature_continue`, ensure `.opengemini/feature/<name>/` exists
- Check file permissions
- Verify `project_feature=` matches directory name

## 📚 Additional Resources

- **PATH_SYNTAX_GUIDE.md** - Detailed `project_path=` vs `code_path=` guide
- **README.md** - Full project documentation
- **etc/prompt/agent/default.json** - Agent mode prompt templates
- **etc/mcp/declaration/default.json** - Tool declarations

## 🎓 Learning Path

1. **Start Simple**: Use `research` mode to explore a project
2. **Review Quality**: Try `review` mode on your code
3. **Make Changes**: Use `fix` mode for a small bug
4. **Build Features**: Graduate to `feature` mode
5. **Advanced**: Explore `refactor`, `optimize`, `test` modes

---

**Remember:** Each mode is designed for specific tasks. Choose the right tool for the job, and the AI will be a powerful development partner! 🚀
