async function fetchLogs() {
    const container = document.getElementById('log-container');
    const search = document.getElementById('log-search-input').value;
    const badge = document.getElementById('log-count-badge');

    if (container.innerText === 'Loading...') {
        container.style.opacity = '0.5';
    }

    try {
        const response = await fetch(`/logs/data?limit=2000&search=${encodeURIComponent(search)}`);
        const data = await response.json();

        container.style.opacity = '1';

        if (data.error) {
            container.innerHTML = `<span class="text-danger">${data.error}</span>`;
            return;
        }

        if (!data.logs || data.logs.length === 0) {
            container.innerHTML = '<span class="text-muted">No logs found matching your criteria.</span>';
            badge.innerText = '0 lines';
        } else {
            container.innerText = data.logs.join('');
            badge.innerText = `${data.logs.length} lines`;
            container.scrollTop = container.scrollHeight;
        }
    } catch (err) {
        container.style.opacity = '1';
        container.innerText = "Error fetching logs: " + err;
    }
}

document.getElementById('log-search-input')?.addEventListener('keyup', function(e) {
    if (e.key === 'Enter') {
        fetchLogs();
    }
});

document.addEventListener('DOMContentLoaded', () => {
    const logsEl = document.getElementById('logs');
    if (logsEl) {
           setInterval(fetchLogs, 5000);
    }
});