document.addEventListener('DOMContentLoaded', function () {
    // Only execute on pages with the chat interface
    if (!document.getElementById('chat')) {
        return;
    }

    const chatHistory = document.getElementById('chat-history');
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const modelSelect = document.getElementById('model-select');
    const newChatBtn = document.getElementById('new-chat-btn');
    const attachFileBtn = document.getElementById('attach-file-btn');
    const fileUpload = document.getElementById('file-upload');
    const filePreviewsContainer = document.getElementById('file-previews-container');

    let conversationHistory = []; // Stores {role: 'user'/'assistant', content: '...'}
    let attachedFiles = [];
    const initialChatHistoryHTML = chatHistory.innerHTML;


    // --- Helper Functions ---

    function escapeHtml(unsafe) {
        if (typeof unsafe !== 'string') return '';
        return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function clearFiles() {
        attachedFiles = [];
        fileUpload.value = ''; // Reset file input to allow re-selection of same file
        filePreviewsContainer.innerHTML = '';
        filePreviewsContainer.style.display = 'none';
    }

    function resetChat() {
        conversationHistory = [];
        chatHistory.innerHTML = initialChatHistoryHTML;
        clearFiles();
        chatInput.value = '';
        adjustTextareaHeight();
        chatInput.focus();
    }

    function addMessageToHistory(role, content, files = []) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', role === 'user' ? 'user-message' : 'bot-message');

        const contentDiv = document.createElement('div');
        contentDiv.classList.add('message-content');

        let textContent = '';
        if (role === 'user') {
            textContent = escapeHtml(content).replace(/\n/g, '<br>');
        } else {
            textContent = DOMPurify.sanitize(marked.parse(content, { gfm: true, breaks: true }));
        }

        let filesHtml = '';
        if (files && files.length > 0) {
            filesHtml = '<div class="d-flex flex-wrap gap-2 mt-2">';
            files.forEach(file => {
                if (file.type.startsWith('image/')) {
                    const imageUrl = URL.createObjectURL(file);
                    filesHtml += `<img src="${imageUrl}" alt="${escapeHtml(file.name)}" class="attached-image" style="max-width: 150px; border-radius: 0.5rem;">`;
                } else {
                    filesHtml += `
                    <div class="attached-file">
                        <span class="material-icons">description</span>
                        <span>${escapeHtml(file.name)}</span>
                    </div>`;
                }
            });
            filesHtml += '</div>';
        }

        // Combine text and file attachment HTML
        if (textContent && filesHtml) {
            contentDiv.innerHTML = textContent + filesHtml;
        } else {
            contentDiv.innerHTML = textContent || filesHtml;
        }

        // If there's only files and no text, remove the initial <br> from user message
        if (files.length > 0 && !content.trim() && role === 'user') {
             contentDiv.innerHTML = filesHtml;
        }


        messageDiv.appendChild(contentDiv);
        chatHistory.appendChild(messageDiv);
        chatHistory.scrollTop = chatHistory.scrollHeight; // Scroll to bottom
    }

    function showTypingIndicator() {
        const indicator = `
            <div class="message bot-message" id="typing-indicator">
                <div class="message-content">
                    <div class="typing-indicator">
                        <span></span>
                        <span></span>
                        <span></span>
                    </div>
                </div>
            </div>
        `;
        chatHistory.insertAdjacentHTML('beforeend', indicator);
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    function removeTypingIndicator() {
        const indicator = document.getElementById('typing-indicator');
        if (indicator) {
            indicator.remove();
        }
    }

    function adjustTextareaHeight() {
        chatInput.style.height = 'auto'; // Reset height
        chatInput.style.height = (chatInput.scrollHeight) + 'px'; // Set to content height
    }

    // --- Event Listeners ---

    chatInput.addEventListener('input', adjustTextareaHeight);

    chatInput.addEventListener('keydown', function(event) {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault(); // Prevent new line
            chatForm.dispatchEvent(new Event('submit')); // Trigger form submission
        }
    });

    attachFileBtn.addEventListener('click', () => fileUpload.click());

    function createFilePreview(file) {
        const wrapper = document.createElement('div');
        wrapper.className = 'file-preview-wrapper';
        wrapper.dataset.fileName = file.name;
        wrapper.dataset.fileSize = file.size;

        if (file.type.startsWith('image/')) {
            const img = document.createElement('img');
            img.className = 'preview-image';
            img.src = URL.createObjectURL(file);
            wrapper.appendChild(img);
        } else {
            const genericPreview = document.createElement('div');
            genericPreview.className = 'generic-preview';
            genericPreview.innerHTML = `
                <span class="material-icons">description</span>
                <span>${escapeHtml(file.name)}</span>`;
            wrapper.appendChild(genericPreview);
        }

        const removeBtn = document.createElement('button');
        removeBtn.className = 'btn btn-sm btn-danger remove-file-btn';
        removeBtn.innerHTML = '&times;';
        removeBtn.title = 'Remove file';
        removeBtn.addEventListener('click', () => {
            const index = attachedFiles.findIndex(f => f.name === file.name && f.size === file.size);
            if (index > -1) {
                attachedFiles.splice(index, 1);
            }
            wrapper.remove();
            if (attachedFiles.length === 0) {
                filePreviewsContainer.style.display = 'none';
            }
        });

        wrapper.appendChild(removeBtn);
        filePreviewsContainer.appendChild(wrapper);
    }


    fileUpload.addEventListener('change', function(event) {
        const files = event.target.files;
        if (files.length > 0) {
            filePreviewsContainer.style.display = 'flex';
            for (const file of files) {
                // Avoid adding duplicates
                if (!attachedFiles.some(f => f.name === file.name && f.lastModified === file.lastModified && f.size === file.size)) {
                     attachedFiles.push(file);
                     createFilePreview(file);
                }
            }
            // Clear the input value to allow re-adding the same file if removed
            fileUpload.value = '';
        }
    });


    chatForm.addEventListener('submit', async function(event) {
        event.preventDefault();
        const userInput = chatInput.value.trim();
        if (!userInput && attachedFiles.length === 0) return;

        // Add a user message to history, even if it's just for the files
        addMessageToHistory('user', userInput, [...attachedFiles]);
        conversationHistory.push({ role: 'user', content: userInput || '' });


        const filesToSend = [...attachedFiles]; // Keep a reference to the files

        // Clear input and reset for next message
        chatInput.value = '';
        adjustTextareaHeight();
        clearFiles();

        // --- Prepare for bot response ---
        showTypingIndicator();
        sendBtn.disabled = true;

        // --- Send data to backend ---
        const formData = new FormData();
        formData.append('model', modelSelect.value);
        // Send only the last N messages to manage context window, or implement a more complex strategy
        formData.append('messages', JSON.stringify(conversationHistory));
        if (filesToSend.length > 0) {
            filesToSend.forEach(file => {
                formData.append('file', file); // Use 'file' as the key for getlist
            });
        }

        try {
            const response = await fetch('/chat_api', {
                method: 'POST',
                body: formData
            });

            removeTypingIndicator();

            if (!response.ok) {
                const errorData = await response.json();
                addMessageToHistory('bot', `Error: ${errorData.error || 'Unknown error'}`);
                return;
            }

            // --- Handle streaming response ---
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let botMessageContent = '';

            // Create a placeholder for the bot's message
            const botMessageDiv = document.createElement('div');
            botMessageDiv.classList.add('message', 'bot-message');
            const botContentDiv = document.createElement('div');
            botContentDiv.classList.add('message-content');
            botMessageDiv.appendChild(botContentDiv);
            chatHistory.appendChild(botMessageDiv);

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value, { stream: true });
                botMessageContent += chunk;

                // Parse content as Markdown and sanitize it before inserting into the DOM
                botContentDiv.innerHTML = DOMPurify.sanitize(marked.parse(botMessageContent, { gfm: true, breaks: true }));

                // Render LaTeX math expressions using KaTeX auto-render extension
                if (window.renderMathInElement) {
                    renderMathInElement(botContentDiv, {
                        delimiters: [
                            {left: '$$', right: '$$', display: true},
                            {left: '$', right: '$', display: false},
                            {left: '\\(', right: '\\)', display: false},
                            {left: '\\[', right: '\\]', display: true}
                        ],
                        // To prevent errors from being thrown for invalid math
                        throwOnError: false
                    });
                }

                chatHistory.scrollTop = chatHistory.scrollHeight;
            }

            conversationHistory.push({ role: 'assistant', content: botMessageContent });

        } catch (error) {
            removeTypingIndicator();
            addMessageToHistory('bot', `Network error: ${error.message}`);
        } finally {
            sendBtn.disabled = false;
            chatInput.focus();
        }
    });


    // --- Event Listeners Continued ---
    newChatBtn.addEventListener('click', resetChat);


    // --- Initialization ---

    async function loadModels() {
        try {
            const response = await fetch('/v1/models');
            if (!response.ok) {
                console.error('Failed to load models');
                return;
            }
            const data = await response.json();
            const models = data.data || [];

            // Filter for models that are likely for chat/generation
            const chatModels = models.filter(m => m.id.includes('gemini'));

            modelSelect.innerHTML = ''; // Clear existing options
            chatModels.forEach(model => {
                const option = document.createElement('option');
                option.value = model.id;
                option.textContent = model.id;
                if (model.id.includes('flash')) { // Set flash as default
                    option.selected = true;
                }
                modelSelect.appendChild(option);
            });
        } catch (error) {
            console.error('Error fetching models:', error);
            const option = document.createElement('option');
            option.textContent = 'Error loading models';
            modelSelect.appendChild(option);
        }
    }

    loadModels();
});
