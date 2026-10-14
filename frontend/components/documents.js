/**
 * Documents Component
 * Upload drag-and-drop zone + document register with processing status
 */

let documentListRefreshTimer = null;
let uploadListPollingTimer = null;
let ocrViewerState = { docId: null, page: 1, total: 0 };
let docFilter = 'all';
let docCache = [];

function renderDocuments(container) {
    container.innerHTML = `
        <section class="scrape-hero">
            ${AURORA_HTML.replace('class="aurora"', 'class="aurora is-paper"')}
            <h1 class="hero-title" lang="en">Drop in a report.<span class="line-2">We read it down to the last table.</span></h1>
            <p class="hero-sub">อัปโหลด PDF หรือรูปภาพ ระบบจะ OCR ทีละหน้า แยกตาราง แล้วแบ่งเนื้อหาเป็นช่วง ๆ ให้ถามได้ทันที</p>
        </section>

        <section class="intake" aria-label="Upload">
            <div class="dropzone" id="upload-zone">
                <div class="paper-stack" aria-hidden="true">
                    <span class="sheet sheet-3"></span>
                    <span class="sheet sheet-2"></span>
                    <span class="sheet sheet-1"><i></i><i class="hl"></i><i></i><i class="short"></i></span>
                </div>
                <strong>ลากไฟล์มาวางที่นี่ หรือ <u>เลือกไฟล์</u></strong>
                <span class="hint">PDF, PNG, JPG อัปโหลดได้หลายไฟล์พร้อมกัน</span>
                <input type="file" id="file-input" accept=".pdf,.png,.jpg,.jpeg" multiple aria-label="เลือกไฟล์เอกสาร">
                <div class="upload-progress" id="upload-progress" style="display:none" role="status">
                    <div class="progress-line"></div>
                    <p class="loading-text" id="upload-status-text">Processing document...</p>
                </div>
            </div>
            <dl class="crawl-stats library-stats" id="library-stats">
                <div><dt>เอกสาร</dt><dd><b id="lib-docs">-</b></dd></div>
                <div><dt>Chunks</dt><dd><b id="lib-chunks">-</b></dd></div>
                <div><dt>แถวตาราง</dt><dd><b id="lib-rows">-</b></dd></div>
                <div><dt>หน้าที่ OCR ไม่ผ่าน</dt><dd><b id="lib-failed">-</b></dd></div>
            </dl>
        </section>

        <section class="section" aria-labelledby="doc-list-title">
            <div class="section-head">
                <h2 class="section-title" id="doc-list-title">ทะเบียนเอกสาร <span class="section-note" id="doc-count-label"></span></h2>
                <div class="register-tools">
                    <div class="segmented" role="group" aria-label="กรองตามประเภท" id="doc-filter">
                        <button type="button" data-filter="all" aria-pressed="true">ทั้งหมด</button>
                        <button type="button" data-filter="pdf" aria-pressed="false">PDF</button>
                        <button type="button" data-filter="web" aria-pressed="false">เว็บ</button>
                    </div>
                    <button type="button" class="icon-button" onclick="loadDocumentList()" aria-label="รีเฟรชรายการ" title="รีเฟรช"><i class="ph ph-arrow-clockwise" aria-hidden="true"></i></button>
                </div>
            </div>
            <div id="doc-list">
                <div class="placeholder-line" style="width:80%"></div>
                <div class="placeholder-line" style="width:65%"></div>
                <div class="placeholder-line" style="width:72%"></div>
            </div>
        </section>

        <section class="section" id="doc-table-viewer-card" style="display:none" aria-labelledby="ocr-viewer-title">
            <div class="section-head">
                <div>
                    <h2 class="section-title" id="ocr-viewer-title">ผล OCR</h2>
                    <div class="section-note" id="doc-table-viewer-subtitle">เลือกเอกสารเพื่อดูตารางที่ extract ได้</div>
                </div>
                <button type="button" class="link-btn" onclick="closeDocTablesViewer()">ปิด</button>
            </div>
            <div id="doc-table-viewer-content"></div>
        </section>
    `;

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

    document.getElementById('doc-filter').addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-filter]');
        if (!btn) return;
        docFilter = btn.dataset.filter;
        document.querySelectorAll('#doc-filter button').forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
        renderDocRows();
    });

    docFilter = 'all';
    loadDocumentList();
}

async function uploadFiles(files) {
    const progress = document.getElementById('upload-progress');
    const statusText = document.getElementById('upload-status-text');
    progress.style.display = 'block';

    for (let i = 0; i < files.length; i++) {
        statusText.textContent = `Uploading ${files[i].name} (${i + 1}/${files.length})...`;

        if (uploadListPollingTimer) {
            clearInterval(uploadListPollingTimer);
        }
        loadDocumentList();
        uploadListPollingTimer = setInterval(() => {
            loadDocumentList();
        }, 3000);

        try {
            const result = await api.upload('/documents/upload', files[i]);
            showToast(result.queued
                ? `${files[i].name}: queued ${result.page_count} pages; processing continues in background`
                : `${files[i].name}: ${result.chunks_created} chunks, ${result.tables_extracted} tables`, 'success');
        } catch (e) {
            showToast(`Failed to process ${files[i].name}: ${e.message}`, 'error');
        } finally {
            if (uploadListPollingTimer) {
                clearInterval(uploadListPollingTimer);
                uploadListPollingTimer = null;
            }
        }
    }

    progress.style.display = 'none';
    loadDocumentList();
}

function renderDocStatusCell(doc) {
    const notes = [];
    if (doc.page_count != null) {
        notes.push(`<div class="cell-sub">indexed ${doc.indexed_pages || 0}/${doc.page_count} pages${doc.empty_pages ? `, ${doc.empty_pages} empty` : ''}</div>`);
    }
    if (doc.progress_text) {
        notes.push(`<div class="cell-sub is-progress">กำลัง OCR ${escapeDocHtml(doc.progress_text)}</div>`);
    }
    if (doc.failed_pages?.length) {
        const reasons = doc.failed_page_reasons || {};
        const chips = doc.failed_pages.slice(0, 8).map(page =>
            `<span class="page-chip" title="${escapeDocHtml(reasons[page] || `หน้า ${page} OCR ไม่สำเร็จ`)}">หน้า ${escapeDocHtml(page)}</span>`).join('');
        const more = doc.failed_pages.length > 8 ? `<span class="page-chip is-more">+${doc.failed_pages.length - 8}</span>` : '';
        notes.push(`<div class="page-chips" aria-label="หน้าที่ OCR ไม่สำเร็จ">${chips}${more}</div>`);
    }
    if (!doc.progress_text && !doc.failed_pages?.length && doc.status_detail) {
        notes.push(`<div class="cell-sub is-truncate" title="${escapeDocHtml(doc.status_detail)}">${escapeDocHtml(doc.status_detail)}</div>`);
    }
    return `${statusMark(doc.status)}${notes.join('')}`;
}

async function loadDocumentList() {
    const listEl = document.getElementById('doc-list');
    const countLabel = document.getElementById('doc-count-label');
    if (!listEl || !countLabel) return; // navigated away while a poll was pending

    try {
        const data = await api.get('/documents');
        const docs = data.documents || [];
        docCache = docs;
        countLabel.textContent = `${docs.length} รายการ`;
        renderLibraryStats(docs);
        const hasProcessingDocs = docs.some((doc) => ['pending', 'processing'].includes(doc.status));

        if (documentListRefreshTimer) {
            clearTimeout(documentListRefreshTimer);
            documentListRefreshTimer = null;
        }

        if (hasProcessingDocs) {
            documentListRefreshTimer = setTimeout(() => {
                loadDocumentList();
            }, 4000);
        }

        if (docs.length === 0) {
            listEl.innerHTML = `<p class="empty"><strong>ยังไม่มีเอกสาร</strong>อัปโหลด PDF หรือรูปภาพด้านบนเพื่อเริ่ม OCR และแบ่งเนื้อหา</p>`;
            return;
        }

        renderDocRows();
    } catch (e) {
        listEl.innerHTML = `<p class="message is-error">โหลดรายการเอกสารไม่สำเร็จ (${escapeDocHtml(e.message)}) ตรวจว่า backend ทำงานอยู่ แล้วกดรีเฟรช</p>`;
    }
}

function isWebDoc(doc) {
    return doc.doc_type === 'web_scrape' || Boolean(doc.source_url);
}

function renderLibraryStats(docs) {
    const set = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
    set('lib-docs', docs.length.toLocaleString());
    set('lib-chunks', docs.reduce((s, d) => s + (d.chunk_count || 0), 0).toLocaleString());
    set('lib-rows', docs.reduce((s, d) => s + (d.table_row_count || 0), 0).toLocaleString());
    const failed = docs.reduce((s, d) => s + (d.failed_pages?.length || 0), 0);
    set('lib-failed', failed.toLocaleString());
    document.getElementById('lib-failed')?.classList.toggle('is-query', failed > 0);
}

function renderDocRows() {
    const listEl = document.getElementById('doc-list');
    if (!listEl || !docCache.length) return;
    const docs = docCache.filter(d => docFilter === 'all' || (docFilter === 'web' ? isWebDoc(d) : !isWebDoc(d)));
    const maxChunks = Math.max(1, ...docCache.map(d => d.chunk_count || 0));
    document.querySelectorAll('#doc-filter button').forEach(b => {
        const n = b.dataset.filter === 'all' ? docCache.length : docCache.filter(d => (b.dataset.filter === 'web') === isWebDoc(d)).length;
        b.dataset.count = n;
    });

    if (!docs.length) {
        listEl.innerHTML = `<p class="empty"><strong>ไม่มีเอกสารประเภทนี้</strong>เลือก "ทั้งหมด" เพื่อดูเอกสารทุกไฟล์</p>`;
        return;
    }

    listEl.innerHTML = `<ul class="doc-rows">${docs.map((doc, i) => {
        const web = isWebDoc(doc);
        const type = web ? 'WEB' : (doc.doc_type || 'file').toUpperCase().slice(0, 4);
        const date = doc.created_at ? new Date(doc.created_at).toLocaleDateString('th-TH', { day: 'numeric', month: 'short', year: 'numeric' }) : '-';
        const chunks = doc.chunk_count || 0;
        const share = Math.max(0.6, (chunks / maxChunks) * 100);
        return `
            <li class="doc-row" style="--i:${i}">
                <span class="file-chip${web ? ' is-web' : ''}">${escapeDocHtml(type)}</span>
                <div class="doc-id">
                    <div class="doc-name" title="${escapeDocHtml(doc.filename)}">${escapeDocHtml(doc.filename)}</div>
                    <div class="doc-meta">${web ? 'ดึงจากเว็บ' : 'อัปโหลด'} ${escapeDocHtml(date)}</div>
                </div>
                <div class="doc-status">${renderDocStatusCell(doc)}</div>
                <div class="doc-size" title="${chunks.toLocaleString()} chunks, ${(doc.table_row_count || 0).toLocaleString()} แถวตาราง">
                    <div class="doc-figs"><b>${chunks.toLocaleString()}</b> chunks<span><b>${(doc.table_row_count || 0).toLocaleString()}</b> แถว</span></div>
                    <div class="size-bar" aria-hidden="true"><span style="width:${share.toFixed(2)}%"></span></div>
                </div>
                <div class="doc-actions">
                    <button type="button" class="chip-btn" onclick="viewDocChunks(${doc.id})"><i class="ph ph-rows" aria-hidden="true"></i>Chunks</button>
                    <button type="button" class="chip-btn" onclick="viewPaginatedOcr(${doc.id})"><i class="ph ph-scan" aria-hidden="true"></i>ผล OCR</button>
                    <button type="button" class="icon-button is-danger" onclick="deleteDoc(${doc.id})" aria-label="ลบ ${escapeDocHtml(doc.filename)}" title="ลบเอกสาร"><i class="ph ph-trash" aria-hidden="true"></i></button>
                </div>
            </li>`;
    }).join('')}</ul>`;
}

function viewDocChunks(docId) {
    window.location.hash = `visualizer`;
    // Store selected doc ID for visualizer
    sessionStorage.setItem('selectedDocId', docId);
}

function renderOcrTable(table, label) {
    const headers = table.headers || [];
    const rows = table.rows || [];
    return `<details class="ocr-table" open>
        <summary>${escapeDocHtml(label)}: ${escapeDocHtml(table.title || table.table_name || 'table')} (${rows.length} rows)</summary>
        <div class="register-scroll">
            <table class="register"><thead><tr>${headers.map(h => `<th>${escapeDocHtml(h)}</th>`).join('')}</tr></thead>
            <tbody>${rows.slice(0, 200).map(row => `<tr>${row.map(cell => `<td>${escapeDocHtml(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table>
        </div>${rows.length > 200 ? '<p class="block-meta">Showing first 200 rows on this page.</p>' : ''}
    </details>`;
}

function viewerLoading(text) {
    return `<div class="progress-line"></div><p class="loading-text">${escapeDocHtml(text)}</p>`;
}

function revealViewer(card) {
    card.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
}

async function viewPaginatedOcr(docId, requestedPage = 1) {
    const card = document.getElementById('doc-table-viewer-card');
    const subtitle = document.getElementById('doc-table-viewer-subtitle');
    const content = document.getElementById('doc-table-viewer-content');
    card.style.display = 'block';
    subtitle.textContent = 'Loading one page...';
    content.innerHTML = viewerLoading('Loading OCR page...');
    revealViewer(card);
    try {
        const requested = Math.max(1, Math.floor(Number(requestedPage) || 1));
        const skip = Math.floor((requested - 1) / 25) * 25;
        const listing = await api.get(`/documents/${docId}/pages?skip=${skip}&limit=25`);
        if (!listing.total) {
            await viewDocTables(docId); // legacy documents or images have no PDF-page checkpoints
            return;
        }
        const page = Math.min(requested, listing.total);
        const detail = await api.get(`/documents/${docId}/pages/${page}`);
        ocrViewerState = { docId, page, total: listing.total };
        subtitle.textContent = `${listing.filename}, physical PDF page ${page}/${listing.total}, ${detail.status}`;
        const pageButtons = listing.pages.map(item => `<button type="button" data-status="${escapeDocHtml(item.status)}" ${item.page === page ? 'aria-current="page"' : ''} onclick="viewPaginatedOcr(${docId},${item.page})">${item.page}: ${escapeDocHtml(item.status)}</button>`).join('');
        const raw = (detail.raw_ocr_pages || []).map(part => `<details open style="margin-bottom:10px"><summary>${escapeDocHtml(part.region || 'full')} region, rotation ${escapeDocHtml(part.rotation ?? 0)}°</summary><pre class="code-block" style="max-height:500px">${escapeDocHtml(part.markdown || '')}</pre></details>`).join('');
        const parsed = (detail.raw_ocr_tables || []).map(table => renderOcrTable(table, 'OCR parsed')).join('');
        const stored = (detail.structured_tables || []).map(table => renderOcrTable(table, 'Stored')).join('');
        const unresolved = (detail.quality_reports || []).flatMap(report =>
            (report.row_reports || []).filter(row => row.status === 'unresolved').map(row =>
                `${report.table_name || 'table'} row ${row.row_index + 1}: ${(row.reasons || []).join(', ')}`));
        const qualityNotice = (detail.quality_reports || []).length
            ? `Quality checks: ${unresolved.length} unresolved rows. Other rows may still be unverified.`
            : 'No row-quality report stored for this page. Older uploads were not revalidated; stored values may be wrong.';
        content.innerHTML = `
            <div class="viewer-tools">
                <button type="button" class="link-btn" onclick="viewPaginatedOcr(${docId},${Math.max(1, page - 1)})" ${page === 1 ? 'disabled' : ''}>หน้าก่อน</button>
                <label for="ocr-page-number" class="visually-hidden">เลขหน้า</label>
                <input id="ocr-page-number" class="input" type="number" min="1" max="${listing.total}" value="${page}">
                <button type="button" class="link-btn" onclick="viewPaginatedOcr(${docId},document.getElementById('ocr-page-number').value)">ไปหน้านี้</button>
                <button type="button" class="link-btn" onclick="viewPaginatedOcr(${docId},${Math.min(listing.total, page + 1)})" ${page === listing.total ? 'disabled' : ''}>หน้าถัดไป</button>
                <span class="block-meta">Only this page is loaded. ${escapeDocHtml(detail.error_stage || '')} ${escapeDocHtml(detail.error_message || '')}</span>
            </div>
            <div class="page-index">${pageButtons}</div>
            <div class="viewer-grid">
                <section><h3>Original PDF page</h3><img src="${detail.image_url}" alt="Original PDF page ${page}" loading="lazy"></section>
                <section><h3>Raw OCR</h3>${raw || '<p class="empty">No raw OCR stored for this page.</p>'}</section>
                <section><h3>Parsed OCR tables</h3>${parsed || '<p class="empty">No table detected.</p>'}</section>
                <section><h3>Final stored data</h3>${stored || '<p class="empty">No structured rows stored.</p>'}</section>
            </div>
            <details style="margin-top:22px" open><summary>${escapeDocHtml(qualityNotice)}</summary>
                <div class="quality-notes">
                ${(detail.quality_reports || []).length
                    ? (unresolved.slice(0, 30).map(item => `<div>${escapeDocHtml(item)}</div>`).join('') || '<div>No unresolved rows reported; other rows may still be unverified.</div>')
                    : '<div>Re-upload this PDF to apply the current quality checks.</div>'}
                ${unresolved.length > 30 ? '<div>Showing first 30 unresolved rows.</div>' : ''}
                </div>
            </details>`;
    } catch (error) {
        subtitle.textContent = 'OCR page unavailable';
        content.innerHTML = `<p class="message is-error">${escapeDocHtml(error.message)}</p>`;
    }
}

async function viewDocTables(docId) {
    const card = document.getElementById('doc-table-viewer-card');
    const subtitle = document.getElementById('doc-table-viewer-subtitle');
    const content = document.getElementById('doc-table-viewer-content');

    card.style.display = 'block';
    subtitle.textContent = 'กำลังโหลดตาราง...';
    content.innerHTML = viewerLoading('Loading structured tables...');
    revealViewer(card);

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
        const retryPages = (doc.raw_ocr_retry_pages || []).slice().sort((a, b) => (a.page || 0) - (b.page || 0));
        const rawTables = (doc.raw_ocr_tables || []).slice().sort((a, b) => {
            const pageDiff = (a.page || 0) - (b.page || 0);
            if (pageDiff !== 0) return pageDiff;
            return (a.table_index || 0) - (b.table_index || 0);
        });
        const qualityReports = doc.quality_reports || [];
        const unresolvedRows = qualityReports.flatMap((report) =>
            (report.row_reports || [])
                .filter((row) => row.status === 'unresolved')
                .map((row) => ({ ...row, page: report.page, tableName: report.table_name }))
        );
        const unverifiedRows = qualityReports.flatMap((report) =>
            (report.row_reports || [])
                .filter((row) => row.status === 'unverified')
                .map((row) => ({ ...row, page: report.page, tableName: report.table_name }))
        );
        const retryChanges = qualityReports.flatMap((report) => report.retry_changes || []);
        const retryAccepted = retryChanges.filter((change) => change.status === 'retry_consistent_not_source_verified');
        const retryDisputed = retryChanges.filter((change) => change.status === 'ocr_passes_disagree_unresolved');
        const renderedRowCount = tables.reduce((sum, table) => sum + (table.rows?.length || 0), 0);
        const singlePageGroup = rawPages.length <= 1;

        subtitle.textContent = `${doc.filename}, ${tables.length} structured tables, ${rawPages.length} raw pages, ${rawTables.length} raw tables`;

        if (!tables.length && !rawPages.length && !rawTables.length) {
            content.innerHTML = `<p class="empty"><strong>No OCR artifacts</strong>เอกสารนี้ยังไม่มีข้อมูล OCR ที่เปิดดูได้ หรือเป็นเอกสารที่ ingest ก่อนเปิด artifact pipeline</p>`;
            return;
        }

        const renderStructuredTableCard = (table) => {
            const headers = table.headers || [];
            const visibleRows = table.rows || [];
            const csvPreview = [
                headers.join(','),
                ...visibleRows.map((row) => headers.map((header) => csvCell(row.rowData?.[header] ?? '')).join(',')),
            ].join('\n');

            return `
                <div class="block">
                    <div class="block-head">
                        <span class="block-title">${escapeDocHtml(table.title || table.tableName)}</span>
                        <span class="block-meta">Structured table, ${table.rows.length} rows, ${headers.length} columns</span>
                    </div>
                    <div class="register-scroll">
                        <table class="register">
                            <thead><tr>${headers.map((header) => `<th>${escapeDocHtml(header)}</th>`).join('')}</tr></thead>
                            <tbody>
                                ${visibleRows.map((row) => `<tr>${headers.map((header) => `<td>${escapeDocHtml(row.rowData?.[header] ?? '')}</td>`).join('')}</tr>`).join('')}
                            </tbody>
                        </table>
                    </div>
                    <details style="margin-top:8px">
                        <summary>ดู CSV preview</summary>
                        <pre class="code-block">${escapeDocHtml(csvPreview)}</pre>
                    </details>
                </div>
            `;
        };

        const renderRawPageCard = (page) => `
            <details class="block" open>
                <summary>Raw OCR page ${escapeDocHtml(page.page ?? '-')}</summary>
                <pre class="code-block">${escapeDocHtml(page.markdown || '')}</pre>
            </details>
        `;

        const renderRawTableCard = (table) => `
            <div class="block">
                <div class="block-head">
                    <span class="block-title">${escapeDocHtml(table.title || `raw_table_${table.table_index}`)}</span>
                    <span class="block-meta">Raw OCR table, ${(table.rows || []).length} rows, ${(table.headers || []).length} columns</span>
                </div>
                <details>
                    <summary>ดู raw CSV</summary>
                    <pre class="code-block">${escapeDocHtml(table.csv_text || '')}</pre>
                </details>
            </div>
        `;

        const group = (title, body) => `<div class="group"><h3 class="group-title">${title}</h3>${body}</div>`;

        const structuredHtml = tables.length ? group('Structured tables', tables.map(renderStructuredTableCard).join('')) : '';
        const rawPagesHtml = rawPages.length ? group('Raw OCR pages', rawPages.map(renderRawPageCard).join('')) : '';
        const rawTablesHtml = rawTables.length ? group('Raw OCR tables', rawTables.map(renderRawTableCard).join('')) : '';
        const retryPagesHtml = retryPages.length ? group('Higher-resolution OCR retries', retryPages.map((page) => `
            <details class="block">
                <summary>Retry page ${escapeDocHtml(page.page ?? '?')}</summary>
                <pre class="code-block">${escapeDocHtml(page.markdown || '')}</pre>
            </details>`).join('')) : '';

        const qualityHtml = qualityReports.length ? `
            <div class="group" style="margin-bottom:28px">
                <h3 class="group-title">OCR value checks</h3>
                <p class="${unresolvedRows.length ? 'message is-query' : 'message'}" style="padding-top:0">
                    ${unresolvedRows.length} unresolved rows excluded from structured search and warehouse.
                    ${unverifiedRows.length} rows had no applicable numeric cross-check and are not proven correct.
                    ${retryAccepted.length} cells provisionally corrected after a higher-resolution retry;
                    ${retryDisputed.length} cross-pass disagreements quarantined.
                    Passing a check is not proof that OCR matches the PDF.
                </p>
                ${retryChanges.length ? `<details style="margin-top:6px"><summary>Show OCR retry changes</summary>
                    <div class="quality-notes">
                    ${retryChanges.map((change) => `<div>
                        ${escapeDocHtml(change.table_name || 'table')} row ${change.row_index + 1}, column ${escapeDocHtml(change.column)}:
                        ${escapeDocHtml(change.first_value)} → ${escapeDocHtml(change.retry_value)}
                        (${change.status === 'ocr_passes_disagree_unresolved' ? 'unresolved disagreement' : 'internally consistent, still OCR-derived'})
                    </div>`).join('')}
                    </div>
                </details>` : ''}
                ${unresolvedRows.length ? `
                    <details style="margin-top:6px">
                        <summary>Show unresolved rows and reasons</summary>
                        <div class="quality-notes">
                        ${unresolvedRows.slice(0, 50).map((row) => `
                            <div>
                                Page ${escapeDocHtml(row.page ?? '?')}, ${escapeDocHtml(row.tableName || 'table')}, row ${row.row_index + 1}:
                                ${escapeDocHtml((row.reasons || []).join(', '))}
                                <div>${escapeDocHtml((row.cells || []).map((cell) => cell.value).join(' | '))}</div>
                            </div>
                        `).join('')}
                        ${unresolvedRows.length > 50 ? `<div>Showing first 50 of ${unresolvedRows.length} unresolved rows.</div>` : ''}
                        </div>
                    </details>
                ` : ''}
                ${unverifiedRows.length ? `
                    <details style="margin-top:6px">
                        <summary>Show rows with no applicable cross-check</summary>
                        <div class="quality-notes">
                        ${unverifiedRows.slice(0, 50).map((row) => `
                            <div>
                                Page ${escapeDocHtml(row.page ?? '?')}, ${escapeDocHtml(row.tableName || 'table')}, row ${row.row_index + 1}:
                                ${escapeDocHtml((row.cells || []).map((cell) => cell.value).join(' | '))}
                            </div>
                        `).join('')}
                        ${unverifiedRows.length > 50 ? `<div>Showing first 50 of ${unverifiedRows.length} unverified rows.</div>` : ''}
                        </div>
                    </details>
                ` : ''}
            </div>
        ` : '';

        const combinedSinglePageHtml = singlePageGroup ? `
            <div class="group">
                <h3 class="group-title">Source page group</h3>
                <p class="block-meta" style="margin-bottom:14px">${escapeDocHtml(doc.filename)}: รวม raw OCR, ตารางที่ normalize แล้ว และ raw table ของหน้าเดียวกันไว้ติดกัน เพื่อตรวจเทียบกับต้นฉบับ</p>
                ${rawPages.length ? group('Raw OCR from this page', rawPages.map(renderRawPageCard).join('')) : ''}
                ${tables.length ? group('Structured sections from this page', tables.map(renderStructuredTableCard).join('')) : ''}
                ${rawTables.length ? group('Raw table blocks from this page', rawTables.map(renderRawTableCard).join('')) : ''}
            </div>
        ` : `
            <p class="message" style="margin-bottom:20px">เอกสารนี้มีหลายหน้า OCR จึงยังแสดงทั้งแบบแยกประเภทเหมือนเดิมก่อน เพราะระบบยังไม่มี page-to-section mapping ที่แม่นพอสำหรับทุกหน้า</p>
        `;

        content.innerHTML = `
            <p class="block-meta" style="margin-bottom:14px">Structured rows: ${renderedRowCount.toLocaleString()}</p>
            ${qualityHtml}
            ${combinedSinglePageHtml}
            ${singlePageGroup ? '' : structuredHtml}
            ${singlePageGroup ? '' : rawPagesHtml}
            ${retryPagesHtml}
            ${singlePageGroup ? '' : rawTablesHtml}
        `;
    } catch (e) {
        subtitle.textContent = 'โหลดตารางไม่สำเร็จ';
        content.innerHTML = `<p class="message is-error">Failed to load tables: ${escapeDocHtml(e.message)}</p>`;
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
