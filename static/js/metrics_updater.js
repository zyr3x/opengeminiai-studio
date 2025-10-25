function formatNumber(num) {
    // Add space as a thousands separator
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

function renderKeyTokenStats(stats) {
    const container = document.getElementById('key-token-stats-content');
    if (!container) return;

    if (stats && stats.length > 0) {
        let html = '';
        stats.forEach(keyStats => {
            html += `<h6 class="mt-3 mb-2">Key ID: <span class="badge bg-success">${keyStats.key_id}</span></h6>`;
            html += `<ul class="list-group list-group-flush border-bottom mb-3">`;

            // Total Stats
            html += `<li class="list-group-item d-flex justify-content-between align-items-center small bg-light">`;
            html += `<strong>TOTAL TOKENS</strong>`;
            html += `<span class="badge bg-dark">${formatNumber(keyStats.total_tokens || 0)}</span>`;
            html += `</li>`;

            // Model Breakdown
            // Sort models by total usage for better readability
            const sortedModels = Object.entries(keyStats.models).sort(([, a], [, b]) => (b.input + b.output) - (a.input + a.output));

            for (const [modelName, modelStats] of sortedModels) {
                html += `<li class="list-group-item d-flex justify-content-between align-items-center small">`;
                html += `<span class="text-muted">${modelName}</span>`;
                html += `<span>In: <strong class="text-primary">${formatNumber(modelStats.input)}</strong> / Out: <strong class="text-danger">${formatNumber(modelStats.output)}</strong></span>`;
                html += `</li>`;
            }

            html += `</ul>`;
        });
        container.innerHTML = html;
    } else {
        container.innerHTML = '<p class="text-center text-muted">No usage recorded yet.</p>';
    }
}


function updateMetrics(apiUrl) {
    fetch(apiUrl)
        .then(response => response.json())
        .then(data => {
            // Update Cache & Token Optimization metrics
            document.getElementById('metric-cache-hits').innerText = data.cache_hits || 0;
            document.getElementById('metric-cache-misses').innerText = data.cache_misses || 0;
            document.getElementById('metric-cache-hit-rate').innerText = data.cache_hit_rate || '0.0%';
            document.getElementById('metric-cache-size').innerText = data.cache_size || 0;
            document.getElementById('metric-tokens-saved').innerText = data.tokens_saved || 0;
            document.getElementById('metric-requests-optimized').innerText = data.requests_optimized || 0;

            // Update Tool Usage metrics
            document.getElementById('metric-tool-calls-external').innerText = data.tool_calls_external || 0;

            // Update Key Token Stats
            renderKeyTokenStats(data.key_token_stats);
        })
        .catch(error => console.error('Error fetching metrics:', error));
}

// Initialization logic
document.addEventListener('DOMContentLoaded', () => {
    const metricsDiv = document.getElementById('metrics');
    if (metricsDiv) {
        const metricsApiUrl = metricsDiv.dataset.apiUrl;
        if (metricsApiUrl) {
            // Update immediately on load
            updateMetrics(metricsApiUrl); 
            // Update every 5 seconds
            setInterval(() => updateMetrics(metricsApiUrl), 5000);
        }
    }
});
