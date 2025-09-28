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
    const attachImageBtn = document.getElementById('attach-image-btn');
    const imageUpload = document.getElementById('image-upload');
    const imagePreviewContainer = document.getElementById('image-preview-container');
    const imagePreview = document.getElementById('image-preview');
    const removeImageBtn = document.getElementById('remove-image-btn');

    let conversationHistory = []; // Stores {role: 'user'/'assistant', content: '...'}
    let attachedImageFile = null;
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

    function resetChat() {
        conversationHistory = [];
        chatHistory.innerHTML = initialChatHistoryHTML;
        removeImageBtn.click();
        chatInput.value = '';
        adjustTextareaHeight();
        chatInput.focus();
    }

    function addMessageToHistory(role, content, imageUrl = null) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', role === 'user' ? 'user-message' : 'bot-message');

        const contentDiv = document.createElement('div');
        contentDiv.classList.add('message-content');

        let htmlContent = '';
        if (role === 'user') {
            // For user messages, escape HTML to prevent self-XSS and convert newlines
            htmlContent = escapeHtml(content).replace(/\n/g, '<br>');
        } else {
            // For bot messages, parse Markdown and sanitize the output for security
            htmlContent = DOMPurify.sanitize(marked.parse(content, { gfm: true, breaks: true }));
        }

        if (imageUrl) {
             htmlContent += `<img src="${imageUrl}" alt="Attached image" class="attached-image">`;
        }

        contentDiv.innerHTML = htmlContent;
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

    attachImageBtn.addEventListener('click', () => imageUpload.click());

    imageUpload.addEventListener('change', function(event) {
        const file = event.target.files[0];
        if (file) {
            attachedImageFile = file;
            const reader = new FileReader();
            reader.onload = function(e) {
                imagePreview.src = e.target.result;
                imagePreviewContainer.style.display = 'block';
            };
            reader.readAsDataURL(file);
        }
    });

    removeImageBtn.addEventListener('click', () => {
        attachedImageFile = null;
        imageUpload.value = ''; // Reset file input
        imagePreviewContainer.style.display = 'none';
        imagePreview.src = '';
    });

    chatForm.addEventListener('submit', async function(event) {
        event.preventDefault();
        const userInput = chatInput.value.trim();
        if (!userInput && !attachedImageFile) return;

        // --- Display user's message ---
        const userImagePreviewUrl = attachedImageFile ? URL.createObjectURL(attachedImageFile) : null;
        addMessageToHistory('user', userInput, userImagePreviewUrl);
        conversationHistory.push({ role: 'user', content: userInput });

        // Clear input and reset for next message
        chatInput.value = '';
        adjustTextareaHeight();
        removeImageBtn.click(); // Clear image preview

        // --- Prepare for bot response ---
        showTypingIndicator();
        sendBtn.disabled = true;

        // --- Send data to backend ---
        const formData = new FormData();
        formData.append('model', modelSelect.value);
        // Send only the last N messages to manage context window, or implement a more complex strategy
        formData.append('messages', JSON.stringify(conversationHistory)); 
        if (attachedImageFile) {
            formData.append('image', attachedImageFile);
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
                chatHistory.scrollTop = chatHistory.scrollHeight;
            }

            conversationHistory.push({ role: 'assistant', content: botMessageContent });

        } catch (error) {
            removeTypingIndicator();
            addMessageToHistory('bot', `Network error: ${error.message}`);
        } finally {
            sendBtn.disabled = false;
            chatInput.focus();
            attachedImageFile = null; // Clear file after sending
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
