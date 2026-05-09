(function () {
    var ACCEPTED_EXTENSIONS = ['pdf','txt','csv','doc','docx','xls','xlsx','ppt','pptx'];
    var ICONS_BASE = '../../../components/icons';

    var MODAL_HTML =
        '<div class="upload-modal-overlay" id="uploadModalOverlay" style="display:none;">' +
            '<div class="upload-modal" id="uploadModal">' +
                '<div class="upload-modal__header">' +
                    '<div>' +
                        '<h2 class="upload-modal__title">File Upload</h2>' +
                        '<p class="upload-modal__subtitle">Choose a file and upload securely to proceed.</p>' +
                    '</div>' +
                    '<button class="upload-modal__close" type="button" id="uploadModalClose" aria-label="Close">' +
                        '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
                            '<path d="M18 6L6 18M6 6l12 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
                        '</svg>' +
                    '</button>' +
                '</div>' +
                '<div class="upload-modal__dropzone" id="uploadDropzone">' +
                    '<div class="upload-modal__dropzone-content">' +
                        '<img class="upload-modal__dropzone-illustration" src="' + ICONS_BASE + '/Document%20upload%20icon.svg" alt="Upload documents" width="100" height="104">' +
                        '<p class="upload-modal__dropzone-title">Drag and drop your files</p>' +
                        '<p class="upload-modal__dropzone-formats">PDF, TXT, CSV, DOC, DOCX, XLS, XLSX, PPT, and PPTX formats.</p>' +
                        '<div class="upload-modal__dropzone-actions">' +
                            '<button class="upload-modal__action-btn" type="button" id="uploadPickerBtn">' +
                                '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
                                    '<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
                                '</svg>' +
                                'Upload' +
                            '</button>' +
                            '<button class="upload-modal__action-btn" type="button" id="textInputBtn">' +
                                '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
                                    '<rect x="3" y="3" width="18" height="18" rx="2" stroke="currentColor" stroke-width="2"/>' +
                                    '<path d="M8 8h8M8 12h8M8 16h4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>' +
                                '</svg>' +
                                'Text Input' +
                            '</button>' +
                        '</div>' +
                    '</div>' +
                '</div>' +
                '<div class="upload-modal__files" id="uploadFilesList" style="display:none;">' +
                    '<h3 class="upload-modal__files-title">Uploaded Files</h3>' +
                    '<div class="upload-modal__file-list" id="uploadFileList"></div>' +
                '</div>' +
                '<div class="upload-modal__footer">' +
                    '<button class="upload-modal__btn-cancel" type="button" id="uploadModalCancel">Cancel</button>' +
                    '<button class="upload-modal__btn-submit" type="button" id="uploadModalSubmit" disabled>Submit</button>' +
                '</div>' +
            '</div>' +
            '<input type="file" id="uploadFileInput" multiple accept=".pdf,.txt,.csv,.doc,.docx,.xls,.xlsx,.ppt,.pptx" style="display:none;">' +
        '</div>';

    function init() {
        var container = document.getElementById('uploadModalContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'uploadModalContainer';
            document.body.appendChild(container);
        }
        container.innerHTML = MODAL_HTML;

        var overlay      = document.getElementById('uploadModalOverlay');
        var modal        = document.getElementById('uploadModal');
        var closeBtn     = document.getElementById('uploadModalClose');
        var cancelBtn    = document.getElementById('uploadModalCancel');
        var submitBtn    = document.getElementById('uploadModalSubmit');
        var dropzone     = document.getElementById('uploadDropzone');
        var pickerBtn    = document.getElementById('uploadPickerBtn');
        var textInputBtn = document.getElementById('textInputBtn');
        var fileInput    = document.getElementById('uploadFileInput');
        var filesSection = document.getElementById('uploadFilesList');
        var fileListEl   = document.getElementById('uploadFileList');

        // Each entry: { id, name, size, ext, file (File object), progress, timer }
        var files = [];
        var fileIdCounter = 0;
        var dragCounter   = 0;

        function getFileExtension(name) {
            var parts = name.split('.');
            return parts.length > 1 ? parts.pop().toLowerCase() : '';
        }

        function getFileIconName(ext) {
            if (ext === 'pdf')              return 'pdf';
            if (ext === 'doc' || ext === 'docx') return 'doc';
            if (ext === 'txt')              return 'txt';
            return 'file';
        }

        function formatFileSize(bytes) {
            if (bytes < 1024)              return bytes + 'B';
            if (bytes < 1024 * 1024)       return (bytes / 1024).toFixed(1) + 'KB';
            return (bytes / (1024 * 1024)).toFixed(1) + 'MB';
        }

        function getCsrf() {
            return (document.cookie.match(/(^| )csrftoken=([^;]+)/) || [])[2] || '';
        }

        function openModal() {
            overlay.style.display = '';
            document.body.style.overflow = 'hidden';
        }

        function closeModal() {
            overlay.style.display = 'none';
            document.body.style.overflow = '';
            resetModal();
        }

        function resetModal() {
            files.forEach(function (f) { if (f.timer) clearInterval(f.timer); });
            files         = [];
            fileIdCounter = 0;
            dragCounter   = 0;
            filesSection.style.display = 'none';
            fileListEl.innerHTML       = '';
            submitBtn.disabled         = true;
            submitBtn.textContent      = 'Submit';
            dropzone.classList.remove('dragover');
        }

        function updateSubmitState() {
            if (files.length === 0) { submitBtn.disabled = true; return; }
            submitBtn.disabled = !files.every(function (f) { return f.progress >= 100; });
        }

        function renderFileRow(fileObj) {
            var row = document.createElement('div');
            row.className       = 'upload-modal__file-row';
            row.dataset.fileId  = fileObj.id;

            var iconName = getFileIconName(fileObj.ext);
            var sizeStr  = formatFileSize(fileObj.size);

            row.innerHTML =
                '<div class="upload-modal__file-icon">' +
                    '<img src="' + ICONS_BASE + '/' + iconName + '.svg" alt="' + fileObj.ext + '" width="32" height="32">' +
                '</div>' +
                '<div class="upload-modal__file-info">' +
                    '<span class="upload-modal__file-name">' + fileObj.name + '</span>' +
                    '<span class="upload-modal__file-status" data-status-id="' + fileObj.id + '">' +
                        sizeStr + ' | 0% • Ready' +
                    '</span>' +
                '</div>' +
                '<button class="upload-modal__file-delete" type="button" data-delete-id="' + fileObj.id + '" aria-label="Remove file">' +
                    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
                        '<path d="M3 6h18M8 6V4a1 1 0 011-1h6a1 1 0 011 1v2M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>' +
                    '</svg>' +
                '</button>';

            return row;
        }

        function updateFileStatus(fileObj, text, done) {
            var statusEl = fileListEl.querySelector('[data-status-id="' + fileObj.id + '"]');
            if (!statusEl) return;
            statusEl.textContent = text;
            if (done) {
                statusEl.classList.add('upload-modal__file-status--done');
            } else {
                statusEl.classList.remove('upload-modal__file-status--done');
            }
        }

        function addFiles(rawFiles) {
            var added = false;
            for (var i = 0; i < rawFiles.length; i++) {
                var f   = rawFiles[i];
                var ext = getFileExtension(f.name);
                if (ACCEPTED_EXTENSIONS.indexOf(ext) === -1) continue;

                var fileObj = {
                    id:       ++fileIdCounter,
                    name:     f.name,
                    size:     f.size,
                    ext:      ext,
                    file:     f,       // keep the real File object for FormData
                    progress: 100,     // ready immediately — server does the real work
                    timer:    null
                };
                files.push(fileObj);
                var row = renderFileRow(fileObj);
                fileListEl.appendChild(row);
                updateFileStatus(fileObj, formatFileSize(fileObj.size) + ' | Ready', true);
                added = true;
            }

            if (added) {
                filesSection.style.display = '';
                updateSubmitState();
            }
        }

        function removeFile(id) {
            var idx = -1;
            for (var i = 0; i < files.length; i++) {
                if (files[i].id === id) { idx = i; break; }
            }
            if (idx === -1) return;
            if (files[idx].timer) clearInterval(files[idx].timer);
            files.splice(idx, 1);

            var row = fileListEl.querySelector('[data-file-id="' + id + '"]');
            if (row) row.remove();

            if (files.length === 0) filesSection.style.display = 'none';
            updateSubmitState();
        }

        // ── Submit: POST each file to the server ────────────────────────────
        submitBtn.addEventListener('click', function () {
            if (submitBtn.disabled || files.length === 0) return;

            var workspaceId = (typeof window.WORKSPACE_ID !== 'undefined' && window.WORKSPACE_ID !== '')
                ? window.WORKSPACE_ID
                : null;
            if (!workspaceId) {
                alert('Workspace not loaded. Please refresh the page.');
                return;
            }

            submitBtn.disabled    = true;
            submitBtn.textContent = 'Uploading…';

            var csrf    = getCsrf();
            var pending = files.slice(); // snapshot
            var errors  = [];

            function uploadNext(index) {
                if (index >= pending.length) {
                    // All done
                    if (errors.length > 0) {
                        alert('Some files failed to upload:\n' + errors.join('\n'));
                    }
                    closeModal();
                    window.location.reload();
                    return;
                }

                var fileObj  = pending[index];
                var formData = new FormData();
                formData.append('file', fileObj.file, fileObj.name);
                formData.append('workspace_id', workspaceId);

                updateFileStatus(
                    fileObj,
                    formatFileSize(fileObj.size) + ' | Uploading…',
                    false
                );

                fetch('/documents/upload/', {
                    method:  'POST',
                    headers: { 'X-CSRFToken': csrf },
                    body:    formData,
                })
                .then(function (res) { return res.json().then(function (data) { return { ok: res.ok, data: data }; }); })
                .then(function (result) {
                    if (result.ok) {
                        updateFileStatus(
                            fileObj,
                            formatFileSize(fileObj.size) + ' | Indexed (' + (result.data.chunks || '?') + ' chunks)',
                            true
                        );
                    } else {
                        var msg = (result.data && result.data.error) ? result.data.error : 'Unknown error';
                        updateFileStatus(fileObj, formatFileSize(fileObj.size) + ' | Failed: ' + msg, false);
                        errors.push(fileObj.name + ': ' + msg);
                    }
                    uploadNext(index + 1);
                })
                .catch(function (err) {
                    updateFileStatus(fileObj, formatFileSize(fileObj.size) + ' | Network error', false);
                    errors.push(fileObj.name + ': Network error');
                    uploadNext(index + 1);
                });
            }

            uploadNext(0);
        });

        // ── Text Input button → redirect to text input page ─────────────────
        textInputBtn.addEventListener('click', function () {
            var workspaceId = (typeof window.WORKSPACE_ID !== 'undefined' && window.WORKSPACE_ID !== '')
                ? window.WORKSPACE_ID
                : null;
            if (!workspaceId) {
                alert('Workspace not loaded. Please refresh the page.');
                return;
            }
            window.location.href = '/documents/' + workspaceId + '/text-input/';
        });

        // ── Drag & drop ──────────────────────────────────────────────────────
        closeBtn.addEventListener('click', closeModal);
        cancelBtn.addEventListener('click', closeModal);

        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) closeModal();
        });

        modal.addEventListener('click', function (e) { e.stopPropagation(); });

        dropzone.addEventListener('dragenter', function (e) {
            e.preventDefault();
            dragCounter++;
            dropzone.classList.add('dragover');
        });

        dropzone.addEventListener('dragover', function (e) { e.preventDefault(); });

        dropzone.addEventListener('dragleave', function (e) {
            e.preventDefault();
            dragCounter--;
            if (dragCounter <= 0) {
                dragCounter = 0;
                dropzone.classList.remove('dragover');
            }
        });

        dropzone.addEventListener('drop', function (e) {
            e.preventDefault();
            dragCounter = 0;
            dropzone.classList.remove('dragover');
            if (e.dataTransfer.files.length > 0) {
                addFiles(e.dataTransfer.files);
            }
        });

        pickerBtn.addEventListener('click', function () { fileInput.click(); });

        fileInput.addEventListener('change', function () {
            if (fileInput.files.length > 0) addFiles(fileInput.files);
            fileInput.value = '';
        });

        fileListEl.addEventListener('click', function (e) {
            var deleteBtn = e.target.closest('[data-delete-id]');
            if (deleteBtn) removeFile(parseInt(deleteBtn.dataset.deleteId));
        });

        // ── Open modal from upload button ────────────────────────────────────
        var uploadBtn = document.getElementById('uploadBtn');
        if (uploadBtn) uploadBtn.addEventListener('click', openModal);

        window.openUploadModal = openModal;
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
