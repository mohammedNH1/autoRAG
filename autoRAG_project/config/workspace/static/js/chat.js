// Configuration
const API_BASE_URL = 'https://e0b3eca3-ecc4-4870-b7b0-1a71e82840dc.mock.pstmn.io';
const API_ENDPOINTS = {
  GET_MESSAGES: '/api/chat/messages',
  SEND_MESSAGE: '/api/chat/send'
};

// Mock data for workspace context
const WORKSPACE_CONTEXT = {
  workspace_id: 'ws_123',
  session_id: 's_456',
  user_id: 'u_789'
};

// State
let messages = [];
let messageCounter = 1;

// DOM Elements
const chatMessagesContainer = document.getElementById('chatMessages');
const messageInput = document.getElementById('messageInput');
const sendButton = document.getElementById('sendButton');

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  console.log('🚀 Chat page loaded');

  // Fetch initial messages
  fetchMessages();

  // Setup event listeners
  sendButton.addEventListener('click', handleSendMessage);
  messageInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  });
});

/**
 * Fetch initial messages from the API
 */
async function fetchMessages() {
  try {
    console.log('📡 Fetching messages from API...');

    const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.GET_MESSAGES}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json'
      }
    });

    if (!response.ok) {
      throw new Error(`HTTP Error: ${response.status}`);
    }

    const data = await response.json();
    console.log('✅ Messages fetched successfully:', data);

    // Store messages
    if (data.messages && Array.isArray(data.messages)) {
      messages = data.messages;
      renderMessages();
    } else {
      showEmptyState();
    }
  } catch (error) {
    console.error('❌ Error fetching messages:', error);
    showErrorState('Failed to load messages. Please refresh the page.');
  }
}

/**
 * Render all messages to the UI
 */
function renderMessages() {
  chatMessagesContainer.innerHTML = '';

  if (messages.length === 0) {
    showEmptyState();
    return;
  }

  messages.forEach((msg) => {
    const messageElement = createMessageElement(msg);
    chatMessagesContainer.appendChild(messageElement);
  });

  // Scroll to bottom
  scrollToBottom();
}

/**
 * Create a message DOM element
 */
function createMessageElement(msg) {
  const messageDiv = document.createElement('div');
  messageDiv.className = `message ${msg.sender}`;

  // Determine avatar
  const avatarText = msg.sender === 'user' ? 'You' : 'AR';

  // Format timestamp
  const timestamp = msg.timestamp ? formatTime(msg.timestamp) : '';

  messageDiv.innerHTML = `
    <div class="message-avatar">${avatarText}</div>
    <div>
      <div class="message-bubble">
        <div class="message-sender">${msg.sender === 'user' ? 'You' : 'AutoRAG'}</div>
        <div class="message-content">${escapeHtml(msg.text)}</div>
        ${timestamp ? `<div class="message-time">${timestamp}</div>` : ''}
      </div>
    </div>
  `;

  return messageDiv;
}

/**
 * Handle send message action
 */
async function handleSendMessage() {
  const messageText = messageInput.value.trim();

  if (!messageText) {
    console.warn('⚠️ Empty message, not sending');
    return;
  }

  // Disable input during send
  messageInput.disabled = true;
  sendButton.disabled = true;

  try {
    console.log('📤 Sending message:', messageText);

    // Create user message object
    const userMessage = {
      id: `msg_${Date.now()}`,
      sender: 'user',
      text: messageText,
      timestamp: new Date().toISOString()
    };

    // Add user message to UI immediately (optimistic update)
    messages.push(userMessage);
    renderMessages();

    // Clear input
    messageInput.value = '';

    // Create exact payload as specified
    const payload = {
      workspace_id: WORKSPACE_CONTEXT.workspace_id,
      session_id: WORKSPACE_CONTEXT.session_id,
      user_id: WORKSPACE_CONTEXT.user_id,
      message_id: `cmsg_${String(messageCounter).padStart(3, '0')}`,
      message: messageText
    };

    messageCounter++;

    console.log('📨 Sending payload:', payload);

    // Send to API
    const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.SEND_MESSAGE}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      throw new Error(`HTTP Error: ${response.status}`);
    }

    const data = await response.json();
    console.log('✅ Message sent successfully, response:', data);

    // Handle assistant reply if present
    if (data.reply) {
      const assistantMessage = {
        id: data.reply.id || `msg_${Date.now()}`,
        sender: 'assistant',
        text: data.reply.text,
        timestamp: data.reply.timestamp || new Date().toISOString()
      };

      messages.push(assistantMessage);
      renderMessages();
    }

  } catch (error) {
    console.error('❌ Error sending message:', error);

    // Show error message to user
    showNotification('Failed to send message. Please try again.');

    // Remove the optimistic user message on failure
    messages = messages.filter(m => m.text !== messageText);
    renderMessages();

  } finally {
    // Re-enable input
    messageInput.disabled = false;
    sendButton.disabled = false;
    messageInput.focus();
  }
}

/**
 * Show empty state when no messages
 */
function showEmptyState() {
  chatMessagesContainer.innerHTML = `
    <div class="empty-state">
      <div class="empty-state-icon">💬</div>
      <div class="empty-state-text">No messages yet. Start a conversation!</div>
    </div>
  `;
}

/**
 * Show error state
 */
function showErrorState(message) {
  chatMessagesContainer.innerHTML = `
    <div class="empty-state">
      <div class="empty-state-icon">⚠️</div>
      <div class="empty-state-text">${escapeHtml(message)}</div>
    </div>
  `;
}

/**
 * Show temporary notification
 */
function showNotification(message) {
  console.log('📢 Notification:', message);
  alert(message); // Simple notification for now
}

/**
 * Format timestamp to readable format
 */
function formatTime(timestamp) {
  try {
    const date = new Date(timestamp);
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${hours}:${minutes}`;
  } catch {
    return '';
  }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  };
  return text.replace(/[&<>"']/g, (char) => map[char]);
}

/**
 * Scroll chat to bottom
 */
function scrollToBottom() {
  setTimeout(() => {
    chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight;
  }, 0);
}

console.log('✨ Chat.js loaded successfully');
