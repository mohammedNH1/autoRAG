/**
 * Workspace page — modal, filter tabs, search
 */

(function () {
    'use strict';

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
            if (nameError) nameError.textContent = 'Workspace name is required';
            nameInput.classList.add('has-error');
            return false;
        }
        if (name.length > 150) {
            if (nameError) nameError.textContent = 'Name must be 150 characters or fewer';
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

            setLoading(true);

            const payload = {
                name: nameInput.value.trim(),
                description: descInput ? descInput.value.trim() : '',
            };

            fetch('/workspace/create/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCSRFToken(),
                },
                body: JSON.stringify(payload),
            })
            .then(function (res) { return res.json().then(function (data) { return { ok: res.ok, data: data }; }); })
            .then(function (result) {
                if (!result.ok) {
                    if (nameError) nameError.textContent = result.data.error || 'Something went wrong';
                    nameInput.classList.add('has-error');
                    setLoading(false);
                    return;
                }
                window.location.href = '/questionnaire/?workspace_id=' + result.data.workspace_id;
            })
            .catch(function () {
                if (nameError) nameError.textContent = 'Network error. Please try again.';
                nameInput.classList.add('has-error');
                setLoading(false);
            });
        });
    }

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
