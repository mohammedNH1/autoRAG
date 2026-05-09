(function () {
  const cfg = window.CHAT_CONFIG || {};
  const API_BASE_URL = (typeof cfg.apiBaseUrl === 'string') ? cfg.apiBaseUrl : '';
  const SEND_MESSAGE_URL = API_BASE_URL + '/api/chat/send';

  const WORKSPACE_ID = (typeof cfg.workspaceId !== 'undefined') ? String(cfg.workspaceId) : '';
  const WORKSPACE_CHAT_ROOT_URL = cfg.workspaceChatRootUrl || ('/workspace/' + WORKSPACE_ID + '/');

  // activeSessionId is '' when the server is rendering the empty / "New Session" state.
  let activeSessionId = cfg.activeSessionId || '';
  let messages = Array.isArray(cfg.initialMessages) ? cfg.initialMessages.slice() : [];

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  function escapeHtml(text) {
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
    return String(text).replace(/[&<>"']/g, (char) => map[char]);
  }

  function renderMarkdown(text) {
    return escapeHtml(text)
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\n---\n/g, '\n<hr class="response-divider">\n')
      .replace(/\n/g, '<br>');
  }

  function formatTime(timestamp) {
    if (!timestamp) return '';
    try {
      const date = new Date(timestamp);
      return String(date.getHours()).padStart(2, '0') + ':' + String(date.getMinutes()).padStart(2, '0');
    } catch (e) {
      return '';
    }
  }

  function sessionItemInnerHtml(title) {
    return '<div class="session-indicator"></div><span class="session-title">' + escapeHtml(title) + '</span>';
  }

  function updateSessionsCount() {
    const sessionsList = document.querySelector('.sessions-list');
    const countElement = document.querySelector('.sessions-count');
    if (!sessionsList || !countElement) return;
    countElement.textContent = sessionsList.querySelectorAll('.session-item').length + ' Total';
  }

  function showWelcomeState() {
    const main = document.querySelector('.main-content');
    if (main) main.classList.add('welcome-mode');
    const container = document.getElementById('chatMessages');
    if (container) {
      container.innerHTML =
        '<div class="welcome-state"><h2 class="welcome-title">What can I help with?</h2></div>';
    }
  }

  function renderMessages() {
    const container = document.getElementById('chatMessages');
    if (!container) return;

    if (messages.length === 0) {
      showWelcomeState();
      return;
    }

    const main = document.querySelector('.main-content');
    if (main) main.classList.remove('welcome-mode');

    container.innerHTML = '';
    messages.forEach((msg) => {
      const el = document.createElement('div');
      el.className = 'message ' + msg.sender;
      const timestamp = msg.timestamp ? formatTime(msg.timestamp) : '';
      el.innerHTML =
        '<div class="message-bubble">' +
        (msg.sender === 'assistant' ? '<div class="message-sender">AutoRAG</div>' : '') +
        '<div class="message-content">' + renderMarkdown(msg.text) + '</div>' +
        (timestamp ? '<div class="message-time">' + timestamp + '</div>' : '') +
        '</div>';
      container.appendChild(el);
    });
    scrollToBottom();
  }

  function scrollToBottom() {
    setTimeout(() => {
      const container = document.getElementById('chatMessages');
      if (container) container.scrollTop = container.scrollHeight;
    }, 0);
  }

  function showErrorModal(message) {
    const el = document.getElementById('errorMessage');
    const modal = document.getElementById('errorModal');
    if (el) el.textContent = message;
    if (modal) modal.style.display = 'flex';
  }

  window.closeErrorModal = function () {
    const modal = document.getElementById('errorModal');
    if (modal) modal.style.display = 'none';
  };

  function onSessionCreated(sessionId, sessionTitle) {
    // A brand-new session was just created by the backend on this user's first send.
    // Reflect it in the URL, header, and sidebar without a full reload.
    activeSessionId = sessionId;
    const newUrl = WORKSPACE_CHAT_ROOT_URL + 'chat/' + sessionId + '/';
    try {
      window.history.replaceState({}, '', newUrl);
    } catch (e) { /* ignore */ }

    const headerSessionEl = document.getElementById('headerSessionName');
    if (headerSessionEl && sessionTitle) headerSessionEl.textContent = sessionTitle;

    const sessionsList = document.querySelector('.sessions-list');
    if (sessionsList) {
      sessionsList.querySelectorAll('.session-item').forEach((i) => i.classList.remove('active'));
      const item = document.createElement('a');
      item.className = 'session-item active';
      item.href = newUrl;
      item.dataset.sessionId = sessionId;
      item.dataset.sessionName = sessionTitle || 'New Session';
      item.innerHTML = sessionItemInnerHtml(sessionTitle || 'New Session');
      sessionsList.insertBefore(item, sessionsList.firstChild);
    }
    updateSessionsCount();
  }

  async function sendMessage() {
    const input = document.getElementById('messageInput');
    const sendBtn = document.getElementById('sendButton');
    if (!input || !sendBtn) return;

    const messageText = input.value.trim();
    if (!messageText) return;

    sendBtn.disabled = true;
    input.disabled = true;

    const userMessage = {
      message_id: 'pending_' + Date.now(),
      sender: 'user',
      text: messageText,
      timestamp: new Date().toISOString()
    };
    messages.push(userMessage);
    renderMessages();
    input.value = '';

    // Thinking placeholder.
    const container = document.getElementById('chatMessages');
    if (container) {
      const thinkingEl = document.createElement('div');
      thinkingEl.id = 'thinkingPlaceholder';
      thinkingEl.className = 'message assistant message--thinking';
      thinkingEl.innerHTML =
        '<div class="message-bubble"><div class="message-sender">AutoRAG</div>' +
        '<div class="message-content">Thinking…</div></div>';
      container.appendChild(thinkingEl);
      scrollToBottom();
    }

    const payload = {
      workspace_id: WORKSPACE_ID,
      // Backend treats missing/blank session_id as "create a new session for this user".
      session_id: activeSessionId || null,
      message: messageText
    };

    try {
      const response = await fetch(SEND_MESSAGE_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify(payload)
      });
      const text = await response.text();
      let data = null;
      try { data = text.trim() ? JSON.parse(text) : null; } catch (_) { data = null; }

      if (!response.ok) {
        const err = new Error('HTTP ' + response.status + (text.trim() ? ': ' + text.trim() : ''));
        err.status = response.status;
        throw err;
      }

      // If the backend created a session for us, adopt it.
      if (data && data.session_id && !activeSessionId) {
        onSessionCreated(data.session_id, data.session_title);
      } else if (data && data.session_title && activeSessionId === data.session_id) {
        // Backend auto-titled an existing session (first message path) — reflect it.
        const headerSessionEl = document.getElementById('headerSessionName');
        if (headerSessionEl) headerSessionEl.textContent = data.session_title;
        const sidebarItem = document.querySelector(
          '.session-item[data-session-id="' + activeSessionId + '"]'
        );
        if (sidebarItem) {
          sidebarItem.dataset.sessionName = data.session_title;
          const span = sidebarItem.querySelector('.session-title');
          if (span) span.textContent = data.session_title;
        }
      }

      const thinkingPlaceholder = document.getElementById('thinkingPlaceholder');
      if (thinkingPlaceholder) thinkingPlaceholder.remove();

      const assistantText = (data && typeof data.response === 'string') ? data.response : 'No response.';
      messages.push({
        message_id: 'asst_' + Date.now(),
        sender: 'assistant',
        text: assistantText,
        timestamp: new Date().toISOString()
      });
      renderMessages();
    } catch (e) {
      const thinkingPlaceholder = document.getElementById('thinkingPlaceholder');
      if (thinkingPlaceholder) thinkingPlaceholder.remove();
      // Drop the optimistic user message on failure.
      messages = messages.filter((m) => m.message_id !== userMessage.message_id);
      renderMessages();
      showErrorModal(e.message || 'Network error. Please try again.');
    } finally {
      sendBtn.disabled = false;
      input.disabled = false;
      input.focus();
    }
  }

  function onNewSessionClick() {
    // Don't create a DB row until the user actually sends. Navigating to the
    // workspace root renders the empty "What can I help with?" state.
    if (!activeSessionId) return; // already on the empty state
    window.location.href = WORKSPACE_CHAT_ROOT_URL;
  }

  function enterHeaderRenameMode() {
    const headerLeft = document.querySelector('.header-left');
    const titleEl = document.getElementById('headerSessionName');
    const penBtn = document.querySelector('.header-session-edit-btn');
    if (!headerLeft || !titleEl || !penBtn) return;
    if (headerLeft.classList.contains('header-renaming')) return;
    if (!activeSessionId) return; // can't rename a session that doesn't exist yet

    const currentName = titleEl.textContent || '';
    headerLeft.classList.add('header-renaming');

    const editor = document.createElement('div');
    editor.className = 'header-rename-editor';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'header-rename-input';
    input.value = currentName;
    const confirmBtn = document.createElement('button');
    confirmBtn.type = 'button';
    confirmBtn.className = 'header-rename-confirm';
    confirmBtn.title = 'Confirm rename';
    confirmBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M5 13L9 17L19 7" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'header-rename-cancel';
    cancelBtn.title = 'Cancel rename';
    cancelBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M6 18L18 6M6 6L18 18" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    editor.appendChild(input);
    editor.appendChild(confirmBtn);
    editor.appendChild(cancelBtn);

    titleEl.style.display = 'none';
    penBtn.style.display = 'none';
    headerLeft.appendChild(editor);
    input.focus();
    input.select();

    confirmBtn.addEventListener('click', (e) => { e.stopPropagation(); exitHeaderRenameMode(true); });
    cancelBtn.addEventListener('click', (e) => { e.stopPropagation(); exitHeaderRenameMode(false); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); exitHeaderRenameMode(true); }
      else if (e.key === 'Escape') { e.preventDefault(); exitHeaderRenameMode(false); }
    });
    setTimeout(() => document.addEventListener('mousedown', _headerRenameOutsideHandler), 0);
  }

  function _headerRenameOutsideHandler(e) {
    const editor = document.querySelector('.header-rename-editor');
    if (editor && !editor.contains(e.target)) {
      exitHeaderRenameMode(false);
      document.removeEventListener('mousedown', _headerRenameOutsideHandler);
    }
  }

  function exitHeaderRenameMode(commit) {
    const headerLeft = document.querySelector('.header-left');
    const titleEl = document.getElementById('headerSessionName');
    const penBtn = document.querySelector('.header-session-edit-btn');
    const editor = document.querySelector('.header-rename-editor');
    if (!headerLeft || !editor) return;

    const input = editor.querySelector('.header-rename-input');
    const newName = input ? input.value.trim() : '';
    if (commit && newName !== '') commitHeaderRename(newName);

    editor.remove();
    if (titleEl) titleEl.style.display = '';
    if (penBtn) { penBtn.style.display = ''; penBtn.style.opacity = '0'; }
    headerLeft.classList.remove('header-renaming');
    document.removeEventListener('mousedown', _headerRenameOutsideHandler);
  }

  function commitHeaderRename(newTitle) {
    if (!activeSessionId) return;
    const titleEl = document.getElementById('headerSessionName');
    if (titleEl) titleEl.textContent = newTitle;

    const sidebarItem = document.querySelector(
      '.session-item[data-session-id="' + activeSessionId + '"]'
    );
    if (sidebarItem) {
      sidebarItem.dataset.sessionName = newTitle;
      const span = sidebarItem.querySelector('.session-title');
      if (span) span.textContent = newTitle;
    }

    fetch(WORKSPACE_CHAT_ROOT_URL + 'sessions/' + activeSessionId + '/rename/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify({ title: newTitle })
    }).catch((e) => console.warn('rename failed:', e));
  }

  document.addEventListener('DOMContentLoaded', () => {
    renderMessages();
    updateSessionsCount();

    const input = document.getElementById('messageInput');
    if (input) {
      input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          sendMessage();
        }
      });
      input.focus();
    }

    const sendBtn = document.getElementById('sendButton');
    if (sendBtn) sendBtn.addEventListener('click', sendMessage);

    const newSessionBtn = document.querySelector('.new-session-btn');
    if (newSessionBtn) newSessionBtn.addEventListener('click', onNewSessionClick);

    const headerEditBtn = document.querySelector('.header-session-edit-btn');
    if (headerEditBtn) headerEditBtn.addEventListener('click', enterHeaderRenameMode);

    const headerLeft = document.querySelector('.header-left');
    if (headerLeft && headerEditBtn) {
      headerLeft.addEventListener('mouseenter', () => {
        if (!headerLeft.classList.contains('header-renaming') && activeSessionId) {
          headerEditBtn.style.opacity = '1';
        }
      });
      headerLeft.addEventListener('mouseleave', () => {
        if (!headerLeft.classList.contains('header-renaming')) {
          headerEditBtn.style.opacity = '0';
        }
      });
    }
  });
})();
