/**
 * Ask (chat) Component
 * Empty state is a hero: the light field, a large question prompt, one pill
 * input. Once a question is asked the hero steps back, the pill docks to the
 * bottom of the screen and the page becomes a conversation: the reader's
 * questions on the right, answers on the left with their evidence (the PDF
 * page and the notes) under each answer, and follow-up questions to tap.
 *
 * The query API is single-turn, so follow-ups ("แล้วปี 2565 ล่ะ") are resolved
 * here into a full question from the previous answer's metric and year, and
 * the resolved question is shown under the reader's bubble.
 */

// Questions answerable from the annual report already in the corpus.
const CHAT_EXAMPLE_QUESTIONS = [
    { q: 'สินทรัพย์รวมปี 2567 เท่าไร', kind: 'ตัวเลขจากตาราง' },
    { q: 'กำไรสุทธิปี 2567 เทียบกับปีก่อน', kind: 'เทียบสองปี' },
    { q: 'กรุงศรีมีเป้าหมาย Net Zero ภายในปีใด', kind: 'ข้อความในเอกสาร' },
];

// Retrieval methods named the way a reader understands them; the raw
// method id stays available as a tooltip for whoever is debugging.
const CHAT_METHODS = {
    vector: 'ค้นจากข้อความในเอกสาร',
    sql: 'ค้นจากตารางข้อมูล',
    hybrid: 'ค้นทั้งข้อความและตาราง',
    multi_hop: 'ค้นหลายขั้นตอน',
    graph: 'ค้นจากความสัมพันธ์ขององค์กร',
    graph_sql_hybrid: 'ค้นจากความสัมพันธ์และตาราง',
    direct_structured_fact: 'ดึงจากตารางโดยตรง',
};

const CHAT_QUALITY = {
    passed_checks: { cls: 'mark-ok', label: 'ผ่านการตรวจ' },
    unverified: { cls: 'mark-query', label: 'ยังไม่ตรวจตัวเลข' },
    unknown: { cls: 'mark-none', label: 'ไม่ทราบคุณภาพ' },
};

// Long note lists fold away past this many.
const NOTES_VISIBLE = 5;

let chatExchangeSeq = 0;

// What the conversation is about, for resolving follow-ups.
let chatContext = { label: null, year: null };
const FOLLOW_UP_CUE = /(แล้ว|ล่ะ|ละ|ปีก่อน|ปีที่แล้ว|เทียบ|ย้อนหลัง|ต่อ)/;
const PREV_YEAR_CUE = /(ปีก่อน|ปีที่แล้ว)/;
const FOLLOW_UP_METRICS = ['สินทรัพย์รวม', 'หนี้สินรวม', 'เงินรับฝาก', 'รายได้ดอกเบี้ยสุทธิ', 'กำไรสุทธิ'];
const BOT_MARK = '<svg class="brand-mark" viewBox="0 0 24 24" aria-hidden="true"><path class="logo-page" d="M7 2H14.6L19.5 6.9V10.4H4.5V4.5A2.5 2.5 0 0 1 7 2Z"/><path class="logo-fold" d="M14.6 2V5.2A1.7 1.7 0 0 0 16.3 6.9H19.5Z"/><rect class="logo-hl" x="2" y="12" width="20" height="3.6" rx="1.8"/><path class="logo-page" d="M4.5 17.2H19.5V19.5A2.5 2.5 0 0 1 17 22H7A2.5 2.5 0 0 1 4.5 19.5Z"/></svg>';

function renderChat(container) {
    container.innerHTML = `
        <div class="ask-page" id="ask-page">
            <section class="hero ask-hero">
                ${AURORA_HTML.replace('class="aurora"', 'class="aurora is-ask"')}
                <div class="ask-grid">
                    <div class="ask-copy">
                        <h1 class="hero-title" lang="en">Ask the report.<span class="line-2">Get the page it came from.</span></h1>
                        <p class="hero-sub">ถามเป็นภาษาไทยได้เลย ทุกตัวเลขในคำตอบจะมีหน้า PDF ที่มาแนบไว้ให้เปิดดูเทียบได้ทันที</p>
                        <form class="ask-pill" id="chat-form">
                            <label for="chat-input" class="visually-hidden">คำถาม</label>
                            <textarea id="chat-input" rows="1" autocomplete="off"
                                placeholder="ถามอะไรก็ได้เกี่ยวกับเอกสารในระบบ"></textarea>
                            <button type="submit" class="btn btn-primary" id="btn-send">ถาม</button>
                        </form>
                        <label class="demo-switch">
                            <input type="checkbox" id="demo-toggle" role="switch">
                            <span class="switch-track" aria-hidden="true"></span>
                            <span>โหมดจำลอง <span class="demo-note">ตอบจาก warehouse และข้อความในเอกสารโดยตรง ไม่เรียกโมเดล</span></span>
                        </label>
                    </div>
                    <div class="page-fan" id="page-fan" aria-hidden="true"></div>
                </div>
                <div class="ask-cards" id="chat-welcome">
                    ${CHAT_EXAMPLE_QUESTIONS.map((ex, i) => `
                        <button type="button" class="example ask-card" data-question="${escapeHtml(ex.q)}" style="--i:${i}">
                            <span class="ask-card-kind">${escapeHtml(ex.kind)}</span>
                            <span class="ask-card-q">${escapeHtml(ex.q)}</span>
                            <span class="ask-card-foot" data-example-foot="${i}">ถามเลย<i class="ph ph-arrow-up-right" aria-hidden="true"></i></span>
                        </button>`).join('')}
                </div>
            </section>

            <div class="chat-head" id="chat-head">
                <span class="chat-title">การสนทนา</span>
                <span class="demo-badge" id="chat-demo-badge" hidden>โหมดจำลอง</span>
                <button type="button" class="chip-btn" id="btn-new-chat"><i class="ph ph-plus" aria-hidden="true"></i>แชทใหม่</button>
            </div>
            <div class="thread" id="chat-messages" aria-live="polite"></div>
        </div>

        <div class="composer" id="chat-composer">
            <div class="composer-slot"></div>
            <div class="composer-hint">Enter เพื่อส่ง, Shift+Enter ขึ้นบรรทัดใหม่</div>
        </div>

        <dialog class="page-viewer" id="page-viewer" aria-label="หน้าเอกสาร">
            <div class="page-viewer-head">
                <div><strong id="page-viewer-title"></strong><span id="page-viewer-sub"></span></div>
                <button type="button" class="icon-button" id="page-viewer-close" aria-label="ปิด"><i class="ph ph-x" aria-hidden="true"></i></button>
            </div>
            <div class="page-viewer-body"><img id="page-viewer-img" alt=""></div>
        </dialog>
    `;

    const input = document.getElementById('chat-input');
    const form = document.getElementById('chat-form');
    const page = document.getElementById('ask-page');

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        sendMessage();
    });
    input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
            event.preventDefault();
            sendMessage();
        }
    });
    input.addEventListener('input', () => autosizeComposer(input));

    page.addEventListener('click', (event) => {
        const chunkLink = event.target.closest('[data-open-chunk]');
        if (chunkLink) {
            try {
                sessionStorage.setItem('selectedDocId', chunkLink.dataset.doc);
                sessionStorage.setItem('selectedChunk', chunkLink.dataset.chunk);
            } catch (_) { /* storage blocked */ }
            window.location.hash = 'visualizer';
            return;
        }
        const opener = event.target.closest('[data-open-page]');
        if (opener) {
            event.preventDefault();
            openPageViewer(opener.dataset.doc, opener.dataset.page, opener.dataset.title || '');
            return;
        }
        const copy = event.target.closest('[data-copy-answer]');
        if (copy) {
            copyAnswer(copy);
            return;
        }
        const example = event.target.closest('.example, .follow-up');
        if (!example) return;
        input.value = example.dataset.question;
        sendMessage();
    });

    document.getElementById('btn-new-chat').addEventListener('click', resetChat);
    chatContext = { label: null, year: null };

    // Pointing at an example lifts the page it will be answered from.
    page.addEventListener('mouseover', (event) => {
        const card = event.target.closest('.ask-card');
        if (card && card.dataset.page) liftFanPage(card.dataset.page);
    });

    const demoToggle = document.getElementById('demo-toggle');
    demoToggle.checked = demoModeOn();
    demoToggle.addEventListener('change', () => setDemoMode(demoToggle.checked));

    const viewer = document.getElementById('page-viewer');
    document.getElementById('page-viewer-close').addEventListener('click', () => viewer.close());
    viewer.addEventListener('click', (event) => { if (event.target === viewer) viewer.close(); });

    buildPageFan();

    // Pointing at a note number lights up its note, and the reverse.
    const linkHighlight = (event, on) => {
        const node = event.target.closest('[data-source-index]');
        if (!node) return;
        const exchange = node.closest('.exchange');
        if (!exchange) return;
        const index = node.dataset.sourceIndex;
        exchange.querySelectorAll(`[data-source-index="${index}"]`).forEach(el => {
            el.classList.toggle('is-linked', on);
            el.querySelector('.note-ref')?.classList.toggle('is-linked', on);
        });
        if (on) showEvidencePage(exchange, index);
    };
    page.addEventListener('mouseover', (e) => linkHighlight(e, true));
    page.addEventListener('mouseout', (e) => linkHighlight(e, false));
    page.addEventListener('focusin', (e) => linkHighlight(e, true));
    page.addEventListener('focusout', (e) => linkHighlight(e, false));

    // A question typed on the overview arrives here.
    let pending = null;
    try {
        pending = sessionStorage.getItem('pendingQuestion');
        sessionStorage.removeItem('pendingQuestion');
    } catch (_) { /* storage blocked */ }
    if (pending) {
        input.value = pending;
        sendMessage();
    } else {
        input.focus({ preventScroll: true });
    }
}

function autosizeComposer(input) {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
}

// The hero steps back and the pill docks to the bottom of the screen.
function dockComposer() {
    const page = document.getElementById('ask-page');
    if (!page || page.classList.contains('has-thread')) return;
    page.classList.add('has-thread');
    document.querySelector('#chat-composer .composer-slot')?.appendChild(document.getElementById('chat-form'));
    document.getElementById('chat-input').placeholder = 'ถามต่อได้เลย เช่น แล้วปีก่อนล่ะ';
    const badge = document.getElementById('chat-demo-badge');
    if (badge) badge.hidden = !demoModeOn();
}

// Back to an empty conversation: the hero returns and the pill goes home.
function resetChat() {
    const page = document.getElementById('ask-page');
    const form = document.getElementById('chat-form');
    const input = document.getElementById('chat-input');
    document.getElementById('chat-messages').innerHTML = '';
    chatContext = { label: null, year: null };
    page.classList.remove('has-thread');
    document.querySelector('.ask-copy .demo-switch')?.before(form);
    input.placeholder = 'ถามอะไรก็ได้เกี่ยวกับเอกสารในระบบ';
    input.value = '';
    autosizeComposer(input);
    window.scrollTo({ top: 0, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
    input.focus({ preventScroll: true });
}

function sourcePage(source) {
    const documentId = Number(source.document_id);
    const page = Number(source.page);
    const hasPage = Number.isInteger(documentId) && documentId > 0
        && Number.isInteger(page) && page > 0;
    return { documentId, page, hasPage };
}

function safeWebUrl(source) {
    if (source.type !== 'web' || !source.url) return null;
    try {
        const url = new URL(source.url);
        if (url.protocol === 'https:' || url.protocol === 'http:') return url;
    } catch (_) { /* Invalid URL remains uncited. */ }
    return null;
}

// Superscript note number inside the answer text.
function renderNoteRef(source, sourceIndex) {
    const n = Number(sourceIndex) + 1;
    const { documentId, page, hasPage } = sourcePage(source);
    const filename = escapeHtml(String(source.filename || 'Document'));
    if (hasPage) {
        return `<a class="note-ref" href="/api/documents/${documentId}/pages/${page}/image" target="_blank" rel="noopener"
            data-open-page data-doc="${documentId}" data-page="${page}" data-title="${filename}"
            aria-label="หมายเหตุ ${n}: ${filename} หน้า ${page}">${n}</a>`;
    }
    const url = safeWebUrl(source);
    if (url) {
        return `<a class="note-ref" href="${escapeHtml(url.href)}" target="_blank" rel="noopener"
            aria-label="หมายเหตุ ${n}: ${escapeHtml(String(source.title || url.hostname))}">${n}</a>`;
    }
    return `<span class="note-ref" aria-label="หมายเหตุ ${n}: ${filename} ไม่ทราบหน้า">${n}</span>`;
}

// One note in the properties column.
function renderChatSource(source, sourceIndex = 0) {
    const n = Number(sourceIndex) + 1;
    const { documentId, page, hasPage } = sourcePage(source);
    const url = safeWebUrl(source);

    let origin;
    if (url && !hasPage) {
        origin = `${escapeHtml(String(source.title || url.hostname))} <span class="note-page">${escapeHtml(url.hostname)}</span>`;
    } else {
        origin = `${escapeHtml(String(source.filename || 'Document'))} <span class="note-page">${hasPage ? `หน้า ${page}` : 'ไม่ทราบหน้า'}</span>`;
    }

    const cellParts = [source.row_label, source.column]
        .filter(value => value !== null && value !== undefined && String(value).trim())
        .map(value => escapeHtml(String(value)));
    const hasValue = source.value !== null && source.value !== undefined && String(source.value).trim();
    const cell = cellParts.length ? `<div class="note-cell">${cellParts.join(', ')}</div>` : '';
    const value = hasValue ? `<span class="note-value">${escapeHtml(String(source.value))}</span>` : '';
    const excerpt = !cell && !value && source.excerpt
        ? `<div class="note-excerpt">${escapeHtml(String(source.excerpt).replace(/\s+/g, ' ').slice(0, 220))}</div>`
        : '';

    const quality = CHAT_QUALITY[source.quality_status] || CHAT_QUALITY.unknown;
    let open = '';
    if (hasPage) {
        open = `<a href="/api/documents/${documentId}/pages/${page}/image" target="_blank" rel="noopener"
            data-open-page data-doc="${documentId}" data-page="${page}" data-title="${escapeHtml(String(source.filename || 'Document'))}">เปิดหน้า</a>`;
    } else if (url) {
        open = `<a href="${escapeHtml(url.href)}" target="_blank" rel="noopener">เปิดเว็บ</a>`;
    }

    return `
        <li class="note" data-source-index="${Number(sourceIndex)}">
            <span class="note-n">${n}</span>
            <div>
                <div class="note-src">${origin}</div>
                ${cell}${value}${excerpt}
                <div class="note-foot"><span class="mark ${quality.cls}">${quality.label}</span>${open}</div>
            </div>
        </li>
    `;
}

function renderNoteList(sources) {
    const rows = sources.map((s, i) => renderChatSource(s, i));
    const head = rows.slice(0, NOTES_VISIBLE).join('');
    const rest = rows.slice(NOTES_VISIBLE);
    return `
        <ol class="notes">${head}</ol>
        ${rest.length ? `
            <details class="notes-more">
                <summary>อีก ${rest.length} หมายเหตุ</summary>
                <ol class="notes">${rest.join('')}</ol>
            </details>
        ` : ''}
    `;
}

// Only sources a claim actually cites become notes. Anything retrieved but
// not cited folds away under the answer, so an "insufficient evidence" answer
// is not framed by a column of evidence.
function renderNotes(sources, citations) {
    if (!Array.isArray(sources) || sources.length === 0) return { margin: '', retrieved: '' };
    const cited = Array.isArray(citations) && citations.length > 0;
    if (cited) {
        return {
            margin: `
                <section class="evidence evidence-inline" aria-label="ที่มาของคำตอบ">
                    ${renderEvidencePage(sources, citations)}
                    <div class="evidence-notes">
                        <div class="notes-head">ที่มา</div>
                        ${renderNoteList(sources)}
                        <p class="evidence-caveat">ค่าจาก OCR ยังไม่ได้ตรวจเทียบด้วยตา กดภาพหน้าเพื่อเทียบกับต้นฉบับ</p>
                    </div>
                </section>
            `,
            retrieved: '',
        };
    }
    return {
        margin: '',
        retrieved: `
            <details class="retrieved">
                <summary>ข้อมูลที่ค้นเจอแต่ไม่ได้ใช้อ้างอิง (${sources.length} รายการ)</summary>
                <ol class="notes">${sources.map((s, i) => renderChatSource(s, i)).join('')}</ol>
            </details>
        `,
    };
}

// ------------------------------------------------------------------
// The page itself
// ------------------------------------------------------------------
function pageImageUrl(documentId, page) {
    return `/api/documents/${documentId}/pages/${page}/image`;
}

// The evidence column opens on the first cited page; pointing at another
// note or note number swaps the page in place.
function renderEvidencePage(sources, citations) {
    const firstCited = (citations || []).map(c => c.source_index).find(i => sourcePage(sources[i] || {}).hasPage);
    const index = firstCited ?? sources.findIndex(s => sourcePage(s).hasPage);
    if (index === undefined || index < 0) {
        // No page number: show the passage itself and where it sits among the chunks.
        const cited = sources[(citations || [])[0]?.source_index] || sources[0] || {};
        if (cited.excerpt) {
            const chunk = Number.isInteger(cited.chunk_index) ? cited.chunk_index : null;
            return `
                <figure class="quote-card">
                    <i class="ph ph-quotes" aria-hidden="true"></i>
                    ${quoteContext(cited)}
                    <figcaption>${escapeHtml(String(cited.filename || 'Document'))}${chunk !== null ? `, chunk ${chunk}` : ''}</figcaption>
                    ${chunk !== null && cited.document_id ? `<button type="button" class="chip-btn" data-open-chunk data-doc="${Number(cited.document_id)}" data-chunk="${chunk}"><i class="ph ph-rows" aria-hidden="true"></i>ดูใน Chunks</button>` : ''}
                    <p>แหล่งข้อมูลนี้ไม่มีเลขหน้า PDF</p>
                </figure>`;
        }
        return `<div class="page-preview is-empty"><span class="skeleton-page"></span><p>แหล่งข้อมูลนี้ไม่มีเลขหน้า PDF</p></div>`;
    }
    const s = sources[index];
    const { documentId, page } = sourcePage(s);
    const title = escapeHtml(String(s.filename || 'Document'));
    return `
        <button type="button" class="page-preview" data-open-page data-doc="${documentId}" data-page="${page}" data-title="${title}"
            aria-label="เปิดหน้า ${page} ของ ${title} แบบเต็ม">
            <img src="${pageImageUrl(documentId, page)}" alt="" loading="lazy">
            <span class="page-tab">หน้า <b>${page}</b></span>
            <span class="page-zoom"><i class="ph ph-arrows-out-simple" aria-hidden="true"></i>ดูเต็มหน้า</span>
        </button>`;
}

// A passage answer: the clause that answers, its key terms marked, and where it sits.
function renderAnswerQuote(quote) {
    let html = escapeHtml(String(quote.text || ''));
    (quote.marks || []).forEach(m => {
        const e = escapeHtml(String(m));
        const at = html.indexOf(e);
        if (at >= 0) html = `${html.slice(0, at)}<mark>${e}</mark>${html.slice(at + e.length)}`;
    });
    const s = quote.source || {};
    const chunk = Number.isInteger(s.chunk_index) ? s.chunk_index : null;
    return `
        <figure class="answer-quote">
            <blockquote>${html}</blockquote>
            <figcaption>
                <span class="quote-src"><i class="ph ph-file-text" aria-hidden="true"></i>${escapeHtml(String(s.filename || 'Document'))}${chunk !== null ? `<span>chunk ${chunk}, ไม่มีเลขหน้า PDF</span>` : ''}</span>
                ${chunk !== null && s.document_id ? `<button type="button" class="chip-btn" data-open-chunk data-doc="${Number(s.document_id)}" data-chunk="${chunk}"><i class="ph ph-rows" aria-hidden="true"></i>ดูใน Chunks</button>` : ''}
            </figcaption>
            ${s.context ? `<details class="quote-more"><summary>อ่านข้อความทั้งช่วง</summary>${quoteContext(s)}</details>` : ''}
        </figure>`;
}

// The whole chunk, with the quoted window marked.
function quoteContext(source) {
    const quote = String(source.excerpt || '');
    const context = String(source.context || '');
    const core = quote.replace(/^…|…$/g, '');
    const at = context && core ? context.indexOf(core) : -1;
    if (at < 0) return `<blockquote class="quote-context">${escapeHtml(quote)}</blockquote>`;
    return `<blockquote class="quote-context">${escapeHtml(context.slice(0, at))}<mark>${escapeHtml(core)}</mark>${escapeHtml(context.slice(at + core.length))}</blockquote>`;
}

function showEvidencePage(exchange, index) {
    const note = exchange.querySelector(`.note[data-source-index="${index}"] [data-open-page]`)
        || exchange.querySelector(`.answer [data-source-index="${index}"] [data-open-page]`);
    const preview = exchange.querySelector('.evidence .page-preview:not(.is-empty)');
    if (!note || !preview) return;
    if (preview.dataset.page === note.dataset.page && preview.dataset.doc === note.dataset.doc) return;
    preview.dataset.doc = note.dataset.doc;
    preview.dataset.page = note.dataset.page;
    preview.querySelector('.page-tab b').textContent = note.dataset.page;
    const img = preview.querySelector('img');
    img.classList.add('is-swapping');
    img.onload = () => img.classList.remove('is-swapping');
    img.src = pageImageUrl(note.dataset.doc, note.dataset.page);
}

function openPageViewer(documentId, page, title) {
    const viewer = document.getElementById('page-viewer');
    if (!viewer) return;
    document.getElementById('page-viewer-title').textContent = title || 'เอกสาร';
    document.getElementById('page-viewer-sub').textContent = `หน้า ${page}`;
    const img = document.getElementById('page-viewer-img');
    img.alt = `${title} หน้า ${page}`;
    img.src = pageImageUrl(documentId, page);
    viewer.showModal();
}

// Hero: the pages the warehouse holds the most figures from, fanned out.
async function buildPageFan() {
    const fan = document.getElementById('page-fan');
    if (!fan) return;
    try {
        const data = await api.post('/warehouse/query', {
            sql: `SELECT document_id, table_name, count(*) AS n FROM fact_financial_metrics
                  WHERE table_name LIKE '[p%' AND unit = 'ล้านบาท' GROUP BY 1, 2 ORDER BY n DESC LIMIT 12`,
        });
        const seen = new Set();
        const pages = [];
        (data.rows || []).forEach(r => {
            const page = pageFromTable(r.table_name);
            const key = `${r.document_id}:${page}`;
            if (page && !seen.has(key) && pages.length < 3) { seen.add(key); pages.push({ doc: r.document_id, page }); }
        });
        if (!pages.length) return;
        fan.innerHTML = pages.map((p, i) => `
            <figure class="fan-page" data-page="${p.page}" style="--k:${i}">
                <img src="${pageImageUrl(p.doc, p.page)}" alt="" loading="lazy">
                <figcaption class="page-tab">หน้า <b>${p.page}</b></figcaption>
            </figure>`).join('');
        fan.querySelector('.fan-page')?.classList.add('is-front');
        labelExampleCards();
    } catch (_) { /* the fan is decoration; leave it empty */ }
}

function liftFanPage(page) {
    const target = document.querySelector(`#page-fan .fan-page[data-page="${page}"]`);
    if (!target) return;
    document.querySelectorAll('#page-fan .fan-page').forEach(el => el.classList.toggle('is-front', el === target));
}

// Example cards say which page they will be answered from, when the warehouse knows.
async function labelExampleCards() {
    try {
        const labels = await demoLoadLabels();
        for (const [i, ex] of CHAT_EXAMPLE_QUESTIONS.entries()) {
            const label = demoMatchLabel(ex.q, labels);
            if (!label) continue;
            const data = await api.post('/warehouse/query', {
                sql: `SELECT table_name, count(*) AS n FROM fact_financial_metrics WHERE row_label = ${sqlText(label)}
                      AND unit = 'ล้านบาท' AND table_name LIKE '[p%' GROUP BY 1 ORDER BY n DESC LIMIT 1`,
            });
            const page = pageFromTable(data.rows?.[0]?.table_name);
            const foot = document.querySelector(`[data-example-foot="${i}"]`);
            if (!page || !foot) continue;
            foot.closest('.ask-card').dataset.page = page;
            foot.innerHTML = `ตอบจากหน้า ${page}<i class="ph ph-arrow-up-right" aria-hidden="true"></i>`;
        }
    } catch (_) { /* labels are a nicety */ }
}

function methodLabel(method) {
    const key = String(method || '');
    return `<span title="method: ${escapeHtml(key)}">${escapeHtml(CHAT_METHODS[key] || key || 'ไม่ทราบวิธีค้น')}</span>`;
}

function scrollToExchange(el) {
    el.scrollIntoView({ block: 'start', behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
}

// Turn a follow-up into a full question the single-turn API can answer.
async function resolveQuestion(question) {
    let labels = [];
    try { labels = await demoLoadLabels(); } catch (_) { return question; }
    const label = demoMatchLabel(question, labels);
    let year = (/25\d\d/.exec(question) || [])[0] || null;
    const follow = FOLLOW_UP_CUE.test(question) || Array.from(question).length <= 24;
    if (!year && chatContext.year && PREV_YEAR_CUE.test(question)) year = String(Number(chatContext.year) - 1);
    if (label && !year && chatContext.year && follow) return `${label} ปี ${chatContext.year} เท่าไร`;
    if (!label && chatContext.label && follow && year) return `${chatContext.label} ปี ${year} เท่าไร`;
    return question;
}

// Questions worth asking next, built from what the answer just showed.
function followUpQuestions(result) {
    const s = result.series;
    if (!s) return [];
    const years = s.points.map(p => p.x);
    const at = years.indexOf(String(s.year));
    const out = [];
    if (at > 0) out.push(`แล้วปี ${years[at - 1]} ล่ะ`);
    FOLLOW_UP_METRICS.filter(m => !String(s.title).startsWith(m)).slice(0, 2).forEach(m => out.push(`แล้ว${m}ล่ะ`));
    return out;
}

async function copyAnswer(button) {
    // Copy the answer without its note numbers.
    const answer = button.closest('.msg-body')?.querySelector('.answer')?.cloneNode(true);
    answer?.querySelectorAll('.note-ref').forEach(ref => ref.remove());
    const text = (answer?.textContent || '').replace(/\s+/g, ' ').trim();
    try {
        await navigator.clipboard.writeText(text);
        button.classList.add('is-done');
        button.querySelector('span').textContent = 'คัดลอกแล้ว';
        setTimeout(() => {
            button.classList.remove('is-done');
            button.querySelector('span').textContent = 'คัดลอก';
        }, 1600);
    } catch (_) {
        showToast('คัดลอกไม่สำเร็จ เบราว์เซอร์ไม่อนุญาต', 'warning');
    }
}

async function sendMessage() {
    const input = document.getElementById('chat-input');
    const question = input.value.trim();
    if (!question) return;

    const messages = document.getElementById('chat-messages');
    const sendBtn = document.getElementById('btn-send');
    if (sendBtn.disabled) return;
    dockComposer();

    // insertAdjacentHTML, not innerHTML +=: re-parsing the thread would rebuild
    // every earlier turn, closing open notes and replaying entrances.
    const id = `exchange-${++chatExchangeSeq}`;
    messages.insertAdjacentHTML('beforeend', `
        <article class="exchange turn" id="${id}">
            <div class="msg-user">
                <h2 class="bubble">${escapeHtml(question)}</h2>
            </div>
            <div class="msg-bot">
                <span class="bot-avatar">${BOT_MARK}</span>
                <div class="msg-body exchange-main">
                    <div class="thinking" aria-label="กำลังเรียบเรียงคำตอบ">
                        <span class="typing" aria-hidden="true"><i></i><i></i><i></i></span>
                        <span class="loading-text">${demoModeOn() ? 'กำลังค้นใน warehouse และเอกสาร' : 'กำลังค้นข้อมูลและเรียบเรียงคำตอบ'}</span>
                    </div>
                </div>
            </div>
        </article>
    `);
    const exchange = document.getElementById(id);
    const body = exchange.querySelector('.msg-body');
    scrollToExchange(exchange);

    input.value = '';
    autosizeComposer(input);
    sendBtn.disabled = true;

    try {
        const resolved = await resolveQuestion(question);
        if (resolved !== question) {
            exchange.querySelector('.msg-user').insertAdjacentHTML('beforeend',
                `<div class="msg-resolved"><i class="ph ph-arrow-bend-down-right" aria-hidden="true"></i>ตีความเป็น "${escapeHtml(resolved)}"</div>`);
        }
        const result = demoModeOn() ? await demoAnswer(resolved) : await api.post('/query', { question: resolved });
        // A quoted passage carries its own source line; it needs no notes card.
        const notes = result.quote ? { margin: '', retrieved: '' } : renderNotes(result.sources, result.claim_citations);
        const sql = result.sql_info && result.sql_info.sql
            ? `<details class="sql-used"><summary>SQL ที่ใช้</summary><pre class="code-block">${escapeHtml(result.sql_info.sql)}</pre></details>`
            : '';
        const follow = followUpQuestions(result);
        body.querySelector('.thinking').outerHTML = `
            <div class="answer">${formatCapturedAnswer(result)}</div>
            <div class="answer-tail"></div>
            <div class="answer-meta">
                <button type="button" class="meta-btn" data-copy-answer><i class="ph ph-copy" aria-hidden="true"></i><span>คัดลอก</span></button>
                ${result.demo ? '<span class="demo-badge" title="คำตอบนี้ประกอบจากข้อมูลในระบบโดยตรง ไม่ได้เรียกโมเดล">คำตอบจำลอง</span>' : ''}
                ${methodLabel(result.method)}
                ${sql}
            </div>
            ${follow.length ? `<div class="follow-ups" aria-label="ถามต่อ">${follow.map(q =>
                `<button type="button" class="follow-up" data-question="${escapeHtml(q)}">${escapeHtml(q)}<i class="ph ph-arrow-right" aria-hidden="true"></i></button>`).join('')}</div>` : ''}
        `;
        const tail = body.querySelector('.answer-tail');
        if (result.quote) {
            const answerEl = body.querySelector('.answer');
            if (Array.from(String(result.answer)).length <= 40) answerEl.classList.add('is-short');
            tail.insertAdjacentHTML('beforeend', renderAnswerQuote(result.quote));
        }
        if (result.series && result.series.points.length > 1) {
            const s = result.series;
            const first = s.points[0].x, last = s.points[s.points.length - 1].x;
            tail.insertAdjacentHTML('beforeend', `
                <figure class="answer-chart">
                    <figcaption>${escapeHtml(s.title)} ปี ${escapeHtml(first)} ถึง ${escapeHtml(last)} <span>${escapeHtml(s.unit)}${s.page ? `, ตารางหน้า ${s.page}` : ''}</span></figcaption>
                    <div class="chart"></div>
                </figure>`);
            renderLineChart(tail.querySelector('.answer-chart .chart'), s.points, { height: 160, axis: true, unit: s.unit, title: s.title, padX: 22 });
            chatContext = { label: s.title, year: String(s.year) };
        }
        if (notes.margin) tail.insertAdjacentHTML('beforeend', notes.margin);
        if (notes.retrieved) tail.insertAdjacentHTML('beforeend', notes.retrieved);
    } catch (e) {
        exchange.classList.add('is-error');
        body.querySelector('.thinking').outerHTML = `
            <div class="answer">ส่งคำถามไม่สำเร็จ (${escapeHtml(e.message)}) คำถามถูกใส่กลับในช่องพิมพ์แล้ว ลองส่งอีกครั้ง</div>
        `;
        input.value = question;
        autosizeComposer(input);
    }

    sendBtn.disabled = false;
    input.focus({ preventScroll: true });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function formatAnswer(text) {
    // Basic formatting: newlines to <br>, detect simple markdown bold
    return escapeHtml(String(text || ''))
        .replace(/\n/g, '<br>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
}

function formatCapturedAnswer(result) {
    const answer = String(result.answer || '');
    const points = Array.from(answer);
    const slice = (start, end) => points.slice(start, end).join('');
    const spans = result.claim_spans;
    const claims = result.answer_claims;
    const links = result.claim_citations;
    if (!Array.isArray(spans) || !Array.isArray(claims) || !Array.isArray(links)
        || spans.length !== claims.length) return formatAnswer(answer);
    let output = '', cursor = 0;
    for (let i = 0; i < spans.length; i++) {
        const { start, end } = spans[i];
        if (!Number.isInteger(start) || !Number.isInteger(end) || start < cursor
            || end <= start || end > points.length || slice(start, end) !== claims[i])
            return formatAnswer(answer);
        output += formatAnswer(slice(cursor, end));
        for (const link of links.filter(link => link.claim_index === i)) {
            const source = (result.sources || [])[link.source_index];
            if (source && source.source_id === link.source_id) {
                output += `<span data-claim-index="${i}" data-source-index="${link.source_index}">${renderNoteRef(source, link.source_index)}</span>`;
            }
        }
        cursor = end;
    }
    return output + formatAnswer(slice(cursor));
}
