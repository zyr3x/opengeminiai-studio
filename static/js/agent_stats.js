// Agent Intelligence Statistics JavaScript

// Refresh agent statistics
async function refreshAgentStats() {
    const statsContent = document.getElementById('agent_stats_content');
    const statsCard = document.getElementById('agent_stats_card');
    
    if (!statsContent) return;
    
    // Show loading
    statsContent.innerHTML = '<div class="spinner-border spinner-border-sm" role="status"><span class="visually-hidden">Loading...</span></div> Loading statistics...';
    
    try {
        const response = await fetch('/get_agent_stats');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const stats = await response.json();
        
        // Build HTML for stats display
        let html = '<div class="row">';
        
        // Agent Intelligence stats
        html += '<div class="col-md-6">';
        html += '<h6 class="mb-3">🧠 Agent Intelligence</h6>';
        
        if (stats.agent && stats.agent.enabled) {
            html += '<div class="table-responsive">';
            html += '<table class="table table-sm">';
            html += '<tr><td class="text-muted">Status:</td><td><span class="badge bg-success">Enabled</span></td></tr>';
            html += '<tr><td class="text-muted">Tool Executions:</td><td><strong>' + (stats.agent.tool_history || 0) + '</strong></td></tr>';
            html += '<tr><td class="text-muted">Error Patterns:</td><td><strong>' + (stats.agent.error_patterns || 0) + '</strong></td></tr>';
            html += '</table>';
            html += '</div>';
        } else {
            html += '<p class="text-muted">Not enabled</p>';
        }
        
        html += '</div>';
        
        // Aux Model stats
        html += '<div class="col-md-6">';
        html += '<h6 class="mb-3">🤖 Enhanced Aux Model</h6>';
        
        if (stats.aux_model && stats.aux_model.enabled) {
            const cacheHitRate = ((stats.aux_model.cache_hit_rate || 0) * 100).toFixed(1);
            
            html += '<div class="table-responsive">';
            html += '<table class="table table-sm">';
            html += '<tr><td class="text-muted">Status:</td><td><span class="badge bg-success">Enabled</span></td></tr>';
            html += '<tr><td class="text-muted">Total API Calls:</td><td><strong>' + (stats.aux_model.total_calls || 0) + '</strong></td></tr>';
            html += '<tr><td class="text-muted">Tokens Saved:</td><td><strong class="text-success">' + (stats.aux_model.tokens_saved || 0).toLocaleString() + '</strong></td></tr>';
            html += '<tr><td class="text-muted">Cache Hit Rate:</td><td><strong>' + cacheHitRate + '%</strong></td></tr>';
            html += '<tr><td class="text-muted">Cache Hits:</td><td>' + (stats.aux_model.cache_hits || 0) + '</td></tr>';
            html += '<tr><td class="text-muted">Cache Misses:</td><td>' + (stats.aux_model.cache_misses || 0) + '</td></tr>';
            html += '</table>';
            html += '</div>';
        } else {
            html += '<p class="text-muted">Not enabled</p>';
        }
        
        html += '</div>';
        html += '</div>';
        
        // Show success metrics if any
        if (stats.aux_model && stats.aux_model.enabled && stats.aux_model.tokens_saved > 0) {
            const tokensSaved = stats.aux_model.tokens_saved;
            const estimatedCostSaving = (tokensSaved / 1000000 * 0.075).toFixed(2); // Approximate cost
            
            html += '<div class="alert alert-success mt-3" role="alert">';
            html += '<h6 class="alert-heading">💰 Savings</h6>';
            html += '<p class="mb-0">Total tokens saved: <strong>' + tokensSaved.toLocaleString() + '</strong></p>';
            html += '<p class="mb-0"><small>Estimated cost savings: ~$' + estimatedCostSaving + '</small></p>';
            html += '</div>';
        }
        
        statsContent.innerHTML = html;
        
        // Show card if stats are available
        if ((stats.agent && stats.agent.enabled) || (stats.aux_model && stats.aux_model.enabled)) {
            statsCard.style.display = 'block';
        }
        
    } catch (error) {
        console.error('Error fetching agent stats:', error);
        statsContent.innerHTML = '<div class="alert alert-danger">Error loading statistics: ' + error.message + '</div>';
    }
}

// Reset agent session
async function resetAgentSession() {
    if (!confirm('Are you sure you want to reset the agent session? This will clear all memory and cached data.')) {
        return;
    }
    
    try {
        const response = await fetch('/reset_agent_session', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const result = await response.json();
        alert('✅ ' + (result.message || 'Agent session reset successfully'));
        
        // Refresh stats after reset
        setTimeout(refreshAgentStats, 500);
        
    } catch (error) {
        console.error('Error resetting agent session:', error);
        alert('❌ Error resetting agent session: ' + error.message);
    }
}

// Auto-refresh stats when configuration section is visible
function setupAgentStatsAutoRefresh() {
    // Check if agent intelligence or aux model is enabled
    const agentIntelligenceEnabled = document.getElementById('agent_intelligence_enabled');
    const auxModelEnabled = document.getElementById('agent_aux_model_enabled');
    
    if ((agentIntelligenceEnabled && agentIntelligenceEnabled.checked) || 
        (auxModelEnabled && auxModelEnabled.checked)) {
        // Refresh stats immediately
        refreshAgentStats();
        
        // Set up periodic refresh (every 30 seconds)
        setInterval(refreshAgentStats, 30000);
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    setupAgentStatsAutoRefresh();
    
    // Refresh stats when switching to configuration tab
    const configLink = document.querySelector('a[href="#configuration"]');
    if (configLink) {
        configLink.addEventListener('click', function() {
            setTimeout(refreshAgentStats, 300);
        });
    }
});
