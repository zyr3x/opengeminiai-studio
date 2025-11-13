document.addEventListener('DOMContentLoaded', function () {
    // MCP Editor Logic
    const mcpUserFriendlyEditor = document.getElementById('mcp-user-friendly-editor');
    if (!mcpUserFriendlyEditor) return; // Don't run if the editor is not on the page

    const mcpAdvancedEditor = document.getElementById('mcp-advanced-editor');
    const mcpEditorSwitch = document.getElementById('mcp-editor-mode-switch');
    const mcpTextarea = document.getElementById('mcp_config_textarea');
    const mcpContainer = document.getElementById('mcp-servers-container');
    const mcpMaxFunctionDeclarationsInput = document.getElementById('mcp-max-function-declarations'); // New line

    // Add event delegation for enabled switch
    if (mcpContainer) {
        mcpContainer.addEventListener('change', function(e) {
            if (e.target.classList.contains('mcp-enabled-input')) {
                const accordionItem = e.target.closest('.accordion-item');
                if (accordionItem) {
                    accordionItem.classList.toggle('disabled-item', !e.target.checked);
                }
            }
        });
    }

    function toggleMcpEditorView() {
        if (!mcpEditorSwitch) return;
        if (mcpEditorSwitch.checked) {
            mcpUserFriendlyEditor.classList.remove('d-none');
            mcpAdvancedEditor.classList.add('d-none');
        } else {
            mcpUserFriendlyEditor.classList.add('d-none');
            mcpAdvancedEditor.classList.remove('d-none');
        }
    }

    if (mcpEditorSwitch) {
        mcpEditorSwitch.addEventListener('change', toggleMcpEditorView);
        toggleMcpEditorView(); // Initial state
    }

    if (!mcpContainer) return;
    let mcpServerCounter = mcpContainer.children.length;

    const mcpArgTemplate = `
        <div class="input-group mb-2">
            <input type="text" class="form-control mcp-arg-input" value="">
            <button class="btn btn-outline-danger mcp-remove-item-btn" type="button"><span class="material-icons">close</span></button>
        </div>`;

    const mcpEnvTemplate = `
        <div class="input-group mb-2">
            <input type="text" class="form-control mcp-env-key-input" placeholder="Key" value="">
            <span class="input-group-text">=</span>
            <input type="text" class="form-control mcp-env-value-input" placeholder="Value" value="">
            <button class="btn btn-outline-danger mcp-remove-item-btn" type="button"><span class="material-icons">close</span></button>
        </div>`;

    mcpContainer.addEventListener('click', async function(e) {
        const addArgBtn = e.target.closest('.mcp-add-arg-btn');
        const addEnvBtn = e.target.closest('.mcp-add-env-btn');
        const removeItemBtn = e.target.closest('.mcp-remove-item-btn');
        const deleteServerBtn = e.target.closest('.mcp-delete-server-btn');
        const checkBtn = e.target.closest('.mcp-check-commands-btn');

        if (addArgBtn) {
            addArgBtn.previousElementSibling.insertAdjacentHTML('beforeend', mcpArgTemplate);
        } else if (addEnvBtn) {
            addEnvBtn.previousElementSibling.insertAdjacentHTML('beforeend', mcpEnvTemplate);
        } else if (removeItemBtn) {
            removeItemBtn.closest('.input-group').remove();
        } else if (deleteServerBtn) {
            deleteServerBtn.closest('.accordion-item').remove();
        } else if (checkBtn) {
            const accordionItem = checkBtn.closest('.accordion-item');
            const infoContainer = accordionItem.querySelector('.mcp-commands-info-container');

            const escapeHtml = (text) => {
                if (typeof text !== 'string') return '';
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            };

            const command = accordionItem.querySelector('.mcp-command-input').value.trim();
            const args = Array.from(accordionItem.querySelectorAll('.mcp-arg-input')).map(input => input.value.trim()).filter(Boolean);
            const env = {};
            accordionItem.querySelectorAll('.mcp-env-container .input-group').forEach(group => {
                const keyInput = group.querySelector('.mcp-env-key-input');
                const valueInput = group.querySelector('.mcp-env-value-input');
                if (keyInput && valueInput) {
                    const key = keyInput.value.trim();
                    if (key) env[key] = valueInput.value;
                }
            });

            infoContainer.style.display = 'block';
            infoContainer.innerHTML = `<div class="d-flex align-items-center"><div class="spinner-border spinner-border-sm me-2" role="status"></div><span>Fetching commands...</span></div>`;
            checkBtn.disabled = true;

            try {
                const response = await fetch('/mcp_tool_info', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ command, args, env })
                });
                const data = await response.json();

                if (!response.ok && !data.error) {
                   throw new Error(data.error || 'Server returned an error');
                }

                if (data.error) {
                    let stderrHtml = data.stderr ? `<pre class="mt-2" style="white-space: pre-wrap; word-break: break-all; max-height: 200px; overflow-y: auto; background-color: #f1f1f1; padding: 10px; border-radius: 4px;">${escapeHtml(data.stderr)}</pre>` : '';
                    infoContainer.innerHTML = `<div class="alert alert-danger mb-0"><strong>Error:</strong> ${data.error}${stderrHtml}</div>`;
                } else if (data.tools && data.tools.length > 0) {
                    let html = '<h6>Available Commands:</h6><ul class="list-group list-group-flush">';
                    data.tools.forEach(tool => {
                        const description = tool.description || 'No description available.';
                        html += `<li class="list-group-item px-0 py-2">
                                    <strong>${tool.name}</strong>
                                    <p class="mb-0 text-muted small">${escapeHtml(description)}</p>
                                 </li>`;
                    });
                    html += '</ul>';
                    infoContainer.innerHTML = html;
                } else {
                    infoContainer.innerHTML = `<div class="alert alert-warning mb-0">No commands found for this tool.</div>`;
                }
            } catch (error) {
                infoContainer.innerHTML = `<div class="alert alert-danger mb-0"><strong>Request Failed:</strong> ${error.message}</div>`;
            } finally {
                checkBtn.disabled = false;
            }
        }
    });

    mcpContainer.addEventListener('input', function(e) {
        if (e.target.classList.contains('mcp-server-name-input')) {
            const newName = e.target.value || 'New Server';
            const headerButton = e.target.closest('.accordion-item').querySelector('.accordion-button');
            headerButton.textContent = newName;
        }
    });

    const addServerBtn = document.getElementById('mcp-add-server-btn');
    if (addServerBtn && !addServerBtn.dataset.listenerAttached) {
        addServerBtn.dataset.listenerAttached = 'true';
        addServerBtn.addEventListener('click', function() {
            mcpServerCounter++;
            const newServerTemplate = `
                <div class="accordion-item">
                    <h2 class="accordion-header" id="mcp-heading-${mcpServerCounter}">
                        <button class="accordion-button" type="button" data-bs-toggle="collapse" data-bs-target="#mcp-collapse-${mcpServerCounter}" aria-expanded="true" aria-controls="mcp-collapse-${mcpServerCounter}">
                            New Server
                        </button>
                    </h2>
                    <div id="mcp-collapse-${mcpServerCounter}" class="accordion-collapse collapse show" aria-labelledby="mcp-heading-${mcpServerCounter}" data-bs-parent="#mcp-servers-container">
                        <div class="accordion-body">
                            <div class="mb-3">
                                <label class="form-label"><b>Server Name</b></label>
                                <input type="text" class="form-control mcp-server-name-input" value="new_server_${mcpServerCounter}">
                            </div>
                            <div class="form-check form-switch mb-3">
                                <input class="form-check-input mcp-enabled-input" type="checkbox" role="switch" id="mcp-enabled-${mcpServerCounter}" checked>
                                <label class="form-check-label" for="mcp-enabled-${mcpServerCounter}"><b>Enabled</b></label>
                            </div>
                            <div class="mb-3">
                                <label for="mcp-priority-${mcpServerCounter}" class="form-label"><b>Priority</b></label>
                                <input type="number" class="form-control mcp-priority-input" id="mcp-priority-${mcpServerCounter}" value="0" placeholder="0">
                            </div>
                            <div class="mb-3">
                                <label class="form-label"><b>Command</b></label>
                                <input type="text" class="form-control mcp-command-input" value="">
                            </div>
                            <div class="mb-3">
                                <label class="form-label"><b>Arguments</b></label>
                                <div class="mcp-args-container"></div>
                                <button class="btn btn-sm btn-outline-secondary mcp-add-arg-btn" type="button">Add Argument</button>
                            </div>
                            <div class="mb-3">
                                <label class="form-label"><b>Environment Variables</b></label>
                                <div class="mcp-env-container"></div>
                                <button class="btn btn-sm btn-outline-secondary mcp-add-env-btn" type="button">Add Variable</button>
                            </div>
                             <div class="mt-3">
                                <button class="btn btn-info btn-sm mcp-check-commands-btn" type="button">
                                    <span class="material-icons" style="vertical-align: middle; font-size: 1.1rem;">checklist</span> Check Commands
                                </button>
                            </div>
                            <div class="mcp-commands-info-container mt-3" style="display: none;">
                                <!-- Populated by JS -->
                            </div>
                            <hr>
                            <button class="btn btn-danger mcp-delete-server-btn" type="button"><span class="material-icons fs-6 me-1" style="vertical-align: text-bottom;">delete</span>Delete Server</button>
                        </div>
                    </div>
                </div>`;
            mcpContainer.insertAdjacentHTML('beforeend', newServerTemplate);
        });
    }

    const mcpForm = document.getElementById('mcp-form');
    if (mcpForm) {
        mcpForm.addEventListener('submit', function() {
            if (mcpEditorSwitch.checked) {
                const mcpData = { mcpServers: {} };
                mcpContainer.querySelectorAll('.accordion-item').forEach(item => {
                    const serverNameInput = item.querySelector('.mcp-server-name-input');
                    const serverName = serverNameInput ? serverNameInput.value.trim() : '';

                    if (serverName) {
                        const command = item.querySelector('.mcp-command-input').value.trim();
                        const args = Array.from(item.querySelectorAll('.mcp-arg-input'))
                            .map(input => input.value.trim())
                            .filter(Boolean);

                        const env = {};
                        item.querySelectorAll('.mcp-env-container .input-group').forEach(group => {
                            const keyInput = group.querySelector('.mcp-env-key-input');
                            const valueInput = group.querySelector('.mcp-env-value-input');
                            if (keyInput && valueInput) {
                                const key = keyInput.value.trim();
                                if (key) {
                                    env[key] = valueInput.value;
                                }
                            }
                        });

                        const enabled = item.querySelector('.mcp-enabled-input').checked;
                        const priority = parseInt(item.querySelector('.mcp-priority-input').value, 10) || 0;

                        mcpData.mcpServers[serverName] = { command, args, env, enabled, priority };
                    }
                });

                // Add Max Function Declarations to the config
                if (mcpMaxFunctionDeclarationsInput) {
                    const limit = parseInt(mcpMaxFunctionDeclarationsInput.value, 10);
                    if (!isNaN(limit) && limit > 0) {
                        mcpData.maxFunctionDeclarations = limit;
                    } else {
                        // Fallback to a sensible default if value is invalid, or ensure it's not set
                        // If you want it to revert to the server's default when invalid, don't set it here.
                        // For now, let's explicitly set it to handler's default if invalid.
                        mcpData.maxFunctionDeclarations = 64; // This should match mcp_handler.MAX_FUNCTION_DECLARATIONS_DEFAULT
                    }
                }

                mcpTextarea.value = JSON.stringify(mcpData, null, 2);
            }
        });
    }
});
