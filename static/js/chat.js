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
    const chatListContainer = document.getElementById('chat-list-container');
    const chatTitle = document.getElementById('chat-title');

    let currentChatId = null;
    let attachedFiles = [];
    const initialBotMessageHTML = `
        <div class="message bot-message">
            <div class="message-content">
                <p>Hello! I'm your AI assistant. To start, create a new chat from the sidebar.</p>
            </div>
        </div>`;


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
        fileUpload.value = '';
        filePreviewsContainer.innerHTML = '';
        filePreviewsContainer.style.display = 'none';
    }

    function addMessageToHistory(role, content, files = []) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', role === 'user' ? 'user-message' : 'bot-message');

        const contentDiv = document.createElement('div');
        contentDiv.classList.add('message-content');

        let textContent = '';
        if (role === 'user' || role === 'assistant') { // assistant role from db
             textContent = DOMPurify.sanitize(marked.parse(content, { gfm: true, breaks: true }));
        } else { // bot role for errors
            textContent = `<p>${escapeHtml(content)}</p>`;
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

        contentDiv.innerHTML = textContent + filesHtml;

        messageDiv.appendChild(contentDiv);
        chatHistory.appendChild(messageDiv);
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    function showTypingIndicator() {
        const indicator = `
            <div class="message bot-message" id="typing-indicator">
                <div class="message-content">
                    <div class="typing-indicator"><span></span><span></span><span></span></div>
                </div>
            </div>`;
        chatHistory.insertAdjacentHTML('beforeend', indicator);
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    function removeTypingIndicator() {
        const indicator = document.getElementById('typing-indicator');
        if (indicator) indicator.remove();
    }

    function adjustTextareaHeight() {
        chatInput.style.height = 'auto';
        chatInput.style.height = (chatInput.scrollHeight) + 'px';
    }


    // --- Chat Management ---

    async function createNewChat() {
        try {
            const response = await fetch('/api/chats', { method: 'POST' });
            if (!response.ok) throw new Error('Failed to create new chat');
            const newChat = await response.json();
            await loadChats(); // Reload list which will also load the new chat
        } catch (error) {
            console.error('Error creating new chat:', error);
            addMessageToHistory('bot', 'Error: Could not create a new chat.');
        }
    }

    async function deleteChat(chatId, chatTitle) {
        if (!confirm(`Are you sure you want to delete the chat "${chatTitle}"?`)) {
            return;
        }
        try {
            const response = await fetch(`/api/chats/${chatId}`, { method: 'DELETE' });
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to delete chat.');
            }

            // If the deleted chat was the active one, clear currentChatId so loadChats will pick a new one.
            if (currentChatId === chatId) {
                currentChatId = null;
            }

            await loadChats();
        } catch (error) {
            console.error('Error deleting chat:', error);
            addMessageToHistory('bot', `Error: Could not delete chat. ${error.message}`);
        }
    }

    async function loadChat(chatId) {
        if (!chatId) return;
        currentChatId = chatId;

        // Highlight active chat in sidebar
        document.querySelectorAll('#chat-list-container .list-group-item').forEach(item => {
            item.classList.remove('active');
            if (item.dataset.chatId == chatId) {
                item.classList.add('active');
                chatTitle.textContent = item.textContent;
            }
        });

        chatHistory.innerHTML = ''; // Clear messages
        try {
            const response = await fetch(`/api/chats/${chatId}/messages`);
            if (!response.ok) throw new Error('Failed to load messages');
            const messages = await response.json();
            if (messages.length === 0) {
                 chatHistory.innerHTML = `
                    <div class="message bot-message">
                        <div class="message-content"><p>This is a new chat. Ask me anything!</p></div>
                    </div>`;
            } else {
                messages.forEach(msg => addMessageToHistory(msg.role, msg.content));
            }
        } catch (error) {
            console.error(`Error loading chat ${chatId}:`, error);
            addMessageToHistory('bot', 'Error: Could not load chat history.');
        }
    }

    async function loadChats() {
        try {
            const response = await fetch('/api/chats');
            if (!response.ok) throw new Error('Failed to load chats');
            const chats = await response.json();
            chatListContainer.innerHTML = ''; // Clear list

            if (chats.length === 0) {
                await createNewChat(); // Will recall loadChats
            } else {
                const listGroup = document.createElement('div');
                listGroup.className = 'list-group list-group-flush';
                chats.forEach(chat => {
                    const a = document.createElement('a');
                    a.href = '#chat';
                    a.className = 'list-group-item list-group-item-action text-truncate d-flex justify-content-between align-items-center';
                    a.dataset.chatId = chat.id;
                    a.onclick = (e) => { e.preventDefault(); loadChat(chat.id); };

                    const titleSpan = document.createElement('span');
                    titleSpan.textContent = chat.title;

                    const deleteBtn = document.createElement('button');
                    deleteBtn.className = 'btn btn-sm btn-outline-danger p-0 px-1 d-flex align-items-center flex-shrink-0';
                    deleteBtn.innerHTML = '<span class="material-icons fs-6">delete</span>';
                    deleteBtn.title = 'Delete Chat';
                    deleteBtn.onclick = (e) => {
                        e.stopPropagation(); // Prevent parent `a` tag's click handler
                        deleteChat(chat.id, chat.title);
                    };

                    a.appendChild(titleSpan);
                    a.appendChild(deleteBtn);
                    listGroup.appendChild(a);
                });
                chatListContainer.appendChild(listGroup);

                // If no chat is selected, or selected chat is gone, load the first one
                if (!currentChatId || !chats.some(c => c.id === currentChatId)) {
                    await loadChat(chats[0].id);
                } else {
                    await loadChat(currentChatId); // Reload current chat to refresh title
                }
            }
        } catch (error) {
            console.error('Error loading chats:', error);
            chatHistory.innerHTML = initialBotMessageHTML;
        }
    }


    // --- Event Listeners ---

    chatInput.addEventListener('input', adjustTextareaHeight);
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event('submit'));
        }
    });

    attachFileBtn.addEventListener('click', () => fileUpload.click());
    newChatBtn.addEventListener('click', createNewChat);

    fileUpload.addEventListener('change', function(event) {
        const files = event.target.files;
        if (!files.length) return;
        filePreviewsContainer.style.display = 'flex';
        for (const file of files) {
            if (!attachedFiles.some(f => f.name === file.name && f.size === file.size)) {
                 attachedFiles.push(file);
                 createFilePreview(file);
            }
        }
        fileUpload.value = '';
    });

    function createFilePreview(file) {
        const wrapper = document.createElement('div');
        wrapper.className = 'file-preview-wrapper';
        if (file.type.startsWith('image/')) {
            const img = document.createElement('img');
            img.src = URL.createObjectURL(file);
            wrapper.appendChild(img);
        } else {
            wrapper.innerHTML = `<span class="material-icons">description</span>`;
        }
        const removeBtn = document.createElement('button');
        removeBtn.className = 'btn btn-sm btn-danger remove-file-btn';
        removeBtn.innerHTML = '&times;';
        removeBtn.onclick = () => {
            attachedFiles = attachedFiles.filter(f => f.name !== file.name || f.size !== file.size);
            wrapper.remove();
            if (attachedFiles.length === 0) filePreviewsContainer.style.display = 'none';
        };
        wrapper.appendChild(removeBtn);
        filePreviewsContainer.appendChild(wrapper);
    }

    chatForm.addEventListener('submit', async function(event) {
        event.preventDefault();
        const userInput = chatInput.value.trim();
        if (!userInput && attachedFiles.length === 0) return;

        addMessageToHistory('user', userInput, [...attachedFiles]);
        const filesToSend = [...attachedFiles];
        chatInput.value = '';
        adjustTextareaHeight();
        clearFiles();

        showTypingIndicator();
        sendBtn.disabled = true;

        const formData = new FormData();
        formData.append('chat_id', currentChatId);
        formData.append('model', modelSelect.value);
        formData.append('message', userInput);
        filesToSend.forEach(file => formData.append('file', file));

        try {
            const response = await fetch('/chat_api', { method: 'POST', body: formData });
            removeTypingIndicator();

            if (!response.ok) {
                const err = await response.json();
                addMessageToHistory('bot', `Error: ${err.error || 'Unknown error'}`);
                return;
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let botMessageContent = '';
            const botMessageDiv = document.createElement('div');
            botMessageDiv.className = 'message bot-message';
            const botContentDiv = document.createElement('div');
            botContentDiv.className = 'message-content';
            botMessageDiv.appendChild(botContentDiv);
            chatHistory.appendChild(botMessageDiv);

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                botMessageContent += decoder.decode(value, { stream: true });
                botContentDiv.innerHTML = DOMPurify.sanitize(marked.parse(botMessageContent, { gfm: true, breaks: true }));
                if (window.renderMathInElement) renderMathInElement(botContentDiv, { delimiters: [{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false},{left:'\\(',right:'\\)',display:false},{left:'\\[',right:'\\]',display:true}], throwOnError: false });
                chatHistory.scrollTop = chatHistory.scrollHeight;
            }

            if (userInput) { // Only reload chats if there was text, to update title
                await loadChats();
            }

        } catch (error) {
            removeTypingIndicator();
            addMessageToHistory('bot', `Network error: ${error.message}`);
        } finally {
            sendBtn.disabled = false;
            chatInput.focus();
        }
    });

    // --- Initialization ---
    async function loadModels() {
        try {
            const response = await fetch('/v1/models');
            if (!response.ok) throw new Error('Failed to load models');
            const data = await response.json();
            const models = data.data.filter(m => m.id.includes('gemini'));
            modelSelect.innerHTML = '';
            models.forEach(model => {
                const option = document.createElement('option');
                option.value = model.id;
                option.textContent = model.id;
                if (model.id.includes('flash')) option.selected = true;
                modelSelect.appendChild(option);
            });
        } catch (error) {
            console.error('Error fetching models:', error);
            modelSelect.innerHTML = '<option>Error loading models</option>';
        }
    }

    loadModels();
    loadChats();
});
