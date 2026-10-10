/**
 * Business Agent - Main Application
 * SPA Router, API Client, shared UI helpers, and the Overview page
 */

// ============================================================
// API Client
// ============================================================
const API_BASE = '/api';

const api = {
    async get(path) {
        const res = await fetch(`${API_BASE}${path}`);
        if (!res.ok) throw new Error(`API Error: ${res.status}`);
        return res.json();
    },

    async post(path, body) {
        const res = await fetch(`${API_BASE}${path}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error(`API Error: ${res.status}`);
        return res.json();
    },

    async upload(path, file) {
        const form = new FormData();
        form.append('file', file);
        const res = await fetch(`${API_BASE}${path}`, {
            method: 'POST',
            body: form,
        });
        if (!res.ok) throw new Error(`API Error: ${res.status}`);
        return res.json();
    },

    async delete(path) {
        const res = await fetch(`${API_BASE}${path}`, { method: 'DELETE' });
        if (!res.ok) throw new Error(`API Error: ${res.status}`);
        return res.json();
    },
};

// Local escaper so this file does not depend on component load order.
function escapeText(text) {
    return String(text ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// The atmospheric light field. Decorative, so hidden from assistive tech.
const AURORA_HTML = '<div class="aurora" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></div>';

// Document status: a coloured dot plus a word, never colour alone.
const STATUS_MARKS = {
    completed: { cls: 'mark-ok', label: 'ครบ' },
    partial: { cls: 'mark-query', label: 'บางส่วน' },
    failed: { cls: 'mark-fail', label: 'ล้มเหลว' },
    processing: { cls: 'mark-busy', label: 'กำลังประมวลผล' },
    pending: { cls: 'mark-busy', label: 'รอคิว' },
};

function statusMark(status) {
    const meta = STATUS_MARKS[status] || { cls: 'mark-none', label: status || 'ไม่ทราบ' };
    return `<span class="mark ${meta.cls}" title="${escapeText(status || 'unknown')}">${meta.label}</span>`;
}

// A number arriving on its own: count up once, fast, then rest.
function countUp(el, target, duration = 900) {
    if (!el) return;
    const end = Number(target) || 0;
    if (prefersReducedMotion() || end === 0) {
        el.textContent = end.toLocaleString();
        return;
    }
    const start = performance.now();
    const step = (now) => {
        const t = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - t, 4);
        el.textContent = Math.round(end * eased).toLocaleString();
        if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
}

// ============================================================
// Toast Notifications
// Reserved for results with no on-screen origin (background jobs,
// uploads finishing while the person looks elsewhere).
// ============================================================
const toastContainer = document.createElement('div');
toastContainer.className = 'toast-container';
toastContainer.setAttribute('role', 'status');
toastContainer.setAttribute('aria-live', 'polite');
document.body.appendChild(toastContainer);

const TOAST_MARKS = { success: 'mark-ok', error: 'mark-fail', warning: 'mark-query', info: 'mark-none' };

function showToast(message, type = 'info', duration = 4000) {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span class="mark ${TOAST_MARKS[type] || TOAST_MARKS.info}" aria-hidden="true"></span><span>${escapeText(message)}</span>`;
    toastContainer.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('is-leaving');
        setTimeout(() => toast.remove(), 160);
    }, duration);
}

// ============================================================
// Theme (dark by default)
// ============================================================
function currentTheme() {
    return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

function syncThemeToggle() {
    const button = document.getElementById('theme-toggle');
    if (!button) return;
    const dark = currentTheme() === 'dark';
    button.innerHTML = `<i class="ph ${dark ? 'ph-sun' : 'ph-moon'}" aria-hidden="true"></i>`;
    button.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
    button.title = button.getAttribute('aria-label');
}

function toggleTheme() {
    const next = currentTheme() === 'dark' ? 'light' : 'dark';
    const root = document.documentElement;
    root.setAttribute('data-theme-switching', '');
    if (next === 'light') root.dataset.theme = 'light';
    else delete root.dataset.theme;
    void document.body.offsetHeight;
    requestAnimationFrame(() => root.removeAttribute('data-theme-switching'));
    try { localStorage.setItem('ba-theme', next); } catch (_) { /* storage blocked */ }
    syncThemeToggle();
    // Charts read their colours from CSS, so the next frame already matches.
}

// ============================================================
// Line chart (single series, one hue, hover crosshair + tooltip)
// ============================================================
let chartSeq = 0;

function renderLineChart(container, points, { height = 220, axis = true, unit = '', title = '', animate = true, padX = 14 } = {}) {
    if (!container || points.length < 2) return;
    const id = `chart-${++chartSeq}`;
    const width = Math.max(240, Math.round(container.clientWidth || 480));
    const pad = { top: 16, right: padX, bottom: axis ? 30 : 0, left: padX };
    const ys = points.map(p => p.y);
    const min = Math.min(...ys);
    const max = Math.max(...ys);
    const span = (max - min) || Math.abs(max) || 1;
    const lo = min - span * 0.18;
    const hi = max + span * 0.12;
    const x = i => pad.left + (i * (width - pad.left - pad.right)) / (points.length - 1);
    const y = v => pad.top + (1 - (v - lo) / (hi - lo)) * (height - pad.top - pad.bottom);
    const coords = points.map((p, i) => [x(i), y(p.y)]);
    const line = coords.map(([cx, cy], i) => `${i ? 'L' : 'M'}${cx.toFixed(1)},${cy.toFixed(1)}`).join(' ');
    const area = `${line} L${coords[coords.length - 1][0].toFixed(1)},${height - pad.bottom} L${coords[0][0].toFixed(1)},${height - pad.bottom} Z`;
    const grid = axis ? [0.25, 0.5, 0.75].map(f => {
        const gy = pad.top + f * (height - pad.top - pad.bottom);
        return `<line class="grid-line" x1="${pad.left}" x2="${width - pad.right}" y1="${gy}" y2="${gy}"></line>`;
    }).join('') : '';
    const labels = axis ? points.map((p, i) => `<text class="axis-label" x="${x(i)}" y="${height - 8}" text-anchor="${i === 0 ? 'start' : i === points.length - 1 ? 'end' : 'middle'}">${escapeText(p.x)}</text>`).join('') : '';
    const dots = coords.map(([cx, cy], i) => `<circle class="${i === coords.length - 1 ? 'dot-last' : 'dot'}" data-i="${i}" cx="${cx}" cy="${cy}" r="${i === coords.length - 1 ? 4.5 : (axis ? 3.5 : 0)}"></circle>`).join('');
    const colW = (width - pad.left - pad.right) / (points.length - 1);
    const hits = coords.map(([cx], i) => `<rect class="hit" data-i="${i}" x="${Math.max(0, cx - colW / 2)}" y="0" width="${colW}" height="${height}"></rect>`).join('');
    const summary = `${title}: ${points.map(p => `${p.x} ${p.y.toLocaleString()} ${unit}`).join(', ')}`;

    container.innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="${escapeText(summary)}">
            <defs>
                <linearGradient id="${id}-fill" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stop-color="var(--chart)" stop-opacity="0.32"></stop>
                    <stop offset="100%" stop-color="var(--chart)" stop-opacity="0"></stop>
                </linearGradient>
            </defs>
            ${grid}
            <path d="${area}" fill="url(#${id}-fill)"></path>
            <line class="crosshair" x1="0" x2="0" y1="${pad.top}" y2="${height - pad.bottom}"></line>
            <path class="line" d="${line}"></path>
            ${dots}
            ${labels}
            ${hits}
        </svg>
        <div class="chart-tip" role="presentation"></div>
        <table class="visually-hidden"><caption>${escapeText(title)}</caption>
            <tbody>${points.map(p => `<tr><th scope="row">${escapeText(p.x)}</th><td>${p.y.toLocaleString()} ${escapeText(unit)}</td></tr>`).join('')}</tbody>
        </table>
    `;

    const svg = container.querySelector('svg');
    const path = svg.querySelector('.line');
    const len = path.getTotalLength();
    path.style.strokeDasharray = len;
    path.style.setProperty('--len', len);
    container.classList.toggle('is-drawn', animate && !prefersReducedMotion());

    const tip = container.querySelector('.chart-tip');
    const cross = svg.querySelector('.crosshair');
    const show = (i) => {
        const [cx, cy] = coords[i];
        const scale = svg.getBoundingClientRect().width / width;
        cross.setAttribute('x1', cx); cross.setAttribute('x2', cx);
        cross.style.opacity = 1;
        tip.innerHTML = `${escapeText(points[i].x)} <b>${points[i].y.toLocaleString()}</b> ${escapeText(unit)}`;
        tip.style.left = `${cx * scale}px`;
        tip.style.top = `${cy * scale}px`;
        tip.classList.add('is-visible');
    };
    const hide = () => { cross.style.opacity = 0; tip.classList.remove('is-visible'); };
    svg.querySelectorAll('.hit').forEach(rect => {
        rect.addEventListener('pointerenter', () => show(Number(rect.dataset.i)));
        rect.addEventListener('pointerleave', hide);
    });
}

// ============================================================
// SPA Router
// ============================================================
const pages = {
    dashboard: renderDashboard,
    scraping: renderScraping,
    documents: renderDocuments,
    chat: renderChat,
    visualizer: renderChunkVisualizer,
};

let hasNavigated = false;

function navigate(page) {
    const target = pages[page] ? page : 'dashboard';

    document.querySelectorAll('.nav-item').forEach(el => {
        el.classList.remove('active');
        el.removeAttribute('aria-current');
    });
    const navEl = document.getElementById(`nav-${target}`);
    if (navEl) {
        navEl.classList.add('active');
        navEl.setAttribute('aria-current', 'page');
    }

    // Render immediately; navigation is frequent and must never wait.
    const main = document.getElementById('main-content');
    main.classList.remove('is-entering');
    main.classList.add('is-leaving');
    pages[target](main);
    window.scrollTo(0, 0);
    void main.offsetHeight;
    main.classList.add('is-entering');
    main.classList.remove('is-leaving');
    main.addEventListener('transitionend', () => main.classList.remove('is-entering'), { once: true });

    if (hasNavigated) main.focus({ preventScroll: true });
    hasNavigated = true;
}

function handleRoute() {
    const hash = window.location.hash.slice(1) || 'dashboard';
    navigate(hash);
}

window.addEventListener('hashchange', handleRoute);

// ============================================================
// Overview Page
// ============================================================

// Standard statement line items. For each, the table holding the most
// years in ล้านบาท wins, so the page follows whatever report is loaded.
const KEY_METRICS = [
    { label: 'สินทรัพย์รวม', title: 'สินทรัพย์รวม' },
    { label: 'กำไรสุทธิ (ส่วนที่เป็นของธนาคาร)', title: 'กำไรสุทธิส่วนของธนาคาร', short: 'กำไรสุทธิ' },
    { label: 'รายได้ดอกเบี้ยสุทธิ', title: 'รายได้ดอกเบี้ยสุทธิ' },
    { label: 'เงินรับฝาก', title: 'เงินรับฝาก' },
    { label: 'หนี้สินรวม', title: 'หนี้สินรวม' },
];

function sourceLabel(tableName) {
    const m = /^\[p(\d+)\]\s*(.*)$/.exec(String(tableName || ''));
    return m ? `${m[2] || 'ตาราง'} หน้า ${m[1]}` : String(tableName || '');
}

async function loadKeySeries() {
    const labels = KEY_METRICS.map(m => `'${m.label.replace(/'/g, "''")}'`).join(',');
    const data = await api.post('/warehouse/query', {
        sql: `SELECT row_label, metric_year, numeric_value, table_name FROM fact_financial_metrics
              WHERE row_label IN (${labels}) AND unit = 'ล้านบาท' AND numeric_value IS NOT NULL`,
    });
    const groups = {};
    (data.rows || []).forEach(r => {
        const key = `${r.row_label}\u0000${r.table_name}`;
        (groups[key] ||= { label: r.row_label, table: r.table_name, years: {} }).years[r.metric_year] = Number(r.numeric_value);
    });
    return KEY_METRICS.map(metric => {
        const best = Object.values(groups)
            .filter(g => g.label === metric.label)
            .sort((a, b) => Object.keys(b.years).length - Object.keys(a.years).length)[0];
        if (!best || Object.keys(best.years).length < 2) return null;
        const points = Object.keys(best.years).sort().map(yr => ({ x: yr, y: best.years[yr] }));
        return { ...metric, points, source: sourceLabel(best.table) };
    }).filter(Boolean);
}

function deltaText(points) {
    const last = points[points.length - 1];
    const prev = points[points.length - 2];
    if (!prev || !prev.y) return '';
    const pct = ((last.y - prev.y) / Math.abs(prev.y)) * 100;
    const glyph = pct > 0 ? '\u25B2' : pct < 0 ? '\u25BC' : '\u2022';
    return `<span class="delta-pill" title="เทียบกับปี ${escapeText(prev.x)}"><span aria-hidden="true">${glyph}</span>${Math.abs(pct).toFixed(1)}%<span class="visually-hidden"> ${pct >= 0 ? 'เพิ่มขึ้น' : 'ลดลง'}จากปี ${escapeText(prev.x)}</span></span>`;
}

function metricTile(series, hero = false, index = 0) {
    const last = series.points[series.points.length - 1];
    const question = `${series.title}ปี ${last.x} เท่าไร`;
    return `
        <a class="tile tile-metric${hero ? ' tile-hero' : ''}" href="#chat" data-question="${escapeText(question)}" style="--i:${index}"
            aria-label="ถาม: ${escapeText(question)}">
            <div class="tile-top">
                <div class="tile-label" title="${escapeText(series.title)}">${escapeText(series.short || series.title)} <span class="tile-year">${escapeText(last.x)}</span></div>
                <span class="tile-ask" aria-hidden="true">ถามเรื่องนี้</span>
            </div>
            <div class="tile-value">${last.y.toLocaleString()}<span class="tile-unit">ล้านบาท</span></div>
            <div class="tile-meta">${deltaText(series.points)}${hero ? `<span class="tile-source">ที่มา ${escapeText(series.source)}</span>` : ''}</div>
            <div class="chart chart-bleed" data-series="${escapeText(series.label)}"></div>
        </a>
    `;
}

async function renderDashboard(container) {
    container.innerHTML = `
        <section class="hero">
            ${AURORA_HTML}
            <h1 class="hero-title" lang="en">Every figure,<span class="line-2">traced to the page.</span></h1>
            <p class="hero-sub">ถามเป็นภาษาไทยได้ทันที ระบบค้นทั้งเนื้อความและตารางงบการเงินให้</p>
            <div class="ticker" aria-label="ข้อมูลในระบบ">
                <span>ข้อเท็จจริงทางการเงิน<b id="tick-facts">0</b></span>
                <span>เอกสาร<b id="tick-docs">0</b></span>
                <span>ข้อความที่ค้นได้<b id="tick-chunks">0</b></span>
                <span>แถวตาราง<b id="tick-rows">0</b></span>
            </div>
            <form class="ask-pill" id="overview-ask">
                <label for="overview-question" class="visually-hidden">คำถาม</label>
                <input id="overview-question" type="text" autocomplete="off" placeholder="เช่น สินทรัพย์รวมปี 2567 เท่าไร">
                <button type="submit" class="btn btn-primary">ถาม</button>
            </form>
        </section>

        <div class="bento" id="overview-bento">
            <div class="tile tile-hero"><div class="placeholder-line" style="width:40%"></div><div class="placeholder-line" style="width:60%;height:40px"></div></div>
        </div>
    `;

    document.getElementById('overview-ask').addEventListener('submit', (event) => {
        event.preventDefault();
        const input = document.getElementById('overview-question');
        const question = input.value.trim();
        if (!question) { input.focus(); return; }
        try { sessionStorage.setItem('pendingQuestion', question); } catch (_) { /* storage blocked */ }
        window.location.hash = 'chat';
    });

    const [docsResult, statusResult, seriesResult] = await Promise.allSettled([
        api.get('/documents'),
        api.get('/warehouse/status'),
        loadKeySeries(),
    ]);

    const docs = docsResult.status === 'fulfilled' ? (docsResult.value.documents || []) : [];
    const chunks = docs.reduce((sum, d) => sum + (d.chunk_count || 0), 0);
    const rows = docs.reduce((sum, d) => sum + (d.table_row_count || 0), 0);
    const facts = statusResult.status === 'fulfilled' ? statusResult.value.total_fact_records : 0;
    countUp(document.getElementById('tick-facts'), facts);
    countUp(document.getElementById('tick-docs'), docs.length);
    countUp(document.getElementById('tick-chunks'), chunks);
    countUp(document.getElementById('tick-rows'), rows);

    const bento = document.getElementById('overview-bento');
    if (!bento) return;
    const series = seriesResult.status === 'fulfilled' ? seriesResult.value : [];

    const recentDocs = docsResult.status === 'fulfilled'
        ? (docs.length
            ? `<ul class="doc-list">${docs.slice(0, 4).map(d => `
                <li>
                    <span class="file-chip">${escapeText((d.doc_type || 'file').replace('web_scrape', 'web').toUpperCase().slice(0, 4))}</span>
                    <div class="doc-text"><div class="name">${escapeText(d.filename)}</div>
                    <div class="meta">${(d.chunk_count || 0).toLocaleString()} chunks, ${(d.table_row_count || 0).toLocaleString()} แถวตาราง</div></div>
                    ${statusMark(d.status)}
                </li>`).join('')}</ul>`
            : '<p class="empty"><strong>ยังไม่มีเอกสาร</strong>เริ่มจากอัปโหลดในหน้าเอกสาร</p>')
        : `<p class="message is-error">โหลดรายการเอกสารไม่สำเร็จ (${escapeText(docsResult.reason?.message)})</p>`;

    bento.innerHTML = `
        ${series[0] ? metricTile(series[0], true, 0) : ''}
        ${series.slice(1, 5).map((s, i) => metricTile(s, false, i + 1)).join('')}
        <article class="tile tile-wide tile-docs" style="--i:5">
            <div class="section-head" style="margin:0">
                <div class="tile-label">เอกสารล่าสุด</div>
                <a href="#documents" class="link-btn">ดูทั้งหมด</a>
            </div>
            ${recentDocs}
        </article>
        <article class="tile tile-wide tile-flow" style="--i:6">
            <div class="tile-label">จากเอกสารถึงคำตอบ</div>
            <ol class="flow">
                <li><div class="step-name">รับเอกสาร</div><div class="step-detail">อัปโหลดหรือดึงจากเว็บ</div></li>
                <li><div class="step-name">OCR</div><div class="step-detail">อ่านข้อความและตาราง</div></li>
                <li><div class="step-name">ทำความสะอาด</div><div class="step-detail">PyThaiNLP</div></li>
                <li><div class="step-name">แบ่งเนื้อหา</div><div class="step-detail">Semantic + LLM</div></li>
                <li><div class="step-name">ตอบ</div><div class="step-detail">Vector + SQL</div></li>
            </ol>
        </article>
    `;
    if (!series.length) {
        bento.insertAdjacentHTML('afterbegin', `<article class="tile tile-hero"><p class="empty"><strong>ยังไม่มีตัวเลขงบการเงินในคลัง</strong>อัปโหลดรายงานประจำปีเพื่อให้ตัวเลขสำคัญขึ้นที่นี่</p></article>`);
    }

    const draw = (animate) => series.forEach((s, i) => {
        const el = bento.querySelector(`.chart[data-series="${CSS.escape(s.label)}"]`);
        renderLineChart(el, s.points, { height: i === 0 ? 250 : 92, axis: i === 0, unit: 'ล้านบาท', title: s.title, animate, padX: i === 0 ? 28 : 6 });
    });
    draw(true);
    bento.addEventListener('click', (event) => {
        const tile = event.target.closest('.tile-metric');
        if (!tile) return;
        event.preventDefault();
        try { sessionStorage.setItem('pendingQuestion', tile.dataset.question); } catch (_) { /* storage blocked */ }
        window.location.hash = 'chat';
    });
    let resizeTimer = null;
    const observer = new ResizeObserver(() => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            if (!document.body.contains(bento)) { observer.disconnect(); return; }
            draw(false);
        }, 150);
    });
    observer.observe(bento);
}

// ============================================================
// Initialize
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    syncThemeToggle();
    document.getElementById('theme-toggle')?.addEventListener('click', toggleTheme);
    handleRoute();

    const status = document.getElementById('system-status');
    const statusText = document.getElementById('system-status-text');
    api.get('/health')
        .then(() => { status.dataset.state = 'online'; statusText.textContent = 'Ready'; })
        .catch(() => { status.dataset.state = 'offline'; statusText.textContent = 'Offline'; });
});
