document.addEventListener('DOMContentLoaded', function() {
    const htmlElement = document.documentElement;
    const darkModeToggle = document.getElementById('darkModeToggle');
    const darkModeIcon = document.getElementById('darkModeIcon');
    const navLinks = document.querySelectorAll('.nav-link');
    const contentSections = document.querySelectorAll('.content-section');
    const navbarCollapse = document.getElementById('navbarNav');
    const mainContent = document.querySelector('.main-content');
    const body = document.querySelector('body');
    // Function to set the theme
    function setTheme(theme) {
        htmlElement.setAttribute('data-bs-theme', theme);
        localStorage.setItem('theme', theme);
        if (darkModeToggle) { // Ensure toggle exists before trying to set its state
            darkModeToggle.checked = (theme === 'dark');
        }
        if (darkModeIcon) { // Ensure icon exists before trying to set its content
            darkModeIcon.textContent = (theme === 'dark') ? 'dark_mode' : 'light_mode';
        }
        // Re-initialize and re-render mermaid diagrams with the new theme
        if (window.mermaid) {
            window.mermaid.initialize({ startOnLoad: false, theme: theme });
            // This will re-render all diagrams on the page with the new theme.
             try {
                window.mermaid.run({
                    nodes: document.querySelectorAll('.mermaid')
                });
            } catch(e) {
                console.error("Failed to re-render mermaid diagrams on theme change:", e);
            }
        }
    }

    // Function to show/hide content sections based on hash
    function showSectionBasedOnHash() {
        let hash = window.location.hash || '#home';
        let sectionId = hash.substring(1);

        // Hide all sections
        contentSections.forEach(function(section) {
            section.style.display = 'none';
        });

        // Show the target section
        let targetSection = document.getElementById(sectionId);
        if (targetSection) {
            targetSection.style.display = 'block';
        } else {
            // Fallback to chat if hash is invalid
            const chatSection = document.getElementById('chat');
            if (chatSection) {
                chatSection.style.display = 'block';
            }
            hash = '#chat';
        }

        if (mainContent) {
            if (hash === '#chat') {
                body.classList.add('chat');
                mainContent.classList.remove('container');
                mainContent.classList.add('container-fluid');
            } else {
                body.classList.remove('chat');
                mainContent.classList.remove('container-fluid');
                mainContent.classList.add('container');
            }
        }

        // Update active link in navbar
        navLinks.forEach(function(link) {
            if (link.getAttribute('href') === hash) {
                link.classList.add('active');
                link.setAttribute('aria-current', 'page');
            } else {
                link.classList.remove('active');
                link.removeAttribute('aria-current');
            }
        });
    }


    // --- Initializations ---

     // The theme is now initialized by an inline script in layout.html to prevent flickering.
    // We only need to set the toggle state based on the current theme attribute.
    if (darkModeToggle) {
        darkModeToggle.checked = (htmlElement.getAttribute('data-bs-theme') === 'dark');
    }
    if (darkModeIcon) {
        darkModeIcon.textContent = (htmlElement.getAttribute('data-bs-theme') === 'dark') ? 'dark_mode' : 'light_mode';
    }

    // 2. Display the correct content section on load
    showSectionBasedOnHash();

    // --- Event Listeners ---

    // 1. Toggle theme on switch change
    if (darkModeToggle) { // Only add listener if toggle element exists
        darkModeToggle.addEventListener('change', function() {
            if (this.checked) {
                setTheme('dark');
            } else {
                setTheme('light');
            }
        });
    }

    // 2. Handle navigation to content sections
    navLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const targetId = this.getAttribute('href');

            // Update URL hash without page reload, which will trigger hashchange event
            history.pushState(null, '', targetId);
            showSectionBasedOnHash(); // Manually call to update UI immediately

            // Close navbar toggler on link click for small screens
            if (navbarCollapse) {
                const bsCollapse = bootstrap.Collapse.getInstance(navbarCollapse);
                if (bsCollapse && navbarCollapse.classList.contains('show')) {
                    bsCollapse.hide();
                }
            }
        });
    });

    // 3. Re-run section display logic on hash change (e.g., if user navigates using browser back/forward)
    window.addEventListener('hashchange', showSectionBasedOnHash);

    // --- API Key Management ---

    const keyManagerForm = document.getElementById('key-manager-form');
    const setActiveKeyBtn = document.getElementById('set-active-key-btn');
    const apiKeyListBody = document.getElementById('api-key-list-body');

    function maskApiKey(key) {
        if (key && key.length > 8) {
            return key.substring(0, 4) + '...' + key.substring(key.length - 4);
        }
        return '...';
    }

    async function loadApiKeys() {
        try {
            const response = await fetch('/get_api_key_data');
            if (!response.ok) throw new Error('Failed to fetch API keys.');

            const data = await response.json();
            const { keys, active_key_id } = data;
            const select = document.getElementById('active-key-select');

            select.innerHTML = '';
            apiKeyListBody.innerHTML = '';

            if (!keys || Object.keys(keys).length === 0) {
                apiKeyListBody.innerHTML = '<tr><td colspan="4" class="text-center">No API keys stored.</td></tr>';
                select.innerHTML = '<option disabled selected>No keys available</option>';
            } else {
                for (const keyId in keys) {
                    const option = document.createElement('option');
                    option.value = keyId;
                    option.textContent = keyId;
                    if (keyId === active_key_id) {
                        option.selected = true;
                    }
                    select.appendChild(option);

                    const isActive = keyId === active_key_id;
                    const statusBadge = isActive ? '<span class="badge bg-success">Active</span>' : '<span class="badge bg-secondary">Inactive</span>';
                    const row = `
                        <tr>
                            <td>${keyId}</td>
                            <td>${maskApiKey(keys[keyId])}</td>
                            <td>${statusBadge}</td>
                            <td>
                                <button class="btn btn-danger btn-sm delete-key-btn" data-key-id="${keyId}">Delete</button>
                            </td>
                        </tr>
                    `;
                    apiKeyListBody.insertAdjacentHTML('beforeend', row);
                }
            }
        } catch (error) {
            console.error('Error loading API keys:', error);
            apiKeyListBody.innerHTML = '<tr><td colspan="4" class="text-center text-danger">Error loading keys.</td></tr>';
        }
    }

    async function handleApiResponse(response) {
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'An unknown error occurred.');
        }
        return data;
    }

    // --- Initializations ---

    // 1. Initialize theme
    if (darkModeToggle) {
        darkModeToggle.checked = (htmlElement.getAttribute('data-bs-theme') === 'dark');
    }
    if (darkModeIcon) {
        darkModeIcon.textContent = (htmlElement.getAttribute('data-bs-theme') === 'dark') ? 'dark_mode' : 'light_mode';
    }

    // 2. Display the correct content section on load
    showSectionBasedOnHash();

    // 3. Initial load of API keys if configuration tab is active
    if (window.location.hash === '#configuration') {
        loadApiKeys();
    }

    // --- Event Listeners ---

    // 1. Theme toggle
    if (darkModeToggle) {
        darkModeToggle.addEventListener('change', function() {
            setTheme(this.checked ? 'dark' : 'light');
        });
    }

    // 2. Navigation link clicks
    navLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const targetId = this.getAttribute('href');
            if (window.location.hash !== targetId) {
                 history.pushState(null, '', targetId);
            }
            showSectionBasedOnHash();

            if (navbarCollapse && navbarCollapse.classList.contains('show')) {
                const bsCollapse = bootstrap.Collapse.getInstance(navbarCollapse);
                if (bsCollapse) bsCollapse.hide();
            }
        });
    });

    // 3. Handle back/forward browser navigation
    window.addEventListener('hashchange', showSectionBasedOnHash);

    // 4. Load API keys when configuration tab is shown
    const configTab = document.querySelector('a[data-bs-toggle="tab"][href="#configuration"]');
    if (configTab) {
        configTab.addEventListener('shown.bs.tab', loadApiKeys);
    }

    // 5. API Key Management Form Submission
    if (keyManagerForm) {
        keyManagerForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const keyIdInput = document.getElementById('key-id-input');
            const keyValueInput = document.getElementById('key-value-input');
            const setActiveCheckbox = document.getElementById('set-as-active-checkbox');

            try {
                const response = await fetch('/add_or_update_api_key', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        key_id: keyIdInput.value,
                        key_value: keyValueInput.value,
                        set_active: setActiveCheckbox.checked
                    })
                });
                const result = await handleApiResponse(response);
                alert(result.message);
                keyManagerForm.reset();
                const accordionCollapse = document.querySelector('#collapseOne');
                if (accordionCollapse.classList.contains('show')) {
                    const bsCollapse = bootstrap.Collapse.getInstance(accordionCollapse);
                    if (bsCollapse) bsCollapse.hide();
                }
                loadApiKeys();
            } catch (error) {
                alert('Error: ' + error.message);
            }
        });
    }

    // 6. Set Active API Key Button
    if (setActiveKeyBtn) {
        setActiveKeyBtn.addEventListener('click', async function() {
            const selectedKeyId = document.getElementById('active-key-select').value;
            if (!selectedKeyId) {
                alert("Please select a key to set as active.");
                return;
            }
            try {
                const response = await fetch('/set_active_api_key', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key_id: selectedKeyId })
                });
                const result = await handleApiResponse(response);
                alert(result.message);
                loadApiKeys();
            } catch (error) {
                alert('Error: ' + error.message);
            }
        });
    }

    // 7. Delete API Key Buttons (Event Delegation)
    if (apiKeyListBody) {
        apiKeyListBody.addEventListener('click', async function(e) {
            if (e.target && e.target.classList.contains('delete-key-btn')) {
                const keyId = e.target.dataset.keyId;
                if (confirm(`Are you sure you want to delete the key '${keyId}'?`)) {
                    try {
                        const response = await fetch('/delete_api_key', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ key_id: keyId })
                        });
                        const result = await handleApiResponse(response);
                        alert(result.message);
                        loadApiKeys();
                    } catch (error) {
                        alert('Error: ' + error.message);
                    }
                }
            }
        });
    }
});