/**
 * Workspace page — modal, filter tabs, search
 */

(function () {
    'use strict';

    var _t = (typeof gettext === 'function') ? gettext : function (s) { return s; };
    var _interp = (typeof interpolate === 'function') ? interpolate : function (fmt, obj) {
        return fmt.replace(/%\(\w+\)s/g, function (m) {
            var k = m.slice(2, -2);
            return obj[k] != null ? obj[k] : m;
        });
    };

    // ── Modal elements ────────────────────────────────────────
    const overlay      = document.getElementById('createModal');
    const form         = document.getElementById('createWorkspaceForm');
    const nameInput    = document.getElementById('workspaceName');
    const descInput    = document.getElementById('workspaceDescription');
    const nameError    = document.getElementById('nameError');
    const submitBtn    = document.getElementById('modalSubmitBtn');
    const btnLabel     = submitBtn ? submitBtn.querySelector('.btn-label') : null;
    const btnLoading   = submitBtn ? submitBtn.querySelector('.btn-loading') : null;
    const nameCounter  = document.getElementById('nameCounter');
    const modalTitle   = document.getElementById('modalTitle');

    // ── RAG questionnaire stage elements ──────────────────────
    const ragStage     = document.getElementById('ragStage');
    const ragForm      = document.getElementById('ragForm');
    const ragStepNum   = document.getElementById('ragStepNum');
    const ragPrevBtn   = document.getElementById('ragPrevBtn');
    const ragNextBtn   = document.getElementById('ragNextBtn');
    const ragSubmitBtn = document.getElementById('ragSubmitBtn');
    const ragError     = document.getElementById('ragError');
    const ragSuccess   = document.getElementById('ragSuccess');
    const ragSubmitLabel   = ragSubmitBtn ? ragSubmitBtn.querySelector('.btn-label') : null;
    const ragSubmitLoading = ragSubmitBtn ? ragSubmitBtn.querySelector('.btn-loading') : null;

    const RAG_TOTAL = 8;
    let ragCurrent  = 1;
    let pendingWorkspace = null;  // { name, description, image: File } collected at stage 1, sent with stage 2 submit

    // ── Image picker ──────────────────────────────────────────
    const imageInput   = document.getElementById('workspaceImage');
    const imageBtn     = document.getElementById('wsImageBtn');
    const imagePreview = document.getElementById('wsImagePreview');
    const imageError   = document.getElementById('imageError');

    function clearImageError() {
        if (imageError) imageError.textContent = '';
    }

    if (imageBtn && imageInput) {
        imageBtn.addEventListener('click', function () { imageInput.click(); });
    }

    if (imageInput) {
        imageInput.addEventListener('change', function () {
            clearImageError();
            const file = imageInput.files && imageInput.files[0];
            if (!file) {
                if (imagePreview) imagePreview.classList.remove('has-image');
                return;
            }
            if (!file.type.startsWith('image/')) {
                if (imageError) imageError.textContent = _t('File must be an image.');
                imageInput.value = '';
                return;
            }
            if (file.size > 5 * 1024 * 1024) {
                if (imageError) imageError.textContent = _t('Image must be 5 MB or smaller.');
                imageInput.value = '';
                return;
            }
            if (imagePreview) {
                const reader = new FileReader();
                reader.onload = function (e) {
                    imagePreview.style.backgroundImage = 'url(' + JSON.stringify(e.target.result) + ')';
                    imagePreview.classList.add('has-image');
                };
                reader.readAsDataURL(file);
            }
        });
    }

    const openTriggers = [
        document.getElementById('createWorkspaceBtn'),
        document.getElementById('emptyCreateBtn'),
    ];

    const closeTriggers = [
        document.getElementById('modalCloseBtn'),
        document.getElementById('modalCancelBtn'),
    ];

    function openModal() {
        if (!overlay) return;
        overlay.classList.add('visible');
        if (nameInput) nameInput.focus();
        document.body.style.overflow = 'hidden';
    }

    function closeModal() {
        if (!overlay) return;
        overlay.classList.remove('visible');
        document.body.style.overflow = '';
        resetForm();
    }

    function resetForm() {
        if (!form) return;
        form.reset();
        clearErrors();
        setLoading(false);
        if (nameCounter) nameCounter.textContent = '0 / 150';
        if (imagePreview) {
            imagePreview.style.backgroundImage = '';
            imagePreview.classList.remove('has-image');
        }
        clearImageError();
        resetRagStage();
        showStage('name');
    }

    function showStage(stage) {
        const isName    = stage === 'name';
        const isRag     = stage === 'rag';
        const isSuccess = stage === 'success';

        if (form)       form.hidden       = !isName;
        if (ragStage)   ragStage.hidden   = !isRag;
        if (ragSuccess) ragSuccess.hidden = !isSuccess;

        if (modalTitle) {
            if (isName)         modalTitle.textContent = _t('Create Workspace');
            else if (isRag)     modalTitle.textContent = _t('Configure RAG');
            else if (isSuccess) modalTitle.textContent = _t('Done');
        }
    }

    function resetRagStage() {
        ragCurrent = 1;
        pendingWorkspace = null;
        if (ragForm) {
            ragForm.querySelectorAll('input[type="hidden"]').forEach(function (i) { i.value = ''; });
            ragForm.querySelectorAll('.rag-option.is-selected').forEach(function (b) { b.classList.remove('is-selected'); });
        }
        if (ragError) { ragError.hidden = true; ragError.textContent = ''; }
        setRagSubmitLoading(false);
        updateRagUI();
    }

    function updateRagUI() {
        if (!ragForm) return;
        ragForm.querySelectorAll('.rag-question').forEach(function (q) {
            const idx = parseInt(q.getAttribute('data-q'), 10);
            q.classList.toggle('is-active', idx === ragCurrent);
        });
        if (ragStepNum)   ragStepNum.textContent = String(ragCurrent);
        if (ragPrevBtn)   ragPrevBtn.style.visibility = ragCurrent === 1 ? 'hidden' : '';
        if (ragNextBtn)   ragNextBtn.hidden   = ragCurrent === RAG_TOTAL;
        if (ragSubmitBtn) ragSubmitBtn.hidden = ragCurrent !== RAG_TOTAL;
    }

    function currentRagAnswerFilled() {
        if (!ragForm) return false;
        const q = ragForm.querySelector('.rag-question[data-q="' + ragCurrent + '"]');
        if (!q) return false;
        const input = q.querySelector('input[type="hidden"]');
        return !!(input && input.value);
    }

    function setRagSubmitLoading(loading) {
        if (!ragSubmitBtn) return;
        ragSubmitBtn.disabled = loading;
        if (ragNextBtn) ragNextBtn.disabled = loading;
        if (ragPrevBtn) ragPrevBtn.disabled = loading;
        if (ragSubmitLabel)   ragSubmitLabel.style.display   = loading ? 'none' : '';
        if (ragSubmitLoading) ragSubmitLoading.style.display = loading ? 'inline' : 'none';
    }

    openTriggers.forEach(function (el) { if (el) el.addEventListener('click', openModal); });
    closeTriggers.forEach(function (el) { if (el) el.addEventListener('click', closeModal); });

    if (overlay) {
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) closeModal();
        });
    }

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && overlay && overlay.classList.contains('visible')) {
            closeModal();
        }
    });

    // ── Validation / submission ───────────────────────────────
    function clearErrors() {
        if (nameError) nameError.textContent = '';
        if (nameInput) nameInput.classList.remove('has-error');
        if (descInput) descInput.classList.remove('has-error');
    }

    function validate() {
        clearErrors();
        if (!nameInput) return false;

        const name = nameInput.value.trim();
        if (!name) {
            if (nameError) nameError.textContent = _t('Workspace name is required');
            nameInput.classList.add('has-error');
            return false;
        }
        if (name.length > 150) {
            if (nameError) nameError.textContent = _t('Name must be 150 characters or fewer');
            nameInput.classList.add('has-error');
            return false;
        }
        return true;
    }

    if (nameInput) {
        nameInput.addEventListener('input', function () {
            if (nameInput.classList.contains('has-error')) {
                if (nameError) nameError.textContent = '';
                nameInput.classList.remove('has-error');
            }
            if (nameCounter) nameCounter.textContent = nameInput.value.length + ' / 150';
        });
    }

    function setLoading(loading) {
        if (!submitBtn) return;
        submitBtn.disabled = loading;
        if (btnLabel)   btnLabel.style.display   = loading ? 'none' : '';
        if (btnLoading) btnLoading.style.display = loading ? 'inline' : 'none';
    }

    function getCSRFToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) return meta.getAttribute('content');
        const cookie = document.cookie.split(';').find(function (c) {
            return c.trim().startsWith('csrftoken=');
        });
        return cookie ? cookie.split('=')[1] : '';
    }

    if (form) {
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            if (!validate()) return;

            // Image is optional — null is fine, we just won't attach a file.
            const file = imageInput && imageInput.files && imageInput.files[0] || null;

            // Defer creation until the questionnaire is fully answered.
            pendingWorkspace = {
                name: nameInput.value.trim(),
                description: descInput ? descInput.value.trim() : '',
                image: file,
            };
            showStage('rag');
            updateRagUI();
        });
    }

    // ── RAG questionnaire handlers ────────────────────────────
    if (ragForm) {
        ragForm.querySelectorAll('.rag-option').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                const q = btn.closest('.rag-question');
                if (!q) return;
                q.querySelectorAll('.rag-option').forEach(function (b) { b.classList.remove('is-selected'); });
                btn.classList.add('is-selected');
                const input = q.querySelector('input[type="hidden"]');
                if (input) input.value = btn.getAttribute('data-value') || '';
                if (ragError) { ragError.hidden = true; ragError.textContent = ''; }
            });
        });
    }

    if (ragNextBtn) {
        ragNextBtn.addEventListener('click', function () {
            if (!currentRagAnswerFilled()) {
                if (ragError) {
                    ragError.textContent = _t('Please select an answer');
                    ragError.hidden = false;
                }
                return;
            }
            if (ragCurrent < RAG_TOTAL) ragCurrent++;
            updateRagUI();
        });
    }

    if (ragPrevBtn) {
        ragPrevBtn.addEventListener('click', function () {
            if (ragCurrent > 1) ragCurrent--;
            updateRagUI();
        });
    }

    if (ragSubmitBtn) {
        ragSubmitBtn.addEventListener('click', function () {
            if (!currentRagAnswerFilled()) {
                if (ragError) {
                    ragError.textContent = _t('Please select an answer');
                    ragError.hidden = false;
                }
                return;
            }
            if (!pendingWorkspace || !pendingWorkspace.name) {
                if (ragError) {
                    ragError.textContent = _t('Workspace details missing. Please restart.');
                    ragError.hidden = false;
                }
                return;
            }

            const data = new FormData(ragForm);
            const chunkingMap = {
                'slide_deck':          'slide deck',
                'meeting_notes':       'meeting notes',
                'article':             'article',
                'research_paper':      'research paper',
                'policy':              'policy',
                'books_long_manuals':  'books or long manuals',
                'undecided':           'undecided'
            };
            const chunkingRaw = data.get('chunking_strategy');

            const payload = new FormData();
            payload.append('name',              pendingWorkspace.name);
            payload.append('description',       pendingWorkspace.description);
            if (pendingWorkspace.image) {
                payload.append('workspace_image', pendingWorkspace.image);
            }
            payload.append('language',          data.get('language') || '');
            payload.append('use_case',          data.get('speed_quality') || '');
            payload.append('reference',         data.get('reference') || '');
            payload.append('temperature',       data.get('temperature') || '');
            payload.append('top_p',             data.get('top_p') || '');
            payload.append('metadata',          data.get('document_info') || '');
            payload.append('chunking_strategy', chunkingMap[chunkingRaw] || chunkingRaw || '');

            setRagSubmitLoading(true);
            if (ragError) { ragError.hidden = true; ragError.textContent = ''; }

            fetch('/submit-answers/', {
                method: 'POST',
                headers: {
                    // Let the browser set Content-Type with the multipart boundary.
                    'X-CSRFToken': getCSRFToken(),
                },
                body: payload,
            })
            .then(function (res) { return res.json().then(function (data) { return { ok: res.ok, data: data }; }); })
            .then(function (result) {
                if (!result.ok || result.data.status !== 'success') {
                    if (ragError) {
                        ragError.textContent = (result.data && result.data.error) || _t('Something went wrong');
                        ragError.hidden = false;
                    }
                    setRagSubmitLoading(false);
                    return;
                }
                const newId = result.data.workspace_id;
                showStage('success');
                setTimeout(function () {
                    window.location.href = '/workspace/' + newId + '/';
                }, 1200);
            })
            .catch(function () {
                if (ragError) {
                    ragError.textContent = _t('Network error. Please try again.');
                    ragError.hidden = false;
                }
                setRagSubmitLoading(false);
            });
        });
    }

    // ── Avatar dropdown (Profile / Sign out) ─────────────────
    (function () {
        const wrap = document.getElementById('wsAvatarWrap');
        const btn  = document.getElementById('wsAvatarBtn');
        const menu = document.getElementById('wsAvatarMenu');
        if (!wrap || !btn || !menu) return;

        function close() {
            menu.hidden = true;
            btn.setAttribute('aria-expanded', 'false');
        }
        function open() {
            menu.hidden = false;
            btn.setAttribute('aria-expanded', 'true');
        }

        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            if (menu.hidden) open();
            else close();
        });

        menu.addEventListener('click', function (e) { e.stopPropagation(); });

        document.addEventListener('click', function (e) {
            if (menu.hidden) return;
            if (wrap.contains(e.target)) return;
            close();
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') close();
        });
    })();

    // ── Profile back-path memory ──────────────────────────────
    document.querySelectorAll('a[href*="/accounts/profile"]').forEach(function (a) {
        a.addEventListener('click', function () {
            try {
                if (location.pathname.indexOf('/accounts/profile') !== 0) {
                    sessionStorage.setItem('autorag.profileBack', location.pathname + location.search);
                }
            } catch (_) {}
        });
    });

    // ── Notification bell + invitations dropdown (per-instance) ─
    function escapeHtml(str) {
        return String(str || '').replace(/[&<>"']/g, function (c) {
            return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
        });
    }

    function initNotifBell(wrap) {
        const bell     = wrap.querySelector('.ws-bell');
        const dropdown = wrap.querySelector('.ws-notif');
        const list     = wrap.querySelector('.ws-notif__list');
        const emptyEl  = wrap.querySelector('.ws-notif__empty');
        const loading  = wrap.querySelector('.ws-notif__loading');

        if (!bell || !dropdown || !list) return;

        let loaded = false;

        function updateBellDot(count) {
            const existing = bell.querySelector('.ws-bell__dot');
            if (count > 0) {
                bell.classList.add('has-notifications');
                if (!existing) {
                    const dot = document.createElement('span');
                    dot.className = 'ws-bell__dot';
                    dot.setAttribute('aria-hidden', 'true');
                    bell.appendChild(dot);
                }
            } else {
                bell.classList.remove('has-notifications');
                if (existing) existing.remove();
            }
        }

        function render(invites) {
            list.innerHTML = '';
            if (loading) loading.hidden = true;
            if (!invites || invites.length === 0) {
                if (emptyEl) emptyEl.hidden = false;
                updateBellDot(0);
                return;
            }
            if (emptyEl) emptyEl.hidden = true;

            invites.forEach(function (inv) {
                const row = document.createElement('div');
                row.className = 'ws-notif__item';
                row.setAttribute('data-invite-id', inv.invitation_id);
                var inviteLine = _interp(
                    _t('%(name)s invited you to %(workspace)s'),
                    {
                        name: escapeHtml(inv.invited_by),
                        workspace: '<strong>' + escapeHtml(inv.workspace_name) + '</strong>'
                    },
                    true
                );
                var roleLine = _interp(_t('Role: %(role)s'), { role: escapeHtml(inv.role_label) }, true);
                row.innerHTML =
                    '<div class="ws-notif__item-body">' +
                        '<p class="ws-notif__item-title">' + inviteLine + '</p>' +
                        '<p class="ws-notif__item-sub">' + roleLine + '</p>' +
                    '</div>' +
                    '<div class="ws-notif__item-actions">' +
                        '<button type="button" class="ws-notif__btn ws-notif__btn--accept" data-action="accept">' + _t('Accept') + '</button>' +
                        '<button type="button" class="ws-notif__btn ws-notif__btn--reject" data-action="reject">' + _t('Reject') + '</button>' +
                    '</div>';
                list.appendChild(row);
            });
            updateBellDot(invites.length);
        }

        function load() {
            if (loading) loading.hidden = false;
            if (emptyEl) emptyEl.hidden = true;
            list.innerHTML = '';

            fetch('/workspace/invitations/', {
                method: 'GET',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin',
            })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                loaded = true;
                render(data.invitations || []);
            })
            .catch(function () {
                if (loading) loading.hidden = true;
                list.innerHTML = '<div class="ws-notif__error">' + _t('Failed to load.') + '</div>';
            });
        }

        function open() {
            dropdown.hidden = false;
            bell.setAttribute('aria-expanded', 'true');
            if (!loaded) load();
            else if (list.children.length === 0) load();
        }

        function close() {
            dropdown.hidden = true;
            bell.setAttribute('aria-expanded', 'false');
        }

        bell.addEventListener('click', function (e) {
            e.stopPropagation();
            // close any other open dropdown
            document.querySelectorAll('.ws-bell-wrap .ws-notif').forEach(function (d) {
                if (d !== dropdown) d.hidden = true;
            });
            if (dropdown.hidden) open();
            else close();
        });

        dropdown.addEventListener('click', function (e) { e.stopPropagation(); });

        document.addEventListener('click', function (e) {
            if (dropdown.hidden) return;
            if (wrap.contains(e.target)) return;
            close();
        });

        list.addEventListener('click', function (e) {
            const btn = e.target.closest('button[data-action]');
            if (!btn) return;
            const row = btn.closest('[data-invite-id]');
            if (!row) return;
            const inviteId = row.getAttribute('data-invite-id');
            const action   = btn.getAttribute('data-action');
            const url = '/workspace/invitations/' + inviteId + '/' + action + '/';

            row.querySelectorAll('button').forEach(function (b) { b.disabled = true; });

            fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCSRFToken(),
                },
                credentials: 'same-origin',
            })
            .then(function (res) { return res.json().then(function (data) { return { ok: res.ok, data: data }; }); })
            .then(function (result) {
                if (!result.ok) {
                    row.querySelectorAll('button').forEach(function (b) { b.disabled = false; });
                    return;
                }
                row.remove();
                const remaining = list.querySelectorAll('[data-invite-id]').length;
                updateBellDot(remaining);
                if (remaining === 0 && emptyEl) emptyEl.hidden = false;
                if (action === 'accept') {
                    // refresh page so the new workspace appears in the grid
                    window.location.reload();
                }
            })
            .catch(function () {
                row.querySelectorAll('button').forEach(function (b) { b.disabled = false; });
            });
        });
    }

    document.querySelectorAll('.ws-bell-wrap').forEach(initNotifBell);

    // ── Filter tabs (All / Owned / Joined) ────────────────────
    const tabs   = document.querySelectorAll('.ws-tab');
    const grid   = document.getElementById('workspaceGrid');
    const search = document.getElementById('workspaceSearch');

    let activeFilter = 'all';
    let activeQuery  = '';

    function applyFilters() {
        if (!grid) return;
        const cards = grid.querySelectorAll('.ws-card');
        cards.forEach(function (card) {
            const role = card.getAttribute('data-role') || '';
            const name = card.getAttribute('data-name') || '';

            const filterOk = activeFilter === 'all' || role === activeFilter;
            const queryOk  = !activeQuery || name.indexOf(activeQuery) !== -1;

            card.style.display = (filterOk && queryOk) ? '' : 'none';
        });
    }

    tabs.forEach(function (tab) {
        tab.addEventListener('click', function () {
            tabs.forEach(function (t) {
                t.classList.remove('is-active');
                t.setAttribute('aria-selected', 'false');
            });
            tab.classList.add('is-active');
            tab.setAttribute('aria-selected', 'true');
            activeFilter = tab.getAttribute('data-filter') || 'all';
            applyFilters();
        });
    });

    const clearBtn = document.getElementById('searchClearBtn');

    function updateClearBtn() {
        if (!clearBtn) return;
        clearBtn.classList.toggle('is-visible', !!(search && search.value.length > 0));
    }

    if (search) {
        search.addEventListener('input', function () {
            activeQuery = search.value.trim().toLowerCase();
            applyFilters();
            updateClearBtn();
        });
    }

    if (clearBtn) {
        clearBtn.addEventListener('click', function () {
            if (!search) return;
            search.value = '';
            activeQuery  = '';
            applyFilters();
            updateClearBtn();
            search.focus();
        });
    }
})();
