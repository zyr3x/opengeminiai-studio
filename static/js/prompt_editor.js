document.addEventListener('DOMContentLoaded', function () {
    const userFriendlyEditor = document.getElementById('user-friendly-editor');
    if (!userFriendlyEditor) return; // Don't run if the editor is not on the page

    const advancedEditor = document.getElementById('advanced-editor');
    const editorSwitch = document.getElementById('prompt-editor-mode-switch');
    const promptTextarea = document.getElementById('prompt_overrides_textarea');

    function toggleEditorView() {
        if (editorSwitch.checked) {
            userFriendlyEditor.classList.remove('d-none');
            advancedEditor.classList.add('d-none');
        } else {
            userFriendlyEditor.classList.add('d-none');
            advancedEditor.classList.remove('d-none');
        }
    }

    editorSwitch.addEventListener('change', toggleEditorView);
    toggleEditorView(); // Set initial state

    const container = document.getElementById('prompt-profiles-container');
    let profileCounter = container.children.length;

    const triggerTemplate = `
        <div class="input-group mb-2">
            <input type="text" class="form-control trigger-input" value="">
            <button class="btn btn-outline-danger remove-item-btn" type="button">✖</button>
        </div>`;

    const overrideTemplate = `
        <div class="input-group mb-2">
            <span class="input-group-text" style="width: 50px;">Find</span>
            <input type="text" class="form-control override-key-input" placeholder="Text to find" value="">
            <span class="input-group-text" style="width: 80px;">Replace</span>
            <input type="text" class="form-control override-value-input" placeholder="Replacement text" value="">
            <button class="btn btn-outline-danger remove-item-btn" type="button">✖</button>
        </div>`;

    // Event delegation for all dynamic buttons inside the container
    container.addEventListener('click', function (e) {
        if (e.target.classList.contains('add-trigger-btn')) {
            e.target.previousElementSibling.insertAdjacentHTML('beforeend', triggerTemplate);
        }
        if (e.target.classList.contains('add-override-btn')) {
            e.target.previousElementSibling.insertAdjacentHTML('beforeend', overrideTemplate);
        }
        if (e.target.classList.contains('remove-item-btn')) {
            e.target.closest('.input-group').remove();
        }
        if (e.target.classList.contains('delete-profile-btn')) {
            e.target.closest('.accordion-item').remove();
        }
    });

    // Update accordion header as profile name changes
    container.addEventListener('input', function(e) {
        if (e.target.classList.contains('profile-name-input')) {
            const newName = e.target.value || 'New Profile';
            const headerButton = e.target.closest('.accordion-item').querySelector('.accordion-button');
            headerButton.textContent = newName;
        }
    });

    // Add new profile
    document.getElementById('add-profile-btn').addEventListener('click', function () {
        profileCounter++;
        const newProfileName = `new_profile_${profileCounter}`;
        const newProfileTemplate = `
            <div class="accordion-item" data-profile-name="${newProfileName}">
                <h2 class="accordion-header" id="heading-${profileCounter}">
                    <button class="accordion-button" type="button" data-bs-toggle="collapse" data-bs-target="#collapse-${profileCounter}" aria-expanded="true" aria-controls="collapse-${profileCounter}">
                        New Profile
                    </button>
                </h2>
                <div id="collapse-${profileCounter}" class="accordion-collapse collapse show" aria-labelledby="heading-${profileCounter}" data-bs-parent="#prompt-profiles-container">
                    <div class="accordion-body">
                        <div class="mb-3">
                            <label class="form-label"><b>Profile Name</b></label>
                            <input type="text" class="form-control profile-name-input" value="New Profile">
                        </div>
                        <div class="mb-3">
                            <label class="form-label"><b>Triggers</b></label>
                            <div class="triggers-container"></div>
                            <button class="btn btn-sm btn-outline-secondary add-trigger-btn" type="button">Add Trigger</button>
                        </div>
                        <div class="mb-3">
                            <label class="form-label"><b>Overrides</b></label>
                            <div class="overrides-container"></div>
                            <button class="btn btn-sm btn-outline-secondary add-override-btn" type="button">Add Override</button>
                        </div>
                        <button class="btn btn-danger delete-profile-btn" type="button">Delete Profile</button>
                    </div>
                </div>
            </div>`;
        container.insertAdjacentHTML('beforeend', newProfileTemplate);
    });

    // Before submitting, collect all data and put it in the textarea if in user-friendly mode
    document.getElementById('prompt-form').addEventListener('submit', function () {
        if (editorSwitch.checked) {
            const profilesData = {};
            container.querySelectorAll('.accordion-item').forEach(item => {
                const nameInput = item.querySelector('.profile-name-input');
                const profileName = nameInput ? nameInput.value.trim() : '';

                if (profileName) {
                    const triggers = Array.from(item.querySelectorAll('.trigger-input'))
                        .map(input => input.value.trim())
                        .filter(Boolean);

                    const overrides = {};
                    item.querySelectorAll('.overrides-container .input-group').forEach(group => {
                        const keyInput = group.querySelector('.override-key-input');
                        const valueInput = group.querySelector('.override-value-input');
                        if (keyInput && valueInput) {
                            const key = keyInput.value;
                            const value = valueInput.value;
                            if (key) { // Key must not be empty
                                overrides[key] = value;
                            }
                        }
                    });
                    profilesData[profileName] = { triggers, overrides };
                }
            });
            promptTextarea.value = JSON.stringify(profilesData, null, 2);
        }
    });
});
