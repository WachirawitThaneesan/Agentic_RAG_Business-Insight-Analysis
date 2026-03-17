/**
 * Documents Component
 * Upload drag-and-drop zone + document list with processing status
 */

function renderDocuments(container) {
    container.innerHTML = `
        <div class="page-header">
            <h1>Documents</h1>
            <p>อัปโหลดและจัดการเอกสารการเงิน (PDF / Image)</p>
        </div>

        <!-- Upload Zone -->
        <div class="card" style="margin-bottom:24px">
            <div class="card-header">
                <div class="card-title">Upload Document</div>
            </div>
            <div class="upload-zone" id="upload-zone">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="17 8 12 3 7 8"/>
                    <line x1="12" y1="3" x2="12" y2="15"/>
                </svg>
                <p>Drag & drop files here or <strong style="color:var(--accent-primary-light)">browse</strong></p>
                <p class="upload-hint">Supports PDF, PNG, JPG, JPEG</p>
                <input type="file" id="file-input" accept=".pdf,.png,.jpg,.jpeg" multiple>
            </div>

            <!-- Upload progress -->
            <div id="upload-progress" style="margin-top:16px;display:none">
                <div class="loader">
                    <span class="loader-spinner"></span>
                    <span id="upload-status-text">Processing document...</span>
                </div>
            </div>
        </div>

        <!-- Document List -->
        <div class="card">
            <div class="card-header">
                <div>
                    <div class="card-title">All Documents</div>
                    <div class="card-subtitle" id="doc-count-label">Loading...</div>
                </div>
                <button class="btn btn-secondary btn-sm" onclick="loadDocumentList()">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                    Refresh
                </button>
            </div>
            <div id="doc-list">
                <div class="skeleton" style="height:200px;width:100%"></div>
            </div>
        </div>

        <div class="card" id="doc-table-viewer-card" style="margin-top:24px;display:none">
            <div class="card-header">
                <div>
                    <div class="card-title">Structured Tables</div>
                    <div class="card-subtitle" id="doc-table-viewer-subtitle">เลือกเอกสารเพื่อดูตารางที่ extract ได้</div>
                </div>
                <button class="btn btn-secondary btn-sm" onclick="closeDocTablesViewer()">Close</button>
            </div>
            <div id="doc-table-viewer-content"></div>
        </div>
    `;

    // Setup drag & drop
    const zone = document.getElementById('upload-zone');
    const input = document.getElementById('file-input');

    zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.classList.add('dragover');
    });

    zone.addEventListener('dragleave', () => {
        zone.classList.remove('dragover');
    });

    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('dragover');
        const files = e.dataTransfer.files;
        if (files.length > 0) uploadFiles(files);
    });

    input.addEventListener('change', (e) => {
        if (e.target.files.length > 0) uploadFiles(e.target.files);
    });

    loadDocumentList();
}

async function uploadFiles(files) {
    const progress = document.getElementById('upload-progress');
    const statusText = document.getElementById('upload-status-text');
    progress.style.display = 'block';

    for (let i = 0; i < files.length; i++) {
        statusText.textContent = `Processing ${files[i].name} (${i + 1}/${files.length})...`;

        try {
            const result = await api.upload('/documents/upload', files[i]);
            const modeLabel = result.large_file_mode ? ' • batch mode' : '';
            showToast(
                `${files[i].name}: ${result.chunks_created} chunks, ${result.tables_extracted} tables${modeLabel}`,
                'success'
            );
        } catch (e) {
            showToast(`Failed to process ${files[i].name}: ${e.message}`, 'error');
        }
    }

    progress.style.display = 'none';
    loadDocumentList();
}

async function loadDocumentList() {
    const listEl = document.getElementById('doc-list');
    const countLabel = document.getElementById('doc-count-label');

    try {
        const data = await api.get('/documents');
        const docs = data.documents || [];
        countLabel.textContent = `${docs.length} documents`;

        if (docs.length === 0) {
            listEl.innerHTML = `
                <div class="empty-state">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                        <polyline points="14 2 14 8 20 8"/>
                    </svg>
                    <h3>No documents yet</h3>
                    <p>Upload a PDF or image to get started with OCR extraction and chunking.</p>
                </div>
            `;
            return;
        }

        listEl.innerHTML = `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Filename</th>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Chunks</th>
                        <th>Table Rows</th>
                        <th>Date</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${docs.map(doc => `
                        <tr>
                            <td style="font-weight:500">${doc.filename}</td>
                            <td><span class="badge badge-primary">${doc.doc_type?.toUpperCase() || '—'}</span></td>
                            <td>
                                <span class="badge ${doc.status === 'completed' ? 'badge-success' : doc.status === 'failed' ? 'badge-danger' : 'badge-warning'}">
                                    ${doc.status}
                                </span>
                            </td>
                            <td>${doc.chunk_count}</td>
                            <td>${doc.table_row_count}</td>
                            <td style="font-size:0.8rem;color:var(--text-muted)">
                                ${doc.created_at ? new Date(doc.created_at).toLocaleDateString('th-TH') : '—'}
                            </td>
                            <td style="display:flex;gap:6px">
                                <button class="btn btn-secondary btn-sm" onclick="viewDocChunks(${doc.id})">Chunks</button>
                                <button class="btn btn-secondary btn-sm" onclick="viewDocTables(${doc.id})">Tables</button>
                                <button class="btn btn-danger btn-sm" onclick="deleteDoc(${doc.id})">Delete</button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    } catch (e) {
        listEl.innerHTML = `
            <div class="empty-state" style="padding:24px">
                <p style="color:var(--accent-danger)">Failed to load documents: ${e.message}</p>
            </div>
        `;
    }
}

function viewDocChunks(docId) {
    window.location.hash = `visualizer`;
    // Store selected doc ID for visualizer
    sessionStorage.setItem('selectedDocId', docId);
}

async function viewDocTables(docId) {
    const card = document.getElementById('doc-table-viewer-card');
    const subtitle = document.getElementById('doc-table-viewer-subtitle');
    const content = document.getElementById('doc-table-viewer-content');

    card.style.display = 'block';
    subtitle.textContent = 'กำลังโหลดตาราง...';
    content.innerHTML = `
        <div class="loader" style="padding:24px;justify-content:center">
            <span class="loader-spinner"></span>
            <span>Loading structured tables...</span>
        </div>
    `;
    card.scrollIntoView({ behavior: 'smooth', block: 'start' });

    try {
        const doc = await api.get(`/documents/${docId}`);
        const tables = (doc.structured_tables || []).map((table) => ({
            tableName: table.table_name || table.title || 'untitled_table',
            title: table.title || table.table_name || 'untitled_table',
            headers: table.headers || [],
            rows: (table.rows || []).map((row, index) => ({
                rowIndex: index,
                rowData: Object.fromEntries((table.headers || []).map((header, colIndex) => [header, row[colIndex] ?? ''])),
            })),
        }));
        const rawPages = (doc.raw_ocr_pages || []).slice().sort((a, b) => (a.page || 0) - (b.page || 0));
        const rawTables = (doc.raw_ocr_tables || []).slice().sort((a, b) => (a.table_index || 0) - (b.table_index || 0));
        const renderedRowCount = tables.reduce((sum, table) => sum + (table.rows?.length || 0), 0);

        subtitle.textContent = `${doc.filename} • ${tables.length} structured tables • ${rawPages.length} raw pages • ${rawTables.length} raw tables`;

        if (!tables.length && !rawPages.length && !rawTables.length) {
            content.innerHTML = `
                <div class="empty-state" style="padding:24px">
                    <h3>No OCR artifacts</h3>
                    <p>เอกสารนี้ยังไม่มีข้อมูล OCR ที่เปิดดูได้ หรือเป็นเอกสารที่ ingest ก่อนเปิด artifact pipeline</p>
                </div>
            `;
            return;
        }

        const structuredHtml = tables.length ? `
            <div style="margin-bottom:20px">
                <div style="font-size:0.88rem;font-weight:600;margin-bottom:10px;color:var(--text-primary)">Structured Tables</div>
                ${tables.map((table) => {
            const headers = table.headers || [];
            const visibleRows = table.rows;
            const tableHtml = `
                <div style="overflow:auto;border:1px solid var(--border-primary);border-radius:var(--radius-md)">
                    <table class="data-table" style="min-width:720px;margin-bottom:0">
                        <thead>
                            <tr>${headers.map((header) => `<th>${escapeDocHtml(header)}</th>`).join('')}</tr>
                        </thead>
                        <tbody>
                            ${visibleRows.map((row) => `
                                <tr>
                                    ${headers.map((header) => `<td>${escapeDocHtml(row.rowData?.[header] ?? '')}</td>`).join('')}
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            `;

            const csvPreview = [
                headers.join(','),
                ...visibleRows.map((row) => headers.map((header) => csvCell(row.rowData?.[header] ?? '')).join(',')),
            ].join('\n');

            return `
                <div style="padding:16px;background:var(--bg-tertiary);border-radius:var(--radius-md);margin-bottom:16px">
                    <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px">
                        <div>
                            <div style="font-weight:600">${escapeDocHtml(table.title || table.tableName)}</div>
                            <div style="font-size:0.78rem;color:var(--text-muted)">${table.rows.length} rows • ${headers.length} columns</div>
                        </div>
                        <span class="badge badge-info">Structured Table</span>
                    </div>
                    ${tableHtml}
                    <details style="margin-top:12px">
                        <summary style="cursor:pointer;font-size:0.82rem;color:var(--accent-primary-light)">ดู CSV preview</summary>
                        <pre style="margin-top:8px;padding:12px;background:var(--bg-secondary);border-radius:var(--radius-sm);white-space:pre-wrap;overflow:auto;font-size:0.76rem;color:var(--text-secondary)">${escapeDocHtml(csvPreview)}</pre>
                    </details>
                </div>
            `;
                }).join('')}
            </div>
        ` : '';

        const rawPagesHtml = rawPages.length ? `
            <div style="margin-bottom:20px">
                <div style="font-size:0.88rem;font-weight:600;margin-bottom:10px;color:var(--text-primary)">Raw OCR Pages</div>
                ${rawPages.map((page) => `
                    <details style="padding:16px;background:var(--bg-tertiary);border-radius:var(--radius-md);margin-bottom:16px" ${rawPages.length === 1 ? 'open' : ''}>
                        <summary style="cursor:pointer;font-weight:600">Page ${escapeDocHtml(page.page ?? '—')}</summary>
                        <pre style="margin-top:12px;padding:12px;background:var(--bg-secondary);border-radius:var(--radius-sm);white-space:pre-wrap;overflow:auto;font-size:0.76rem;color:var(--text-secondary)">${escapeDocHtml(page.markdown || '')}</pre>
                    </details>
                `).join('')}
            </div>
        ` : '';

        const rawTablesHtml = rawTables.length ? `
            <div>
                <div style="font-size:0.88rem;font-weight:600;margin-bottom:10px;color:var(--text-primary)">Raw OCR Tables</div>
                ${rawTables.map((table) => `
                    <div style="padding:16px;background:var(--bg-tertiary);border-radius:var(--radius-md);margin-bottom:16px">
                        <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px">
                            <div>
                                <div style="font-weight:600">${escapeDocHtml(table.title || `raw_table_${table.table_index}`)}</div>
                                <div style="font-size:0.78rem;color:var(--text-muted)">${(table.rows || []).length} rows • ${(table.headers || []).length} columns</div>
                            </div>
                            <span class="badge badge-primary">Raw OCR Table</span>
                        </div>
                        <details>
                            <summary style="cursor:pointer;font-size:0.82rem;color:var(--accent-primary-light)">ดู raw CSV</summary>
                            <pre style="margin-top:8px;padding:12px;background:var(--bg-secondary);border-radius:var(--radius-sm);white-space:pre-wrap;overflow:auto;font-size:0.76rem;color:var(--text-secondary)">${escapeDocHtml(table.csv_text || '')}</pre>
                        </details>
                    </div>
                `).join('')}
            </div>
        ` : '';

        content.innerHTML = `
            <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:16px">
                Structured rows: ${renderedRowCount}
            </div>
            ${structuredHtml}
            ${rawPagesHtml}
            ${rawTablesHtml}
        `;
    } catch (e) {
        subtitle.textContent = 'โหลดตารางไม่สำเร็จ';
        content.innerHTML = `
            <div class="empty-state" style="padding:24px">
                <p style="color:var(--accent-danger)">Failed to load tables: ${escapeDocHtml(e.message)}</p>
            </div>
        `;
    }
}

function closeDocTablesViewer() {
    const card = document.getElementById('doc-table-viewer-card');
    const content = document.getElementById('doc-table-viewer-content');
    card.style.display = 'none';
    content.innerHTML = '';
}

function escapeDocHtml(text) {
    return String(text ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function csvCell(value) {
    const text = String(value ?? '');
    if (/[",\n]/.test(text)) {
        return `"${text.replace(/"/g, '""')}"`;
    }
    return text;
}

async function deleteDoc(docId) {
    if (!confirm('Delete this document and all associated data?')) return;

    try {
        await api.delete(`/documents/${docId}`);
        showToast('Document deleted', 'success');
        loadDocumentList();
    } catch (e) {
        showToast(`Delete failed: ${e.message}`, 'error');
    }
}
