document.addEventListener('DOMContentLoaded', function () {
    // MCP Editor Logic
    const mcpUserFriendlyEditor = document.getElementById('mcp-user-friendly-editor');
    if (!mcpUserFriendlyEditor) return; // Don't run if the editor is not on the page

    const mcpAdvancedEditor = document.getElementById('mcp-advanced-editor');
    const mcpEditorSwitch = document.getElementById('mcp-editor-mode-switch');
    const mcpTextarea = document.getElementById('mcp_config_textarea');
    const mcpContainer = document.getElementById('mcp-servers-container');
    const mcpMaxFunctionDeclarationsInput = document.getElementById('mcp-max-function-declarations'); // New line

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
            <button class="btn btn-outline-danger mcp-remove-item-btn" type="button">✖</button>
        </div>`;

    const mcpEnvTemplate = `
        <div class="input-group mb-2">
            <input type="text" class="form-control mcp-env-key-input" placeholder="Key" value="">
            <span class="input-group-text">=</span>
            <input type="text" class="form-control mcp-env-value-input" placeholder="Value" value="">
            <button class="btn btn-outline-danger mcp-remove-item-btn" type="button">✖</button>
        </div>`;

    mcpContainer.addEventListener('click', function(e) {
        if (e.target.classList.contains('mcp-add-arg-btn')) {
            e.target.previousElementSibling.insertAdjacentHTML('beforeend', mcpArgTemplate);
        }
        if (e.target.classList.contains('mcp-add-env-btn')) {
            e.target.previousElementSibling.insertAdjacentHTML('beforeend', mcpEnvTemplate);
        }
        if (e.target.classList.contains('mcp-remove-item-btn')) {
            e.target.closest('.input-group').remove();
        }
        if (e.target.classList.contains('mcp-delete-server-btn')) {
            e.target.closest('.accordion-item').remove();
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
    if (addServerBtn) {
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
                            <button class="btn btn-danger mcp-delete-server-btn" type="button">Delete Server</button>
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

                        mcpData.mcpServers[serverName] = { command, args, env };
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
