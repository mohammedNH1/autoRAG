(function () {
  const cfg = window.CHAT_CONFIG || {};
  const API_BASE_URL = (typeof cfg.apiBaseUrl === 'string') ? cfg.apiBaseUrl : '';
  const API_ENDPOINTS = {
    CREATE_SESSION: '/api/chat/sessions',
    SEND_MESSAGE: '/api/chat/send'
  };

  var WORKSPACE_ID = (typeof cfg.workspaceId !== 'undefined') ? String(cfg.workspaceId) : '1';

  const WORKSPACE_CONTEXT = {
    workspace_id: WORKSPACE_ID,
    session_id: null,
    user_id: 'u_789'
  };

  // Draft = no real session yet (session_id === null, isDraft === true). First send creates session via backend then sends message with returned session_id.
  let currentSession = null;
  const messagesBySession = {};
  const draftSessions = {};
  let sessionCounter = 0;
  let messageCounter = 1;

  function generateLocalId() {
    return 'draft_' + Date.now() + '_' + Math.random().toString(36).slice(2, 11);
  }

  function getCurrentSessionId() {
    return currentSession ? currentSession.session_id : null;
  }

  function getMessageStorageKey() {
    if (!currentSession) return null;
    return currentSession.local_id ?? currentSession.session_id;
  }

  function getMessagesForSession(sessionId) {
    if (!sessionId) return [];
    return messagesBySession[sessionId] || [];
  }

  function setMessagesForSession(sessionId, msgs) {
    if (!sessionId) return;
    messagesBySession[sessionId] = Array.isArray(msgs) ? msgs : [];
  }

  function getSessionNameFromItem(item) {
    return (item.dataset.sessionName || (item.querySelector('.session-title') || {}).textContent || '').trim();
  }

  function isActiveSessionEmpty() {
    const key = getMessageStorageKey();
    if (!key) return true;
    return getMessagesForSession(key).length === 0;
  }

  function updateHeaderEmptyState() {
    const mainHeader = document.querySelector('.main-header');
    if (!mainHeader) return;
    if (isActiveSessionEmpty()) {
      mainHeader.classList.add('header--empty-session');
    } else {
      mainHeader.classList.remove('header--empty-session');
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    showWelcomeState();
    initializeSessionState();

    document.getElementById('messageInput').addEventListener('keypress', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    const sendBtn = document.getElementById('sendButton');
    if (sendBtn) sendBtn.addEventListener('click', sendMessage);

    const newSessionBtn = document.querySelector('.new-session-btn');
    if (newSessionBtn) {
      newSessionBtn.addEventListener('click', () => createNewSession());
    }

    const headerEditBtn = document.querySelector('.header-session-edit-btn');
    if (headerEditBtn) {
      headerEditBtn.addEventListener('click', enterHeaderRenameMode);
    }

    const headerLeft = document.querySelector('.header-left');
    if (headerLeft && headerEditBtn) {
      headerLeft.addEventListener('mouseenter', () => {
        if (!headerLeft.classList.contains('header-renaming')) {
          headerEditBtn.style.opacity = '1';
        }
      });
      headerLeft.addEventListener('mouseleave', () => {
        if (!headerLeft.classList.contains('header-renaming')) {
          headerEditBtn.style.opacity = '0';
        }
      });
    }

    const sessionsList = document.querySelector('.sessions-list');
    if (sessionsList) {
      sessionsList.addEventListener('click', (event) => {
        const item = event.target.closest('.session-item');
        if (!item) return;
        const sessionId = item.dataset.sessionId;
        if (!sessionId) return;
        setActiveSession(sessionId, getSessionNameFromItem(item));
      });
    }

    if (!currentSession) {
      createNewSession();
    }
  });

  function initializeSessionState() {
    const sessionsList = document.querySelector('.sessions-list');
    if (!sessionsList) return;

    const items = Array.from(sessionsList.querySelectorAll('.session-item'));
    sessionCounter = items.length;

    let activeItem = sessionsList.querySelector('.session-item.active');
    if (!activeItem && items.length > 0) {
      activeItem = items[0];
      activeItem.classList.add('active');
    }

    if (activeItem) {
      const sessionId = activeItem.dataset.sessionId || null;
      if (sessionId) {
        setActiveSession(sessionId, getSessionNameFromItem(activeItem));
      }
    }

    updateSessionsCount();
  }

  function deleteDraftSession(sessionId) {
    delete draftSessions[sessionId];
    delete messagesBySession[sessionId];
  }

  function setHeaderDraftMode(isDraft) {
    const mainHeader = document.querySelector('.main-header');
    if (!mainHeader) return;
    if (isDraft) {
      mainHeader.classList.add('header-draft');
    } else {
      mainHeader.classList.remove('header-draft');
    }
  }

  function getNextSessionTitle() {
    const sessionsList = document.querySelector('.sessions-list');
    const count = sessionsList ? sessionsList.querySelectorAll('.session-item').length : 0;
    return 'Session ' + String(count + 1).padStart(2, '0');
  }

  function sessionItemInnerHtml(title) {
    return '<div class="session-indicator"></div><span class="session-title">' + escapeHtml(title) + '</span>';
  }

  function commitDraftSession(session) {
    if (!session || session.local_id == null) return;
    const draft = draftSessions[session.local_id];
    if (!draft) return;

    delete draftSessions[session.local_id];
    const sessionId = session.session_id || session.local_id;
    const sessionName = getNextSessionTitle();
    session.name = sessionName;

    const sessionsList = document.querySelector('.sessions-list');
    if (sessionsList) {
      const existingItem = sessionsList.querySelector('.session-item[data-session-id="' + session.local_id + '"]');
      if (existingItem) {
        existingItem.dataset.sessionId = sessionId;
        existingItem.dataset.sessionName = sessionName;
        existingItem.dataset.clientSessionId = session.local_id;
        existingItem.innerHTML = sessionItemInnerHtml(sessionName);
        existingItem.classList.add('active');
      } else {
        const item = document.createElement('div');
        item.className = 'session-item active';
        item.dataset.sessionId = sessionId;
        item.dataset.sessionName = sessionName;
        item.dataset.clientSessionId = session.local_id;
        item.innerHTML = sessionItemInnerHtml(sessionName);
        sessionsList.appendChild(item);
      }
    }

    setHeaderDraftMode(false);
    const headerSessionEl = document.getElementById('headerSessionName');
    if (headerSessionEl) headerSessionEl.textContent = sessionName;
    updateHeaderEmptyState();
    updateSessionsCount();
  }

  function setActiveSession(sessionId, sessionName) {
    const sessionsList = document.querySelector('.sessions-list');
    if (!sessionsList) return;

    if (currentSession && currentSession.isDraft && currentSession.local_id !== sessionId) {
      const prevMessages = getMessagesForSession(currentSession.local_id);
      if (prevMessages.length === 0) deleteDraftSession(currentSession.local_id);
    }

    sessionsList.querySelectorAll('.session-item').forEach(i => i.classList.remove('active'));
    const targetItem = sessionsList.querySelector('.session-item[data-session-id="' + sessionId + '"]');
    if (targetItem) targetItem.classList.add('active');

    const clientKey = targetItem ? targetItem.dataset.clientSessionId : null;
    currentSession = {
      session_id: sessionId,
      isDraft: !!draftSessions[sessionId],
      local_id: clientKey != null ? clientKey : sessionId,
      name: sessionName || ''
    };
    WORKSPACE_CONTEXT.session_id = sessionId;
    setHeaderDraftMode(currentSession.isDraft);

    if (!currentSession.isDraft) {
      const headerSessionEl = document.getElementById('headerSessionName');
      if (headerSessionEl && sessionName) headerSessionEl.textContent = sessionName;
    }

    renderMessages();
    updateHeaderEmptyState();
  }

  function createNewSession() {
    const sessionsList = document.querySelector('.sessions-list');
    if (!sessionsList) return;

    sessionCounter += 1;
    const local_id = generateLocalId();
    const sessionName = 'New Session ' + sessionCounter;

    if (currentSession && currentSession.isDraft) {
      const prevMessages = getMessagesForSession(currentSession.local_id);
      if (prevMessages.length === 0) deleteDraftSession(currentSession.local_id);
    }

    currentSession = { session_id: null, isDraft: true, local_id: local_id, name: sessionName };
    draftSessions[local_id] = { session_id: null, isDraft: true, local_id: local_id, name: sessionName };
    WORKSPACE_CONTEXT.session_id = null;
    setMessagesForSession(local_id, []);

    sessionsList.querySelectorAll('.session-item').forEach(i => i.classList.remove('active'));
    setHeaderDraftMode(true);
    updateHeaderEmptyState();
    showWelcomeState();
  }

  async function ensureSessionCreated(session) {
    if (!session) return null;
    if (session.session_id != null) return session.session_id;
    const baseUrl = API_BASE_URL || '';
    if (!baseUrl) return null;
    const payload = {
      workspace_id: WORKSPACE_CONTEXT.workspace_id,
      user_id: WORKSPACE_CONTEXT.user_id
    };
    try {
      const response = await fetch(baseUrl + API_ENDPOINTS.CREATE_SESSION, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await response.json().catch(function () { return null; });
      if (!response.ok) throw new Error('Session creation failed: ' + response.status);
      const sessionId = (data && (data.session_id != null ? data.session_id : data.id)) || null;
      if (!sessionId) throw new Error('Session creation did not return session_id');
      session.session_id = sessionId;
      session.isDraft = false;
      WORKSPACE_CONTEXT.session_id = sessionId;
      return sessionId;
    } catch (err) {
      console.error('CREATE_SESSION error:', err);
      throw err;
    }
  }

  function applyBackendState(data) {
    if (!data || typeof data !== 'object') return;

    const workspaceName = data.workspace_name;
    const sessionNameFromData = data.session_name;
    const sessions = Array.isArray(data.sessions) ? data.sessions : null;

    const sessionsHeader = document.querySelector('.sessions-header h3');
    if (workspaceName && sessionsHeader) sessionsHeader.textContent = workspaceName;

    if (sessions) {
      const sessionsList = document.querySelector('.sessions-list');
      if (sessionsList) {
        sessionsList.innerHTML = '';
        sessionCounter = sessions.length;
        sessions.forEach((session, index) => {
          const item = document.createElement('div');
          item.className = 'session-item';
          if (session.is_active) item.classList.add('active');
          item.dataset.sessionId = session.id;
          item.dataset.sessionName = session.title;
          item.dataset.clientSessionId = 'server_' + index;
          item.innerHTML = sessionItemInnerHtml(session.title);
          sessionsList.appendChild(item);
        });
      }
    }

    let activeSessionId = WORKSPACE_CONTEXT.session_id;
    let activeSessionName = sessionNameFromData || null;
    if (sessions) {
      const explicitActive = sessions.find((s) => s.is_active);
      const fallback = sessions[0];
      const chosen = explicitActive || fallback;
      if (chosen) {
        activeSessionId = chosen.id;
        activeSessionName = chosen.title;
      }
    }
    if (activeSessionId) setActiveSession(activeSessionId, activeSessionName || '');
    updateSessionsCount();
  }

  function updateSessionsCount() {
    const sessionsList = document.querySelector('.sessions-list');
    const countElement = document.querySelector('.sessions-count');
    if (!sessionsList || !countElement) return;
    const count = sessionsList.querySelectorAll('.session-item').length;
    countElement.textContent = count + ' Total';
  }

  function enterHeaderRenameMode() {
    const headerLeft = document.querySelector('.header-left');
    const titleEl = document.getElementById('headerSessionName');
    const penBtn = document.querySelector('.header-session-edit-btn');
    if (!headerLeft || !titleEl || !penBtn) return;
    if (headerLeft.classList.contains('header-renaming')) return;

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
    const titleEl = document.getElementById('headerSessionName');
    if (titleEl) titleEl.textContent = newTitle;
    const currentSessionId = getCurrentSessionId();
    if (!currentSessionId) return;
    const sessionsList = document.querySelector('.sessions-list');
    if (!sessionsList) return;
    const item = sessionsList.querySelector('.session-item[data-session-id="' + currentSessionId + '"]');
    if (!item) return;
    item.dataset.sessionName = newTitle;
    const spanEl = item.querySelector('.session-title');
    if (spanEl) spanEl.textContent = newTitle;
  }

  function showWelcomeState() {
    document.querySelector('.main-content').classList.add('welcome-mode');
    document.getElementById('chatMessages').innerHTML =
      '<div class="welcome-state"><h2 class="welcome-title">What can I help with?</h2></div>';
    const input = document.getElementById('messageInput');
    if (input) input.focus();
  }

  function escapeHtml(text) {
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
    return String(text).replace(/[&<>"']/g, (char) => map[char]);
  }

  function formatTime(timestamp) {
    try {
      const date = new Date(timestamp);
      return String(date.getHours()).padStart(2, '0') + ':' + String(date.getMinutes()).padStart(2, '0');
    } catch (e) {
      return '';
    }
  }

  function renderMessages() {
    const container = document.getElementById('chatMessages');
    const storageKey = getMessageStorageKey();
    const currentMessages = getMessagesForSession(storageKey || '');

    if (!storageKey || currentMessages.length === 0) {
      showWelcomeState();
      updateHeaderEmptyState();
      return;
    }

    document.querySelector('.main-content').classList.remove('welcome-mode');
    container.innerHTML = '';

    currentMessages.forEach((msg) => {
      const messageDiv = document.createElement('div');
      messageDiv.className = 'message ' + msg.sender;
      const timestamp = msg.timestamp ? formatTime(msg.timestamp) : '';
      const senderName = msg.sender === 'user' ? 'You' : 'AutoRAG';
      messageDiv.innerHTML =
        '<div class="message-bubble">' +
        (msg.sender === 'assistant' ? '<div class="message-sender">' + senderName + '</div>' : '') +
        '<div class="message-content">' + escapeHtml(msg.text) + '</div>' +
        (timestamp ? '<div class="message-time">' + timestamp + '</div>' : '') +
        '</div>';
      container.appendChild(messageDiv);
    });

    scrollToBottom();
    updateHeaderEmptyState();
  }

  function showErrorModal(message) {
    document.getElementById('errorMessage').textContent = message;
    document.getElementById('errorModal').style.display = 'flex';
  }

  window.closeErrorModal = function () {
    document.getElementById('errorModal').style.display = 'none';
  };

  function scrollToBottom() {
    setTimeout(() => {
      const container = document.getElementById('chatMessages');
      if (container) container.scrollTop = container.scrollHeight;
    }, 0);
  }

  var FRONTEND_ONLY_REPLY_TEXT = 'Not implemented yet.';

  async function sendMessage() {
    const input = document.getElementById('messageInput');
    const messageText = input.value.trim();
    if (!messageText) return;

    if (!currentSession) {
      var local_id = generateLocalId();
      currentSession = { session_id: null, isDraft: true, local_id: local_id, name: 'Session' };
      draftSessions[local_id] = currentSession;
      setMessagesForSession(local_id, []);
    }

    document.querySelector('.main-content').classList.remove('welcome-mode');
    const sendBtn = document.getElementById('sendButton');
    sendBtn.disabled = true;
    input.disabled = true;

    const storageKey = getMessageStorageKey();
    const userMessage = {
      id: 'msg_' + Date.now(),
      sender: 'user',
      text: messageText,
      timestamp: new Date().toISOString()
    };

    var sessionMessages = getMessagesForSession(storageKey).slice();
    sessionMessages.push(userMessage);
    setMessagesForSession(storageKey, sessionMessages);
    renderMessages();
    input.value = '';

    if (cfg.frontendOnly) {
      var thinkingEl = document.createElement('div');
      thinkingEl.id = 'thinkingPlaceholder';
      thinkingEl.className = 'message assistant message--thinking';
      thinkingEl.innerHTML = '<div class="message-bubble"><div class="message-sender">AutoRAG</div><div class="message-content">Thinking…</div></div>';
      document.getElementById('chatMessages').appendChild(thinkingEl);
      scrollToBottom();

      setTimeout(function () {
        var thinkingPlaceholder = document.getElementById('thinkingPlaceholder');
        if (thinkingPlaceholder) thinkingPlaceholder.remove();
        var assistantMessage = {
          id: 'msg_' + Date.now(),
          sender: 'assistant',
          text: FRONTEND_ONLY_REPLY_TEXT,
          timestamp: new Date().toISOString()
        };
        var key = getMessageStorageKey();
        var msgs = getMessagesForSession(key).slice();
        msgs.push(assistantMessage);
        setMessagesForSession(key, msgs);
        renderMessages();
        sendBtn.disabled = false;
        input.disabled = false;
        input.focus();
      }, 600);
      return;
    }

    // First message from draft: create session with workspace_id, then send with returned session_id.
    const wasDraft = currentSession.isDraft;
    if (wasDraft) {
      try {
        await ensureSessionCreated(currentSession);
      } catch (e) {
        showErrorModal('Could not create session. Please try again.');
        sendBtn.disabled = false;
        input.disabled = false;
        input.focus();
        return;
      }
    }
    if (wasDraft) commitDraftSession(currentSession);

    var thinkingEl = document.createElement('div');
    thinkingEl.id = 'thinkingPlaceholder';
    thinkingEl.className = 'message assistant message--thinking';
    thinkingEl.innerHTML = '<div class="message-bubble"><div class="message-sender">AutoRAG</div><div class="message-content">Thinking…</div></div>';
    document.getElementById('chatMessages').appendChild(thinkingEl);
    scrollToBottom();

    var payload = {
      workspace_id: String(WORKSPACE_CONTEXT.workspace_id),
      session_id: String(currentSession.session_id),
      user_id: WORKSPACE_CONTEXT.user_id,
      message_id: 'cmsg_' + String(messageCounter).padStart(3, '0'),
      message: messageText
    };
    messageCounter++;

    var sendUrl = API_BASE_URL + API_ENDPOINTS.SEND_MESSAGE;
    fetch(sendUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (r) {
        return r.text().then(function (text) {
          var parsed = null;
          try { parsed = text.trim() ? JSON.parse(text) : null; } catch (_) { parsed = null; }
          if (!r.ok) {
            var err = new Error('HTTP ' + r.status + (text.trim() ? ': ' + text.trim() : ''));
            err.status = r.status;
            err.body = text;
            throw err;
          }
          return parsed;
        });
      })
      .then(function (d) {
        var responseText = (d && d.reply && typeof d.reply.text === 'string') ? d.reply.text : ((d && typeof d.response === 'string') ? d.response : 'No response.');
        var replyTimestamp = (d && d.reply && d.reply.timestamp) ? d.reply.timestamp : new Date().toISOString();
        var replyId = (d && d.reply && d.reply.id) ? d.reply.id : 'msg_' + Date.now();
        var thinkingPlaceholder = document.getElementById('thinkingPlaceholder');
        if (thinkingPlaceholder) thinkingPlaceholder.remove();

        var assistantMessage = { id: replyId, sender: 'assistant', text: responseText, timestamp: replyTimestamp };
        var key = getMessageStorageKey();
        var msgs = getMessagesForSession(key).slice();
        msgs.push(assistantMessage);
        setMessagesForSession(key, msgs);
        renderMessages();
      })
      .catch(function (e) {
        var thinkingPlaceholder = document.getElementById('thinkingPlaceholder');
        if (thinkingPlaceholder) thinkingPlaceholder.remove();
        if (e.message && e.message.indexOf('HTTP') === 0) {
          showErrorModal(e.body ? e.message + ' — ' + e.body : e.message);
        } else {
          showErrorModal('Network error. Please try again.');
        }
        var key = getMessageStorageKey();
        var failedMsgs = getMessagesForSession(key).slice().filter(function (m) { return m.id !== userMessage.id; });
        setMessagesForSession(key, failedMsgs);
        renderMessages();
      })
      .finally(function () {
        sendBtn.disabled = false;
        input.disabled = false;
        input.focus();
      });
  }
})();
