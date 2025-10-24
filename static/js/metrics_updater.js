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
