import pytest
from app.utils.hooks import HookManager

@pytest.fixture
def hook_manager():
    return HookManager()

def test_hook_registration_priority(hook_manager):
    """Test that hooks are registered and sorted by priority correctly."""
    hook_manager.register_hook('dashboard_top', 'template_c.html', priority=20)
    hook_manager.register_hook('dashboard_top', 'template_a.html', priority=5)
    hook_manager.register_hook('dashboard_top', 'template_b.html', priority=10)
    
    # Priority order should be template_a (5), template_b (10), template_c (20)
    hooks_list = hook_manager._hooks['dashboard_top']
    assert len(hooks_list) == 3
    assert hooks_list[0]['template'] == 'template_a.html'
    assert hooks_list[1]['template'] == 'template_b.html'
    assert hooks_list[2]['template'] == 'template_c.html'

def test_render_hooks_empty(hook_manager):
    """Test rendering a hook that has no registered templates returns empty string."""
    result = hook_manager.render_hooks('non_existent_hook')
    assert result == ""
