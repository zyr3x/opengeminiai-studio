"""
Agent Integration Helpers

Convenience functions for integrating agent intelligence and enhanced aux model
into existing codebase with minimal changes.
"""

from typing import Optional, Dict, List, Tuple
from app.utils.core.logging import log


def should_use_agent_intelligence() -> bool:
    """Check if agent intelligence is enabled and available"""
    try:
        from app.config import config
        return config.AGENT_INTELLIGENCE_ENABLED
    except:
        return False


def should_use_enhanced_aux() -> bool:
    """Check if enhanced aux model is enabled and available"""
    try:
        from app.config import config
        return config.AGENT_AUX_MODEL_ENABLED
    except:
        return False


def create_agent_plan_for_task(
    task_description: str,
    available_tools: List[str]
) -> Optional[Dict]:
    """
    Create an execution plan using agent intelligence
    
    Returns None if agent intelligence is disabled or unavailable
    """
    if not should_use_agent_intelligence():
        return None
    
    try:
        from app.utils.core.mcp_handler import create_agent_plan
        return create_agent_plan(task_description, available_tools)
    except Exception as e:
        log(f"Failed to create agent plan: {e}")
        return None


def get_agent_enhanced_prompt(
    base_prompt: str,
    task_context: Optional[str] = None
) -> str:
    """
    Enhance prompt with agent intelligence context
    
    Args:
        base_prompt: Original prompt text
        task_context: Optional task description for planning
        
    Returns:
        Enhanced prompt with agent context
    """
    if not should_use_agent_intelligence():
        return base_prompt
    
    try:
        from app.utils.core.mcp_handler import get_agent_context_prompt
        context = get_agent_context_prompt()
        if context:
            return base_prompt + context
    except Exception as e:
        log(f"Failed to get agent context: {e}")
    
    return base_prompt


def process_tool_output_smart(
    tool_name: str,
    output: str,
    task_context: Optional[str] = None
) -> Tuple[str, Dict]:
    """
    Process tool output using enhanced aux model if available
    
    Returns:
        (processed_output, metadata)
    """
    if not should_use_enhanced_aux() or not output:
        return output, {'used_aux': False, 'reason': 'disabled'}
    
    try:
        from app.utils.core.aux_model_enhanced import process_tool_output_with_aux
        return process_tool_output_with_aux(tool_name, output, task_context)
    except Exception as e:
        log(f"Enhanced aux model failed: {e}")
        return output, {'used_aux': False, 'reason': 'error', 'error': str(e)}


def get_intelligence_stats() -> Dict:
    """
    Get combined statistics from agent intelligence and aux model
    
    Returns:
        Dictionary with stats from both systems
    """
    stats = {
        'agent': {
            'enabled': should_use_agent_intelligence(),
            'memory_size': 0,
            'tool_history': 0,
            'error_patterns': 0
        },
        'aux_model': {
            'enabled': should_use_enhanced_aux(),
            'total_calls': 0,
            'tokens_saved': 0,
            'cache_hit_rate': 0.0
        }
    }
    
    # Get agent stats
    if should_use_agent_intelligence():
        try:
            from app.utils.core.agent_intelligence import get_agent_orchestrator
            orchestrator = get_agent_orchestrator()
            stats['agent']['tool_history'] = len(orchestrator.memory.tool_history)
            stats['agent']['error_patterns'] = len(orchestrator.memory.error_patterns)
        except Exception as e:
            log(f"Failed to get agent stats: {e}")
    
    # Get aux model stats
    if should_use_enhanced_aux():
        try:
            from app.utils.core.mcp_handler import get_aux_model_stats
            aux_stats = get_aux_model_stats()
            stats['aux_model'].update(aux_stats)
        except Exception as e:
            log(f"Failed to get aux stats: {e}")
    
    return stats


def reset_agent_session():
    """Reset agent intelligence for new session"""
    if not should_use_agent_intelligence():
        return
    
    try:
        from app.utils.core.agent_intelligence import reset_agent_orchestrator
        reset_agent_orchestrator()
        log("✓ Agent session reset")
    except Exception as e:
        log(f"Failed to reset agent session: {e}")


def format_intelligence_stats_for_display(stats: Dict) -> str:
    """Format intelligence stats for display in UI or logs"""
    lines = []
    lines.append("🧠 Agent Intelligence & Aux Model Statistics")
    lines.append("=" * 50)
    
    # Agent stats
    if stats['agent']['enabled']:
        lines.append("\n📊 Agent Intelligence:")
        lines.append(f"  • Tool executions: {stats['agent']['tool_history']}")
        lines.append(f"  • Error patterns: {stats['agent']['error_patterns']}")
    else:
        lines.append("\n📊 Agent Intelligence: Disabled")
    
    # Aux model stats
    if stats['aux_model']['enabled']:
        lines.append("\n🤖 Enhanced Aux Model:")
        lines.append(f"  • Total API calls: {stats['aux_model']['total_calls']}")
        lines.append(f"  • Tokens saved: {stats['aux_model']['tokens_saved']}")
        lines.append(f"  • Cache hit rate: {stats['aux_model']['cache_hit_rate']:.1%}")
    else:
        lines.append("\n🤖 Enhanced Aux Model: Disabled")
    
    return "\n".join(lines)


# Quick access functions for common operations

def plan_and_execute_task(
    task_description: str,
    available_tools: List[str],
    auto_approve: bool = False
) -> Optional[Dict]:
    """
    Create plan and optionally auto-approve it
    
    For interactive mode, set auto_approve=False and review plan first
    """
    plan = create_agent_plan_for_task(task_description, available_tools)
    
    if not plan:
        return None
    
    if auto_approve:
        log("✓ Plan auto-approved")
        return plan
    
    # For interactive mode, plan needs user approval
    log("⏸️  Plan created, awaiting user approval")
    return plan


def smart_summarize(
    tool_name: str,
    content: str,
    task_context: Optional[str] = None
) -> str:
    """
    Smart summarization with automatic strategy selection
    
    Uses enhanced aux model if available, otherwise returns original
    """
    processed, metadata = process_tool_output_smart(tool_name, content, task_context)
    
    if metadata.get('used_aux'):
        tokens_saved = metadata.get('tokens_saved', 0)
        if tokens_saved > 0:
            log(f"✓ Summarized: saved {tokens_saved} tokens")
    
    return processed


def validate_tool_output(
    tool_name: str,
    output: str
) -> Tuple[bool, str]:
    """
    Validate tool output using agent reflection
    
    Returns:
        (is_valid, reason)
    """
    if not should_use_agent_intelligence():
        return True, "Agent intelligence disabled"
    
    try:
        from app.utils.core.agent_intelligence import AgentReflection
        return AgentReflection.validate_tool_output(tool_name, output)
    except Exception as e:
        log(f"Validation failed: {e}")
        return True, "Validation error"


def suggest_recovery_actions(
    error_message: str,
    tool_name: str,
    tool_args: Dict
) -> List[str]:
    """
    Get recovery suggestions for a failed tool execution
    
    Returns:
        List of suggested recovery actions
    """
    if not should_use_agent_intelligence():
        return []
    
    try:
        from app.utils.core.agent_intelligence import AgentReflection
        return AgentReflection.suggest_recovery({
            'error': error_message,
            'tool': tool_name,
            'args': tool_args
        })
    except Exception as e:
        log(f"Failed to get recovery suggestions: {e}")
        return []
