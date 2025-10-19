document.addEventListener('DOMContentLoaded', function() {
    const promptForm = document.getElementById('prompt-form');
    if (!promptForm) {
        return; // Don't run if the prompt editor form is not on the page
    }

    // Helper to generate MCP function options from the global variable created in the template
    function generateMcpToolOptions() {
        let options = '<option value="*">All Functions</option>';
        if (window.mcpFunctionsByTool) {
            for (const toolName in window.mcpFunctionsByTool) {
                options += `<optgroup label="${toolName}">`;
                window.mcpFunctionsByTool[toolName].forEach(func => {
                    options += `<option value="${func.name}">${func.name}</option>`;
                });
                options += `</optgroup>`;
            }
        }
        return options;
    }

    const promptEditorModeSwitch = document.getElementById('prompt-editor-mode-switch');
    const userFriendlyEditor = document.getElementById('user-friendly-editor');
    const advancedEditor = document.getElementById('advanced-editor');
    const promptOverridesTextarea = document.getElementById('prompt_overrides_textarea');
    const promptProfilesContainer = document.getElementById('prompt-profiles-container');
    const addProfileBtn = document.getElementById('add-profile-btn');

    // System Prompt Editor Elements
    const systemPromptForm = document.getElementById('system-prompt-form');
    const systemPromptEditorModeSwitch = document.getElementById('system-prompt-editor-mode-switch');
    const systemFriendlyEditor = document.getElementById('system-friendly-editor');
    const systemAdvancedEditor = document.getElementById('system-advanced-editor');
    const systemPromptsTextarea = document.getElementById('system_prompts_textarea');
    const systemPromptProfilesContainer = document.getElementById('system-prompt-profiles-container');
    const addSystemPromptBtn = document.getElementById('add-system-prompt-btn');

    // Add event delegation for the enabled switch to visually update the item
    promptProfilesContainer.addEventListener('change', function(e) {
        if (e.target.classList.contains('enabled-switch')) {
            const accordionItem = e.target.closest('.accordion-item');
            if (accordionItem) {
                accordionItem.classList.toggle('disabled-item', !e.target.checked);
            }
        }
    });

    // Add event delegation for system prompt enabled switch to visually update the item
    systemPromptProfilesContainer?.addEventListener('change', function(e) {
        if (e.target.classList.contains('system-enabled-switch')) {
            const accordionItem = e.target.closest('.accordion-item');
            if (accordionItem) {
                accordionItem.classList.toggle('disabled-item', !e.target.checked);
            }
        }
    });

    // Initial state based on the switch
    function updateEditorVisibility() {
        if (promptEditorModeSwitch.checked) {
            userFriendlyEditor.classList.remove('d-none');
            advancedEditor.classList.add('d-none');
        } else {
            userFriendlyEditor.classList.add('d-none');
            advancedEditor.classList.remove('d-none');
        }
    }
    updateEditorVisibility();
    promptEditorModeSwitch.addEventListener('change', updateEditorVisibility);

    // Initial state and listener for System Prompt editor visibility
    function updateSystemEditorVisibility() {
        if (systemPromptEditorModeSwitch.checked) {
            systemFriendlyEditor.classList.remove('d-none');
            systemAdvancedEditor.classList.add('d-none');
        } else {
            systemFriendlyEditor.classList.add('d-none');
            systemAdvancedEditor.classList.remove('d-none');
        }
    }
    if (systemPromptEditorModeSwitch) {
        updateSystemEditorVisibility();
        systemPromptEditorModeSwitch.addEventListener('change', updateSystemEditorVisibility);
    }

    // Function to attach event listeners to a newly added or existing profile div
    function attachProfileEventListeners(profileDiv) {
        // TomSelect initialization will now happen on 'shown.bs.collapse' event
        // for existing profiles, or immediately for new ones that start 'show'.

        // Delete Profile
        profileDiv.querySelector('.delete-profile-btn')?.addEventListener('click', function() {
            if (confirm('Are you sure you want to delete this profile?')) {
                // Destroy TomSelect instance before removing the element
                const mcpToolsSelect = profileDiv.querySelector('.prompt-mcp-tools-select');
                if (mcpToolsSelect && mcpToolsSelect.tomselect) {
                    mcpToolsSelect.tomselect.destroy();
                }
                profileDiv.remove();
            }
        });

        // Add Trigger
        profileDiv.querySelector('.add-trigger-btn')?.addEventListener('click', function() {
            const triggersContainer = profileDiv.querySelector('.triggers-container');
            const newTriggerHtml = `
                <div class="input-group mb-2">
                    <input type="text" class="form-control trigger-input" placeholder="e.g., commit message">
                    <button class="btn btn-outline-danger remove-item-btn" type="button"><span class="material-icons">close</span></button>
                </div>
            `;
            triggersContainer.insertAdjacentHTML('beforeend', newTriggerHtml);
            // Re-attach remove listener for the new trigger input
            triggersContainer.lastElementChild.querySelector('.remove-item-btn')?.addEventListener('click', function() {
                this.closest('.input-group').remove();
            });
        });

        // Add Override
        profileDiv.querySelector('.add-override-btn')?.addEventListener('click', function() {
            const overridesContainer = profileDiv.querySelector('.overrides-container');
            const newOverrideHtml = `
                <div class="input-group mb-2">
                    <span class="input-group-text" style="width: 50px;">Find</span>
                    <input type="text" class="form-control override-key-input" placeholder="Text to find">
                    <span class="input-group-text" style="width: 80px;">Replace</span>
                    <input type="text" class="form-control override-value-input" placeholder="Replacement text">
                    <button class="btn btn-outline-danger remove-item-btn" type="button"><span class="material-icons">close</span></button>
                </div>
            `;
            overridesContainer.insertAdjacentHTML('beforeend', newOverrideHtml);
            // Re-attach remove listener for the new override input
            overridesContainer.lastElementChild.querySelector('.remove-item-btn')?.addEventListener('click', function() {
                this.closest('.input-group').remove();
            });
        });

        // Attach listeners for existing remove buttons within the new profile
        profileDiv.querySelectorAll('.remove-item-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                this.closest('.input-group').remove();
            });
        });

        // Update accordion button text if profile name changes
        profileDiv.querySelector('.profile-name-input')?.addEventListener('input', function() {
            const headerButton = profileDiv.querySelector('.accordion-header button');
            if (headerButton) {
                headerButton.textContent = this.value || 'Unnamed Profile';
            }
        });

        // Add listener to toggle MCP select based on disable switch
        const disableToolsSwitch = profileDiv.querySelector('.disable-tools-switch');
        disableToolsSwitch?.addEventListener('change', function() {
            const mcpSelect = profileDiv.querySelector('.prompt-mcp-tools-select');
            if (mcpSelect && mcpSelect.tomselect) {
                if (this.checked) {
                    mcpSelect.tomselect.disable();
                } else {
                    mcpSelect.tomselect.enable();
                }
            }
        });
    }

    // Function to attach event listeners to a newly added or existing system prompt profile div
    function attachSystemPromptEventListeners(profileDiv) {
        // TomSelect initialization will now happen on 'shown.bs.collapse' event
        // for existing profiles, or immediately for new ones that start 'show'.

        // Delete Profile
        profileDiv.querySelector('.system-delete-profile-btn')?.addEventListener('click', function() {
            if (confirm('Are you sure you want to delete this System Prompt?')) {
                // Destroy TomSelect instance before removing the element
                const sysMcpToolsSelect = profileDiv.querySelector('.system-mcp-tools-select');
                if (sysMcpToolsSelect && sysMcpToolsSelect.tomselect) {
                    sysMcpToolsSelect.tomselect.destroy();
                }
                profileDiv.remove();
            }
        });

        // Update accordion button text if profile name changes
        profileDiv.querySelector('.system-prompt-name-input')?.addEventListener('input', function() {
            const headerButton = profileDiv.querySelector('.accordion-header button');
            if (headerButton) {
                headerButton.textContent = this.value || 'Unnamed Prompt';
            }
        });

        // Add listener to toggle MCP select based on disable switch
        const disableToolsSwitch = profileDiv.querySelector('.system-disable-tools-switch');
        disableToolsSwitch?.addEventListener('change', function() {
            const mcpSelect = profileDiv.querySelector('.system-mcp-tools-select');
            if (mcpSelect && mcpSelect.tomselect) {
                if (this.checked) {
                    mcpSelect.tomselect.disable();
                } else {
                    mcpSelect.tomselect.enable();
                }
            }
        });
    }

    // Attach listeners to initially loaded profiles
    document.querySelectorAll('#prompt-profiles-container .accordion-item').forEach(profileDiv => {
        attachProfileEventListeners(profileDiv);
    });

    // Attach listeners to initially loaded system profiles
    document.querySelectorAll('#system-prompt-profiles-container .accordion-item').forEach(profileDiv => {
        attachSystemPromptEventListeners(profileDiv);
    });

    // Add new profile button logic
    if (addProfileBtn && !addProfileBtn.dataset.listenerAttached) {
        addProfileBtn.dataset.listenerAttached = 'true';
        addProfileBtn.addEventListener('click', function() {
            const newProfileIndex = promptProfilesContainer.children.length + 1; // Simple incrementing index
            const mcpToolOptions = generateMcpToolOptions();
            const newProfileHtml = `
                <div class="accordion-item rounded mb-3 shadow-sm" data-profile-name="New Profile ${newProfileIndex}">
                    <h2 class="accordion-header" id="heading-${newProfileIndex}">
                        <button class="accordion-button collapsed bg" type="button" data-bs-toggle="collapse" data-bs-target="#collapse-${newProfileIndex}" aria-expanded="false" aria-controls="collapse-${newProfileIndex}">
                            New Profile ${newProfileIndex}
                        </button>
                    </h2>
                    <div id="collapse-${newProfileIndex}" class="accordion-collapse collapse" aria-labelledby="heading-${newProfileIndex}" data-bs-parent="#prompt-profiles-container">
                        <div class="accordion-body">
                            <div class="mb-3">
                                <label class="form-label"><b>Profile Name</b></label>
                                <input type="text" class="form-control profile-name-input" value="New Profile ${newProfileIndex}">
                            </div>

                            <div class="form-check form-switch mb-3">
                                <input class="form-check-input enabled-switch" type="checkbox" role="switch" id="enabled-${newProfileIndex}" checked>
                                <label class="form-check-label" for="enabled-${newProfileIndex}"><b>Enabled</b></label>
                            </div>

                            <div class="mb-3">
                                <label class="form-label"><b>Triggers</b> (phrases that activate this profile)</label>
                                <div class="triggers-container">
                                    <div class="input-group mb-2">
                                        <input type="text" class="form-control trigger-input" placeholder="e.g., commit message">
                                        <button class="btn btn-outline-danger remove-item-btn" type="button"><span class="material-icons">close</span></button>
                                    </div>
                                </div>
                                <button class="btn btn-sm btn-outline-secondary add-trigger-btn" type="button">Add Trigger</button>
                            </div>

                            <div class="mb-3">
                                <label class="form-label"><b>Overrides</b> (text to find and replace)</label>
                                <div class="overrides-container">
                                    <div class="input-group mb-2">
                                        <span class="input-group-text" style="width: 50px;">Find</span>
                                        <input type="text" class="form-control override-key-input" placeholder="Text to find">
                                        <span class="input-group-text" style="width: 80px;">Replace</span>
                                        <input type="text" class="form-control override-value-input" placeholder="Replacement text">
                                        <button class="btn btn-outline-danger remove-item-btn" type="button"><span class="material-icons">close</span></button>
                                    </div>
                                </div>
                                <button class="btn btn-sm btn-outline-secondary add-override-btn" type="button">Add Override</button>
                            </div>

                            <div class="form-check form-switch mb-3">
                                <input class="form-check-input disable-tools-switch" type="checkbox" role="switch" id="disable-tools-${newProfileIndex}">
                                <label class="form-check-label" for="disable-tools-${newProfileIndex}">Disable MCP Tools (Commands) for this profile</label>
                            </div>

                            <div class="form-check form-switch mb-3">
                                <input class="form-check-input enable-native-tools-switch" type="checkbox" role="switch" id="enable-native-tools-${newProfileIndex}">
                                <label class="form-check-label" for="enable-native-tools-${newProfileIndex}">Enable Native Google Tools (e.g., Search)</label>
                            </div>

                            <div class="mb-3">
                                <label for="mcp-tools-select-${newProfileIndex}" class="form-label"><b>Select MCP Functions</b> (optional)</label>
                                <select id="mcp-tools-select-${newProfileIndex}" class="form-select prompt-mcp-tools-select" multiple>
                                    ${mcpToolOptions}
                                </select>
                                <div class="form-text">Select specific functions to use. This will only have an effect if tools are enabled for this profile.</div>
                            </div>

                            <button class="btn btn-danger delete-profile-btn" type="button">Delete Profile</button>
                        </div>
                    </div>
                </div>
            `;
            promptProfilesContainer.insertAdjacentHTML('beforeend', newProfileHtml);
            const newProfileDiv = promptProfilesContainer.lastElementChild;
            // Attach event listeners to the newly added profile
            attachProfileEventListeners(newProfileDiv);
            // Also explicitly initialize TomSelect for the new, shown profile
            const mcpToolsSelect = newProfileDiv.querySelector('.prompt-mcp-tools-select');
            initTomSelectForElement(mcpToolsSelect);
        });
    }

    // Add new system prompt button logic
    if (addSystemPromptBtn && !addSystemPromptBtn.dataset.listenerAttached) {
        addSystemPromptBtn.dataset.listenerAttached = 'true';
        addSystemPromptBtn.addEventListener('click', function() {
            if (!systemPromptProfilesContainer) return;
            const newProfileIndex = systemPromptProfilesContainer.children.length + 1;
            const profileId = `sys-${newProfileIndex}-${Date.now()}`; // Ensure unique IDs
            const mcpToolOptions = generateMcpToolOptions();
            const newProfileHtml = `
                <div class="accordion-item rounded mb-3 shadow-sm" data-profile-name="New System Prompt ${newProfileIndex}">
                    <h2 class="accordion-header" id="sys-heading-${profileId}">
                        <button class="accordion-button collapsed bg" type="button" data-bs-toggle="collapse" data-bs-target="#sys-collapse-${profileId}" aria-expanded="false" aria-controls="sys-collapse-${profileId}">
                            New System Prompt ${newProfileIndex}
                        </button>
                    </h2>
                    <div id="sys-collapse-${profileId}" class="accordion-collapse collapse show" aria-labelledby="sys-heading-${profileId}" data-bs-parent="#system-prompt-profiles-container">
                        <div class="accordion-body">
                            <div class="mb-3">
                                <label class="form-label"><b>Prompt Name</b></label>
                                <input type="text" class="form-control system-prompt-name-input" value="New System Prompt ${newProfileIndex}">
                            </div>

                            <div class="form-check form-switch mb-3">
                                <input class="form-check-input system-enabled-switch" type="checkbox" role="switch" id="sys-enabled-${profileId}" checked>
                                <label class="form-check-label" for="sys-enabled-${profileId}"><b>Enabled</b></label>
                            </div>

                            <div class="mb-3">
                                <label class="form-label"><b>System Prompt Text</b></label>
                                <textarea class="form-control system-prompt-text-input" rows="5" name="prompt"></textarea>
                                <div class="form-text">This text will be injected as the first message of the conversation.</div>
                            </div>

                            <div class="form-check form-switch mb-3">
                                <input class="form-check-input system-disable-tools-switch" type="checkbox" role="switch" id="sys-disable-tools-${profileId}">
                                <label class="form-check-label" for="sys-disable-tools-${profileId}">Disable MCP Tools (Commands) when this prompt is active</label>
                            </div>

                            <div class="form-check form-switch mb-3">
                                <input class="form-check-input system-enable-native-tools-switch" type="checkbox" role="switch" id="sys-enable-native-tools-${profileId}">
                                <label class="form-check-label" for="sys-enable-native-tools-${profileId}">Enable Native Google Tools (e.g., Search)</label>
                            </div>

                            <div class="mb-3">
                                <label for="sys-mcp-tools-select-${profileId}" class="form-label"><b>Select MCP Functions</b> (optional)</label>
                                <select id="sys-mcp-tools-select-${profileId}" class="form-select system-mcp-tools-select" multiple>
                                    ${mcpToolOptions}
                                </select>
                                <div class="form-text">Select specific functions to use. This will only have an effect if tools are enabled for this prompt.</div>
                            </div>

                            <button class="btn btn-danger system-delete-profile-btn" type="button">Delete Prompt</button>
                        </div>
                    </div>
                </div>
            `;
            systemPromptProfilesContainer.insertAdjacentHTML('beforeend', newProfileHtml);
            const newProfileDiv = systemPromptProfilesContainer.lastElementChild;
            // Attach event listeners to the newly added profile
            attachSystemPromptEventListeners(newProfileDiv);
            // Explicitly initialize TomSelect for the new, shown profile
            const sysMcpToolsSelect = newProfileDiv.querySelector('.system-mcp-tools-select');
            initTomSelectForElement(sysMcpToolsSelect);
        });
    }

    // Function to initialize TomSelect for a given element if not already initialized
    function initTomSelectForElement(selectElement) {
        if (selectElement && !selectElement.tomselect) {
            new TomSelect(selectElement, {
                plugins: ['remove_button', 'optgroup_columns'],
                placeholder: 'Select MCP Functions (optional)...',
                dropdownParent: 'body', // Fixes dropdown being clipped by accordion
                onChange: function(value) {
                    // if value includes '*' and has other items, just keep '*'
                    if (Array.isArray(value) && value.includes('*') && value.length > 1) {
                        this.setValue('*', true); // a silent update
                    }
                }
            });
            // After init, check and set the disabled state
            const profileDiv = selectElement.closest('.accordion-item');
            const switchSelector = selectElement.classList.contains('system-mcp-tools-select') ? '.system-disable-tools-switch' : '.disable-tools-switch';
            const disableSwitch = profileDiv.querySelector(switchSelector);
            if (disableSwitch && disableSwitch.checked) {
                selectElement.tomselect.disable();
            }
        }
    }

    // Listen for Bootstrap's 'shown.bs.collapse' event on the containers
    // to initialize Tom Select for existing (collapsed) profiles when they are opened.
    if (promptProfilesContainer) {
        promptProfilesContainer.addEventListener('shown.bs.collapse', function(event) {
            const profileDiv = event.target.closest('.accordion-item');
            if (profileDiv) {
                const mcpToolsSelect = profileDiv.querySelector('.prompt-mcp-tools-select');
                initTomSelectForElement(mcpToolsSelect);
            }
        });
    }

    if (systemPromptProfilesContainer) {
        systemPromptProfilesContainer.addEventListener('shown.bs.collapse', function(event) {
            const profileDiv = event.target.closest('.accordion-item');
            if (profileDiv) {
                const sysMcpToolsSelect = profileDiv.querySelector('.system-mcp-tools-select');
                initTomSelectForElement(sysMcpToolsSelect);
            }
        });
    }

    // Form submission handler for the user-friendly editor
    promptForm.addEventListener('submit', function(event) {
        if (promptEditorModeSwitch.checked) {
            event.preventDefault(); // Prevent default submission to serialize and then submit

            const profiles = {};
            document.querySelectorAll('#prompt-profiles-container .accordion-item').forEach(profileDiv => {
                const profileNameInput = profileDiv.querySelector('.profile-name-input');
                const newProfileName = profileNameInput ? profileNameInput.value.trim() : '';

                // Skip profiles with empty names, or provide user feedback
                if (!newProfileName) {
                    alert('All profile names must be filled out.');
                    // Optionally highlight the empty field
                    profileNameInput?.focus();
                    throw new Error('Empty profile name found.'); // Stop submission
                }

                const triggers = [];
                profileDiv.querySelectorAll('.triggers-container .trigger-input').forEach(input => {
                    const triggerValue = input.value.trim();
                    if (triggerValue) {
                        triggers.push(triggerValue);
                    }
                });

                const overrides = {};
                profileDiv.querySelectorAll('.overrides-container .input-group').forEach(inputGroup => {
                    const keyInput = inputGroup.querySelector('.override-key-input');
                    const valueInput = inputGroup.querySelector('.override-value-input');
                    const key = keyInput ? keyInput.value.trim() : '';
                    const value = valueInput ? valueInput.value.trim() : '';
                    if (key) { // Only add if key is not empty
                        overrides[key] = value;
                    }
                });

                const disableToolsSwitch = profileDiv.querySelector('.disable-tools-switch');
                const disableTools = disableToolsSwitch ? disableToolsSwitch.checked : false;

                const enableNativeToolsSwitch = profileDiv.querySelector('.enable-native-tools-switch');
                const enableNativeTools = enableNativeToolsSwitch ? enableNativeToolsSwitch.checked : false;

                const mcpToolsSelect = profileDiv.querySelector('.prompt-mcp-tools-select');
                const selectedMcpTools = mcpToolsSelect && mcpToolsSelect.tomselect ? mcpToolsSelect.tomselect.getValue() : [];

                const enabledSwitch = profileDiv.querySelector('.enabled-switch');
                const enabled = enabledSwitch ? enabledSwitch.checked : true;

                profiles[newProfileName] = {
                    enabled: enabled,
                    triggers: triggers,
                    overrides: overrides,
                    disable_tools: disableTools,
                    enable_native_tools: enableNativeTools,
                    selected_mcp_tools: selectedMcpTools // Add selected MCP tools
                };
            });

            promptOverridesTextarea.value = JSON.stringify(profiles, null, 2);

            // Now submit the form manually
            promptForm.submit();
        }
    });

    // Form submission handler for the user-friendly editor (System Prompts)
    systemPromptForm?.addEventListener('submit', function(event) {
        if (systemPromptEditorModeSwitch && systemPromptEditorModeSwitch.checked) {
            event.preventDefault(); // Prevent default submission to serialize and then submit

            const profiles = {};
            document.querySelectorAll('#system-prompt-profiles-container .accordion-item').forEach(profileDiv => {
                const profileNameInput = profileDiv.querySelector('.system-prompt-name-input');
                const newProfileName = profileNameInput ? profileNameInput.value.trim() : '';

                // Skip profiles with empty names, or provide user feedback
                if (!newProfileName) {
                    alert('All system prompt names must be filled out.');
                    profileNameInput?.focus();
                    throw new Error('Empty system prompt name found.'); // Stop submission
                }

                const promptTextInput = profileDiv.querySelector('.system-prompt-text-input');
                const promptText = promptTextInput ? promptTextInput.value.trim() : '';

                const disableToolsSwitch = profileDiv.querySelector('.system-disable-tools-switch');
                const disableTools = disableToolsSwitch ? disableToolsSwitch.checked : false;

                const enableNativeToolsSwitch = profileDiv.querySelector('.system-enable-native-tools-switch');
                const enableNativeTools = enableNativeToolsSwitch ? enableNativeToolsSwitch.checked : false;

                const sysMcpToolsSelect = profileDiv.querySelector('.system-mcp-tools-select');
                const selectedMcpTools = sysMcpToolsSelect && sysMcpToolsSelect.tomselect ? sysMcpToolsSelect.tomselect.getValue() : [];

                const enabledSwitch = profileDiv.querySelector('.system-enabled-switch');
                const enabled = enabledSwitch ? enabledSwitch.checked : true;

                profiles[newProfileName] = {
                    enabled: enabled,
                    prompt: promptText,
                    disable_tools: disableTools,
                    enable_native_tools: enableNativeTools,
                    selected_mcp_tools: selectedMcpTools // Add selected MCP tools
                };
            });

            systemPromptsTextarea.value = JSON.stringify(profiles, null, 2);

            // Now submit the form manually
            systemPromptForm.submit();
        }
    });
});
