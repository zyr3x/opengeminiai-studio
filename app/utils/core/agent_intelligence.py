"""
Advanced Agent Intelligence Module

Provides enhanced decision-making, planning, and self-reflection capabilities
for the AI agent when working in project_path mode.
"""

import json
from typing import List, Dict, Optional, Tuple
from app.utils.core.logging import log
from app.utils.core.optimization_utils import estimate_tokens


class AgentMemory:
    """Maintains context and learning across tool executions"""
    
    def __init__(self):
        self.tool_history: List[Dict] = []
        self.learned_patterns: Dict[str, any] = {}
        self.error_patterns: Dict[str, int] = {}
        self.successful_sequences: List[List[str]] = []
        
    def record_tool_call(self, tool_name: str, args: dict, result: str, success: bool):
        """Record a tool execution for future reference"""
        self.tool_history.append({
            'tool': tool_name,
            'args': args,
            'success': success,
            'result_preview': result[:200] if result else None,
            'timestamp': len(self.tool_history)
        })
        
        if not success:
            self.error_patterns[tool_name] = self.error_patterns.get(tool_name, 0) + 1
    
    def get_recent_context(self, limit: int = 5) -> str:
        """Get summary of recent tool executions"""
        if not self.tool_history:
            return "No previous tool executions in this session."
        
        recent = self.tool_history[-limit:]
        context = "Recent tool executions:\n"
        for item in recent:
            status = "✓" if item['success'] else "✗"
            context += f"  {status} {item['tool']}(...)\n"
        return context
    
    def suggest_next_tools(self, current_goal: str) -> List[str]:
        """Suggest likely next tools based on history"""
        # Analyze successful sequences
        if len(self.tool_history) < 2:
            return []
        
        last_tool = self.tool_history[-1]['tool']
        
        # Common patterns
        patterns = {
            'list_files': ['get_file_content', 'get_file_outline', 'analyze_project_structure'],
            'search_codebase': ['get_file_content', 'find_references'],
            'get_file_content': ['write_file', 'analyze_file_structure'],
            'analyze_file_structure': ['get_code_snippet', 'find_symbol'],
            'find_symbol': ['find_references', 'get_file_content'],
            'git_diff': ['git_status', 'write_file'],
            'run_tests': ['get_file_content', 'search_codebase'],
        }
        
        return patterns.get(last_tool, [])
    
    def clear(self):
        """Clear agent memory"""
        self.tool_history.clear()
        self.error_patterns.clear()


class AgentPlanner:
    """Creates and validates execution plans for complex tasks"""
    
    @staticmethod
    def create_plan(task_description: str, available_tools: List[str]) -> Dict:
        """
        Create a structured plan for achieving a goal
        
        Returns:
            {
                'goal': str,
                'steps': [{'tool': str, 'rationale': str, 'expected_output': str}],
                'risks': [str],
                'validation_method': str
            }
        """
        plan = {
            'goal': task_description,
            'steps': [],
            'risks': [],
            'validation_method': 'manual'
        }
        
        # Analyze task type
        task_lower = task_description.lower()
        
        if 'find' in task_lower or 'search' in task_lower:
            plan['steps'] = [
                {'tool': 'search_codebase', 'rationale': 'Locate relevant code', 'expected': 'File paths and line numbers'},
                {'tool': 'get_file_content', 'rationale': 'Examine found files', 'expected': 'Source code'},
            ]
            
        elif 'test' in task_lower:
            plan['steps'] = [
                {'tool': 'list_files', 'rationale': 'Find test files', 'expected': 'Test directory structure'},
                {'tool': 'run_tests', 'rationale': 'Execute tests', 'expected': 'Test results'},
            ]
            plan['validation_method'] = 'all_tests_pass'
            
        elif 'refactor' in task_lower or 'improve' in task_lower:
            plan['steps'] = [
                {'tool': 'get_file_content', 'rationale': 'Read current code', 'expected': 'Original code'},
                {'tool': 'run_tests', 'rationale': 'Baseline tests', 'expected': 'All pass'},
                {'tool': 'write_file', 'rationale': 'Apply improvements', 'expected': 'Success'},
                {'tool': 'run_tests', 'rationale': 'Verify no breaks', 'expected': 'All pass'},
            ]
            plan['risks'] = ['Breaking functionality', 'Test failures']
            plan['validation_method'] = 'tests_still_pass'
            
        elif 'bug' in task_lower or 'fix' in task_lower:
            plan['steps'] = [
                {'tool': 'search_codebase', 'rationale': 'Find error source', 'expected': 'Problem location'},
                {'tool': 'git_blame', 'rationale': 'Check history', 'expected': 'Recent changes'},
                {'tool': 'get_file_content', 'rationale': 'Examine code', 'expected': 'Bug context'},
                {'tool': 'write_file', 'rationale': 'Apply fix', 'expected': 'Success'},
                {'tool': 'run_tests', 'rationale': 'Verify fix', 'expected': 'Tests pass'},
            ]
            plan['risks'] = ['Incomplete fix', 'New bugs introduced']
            plan['validation_method'] = 'specific_test_passes'
        
        return plan
    
    @staticmethod
    def validate_plan(plan: Dict) -> Tuple[bool, List[str]]:
        """Validate a plan for completeness and safety"""
        issues = []
        
        if not plan.get('steps'):
            issues.append("Plan has no steps")
        
        # Check for destructive operations without safeguards
        destructive = ['write_file', 'create_file', 'execute_command', 'apply_patch']
        has_tests = any(step.get('tool') == 'run_tests' for step in plan.get('steps', []))
        
        for step in plan.get('steps', []):
            if step.get('tool') in destructive and not has_tests:
                issues.append(f"Destructive operation '{step['tool']}' without test validation")
        
        return len(issues) == 0, issues


class AgentReflection:
    """Self-reflection and result validation"""
    
    @staticmethod
    def validate_tool_output(tool_name: str, output: str, expected_type: str = None) -> Tuple[bool, str]:
        """
        Validate if tool output makes sense
        
        Returns: (is_valid, reason)
        """
        if not output:
            return False, "Empty output"
        
        if "Error:" in output or "❌" in output:
            return False, "Output contains error indicators"
        
        # Tool-specific validations
        if tool_name == 'list_files':
            if 'file' not in output.lower() and 'directory' not in output.lower():
                return False, "Output doesn't appear to be a file listing"
        
        elif tool_name == 'get_file_content':
            if len(output) < 10:
                return False, "File content suspiciously short"
        
        elif tool_name == 'run_tests':
            if 'pass' not in output.lower() and 'fail' not in output.lower():
                return False, "Output doesn't appear to be test results"
        
        elif tool_name == 'search_codebase':
            if 'No results' not in output and ':' not in output:
                return False, "Output doesn't appear to be search results"
        
        return True, "Output appears valid"
    
    @staticmethod
    def assess_progress(initial_goal: str, completed_steps: List[Dict]) -> Dict:
        """Assess if we're making progress toward the goal"""
        assessment = {
            'steps_completed': len(completed_steps),
            'appears_productive': True,
            'concerns': [],
            'confidence': 0.7
        }
        
        # Check for repeated failures
        failed_count = sum(1 for step in completed_steps if not step.get('success', True))
        if failed_count > 2:
            assessment['appears_productive'] = False
            assessment['concerns'].append(f"{failed_count} failed steps")
            assessment['confidence'] = 0.3
        
        # Check for circular patterns (same tool repeatedly)
        if len(completed_steps) >= 3:
            last_three = [s.get('tool') for s in completed_steps[-3:]]
            if len(set(last_three)) == 1:
                assessment['concerns'].append(f"Repeating same tool: {last_three[0]}")
                assessment['confidence'] = 0.5
        
        return assessment
    
    @staticmethod
    def suggest_recovery(error_context: Dict) -> List[str]:
        """Suggest recovery actions after an error"""
        suggestions = []
        
        error_msg = error_context.get('error', '').lower()
        tool_name = error_context.get('tool', '')
        
        if 'not found' in error_msg or 'does not exist' in error_msg:
            suggestions.append("Verify path exists using list_files")
            suggestions.append("Check for typos in path")
            suggestions.append("Try searching with search_codebase")
        
        elif 'permission' in error_msg or 'access denied' in error_msg:
            suggestions.append("Check ALLOWED_CODE_PATHS configuration")
            suggestions.append("Verify file permissions")
        
        elif 'syntax error' in error_msg:
            suggestions.append("Review code syntax before writing")
            suggestions.append("Get original file content first")
        
        elif tool_name == 'run_tests' and 'fail' in error_msg:
            suggestions.append("Examine test output for specific failures")
            suggestions.append("Check recent changes with git_diff")
            suggestions.append("Read failing test file")
        
        if not suggestions:
            suggestions.append("Review tool parameters")
            suggestions.append("Check agent mode documentation")
        
        return suggestions


class AgentOrchestrator:
    """Coordinates agent behavior with intelligence"""
    
    def __init__(self):
        self.memory = AgentMemory()
        self.planner = AgentPlanner()
        self.reflection = AgentReflection()
        self.current_plan: Optional[Dict] = None
        
    def start_task(self, task_description: str, available_tools: List[str]) -> Dict:
        """Initialize a new task with planning"""
        log(f"🧠 Agent planning task: {task_description}")
        
        plan = self.planner.create_plan(task_description, available_tools)
        is_valid, issues = self.planner.validate_plan(plan)
        
        if not is_valid:
            log(f"⚠️  Plan validation issues: {issues}")
            plan['warnings'] = issues
        
        self.current_plan = plan
        self.memory.clear()
        
        return plan
    
    def after_tool_execution(self, tool_name: str, args: dict, output: str) -> Dict:
        """Process tool execution results with intelligence"""
        # Validate output
        is_valid, reason = self.reflection.validate_tool_output(tool_name, output)
        
        # Record in memory
        self.memory.record_tool_call(tool_name, args, output, is_valid)
        
        # Get context and suggestions
        context = self.memory.get_recent_context()
        suggestions = self.memory.suggest_next_tools(
            self.current_plan.get('goal', '') if self.current_plan else ''
        )
        
        # Assess progress
        progress = self.reflection.assess_progress(
            self.current_plan.get('goal', '') if self.current_plan else '',
            self.memory.tool_history
        )
        
        result = {
            'output_valid': is_valid,
            'validation_reason': reason,
            'recent_context': context,
            'suggested_next_tools': suggestions,
            'progress_assessment': progress,
        }
        
        # Add recovery suggestions if output invalid
        if not is_valid:
            result['recovery_suggestions'] = self.reflection.suggest_recovery({
                'error': output,
                'tool': tool_name,
                'args': args
            })
        
        return result
    
    def get_planning_prompt(self, user_query: str) -> str:
        """Generate enhanced prompt with planning context"""
        if not self.current_plan:
            return ""
        
        prompt = "\n\n## 🎯 TASK PLAN\n\n"
        prompt += f"**Goal:** {self.current_plan['goal']}\n\n"
        
        if self.current_plan.get('steps'):
            prompt += "**Recommended Steps:**\n"
            for i, step in enumerate(self.current_plan['steps'], 1):
                prompt += f"{i}. Use `{step['tool']}` - {step['rationale']}\n"
        
        if self.current_plan.get('risks'):
            prompt += f"\n**⚠️  Risks:** {', '.join(self.current_plan['risks'])}\n"
        
        if self.current_plan.get('validation_method'):
            prompt += f"**✓ Validation:** {self.current_plan['validation_method']}\n"
        
        # Add memory context
        if self.memory.tool_history:
            prompt += f"\n## 📝 CONTEXT\n\n{self.memory.get_recent_context()}\n"
        
        return prompt


# Global orchestrator instance
_orchestrator: Optional[AgentOrchestrator] = None

def get_agent_orchestrator() -> AgentOrchestrator:
    """Get or create global agent orchestrator"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
    return _orchestrator

def reset_agent_orchestrator():
    """Reset the orchestrator (e.g., for new sessions)"""
    global _orchestrator
    _orchestrator = None
