/**
 * Chunk Visualizer Component
 * Shows a document the way the chunker cut it: one continuous text with
 * numbered paragraphs in the margin, and a seam between chunks whose weight
 * says how alike the two sides are. A heavy seam is a real topic break.
 *
 * Above the text sits the seam strip: every seam in the document as one
 * bar, taller the less alike the two sides are. It stays pinned while the
 * text scrolls, marks the part in view, and jumps to a seam on click.
 */

// Similarity bands: thirds of the 0-1 scale.
const SIM_HIGH = 2 / 3;
const SIM_SPLIT = 1 / 3;

let visChunks = [];
let visScrollHandler = null;
let visResizeObserver = null;
let visThemeObserver = null;
let visOffsets = [];
let visBuckets = [];

function renderChunkVisualizer(container) {
    teardownSeamStrip();
    container.innerHTML = `
        <section class="scrape-hero">
            ${AURORA_HTML.replace('class="aurora"', 'class="aurora is-seam"')}
            <h1 class="hero-title" lang="en">Where the document splits.<span class="line-2">Every seam, scored by meaning.</span></h1>
            <p class="hero-sub">ระบบตัดเอกสารเป็นช่วงตามความหมาย ยิ่งสองช่วงติดกันคล้ายกันน้อย รอยต่อยิ่งหนัก เลือกเอกสารแล้วกดบนแถบเพื่อกระโดดไปดูจุดนั้น</p>

            <div class="ask-pill doc-picker">
                <i class="ph ph-file-text" aria-hidden="true"></i>
                <label for="vis-doc-select" class="visually-hidden">เอกสาร</label>
                <select id="vis-doc-select" onchange="loadChunkVisualization()">
                    <option value="">เลือกเอกสาร</option>
                </select>
                <button type="button" class="icon-button" onclick="refreshDocList()" aria-label="รีเฟรชรายการเอกสาร" title="รีเฟรชรายการ"><i class="ph ph-arrow-clockwise" aria-hidden="true"></i></button>
            </div>
        </section>

        <div id="chunk-vis-area">
            ${visEmptyState()}
        </div>
    `;

    loadVisDocList();
}

function visEmptyState() {
    // A quiet preview of what the strip will look like, so the empty page explains itself.
    const bars = Array.from({ length: 64 }, (_, i) => {
        const h = 18 + 70 * Math.abs(Math.sin(i * 1.7) * Math.cos(i * 0.37));
        return `<span style="height:${h.toFixed(0)}%"></span>`;
    }).join('');
    return `
        <div class="vis-empty">
            <div class="vis-empty-bars" aria-hidden="true">${bars}</div>
            <p class="empty"><strong>ยังไม่ได้เลือกเอกสาร</strong>เลือกเอกสารด้านบน แถบนี้จะแสดงทุกรอยต่อระหว่าง chunks ของเอกสารนั้น</p>
        </div>`;
}

async function loadVisDocList() {
    const select = document.getElementById('vis-doc-select');
    try {
        const data = await api.get('/documents');
        const docs = (data.documents || []).filter(d => ['completed', 'partial'].includes(d.status) && d.chunk_count > 0);

        select.innerHTML = '<option value="">เลือกเอกสาร</option>';
        docs.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.id;
            opt.textContent = `${d.filename} (${d.chunk_count} chunks)`;
            select.appendChild(opt);
        });

        // Auto-select if coming from documents page
        const savedId = sessionStorage.getItem('selectedDocId');
        if (savedId) {
            select.value = savedId;
            sessionStorage.removeItem('selectedDocId');
            loadChunkVisualization();
        }
    } catch (e) {
        showToast('Failed to load document list', 'error');
    }
}

function refreshDocList() {
    loadVisDocList();
}

async function loadChunkVisualization() {
    const docId = document.getElementById('vis-doc-select').value;
    const area = document.getElementById('chunk-vis-area');
    teardownSeamStrip();

    if (!docId) {
        area.innerHTML = visEmptyState();
        return;
    }

    area.innerHTML = `<div class="progress-line"></div><p class="loading-text">กำลังโหลด chunks...</p>`;

    try {
        const data = await api.get(`/chunks/${docId}`);
        renderChunks(area, data);
    } catch (e) {
        area.innerHTML = `<p class="message is-error">โหลด chunks ไม่สำเร็จ: ${escapeHtmlVis(e.message)}</p>`;
    }
}

function similarityBand(sim) {
    if (sim === null || sim === undefined) return '';
    if (sim >= SIM_HIGH) return 'is-high';
    if (sim >= SIM_SPLIT) return 'is-mid';
    return 'is-split';
}

function renderChunks(area, data) {
    const { filename, total_chunks, chunks } = data;
    visChunks = chunks;

    const sims = chunks.map(c => c.similarity_to_next).filter(s => s !== null && s !== undefined);
    const breaks = sims.filter(s => s < SIM_SPLIT).length;
    const tokens = chunks.map(c => Number(c.token_count) || 0);
    const avgTokens = tokens.length ? Math.round(tokens.reduce((a, b) => a + b, 0) / tokens.length) : 0;
    const avgSim = sims.length ? sims.reduce((a, b) => a + b, 0) / sims.length : null;

    let html = `
        <section class="section chunk-view" aria-label="${escapeHtmlVis(filename)}">
            <dl class="crawl-stats chunk-stats">
                <div><dt>Chunks</dt><dd><b>${Number(total_chunks).toLocaleString()}</b></dd></div>
                <div><dt>ยาวเฉลี่ย</dt><dd><b>${avgTokens.toLocaleString()}</b> tokens</dd></div>
                <div><dt>จุดเปลี่ยนเรื่อง</dt><dd><b>${breaks.toLocaleString()}</b> จุด</dd></div>
                <div><dt>ความคล้ายเฉลี่ย</dt><dd><b>${avgSim === null ? '-' : (avgSim * 100).toFixed(1)}</b>${avgSim === null ? '' : '%'}</dd></div>
            </dl>

            <div class="seam-strip" id="seam-strip">
                <div class="strip-head">
                    <div class="strip-title">${escapeHtmlVis(filename)}</div>
                    <ul class="legend" aria-label="ความหมายของรอยต่อ">
                        <li><span class="seam-sample is-split"></span>เปลี่ยนเรื่อง (ต่ำกว่า ${(SIM_SPLIT * 100).toFixed(1)}%)</li>
                        <li><span class="seam-sample is-mid"></span>เกี่ยวข้องกัน</li>
                        <li><span class="seam-sample"></span>คล้ายกัน (${(SIM_HIGH * 100).toFixed(1)}% ขึ้นไป)</li>
                    </ul>
                    <div class="strip-nav">
                        <button type="button" class="chip-btn" id="seam-prev" aria-label="จุดเปลี่ยนเรื่องก่อนหน้า"><i class="ph ph-caret-left" aria-hidden="true"></i></button>
                        <span class="strip-pos" id="seam-pos" aria-live="polite">ช่วง 0</span>
                        <button type="button" class="chip-btn" id="seam-next" aria-label="จุดเปลี่ยนเรื่องถัดไป">จุดเปลี่ยนเรื่องถัดไป<i class="ph ph-caret-right" aria-hidden="true"></i></button>
                    </div>
                </div>
                <div class="strip-plot">
                    <canvas id="seam-canvas" role="img" aria-label="แถบรอยต่อ ${sims.length.toLocaleString()} จุด มีจุดเปลี่ยนเรื่อง ${breaks.toLocaleString()} จุด"></canvas>
                    <div class="strip-window" id="seam-window" aria-hidden="true"></div>
                    <div class="chart-tip strip-tip" id="seam-tip" hidden></div>
                </div>
                <div class="strip-axis" aria-hidden="true"><span>ต้นเอกสาร</span><span class="strip-key">แท่งยิ่งสูง ยิ่งเปลี่ยนเรื่องบ่อยในช่วงนั้น</span><span>ท้ายเอกสาร</span></div>
            </div>

            <div class="chunk-doc">
    `;

    chunks.forEach((chunk, i) => {
        html += `
            <button type="button" class="para" id="chunk-${i}" data-i="${i}" aria-expanded="false" onclick="toggleChunk(this)">
                <span class="para-no">${escapeHtmlVis(chunk.chunk_index)}</span>
                <span>
                    <span class="para-text">${escapeHtmlVis(chunk.chunk_text)}</span>
                    ${chunk.summary ? `<span class="para-summary">สรุป: ${escapeHtmlVis(chunk.summary)}</span>` : ''}
                </span>
                <span class="para-tokens">${chunk.token_count ? `${Number(chunk.token_count).toLocaleString()} tokens` : ''}</span>
            </button>
        `;

        if (i < chunks.length - 1) {
            const sim = chunk.similarity_to_next;
            const known = sim !== null && sim !== undefined;
            const band = similarityBand(sim);
            html += `
                <div class="seam ${band}" role="separator">
                    <span></span>
                    <span class="seam-line"></span>
                    <span class="seam-label">${band === 'is-split' ? '<b>เปลี่ยนเรื่อง</b> ' : ''}${known ? `${(sim * 100).toFixed(1)}%` : '-'}</span>
                </div>
            `;
        }
    });

    html += '</div></section>';
    area.innerHTML = html;
    setupSeamStrip();

    // Arriving from an answer's quote: land on that chunk.
    let target = null;
    try {
        target = sessionStorage.getItem('selectedChunk');
        sessionStorage.removeItem('selectedChunk');
    } catch (_) { /* storage blocked */ }
    if (target !== null) {
        const i = chunks.findIndex(c => String(c.chunk_index) === target);
        if (i >= 0) requestAnimationFrame(() => jumpToChunk(i));
    }
}

// ------------------------------------------------------------------
// Seam strip
// ------------------------------------------------------------------
function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function drawSeamStrip() {
    const canvas = document.getElementById('seam-canvas');
    if (!canvas || !visChunks.length) return;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    const n = Math.max(1, visChunks.length - 1);
    const gold = cssVar('--chart') || '#C08623';
    const base = cssVar('--line-strong') || 'rgba(255,255,255,0.16)';

    // Bars of about 6px. Each bar groups consecutive seams; its height is the
    // share of those seams that are topic breaks, so busy and calm stretches read apart.
    const cols = Math.max(1, Math.min(n, Math.floor(width / 6)));
    const colW = width / cols;
    visBuckets = [];
    for (let c = 0; c < cols; c++) {
        const from = Math.floor((c * n) / cols);
        const to = Math.max(from + 1, Math.floor(((c + 1) * n) / cols));
        let known = 0, splits = 0;
        for (let i = from; i < to; i++) {
            const s = visChunks[i]?.similarity_to_next;
            if (s === null || s === undefined) continue;
            known++;
            if (s < SIM_SPLIT) splits++;
        }
        visBuckets.push({ from, to, known, splits });
        const x = c * colW;
        const w = Math.max(1, colW - 2);
        ctx.fillStyle = base;
        ctx.fillRect(x, height - 1, w, 1);
        if (!known || !splits) continue;
        const h = Math.max(3, (splits / known) * (height - 2));
        ctx.fillStyle = gold;
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(x, height - h, w, h, [2, 2, 0, 0]); else ctx.rect(x, height - h, w, h);
        ctx.fill();
    }
    updateSeamWindow();
}

function bucketAtX(x, width) {
    if (!visBuckets.length) return null;
    return visBuckets[Math.min(visBuckets.length - 1, Math.max(0, Math.floor((x / width) * visBuckets.length)))];
}

function measureOffsets() {
    visOffsets = Array.from(document.querySelectorAll('.chunk-doc .para'), el => el.getBoundingClientRect().top + window.scrollY);
}

function firstVisibleChunk() {
    const strip = document.getElementById('seam-strip');
    const line = window.scrollY + (strip ? strip.getBoundingClientRect().bottom : 0) + 8;
    let lo = 0, hi = visOffsets.length - 1, ans = 0;
    while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (visOffsets[mid] <= line) { ans = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return ans;
}

function lastVisibleChunk() {
    const line = window.scrollY + window.innerHeight;
    let lo = 0, hi = visOffsets.length - 1, ans = 0;
    while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (visOffsets[mid] <= line) { ans = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return ans;
}

function updateSeamWindow() {
    const win = document.getElementById('seam-window');
    const pos = document.getElementById('seam-pos');
    if (!win || !visOffsets.length) return;
    const strip = document.getElementById('seam-strip');
    strip?.classList.toggle('is-stuck', strip.getBoundingClientRect().top <= parseFloat(getComputedStyle(strip).top) + 0.5);
    const n = Math.max(1, visChunks.length - 1);
    const a = firstVisibleChunk();
    const b = Math.max(a, lastVisibleChunk());
    win.style.left = `${(a / n) * 100}%`;
    win.style.width = `max(3px, ${(((b - a) || 1) / n) * 100}%)`;
    if (pos) pos.textContent = `ช่วง ${a.toLocaleString()} ถึง ${b.toLocaleString()}`;
}

function jumpToChunk(i) {
    const el = document.getElementById(`chunk-${i}`);
    if (!el) return;
    const strip = document.getElementById('seam-strip');
    const offset = (strip ? strip.getBoundingClientRect().height : 0) + 110;
    window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - offset, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
    el.classList.remove('is-target');
    void el.offsetWidth;
    el.classList.add('is-target');
}

function stepBreak(dir) {
    const from = firstVisibleChunk();
    const n = visChunks.length - 1;
    for (let i = from + (dir > 0 ? 1 : -1); i >= 0 && i < n; i += dir) {
        const s = visChunks[i]?.similarity_to_next;
        if (s !== null && s !== undefined && s < SIM_SPLIT) { jumpToChunk(dir > 0 ? i + 1 : i); return; }
    }
    showToast(dir > 0 ? 'ไม่มีจุดเปลี่ยนเรื่องหลังจากนี้แล้ว' : 'ไม่มีจุดเปลี่ยนเรื่องก่อนหน้านี้', 'info');
}

function setupSeamStrip() {
    const canvas = document.getElementById('seam-canvas');
    const tip = document.getElementById('seam-tip');
    if (!canvas) return;
    measureOffsets();
    drawSeamStrip();

    canvas.addEventListener('pointermove', (e) => {
        const rect = canvas.getBoundingClientRect();
        const b = bucketAtX(e.clientX - rect.left, rect.width);
        if (!b) return;
        tip.hidden = false;
        tip.innerHTML = `<b>ช่วง ${b.from} ถึง ${b.to}</b><span>เปลี่ยนเรื่อง ${b.splits} จาก ${b.known} รอยต่อ</span>`;
        const x = Math.min(rect.width - 8, Math.max(8, e.clientX - rect.left));
        tip.style.left = `${x}px`;
        tip.classList.toggle('flip', x > rect.width - 160);
    });
    canvas.addEventListener('pointerleave', () => { tip.hidden = true; });
    canvas.addEventListener('click', (e) => {
        const rect = canvas.getBoundingClientRect();
        const b = bucketAtX(e.clientX - rect.left, rect.width);
        if (!b) return;
        // Land on the first topic break inside the bar, or its start if it has none.
        let target = b.from;
        for (let i = b.from; i < b.to; i++) {
            const s = visChunks[i]?.similarity_to_next;
            if (s !== null && s !== undefined && s < SIM_SPLIT) { target = i + 1; break; }
        }
        jumpToChunk(target);
    });
    document.getElementById('seam-next').addEventListener('click', () => stepBreak(1));
    document.getElementById('seam-prev').addEventListener('click', () => stepBreak(-1));

    let ticking = false;
    visScrollHandler = () => {
        if (ticking) return;
        ticking = true;
        requestAnimationFrame(() => { ticking = false; updateSeamWindow(); });
    };
    window.addEventListener('scroll', visScrollHandler, { passive: true });

    let resizeTimer = null;
    visResizeObserver = new ResizeObserver(() => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => { measureOffsets(); drawSeamStrip(); }, 120);
    });
    visResizeObserver.observe(canvas);
    visThemeObserver = new MutationObserver(drawSeamStrip);
    visThemeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
}

function teardownSeamStrip() {
    if (visScrollHandler) window.removeEventListener('scroll', visScrollHandler);
    visResizeObserver?.disconnect();
    visThemeObserver?.disconnect();
    visScrollHandler = null;
    visResizeObserver = null;
    visThemeObserver = null;
    visOffsets = [];
}

function toggleChunk(el) {
    const expanded = el.getAttribute('aria-expanded') !== 'true';
    el.setAttribute('aria-expanded', String(expanded));
    measureOffsets();
    updateSeamWindow();
}

function escapeHtmlVis(text) {
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}
