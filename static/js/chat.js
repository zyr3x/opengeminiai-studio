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
    const systemPromptSelect = document.getElementById('system-prompt-select');
    const newChatBtn = document.getElementById('new-chat-btn');
    const attachFileBtn = document.getElementById('attach-file-btn');
    const fileUpload = document.getElementById('file-upload');
    const filePreviewsContainer = document.getElementById('file-previews-container');
    const recordBtn = document.getElementById('record-btn');
    const chatListContainer = document.getElementById('chat-list-container');
    const chatTitle = document.getElementById('chat-title');
    const mobileChatSelect = document.getElementById('mobile-chat-select'); // Mobile chat dropdown
    const newChatBtnMobile = document.getElementById('new-chat-btn-mobile'); // Mobile new chat button
    const deleteChatBtnUniversal = document.getElementById('delete-chat-btn-universal'); // Universal delete chat button
    const generationTypeSelect = document.getElementById('generation-type-select');
    const el = document.querySelector('#mcp-tools-select');
    const chatSidebar = document.getElementById('chat-sidebar');
    const mainChatArea = document.getElementById('main-chat-area');
    const toggleSidebarBtn = document.getElementById('toggle-sidebar-btn');

    let currentChatId = parseInt(localStorage.getItem('currentChatId')) || null;
    let attachedFiles = [];
    let mediaRecorder;
    let audioChunks = [];
    let isRecording = false;
    const initialBotMessageHTML = `
        <div class="message bot-message">
            <div class="avatar"><span class="material-icons">smart_toy</span></div>
            <div class="message-content">
                <p>Hello! I'm your AI assistant. To start, create a new chat from the sidebar.</p>
            </div>
        </div>`;


    if (el) {
       new TomSelect(el, {
          plugins: ['remove_button'],
          placeholder: 'Select MCP Functions (optional)...',
          dropdownParent: 'body', // Fixes dropdown being clipped by parent elements
           onChange: function(value) {
                if (Array.isArray(value) && value.includes('*') && value.length > 1) {
                    this.setValue('*', true); // silent update
                }
            }
       });
    }

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

    function addMessageToHistory(role, content, files = [], messageId = null) {
        const messageDiv = document.createElement('div');
        const isUser = role === 'user';
        messageDiv.classList.add('message', isUser ? 'user-message' : 'bot-message');

        // Avatar
        const avatarDiv = document.createElement('div');
        avatarDiv.className = 'avatar';
        const avatarIcon = document.createElement('span');
        avatarIcon.className = 'material-icons';
        avatarIcon.textContent = isUser ? 'person' : 'smart_toy';
        avatarDiv.appendChild(avatarIcon);

        const contentDiv = document.createElement('div');
        contentDiv.classList.add('message-content');

        let textContent = '';
        if (role === 'user' || role === 'assistant' || role === 'tool') { // assistant role from db
            // HACK: `df -h` on macOS can add a trailing \ to mount points.
            content = content.replace(/\\"/g, '"').replace("/\\\n","\n").replaceAll("\\\n","\n");

            let html = marked.parse(content, { gfm: true, breaks: true });
             const tempDiv = document.createElement('div');
             tempDiv.innerHTML = html;

             const replaceWithImage = (element, url) => {
                try {
                    // URLs from pollinations sometimes have spaces, encode them.
                    const encodedUrl = encodeURI(url);
                    new URL(encodedUrl); // Basic validation
                    const img = document.createElement('img');
                    img.src = encodedUrl;
                    img.alt = "Generated image";
                    img.style.maxWidth = "100%";
                    img.style.borderRadius = "0.5rem";
                    img.style.marginTop = "0.5rem";
                    element.parentNode.replaceChild(img, element);
                } catch (e) { /* Ignore failed transformations */ }
             };

             // Case 1: Correctly formed <a> tags
             tempDiv.querySelectorAll('a[href*="image.pollinations.ai"]').forEach(a => {
                // To avoid replacing links that are part of larger text, check if link text is the URL itself
                if (a.textContent.trim() === a.href) {
                    replaceWithImage(a, a.href);
                }
             });

             // Case 2: URLs as plain text inside <p> or <code> tags
             tempDiv.querySelectorAll('p, code').forEach(el => {
                const text = el.textContent.trim();
                if (text.startsWith('https://image.pollinations.ai') || text.startsWith('http://image.pollinations.ai')) {
                    // Ensure the element only contains this URL and nothing else.
                    if (el.childNodes.length === 1 && el.childNodes[0].nodeType === Node.TEXT_NODE) {
                        replaceWithImage(el, text);
                    }
                }
             });

             textContent = DOMPurify.sanitize(tempDiv.innerHTML, {ADD_TAGS: ['details', 'summary']});
        } else { // bot role for errors
            textContent = `<p>${escapeHtml(content)}</p>`;
        }


        let filesHtml = '';
        if (files && files.length > 0) {
            filesHtml = '<div class="d-flex flex-wrap gap-2 mt-2">';
            files.forEach(file => {
                const mimeType = file.type || file.mimetype || '';
                if (mimeType.startsWith('image/')) {
                    const imageUrl = file.url || URL.createObjectURL(file);
                    filesHtml += `<img src="${imageUrl}" alt="${escapeHtml(file.name)}" class="attached-image" style="max-width: 150px; border-radius: 0.5rem;">`;
                } else if (mimeType.startsWith('audio/')) {
                    filesHtml += `
                    <div class="attached-file">
                        <span class="material-icons">audiotrack</span>
                        <span>${escapeHtml(file.name)}</span>
                    </div>`;
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
        if (window.renderMathInElement) renderMathInElement(contentDiv, { delimiters: [{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false},{left:'\\(',right:'\\)',display:false},{left:'\\[',right:'\\]',display:true}], throwOnError: false });

        messageDiv.appendChild(avatarDiv);
        messageDiv.appendChild(contentDiv);

        // Add message actions (e.g., delete)
        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'message-actions';

        if (messageId) {
            const deleteBtn = document.createElement('button');
            deleteBtn.className = 'btn btn-sm btn-outline-danger p-0 px-1 delete-message-btn';
            deleteBtn.innerHTML = '<span class="material-icons fs-6">delete</span>';
            deleteBtn.title = 'Delete Message';
            deleteBtn.dataset.messageId = messageId;
            actionsDiv.appendChild(deleteBtn);
        }
        messageDiv.appendChild(actionsDiv);

        chatHistory.appendChild(messageDiv);
        chatHistory.scrollTop = chatHistory.scrollHeight;
        return messageDiv;
    }

    function showTypingIndicator() {
        const indicator = `
            <div class="message bot-message" id="typing-indicator">
                <div class="avatar"><span class="material-icons">smart_toy</span></div>
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

    // --- Sidebar Management ---
    function setSidebarState(collapsed) {
        if (!chatSidebar || !mainChatArea) return;

        if (collapsed) {
            chatSidebar.classList.add('collapsed');
            mainChatArea.classList.add('sidebar-collapsed');
            localStorage.setItem('sidebarState', 'collapsed');
            if (toggleSidebarBtn) {
                toggleSidebarBtn.querySelector('.material-icons').textContent = 'menu_open';
                toggleSidebarBtn.title = 'Expand Sidebar';
            }
        } else { // expanded
            chatSidebar.classList.remove('collapsed');
            mainChatArea.classList.remove('sidebar-collapsed');
            localStorage.setItem('sidebarState', 'expanded');
            if (toggleSidebarBtn) {
                toggleSidebarBtn.querySelector('.material-icons').textContent = 'menu';
                toggleSidebarBtn.title = 'Collapse Sidebar';
            }
        }
    }

    function toggleSidebar() {
        const isCollapsed = localStorage.getItem('sidebarState') === 'collapsed';
        setSidebarState(!isCollapsed);
    }

    function initializeSidebar() {
        const savedState = localStorage.getItem('sidebarState');
        if (savedState === 'collapsed') {
            setSidebarState(true);
        } else {
            setSidebarState(false); // Default to expanded
        }
    }

    // --- Audio Recording ---
    async function startRecording() {
        console.log("Attempting to start recording...");
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            mediaRecorder.ondataavailable = event => {
                audioChunks.push(event.data);
            };
            mediaRecorder.onstop = () => {
                console.log("Recording stopped, creating audio file.");
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                const audioFile = new File([audioBlob], "voice_recording.webm", { type: 'audio/webm' });
                console.log("Audio file created:", audioFile);
                attachedFiles.push(audioFile);
                createFilePreview(audioFile);
                filePreviewsContainer.style.display = 'flex';
                audioChunks = [];
            };
            mediaRecorder.start();
            isRecording = true;
            console.log("Recording started successfully.");
            recordBtn.classList.add('btn-danger');
            recordBtn.classList.remove('btn-outline-secondary');
            recordBtn.querySelector('.material-icons').textContent = 'stop';
            recordBtn.title = 'Stop Recording';
        } catch (err) {
            console.error("Error accessing microphone:", err);
            alert("Could not access microphone. Please ensure you have given permission in your browser settings.");
        }
    }

    function stopRecording() {
        console.log("Stopping recording...");
        mediaRecorder.stop();
        // Stop all media tracks to turn off the browser's recording indicator
        mediaRecorder.stream.getTracks().forEach(track => track.stop());
        isRecording = false;
        recordBtn.classList.remove('btn-danger');
        recordBtn.classList.add('btn-outline-secondary');
        recordBtn.querySelector('.material-icons').textContent = 'mic';
        recordBtn.title = 'Record Voice';
    }


    // --- Chat Management ---

    async function createNewChat() {
        try {
            const response = await fetch('/api/chats', { method: 'POST' });
            if (!response.ok) throw new Error('Failed to create new chat');
            const newChat = await response.json();
            currentChatId = newChat.id; // Set the new chat as the active one
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
                localStorage.removeItem('currentChatId');
            }

            if (!currentChatId && deleteChatBtnUniversal) {
                deleteChatBtnUniversal.style.display = 'none';
            }

            await loadChats();
        } catch (error) {
            console.error('Error deleting chat:', error);
            addMessageToHistory('bot', `Error: Could not delete chat. ${error.message}`);
        }
    }

    async function loadChat(chatId) {
        if (!chatId) {
            if (deleteChatBtnUniversal) deleteChatBtnUniversal.style.display = 'none';
            return;
        }
        currentChatId = chatId;
        localStorage.setItem('currentChatId', chatId);
        let newTitle = "AI Chat";

        if (deleteChatBtnUniversal) {
            deleteChatBtnUniversal.style.display = 'flex'; // Show the button when a chat is loaded
        }

        // Highlight active chat in sidebar (Desktop view)
        document.querySelectorAll('#chat-list-container .list-group-item').forEach(item => {
            item.classList.remove('active');
            if (item.dataset.chatId == chatId) {
                item.classList.add('active');
                newTitle = item.querySelector('span').textContent;
            }
        });

        // Synchronize mobile select and ensure title update
        if (mobileChatSelect) {
            mobileChatSelect.value = chatId;
            const selectedOption = mobileChatSelect.options[mobileChatSelect.selectedIndex];
            if (selectedOption) {
                 newTitle = selectedOption.textContent;
            }
        }

        chatTitle.textContent = newTitle; // Update the chat title

        chatHistory.innerHTML = ''; // Clear messages
        try {
            const response = await fetch(`/api/chats/${chatId}/messages`);
            if (!response.ok) throw new Error('Failed to load messages');
            const messages = await response.json();
            if (messages.length === 0) {
                 chatHistory.innerHTML = `
                    <div class="message bot-message">
                        <div class="avatar"><span class="material-icons">smart_toy</span></div>
                        <div class="message-content"><p>This is a new chat. Ask me anything!</p></div>
                    </div>`;
            } else {
                messages.forEach(msg => addMessageToHistory(msg.role, msg.content, msg.files || [], msg.id));
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
            chatListContainer.innerHTML = ''; // Clear desktop list

            if (mobileChatSelect) {
                mobileChatSelect.innerHTML = '';
            }

            if (chats.length === 0) {
                if (deleteChatBtnUniversal) deleteChatBtnUniversal.style.display = 'none';
                await createNewChat(); // Will recall loadChats
            } else {
                const listGroup = document.createElement('div');
                listGroup.className = 'list-group list-group-flush';
                chats.forEach(chat => {
                    const a = document.createElement('a');
                    a.href = '#chat';
                    a.className = 'list-group-item list-group-item-action d-flex justify-content-between align-items-center';
                    a.dataset.chatId = chat.id;
                    a.onclick = (e) => { e.preventDefault(); loadChat(chat.id); };

                    const titleSpan = document.createElement('span');
                    titleSpan.className = 'text-truncate';
                    titleSpan.textContent = chat.title;

                    const titleAbbr = document.createElement('span');
                    titleAbbr.className = 'chat-title-abbr';
                    titleAbbr.textContent = (chat.title || 'CH').substring(0, 2).toUpperCase();

                    const deleteBtn = document.createElement('button');
                    deleteBtn.className = 'btn btn-sm btn-outline-danger p-0 px-1 d-flex align-items-center flex-shrink-0 chat-delete-btn';
                    deleteBtn.innerHTML = '<span class="material-icons fs-6">delete</span>';
                    deleteBtn.title = 'Delete Chat';
                    deleteBtn.onclick = (e) => {
                        e.stopPropagation(); // Prevent parent `a` tag's click handler
                        deleteChat(chat.id, chat.title);
                    };

                    a.appendChild(titleSpan);
                    a.appendChild(titleAbbr);
                    a.appendChild(deleteBtn);
                    listGroup.appendChild(a);

                    // Populate mobile select
                    if (mobileChatSelect) {
                        const option = document.createElement('option');
                        option.value = chat.id;
                        option.textContent = chat.title;
                        mobileChatSelect.appendChild(option);
                    }
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

    if (recordBtn) {
        recordBtn.addEventListener('click', () => {
            console.log(`Record button clicked. isRecording: ${isRecording}`);
            if (isRecording) {
                stopRecording();
            } else {
                startRecording();
            }
        });
    }

    if (toggleSidebarBtn) {
        toggleSidebarBtn.addEventListener('click', toggleSidebar);
    }

    chatInput.addEventListener('input', adjustTextareaHeight);
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event('submit'));
        }
    });

    attachFileBtn.addEventListener('click', () => fileUpload.click());
    newChatBtn.addEventListener('click', createNewChat);

    // Mobile event listeners
    if (newChatBtnMobile) {
        newChatBtnMobile.addEventListener('click', createNewChat);
    }

    // Universal Delete Listener
    if (deleteChatBtnUniversal) {
        deleteChatBtnUniversal.addEventListener('click', () => {
            if (currentChatId) {
                deleteChat(currentChatId, chatTitle.textContent);
            }
        });
    }

    if (mobileChatSelect) {
        mobileChatSelect.addEventListener('change', function() {
            loadChat(parseInt(this.value));
        });
    }

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
        } else if (file.type.startsWith('audio/')) {
            wrapper.innerHTML = `<span class="material-icons">audiotrack</span>`;
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

    chatHistory.addEventListener('click', async function(e) {
        const deleteBtn = e.target.closest('.delete-message-btn');
        if (deleteBtn) {
            const messageId = deleteBtn.dataset.messageId;
            const messageDiv = deleteBtn.closest('.message');

            if (confirm('Are you sure you want to delete this message?')) {
                try {
                    const response = await fetch(`/api/messages/${messageId}`, { method: 'DELETE' });
                    if (!response.ok) {
                        const errData = await response.json();
                        throw new Error(errData.error || 'Failed to delete message from server.');
                    }
                    messageDiv.remove();
                } catch (error) {
                    console.error('Error deleting message:', error);
                    alert(`Could not delete message: ${error.message}`);
                }
            }
        }
    });


    async function sendMessage(userInput, filesToSend, generationType, userMessageElement = null) {
        // If this is a new message (not a retry), create the element.
        if (!userMessageElement) {
            userMessageElement = addMessageToHistory('user', userInput, filesToSend);
        } else {
            // If it's a retry, remove old error messages.
            const existingError = userMessageElement.querySelector('.message-error-container');
            if (existingError) existingError.remove();
        }

        // Clear input fields for new messages
        chatInput.value = '';
        adjustTextareaHeight();
        clearFiles();

        showTypingIndicator();

        // Disable form elements
        sendBtn.disabled = true;
        chatInput.disabled = true;
        attachFileBtn.disabled = true;
        recordBtn.disabled = true;

        const formData = new FormData();
        formData.append('chat_id', currentChatId);
        formData.append('model', modelSelect.value);
        if (generationType === 'image') {
            formData.append('prompt', userInput);
        } else {
            formData.append('system_prompt_name', systemPromptSelect ? systemPromptSelect.value : '');
            formData.append('message', userInput);
            filesToSend.forEach(file => formData.append('file', file));

            if (el && el.tomselect) {
                const selectedTools = el.tomselect.getValue();
                if (selectedTools && Array.isArray(selectedTools)) {
                    selectedTools.forEach(tool => formData.append('mcp_tools', tool));
                }
            }
        }

        const apiUrl = generationType === 'image' ? '/api/generate_image' : '/chat_api';

        try {
            const response = await fetch(apiUrl, { method: 'POST', body: formData });
            removeTypingIndicator();

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.error || 'API request failed');
            }

            if (generationType === 'image') {
                const data = await response.json();
                addMessageToHistory('assistant', data.content, [], data.message_id);
            } else {
                 const reader = response.body.getReader();
                 const decoder = new TextDecoder();
                 let botMessageContent = '';

                 // Create a new bot message element to stream content into
                 const botMessageDiv = addMessageToHistory('assistant', '', []);

                 const botContentDiv = botMessageDiv.querySelector('.message-content');
                 botContentDiv.innerHTML = ''; // Clear initial content

                // Smart scroll check: only auto-scroll if user is already at the bottom
                const isScrolledToBottom = chatHistory.scrollHeight - chatHistory.clientHeight <= chatHistory.scrollTop + 1;

                 try {
                     while (true) {
                         const { value, done } = await reader.read();
                         if (done) break;

                         const chunk = decoder.decode(value, { stream: true });

                         // Check for special events from the backend
                         if (chunk.startsWith('__LLM_EVENT__')) {
                             try {
                                 const eventData = JSON.parse(chunk.replace('__LLM_EVENT__', ''));
                                 if (eventData.type === 'message_id' && eventData.id) {
                                     const actionsDiv = botMessageDiv.querySelector('.message-actions');
                                     if (actionsDiv && !actionsDiv.querySelector('.delete-message-btn')) {
                                         const deleteBtn = document.createElement('button');
                                         deleteBtn.className = 'btn btn-sm btn-outline-danger p-0 px-1 delete-message-btn';
                                         deleteBtn.innerHTML = '<span class="material-icons fs-6">delete</span>';
                                         deleteBtn.title = 'Delete Message';
                                         deleteBtn.dataset.messageId = eventData.id;
                                         actionsDiv.appendChild(deleteBtn);
                                     }
                                 }
                             } catch (e) {
                                 console.error("Failed to parse LLM event:", e);
                             }
                             continue; // Skip processing this chunk as text
                         }


                         botMessageContent += chunk;
                         botMessageContent = botMessageContent.replace(/\\"/g, '"').replace("/\\\n", "\n").replaceAll("\\\n", "\n");
                         let html = marked.parse(botMessageContent, { gfm: true, breaks: true });

                         const tempDiv = document.createElement('div');
                         tempDiv.innerHTML = html;
                         // Image replacement logic (same as before) ...
                         botContentDiv.innerHTML = DOMPurify.sanitize(tempDiv.innerHTML, { ADD_TAGS: ['details', 'summary'] });
                         if (window.renderMathInElement) renderMathInElement(botContentDiv);

                         if (isScrolledToBottom) {
                            chatHistory.scrollTop = chatHistory.scrollHeight;
                         }
                     }
                 } catch (streamError) {
                     console.error("Streaming error:", streamError);
                     botContentDiv.innerHTML += `<p class="text-danger small mt-2"><strong>Error:</strong> The connection was interrupted during the response.</p>`;
                     chatHistory.scrollTop = chatHistory.scrollHeight;
                 }
            }

            // Success: reload chats to get new IDs and titles
            if (userInput) {
                await loadChats();
            }

        } catch (error) {
            removeTypingIndicator();
            const errorContainer = document.createElement('div');
            errorContainer.className = 'message-error-container text-danger small mt-2';
            errorContainer.innerHTML = `<p class="mb-1"><strong>Error:</strong> ${escapeHtml(error.message)}</p>`;

            const retryBtn = document.createElement('button');
            retryBtn.className = 'btn btn-sm btn-outline-secondary';
            retryBtn.innerHTML = '<span class="material-icons fs-6" style="vertical-align: sub;">refresh</span> Retry';
            retryBtn.onclick = () => {
                sendMessage(userInput, filesToSend, generationType, userMessageElement);
            };

            errorContainer.appendChild(retryBtn);
            userMessageElement.querySelector('.message-content').appendChild(errorContainer);
            chatHistory.scrollTop = chatHistory.scrollHeight;
        } finally {
            // Re-enable form elements
            sendBtn.disabled = false;
            chatInput.disabled = false;
            attachFileBtn.disabled = false;
            recordBtn.disabled = false;
            chatInput.focus();
        }
    }


    chatForm.addEventListener('submit', async function(event) {
        event.preventDefault();
        const userInput = chatInput.value.trim();
        const generationType = generationTypeSelect.value;
        const files = [...attachedFiles];

        if (generationType === 'image' && !userInput) {
             alert("Please enter a prompt to generate an image.");
             return;
        }
        if (generationType === 'text' && !userInput && files.length === 0) {
            return;
        }

        sendMessage(userInput, files, generationType);
    });

    // --- Initialization ---

    function updateChatUIForGenerationType() {
        const generationType = generationTypeSelect.value;
        const textOnlyControls = [
            attachFileBtn,
            recordBtn,
            systemPromptSelect.parentElement, // Select the wrapping div to hide the label as well
            el ? el.parentElement : null // The TomSelect wrapper div
        ].filter(Boolean); // Filter out null elements

        if (generationType === 'image') {
            textOnlyControls.forEach(control => control.style.display = 'none');
            chatInput.placeholder = 'Enter a prompt to generate an image...';
        } else { // 'text'
            textOnlyControls.forEach(control => control.style.display = ''); // Reset to default display
             if (systemPromptSelect.parentElement) systemPromptSelect.parentElement.style.display = 'flex';
             if (el && el.parentElement) el.parentElement.style.display = 'flex';
            chatInput.placeholder = 'Type a message or a prompt...';
        }
    }

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

    if (generationTypeSelect) {
        generationTypeSelect.addEventListener('change', updateChatUIForGenerationType);
    }

    initializeSidebar();
    loadModels();
    loadChats();
    updateChatUIForGenerationType(); // Set initial state
});
