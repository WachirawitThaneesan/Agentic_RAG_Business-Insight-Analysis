/**
 * Web Scraping Component
 * A keyword goes out, sites come back. The crawl map draws the run as it
 * happens: the keyword at the centre, each site Google returns on an orbit,
 * the site being read pulsing, and every PDF it yields as a satellite dot.
 * Every state on the map comes from the progress stream, nothing is staged.
 */

const SCRAPE_BUTTON_IDLE = 'เริ่มค้นหา';
const CRAWL_W = 640;
const CRAWL_H = 440;
const CRAWL_R = 160;

let crawlState = null;
let crawlTimer = null;

function renderScraping(container) {
    container.innerHTML = `
        <section class="scrape-hero">
            ${AURORA_HTML.replace('class="aurora"', 'class="aurora is-web"')}
            <h1 class="hero-title" lang="en">Send it to the web.<span class="line-2">Bring back every PDF it finds.</span></h1>
            <p class="hero-sub">ใส่ keyword ระบบจะค้นใน Google เข้าไปทีละเว็บ ดึงเอกสาร PDF แล้วนำเข้าสู่ระบบให้ถามต่อได้</p>

            <form class="ask-pill" id="scrape-form" style="margin-top:28px">
                <label for="scrape-keyword" class="visually-hidden">Keyword</label>
                <input type="text" id="scrape-keyword" autocomplete="off" placeholder="เช่น งบการเงิน PTT 2567, รายงานความยั่งยืน SCB">
                <button type="submit" class="btn btn-primary" id="btn-scrape">${SCRAPE_BUTTON_IDLE}</button>
            </form>

            <div class="scrape-settings">
                ${stepperHtml('max-sites-slider', 'เว็บไซต์จาก Google', 3, 1, 10)}
                ${stepperHtml('max-files-slider', 'PDF สูงสุดต่อเว็บ', 10, 1, 30)}
            </div>
        </section>

        <section class="crawl" aria-labelledby="crawl-title">
            <h2 class="visually-hidden" id="crawl-title">Crawl map</h2>
            <div class="crawl-map" id="crawl-map"></div>
            <div class="crawl-side">
                <dl class="crawl-stats">
                    <div><dt>เว็บที่เข้าแล้ว</dt><dd><b id="crawl-sites">0</b><span id="crawl-sites-total"></span></dd></div>
                    <div><dt>PDF ที่เจอ</dt><dd><b id="crawl-files">0</b></dd></div>
                    <div><dt>เวลา</dt><dd><b id="crawl-time">0:00</b></dd></div>
                </dl>
                <div id="scrape-progress" role="status" aria-live="polite">
                    <div class="run-status">
                        <span class="mark mark-none" id="scrape-progress-stage">รอเริ่ม</span>
                        <span class="loading-text" id="scrape-progress-text">ใส่ keyword แล้วกดเริ่มค้นหา</span>
                    </div>
                    <div class="progress-line" id="scrape-progress-spinner" style="display:none"></div>
                    <p class="field-help" id="scrape-progress-subtext"></p>
                    <div class="terminal"><ol class="journal" id="scrape-progress-log" aria-label="Activity log"></ol></div>
                </div>
            </div>
        </section>

        <section class="section" id="scrape-results-card" style="display:none" aria-labelledby="scrape-results-title">
            <div class="section-head">
                <h2 class="section-title" id="scrape-results-title">ผลการดึงข้อมูล</h2>
            </div>
            <div id="scrape-results"></div>
        </section>
    `;

    document.getElementById('scrape-form').addEventListener('submit', (event) => {
        event.preventDefault();
        startScraping();
    });
    container.querySelectorAll('.stepper button').forEach(btn => btn.addEventListener('click', () => {
        const input = document.getElementById(btn.dataset.target);
        const next = Math.min(Number(input.max), Math.max(Number(input.min), Number(input.value) + Number(btn.dataset.step)));
        input.value = next;
        syncStepper(input);
    }));
    container.querySelectorAll('.stepper input').forEach(input => input.addEventListener('change', () => {
        input.value = Math.min(Number(input.max), Math.max(Number(input.min), Math.round(Number(input.value) || Number(input.min))));
        syncStepper(input);
    }));
    document.getElementById('scrape-keyword').addEventListener('input', (e) => {
        if (!crawlState || !crawlState.running) drawIdleCrawl(e.target.value.trim());
    });

    crawlState = null;
    drawIdleCrawl('');
}

function stepperHtml(id, label, value, min, max) {
    return `
        <div class="stepper">
            <label for="${id}">${label}</label>
            <div class="stepper-control">
                <button type="button" data-target="${id}" data-step="-1" aria-label="ลด${label}">&minus;</button>
                <input type="number" id="${id}" value="${value}" min="${min}" max="${max}" inputmode="numeric">
                <button type="button" data-target="${id}" data-step="1" aria-label="เพิ่ม${label}">+</button>
            </div>
        </div>
    `;
}

function syncStepper(input) {
    const control = input.closest('.stepper-control');
    control.querySelector('[data-step="-1"]').disabled = Number(input.value) <= Number(input.min);
    control.querySelector('[data-step="1"]').disabled = Number(input.value) >= Number(input.max);
}

// ------------------------------------------------------------------
// Crawl map
// ------------------------------------------------------------------
function truncateLabel(text, n = 20) {
    const s = String(text || '');
    return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

function coreLabel(keyword, cx, cy) {
    const words = String(keyword || '').split(/\s+/).filter(Boolean);
    const lines = [''];
    words.forEach(w => {
        const cur = lines[lines.length - 1];
        if (!cur || (cur + ' ' + w).length <= 11) lines[lines.length - 1] = cur ? `${cur} ${w}` : w;
        else lines.push(w);
    });
    const shown = lines.slice(0, 2).map((l, k, arr) => truncateLabel(k === 1 && lines.length > 2 ? `${l}…` : l, 12));
    const y0 = cy + 5 - (shown.length - 1) * 8;
    return `<text class="core-label" x="${cx}" y="${y0}" text-anchor="middle">${shown.map((l, k) =>
        `<tspan x="${cx}" dy="${k ? 16 : 0}">${escapeHtml(l)}</tspan>`).join('')}</text>`;
}

function drawIdleCrawl(keyword) {
    const map = document.getElementById('crawl-map');
    if (!map) return;
    const cx = CRAWL_W / 2, cy = CRAWL_H / 2;
    map.innerHTML = `
        <svg viewBox="0 0 ${CRAWL_W} ${CRAWL_H}" role="img" aria-label="ยังไม่ได้เริ่มค้นหา">
            <circle class="orbit" cx="${cx}" cy="${cy}" r="${CRAWL_R}"></circle>
            <circle class="orbit orbit-inner" cx="${cx}" cy="${cy}" r="${CRAWL_R * 0.55}"></circle>
            ${[0, 1, 2].map(i => {
                const a = (-90 + i * 120) * Math.PI / 180;
                return `<circle class="ghost" cx="${cx + CRAWL_R * Math.cos(a)}" cy="${cy + CRAWL_R * Math.sin(a)}" r="10"></circle>`;
            }).join('')}
            <circle class="core" cx="${cx}" cy="${cy}" r="46"></circle>
            ${coreLabel(keyword || 'keyword', cx, cy)}
        </svg>
    `;
}

function startCrawlMap(keyword) {
    crawlState = { keyword, running: true, total: 0, sites: [], files: 0, started: Date.now() };
    const map = document.getElementById('crawl-map');
    const cx = CRAWL_W / 2, cy = CRAWL_H / 2;
    map.innerHTML = `
        <svg viewBox="0 0 ${CRAWL_W} ${CRAWL_H}" role="img" aria-label="แผนที่การค้นหา ${escapeHtml(keyword)}">
            <circle class="orbit" cx="${cx}" cy="${cy}" r="${CRAWL_R}"></circle>
            <g class="spokes"></g>
            <g class="sites"></g>
            <circle class="core is-searching" cx="${cx}" cy="${cy}" r="46"></circle>
            ${coreLabel(keyword, cx, cy)}
        </svg>
    `;
    document.getElementById('crawl-sites').textContent = '0';
    document.getElementById('crawl-sites-total').textContent = '';
    document.getElementById('crawl-files').textContent = '0';
    document.getElementById('crawl-time').textContent = '0:00';
    clearInterval(crawlTimer);
    crawlTimer = setInterval(() => {
        const el = document.getElementById('crawl-time');
        if (!el || !crawlState) { clearInterval(crawlTimer); return; }
        const s = Math.floor((Date.now() - crawlState.started) / 1000);
        el.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
    }, 1000);
}

function sitePosition(i, total) {
    const a = (-90 + (i * 360) / Math.max(total, 1)) * Math.PI / 180;
    return { x: CRAWL_W / 2 + CRAWL_R * Math.cos(a), y: CRAWL_H / 2 + CRAWL_R * Math.sin(a), a };
}

function layoutSites(total) {
    const svg = document.querySelector('#crawl-map svg');
    if (!svg || !crawlState) return;
    crawlState.total = total;
    svg.querySelector('.core').classList.remove('is-searching');
    const spokes = svg.querySelector('.spokes');
    const sites = svg.querySelector('.sites');
    spokes.innerHTML = '';
    sites.innerHTML = '';
    crawlState.sites = Array.from({ length: total }, (_, i) => ({ i, status: 'queued', domain: '', files: 0 }));
    crawlState.sites.forEach((site, i) => {
        const p = sitePosition(i, total);
        const c = Math.cos(p.a), s = Math.sin(p.a);
        const anchor = c > 0.35 ? 'start' : c < -0.35 ? 'end' : 'middle';
        const lx = p.x + 44 * c, ly = p.y + 44 * s + 4 + (Math.abs(c) <= 0.35 ? s * 6 : 0);
        spokes.insertAdjacentHTML('beforeend', `<line class="spoke" data-i="${i}" x1="${CRAWL_W / 2}" y1="${CRAWL_H / 2}" x2="${p.x}" y2="${p.y}" style="--d:${i * 70}ms"></line>`);
        sites.insertAdjacentHTML('beforeend', `
            <g class="site is-queued" data-i="${i}" style="--d:${i * 70}ms">
                <g class="files"></g>
                <circle class="site-ring" cx="${p.x}" cy="${p.y}" r="22"></circle>
                <circle class="site-dot" cx="${p.x}" cy="${p.y}" r="13"></circle>
                <text class="site-n" x="${p.x}" y="${p.y + 4}" text-anchor="middle">${i + 1}</text>
                <text class="site-label" x="${lx}" y="${ly}" text-anchor="${anchor}"></text>
            </g>
        `);
    });
    document.getElementById('crawl-sites-total').textContent = ` / ${total}`;
}

function updateSite(i, patch) {
    if (!crawlState || !crawlState.sites[i]) return;
    const site = Object.assign(crawlState.sites[i], patch);
    const g = document.querySelector(`#crawl-map .site[data-i="${i}"]`);
    const spoke = document.querySelector(`#crawl-map .spoke[data-i="${i}"]`);
    if (!g || !spoke) return;
    g.setAttribute('class', `site is-${site.status}`);
    spoke.setAttribute('class', `spoke is-${site.status}`);
    if (site.domain) g.querySelector('.site-label').textContent = truncateLabel(site.domain.replace(/^www\./, ''), 20);

    // PDFs as satellites on an arc facing away from the centre.
    const filesG = g.querySelector('.files');
    if (filesG.childElementCount !== Math.min(site.files, 14)) {
        const p = sitePosition(i, crawlState.total);
        const shown = Math.min(site.files, 14);
        filesG.innerHTML = Array.from({ length: shown }, (_, k) => {
            const spread = Math.min(Math.PI * 0.9, shown * 0.22);
            const ang = p.a - spread / 2 + (shown > 1 ? (spread * k) / (shown - 1) : spread / 2);
            return `<circle class="file-dot" cx="${p.x + 24 * Math.cos(ang)}" cy="${p.y + 24 * Math.sin(ang)}" r="3" style="--d:${k * 40}ms"></circle>`;
        }).join('');
    }
    const done = crawlState.sites.filter(s => s.status === 'done' || s.status === 'failed').length;
    document.getElementById('crawl-sites').textContent = done;
    document.getElementById('crawl-files').textContent = crawlState.sites.reduce((sum, s) => sum + s.files, 0);
}

// Read the structured parts out of the progress stream's messages.
function feedCrawlMap(msg) {
    if (!crawlState) return;
    const text = String(msg.message || '');
    let m;
    if (msg.status === 'found' && (m = /พบ\s*(\d+)\s*เว็บไซต์/.exec(text))) {
        layoutSites(Number(m[1]));
    } else if (msg.status === 'scraping' && (m = /\[เว็บ\s*(\d+)\/(\d+)\]\s*ค้นหา PDF จาก\s*(.+?)\.{0,3}$/.exec(text))) {
        if (!crawlState.total) layoutSites(Number(m[2]));
        updateSite(Number(m[1]) - 1, { status: 'active', domain: m[3].trim() });
    } else if ((m = /\[เว็บ\s*(\d+)\/(\d+)\]\s*พบ PDF ที่ดาวน์โหลดได้\s*(\d+)\s*ไฟล์/.exec(text))) {
        updateSite(Number(m[1]) - 1, { status: 'done', files: Number(m[3]) });
    }
}

function finishCrawlMap(result, failed = false) {
    clearInterval(crawlTimer);
    if (!crawlState) return;
    crawlState.running = false;
    if (result && Array.isArray(result.results)) {
        if (!crawlState.total && result.results.length) layoutSites(result.results.length);
        result.results.forEach((r, i) => {
            const url = r.source_url || r.url || result.urls?.[i] || '';
            let domain = crawlState.sites[i]?.domain;
            try { domain = domain || new URL(url).hostname; } catch (_) { /* keep */ }
            updateSite(i, { status: r.success === false ? 'failed' : 'done', files: (r.files || []).length, domain });
        });
    }
    document.querySelector('#crawl-map .core')?.classList.toggle('is-failed', failed);
    document.querySelector('#crawl-map .core')?.classList.add('is-done');
}

// ------------------------------------------------------------------
// Run
// ------------------------------------------------------------------
async function startScraping() {
    const keyword = document.getElementById('scrape-keyword').value.trim();
    if (!keyword) {
        showToast('กรุณาใส่ keyword', 'warning');
        document.getElementById('scrape-keyword').focus();
        return;
    }

    const maxSites = parseInt(document.getElementById('max-sites-slider').value);
    const maxFiles = parseInt(document.getElementById('max-files-slider').value);

    const btn = document.getElementById('btn-scrape');
    btn.disabled = true;
    btn.textContent = 'กำลังค้นหา...';

    const progressText = document.getElementById('scrape-progress-text');
    const progressStage = document.getElementById('scrape-progress-stage');
    const progressSubtext = document.getElementById('scrape-progress-subtext');
    const progressLog = document.getElementById('scrape-progress-log');
    const progressLine = document.getElementById('scrape-progress-spinner');
    progressLine.style.display = '';
    progressText.textContent = `กำลังค้นหา "${keyword}" ใน Google และเข้าไปสูงสุด ${maxSites} เว็บ`;
    progressStage.className = 'mark mark-busy';
    progressStage.textContent = 'กำลังเริ่ม';
    progressSubtext.textContent = 'เตรียมค้นหาใน Google';
    progressLog.innerHTML = '';
    document.getElementById('scrape-results-card').style.display = 'none';
    appendScrapeProgressLog(progressLog, `เริ่มงาน keyword "${keyword}"`);
    startCrawlMap(keyword);
    document.querySelector('.crawl').scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center' });

    let finalResult = null;
    try {
        const response = await fetch('/api/scrape/keyword', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                keyword: keyword,
                max_sites: maxSites,
                max_files_per_site: maxFiles
            })
        });

        if (!response.ok) {
            throw new Error(`API Error: ${response.status}`);
        }

        if (!response.body) {
            throw new Error('ไม่พบข้อมูล stream จาก backend');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        let lastLogMessage = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            let lines = buffer.split("\n");
            buffer = lines.pop(); // Keep the last incomplete line in buffer

            for (let line of lines) {
                if (!line.trim()) continue;
                try {
                    const msg = JSON.parse(line);
                    if (msg.status === "done") {
                        finalResult = msg.result;
                        progressText.textContent = `เสร็จแล้ว พบ ${finalResult?.total_files || 0} ไฟล์จาก ${finalResult?.urls_scraped || 0} เว็บ`;
                        progressStage.className = 'mark mark-ok';
                        progressStage.textContent = 'เสร็จสิ้น';
                        progressSubtext.textContent = 'นำเข้าข้อมูลเรียบร้อยแล้ว ถามต่อได้ในหน้าถาม';
                        appendScrapeProgressLog(progressLog, 'งาน scrape และนำเข้าข้อมูลเสร็จสมบูรณ์');
                    } else if (msg.message) {
                        feedCrawlMap(msg);
                        updateScrapeProgressUI({
                            progressText,
                            progressStage,
                            progressSubtext,
                            progressLog,
                            msg,
                            lastLogMessageRef: () => lastLogMessage,
                            setLastLogMessage: (value) => { lastLogMessage = value; }
                        });
                    }
                } catch (err) {
                    console.error("Parse error on stream chunk:", line, err);
                }
            }
        }

        finishCrawlMap(finalResult);
        if (finalResult) {
            displayScrapeResults(finalResult);
            showToast(`Scraping เสร็จ พบ ${finalResult.total_files || 0} ไฟล์จาก ${finalResult.urls_scraped} เว็บ`, 'success');
        } else {
            showToast(`Scraping เสร็จสิ้นแต่ไม่พบผลลัพธ์ที่ถูกต้อง`, 'warning');
        }

    } catch (e) {
        finishCrawlMap(finalResult, true);
        progressText.textContent = `Scraping ล้มเหลว: ${e.message}`;
        progressStage.className = 'mark mark-fail';
        progressStage.textContent = 'ล้มเหลว';
        progressSubtext.textContent = 'งานหยุดกลางทาง ตรวจสอบ error แล้วลองใหม่อีกครั้ง';
        appendScrapeProgressLog(progressLog, `เกิดข้อผิดพลาด: ${e.message}`, true);
        showToast(`Scraping ล้มเหลว: ${e.message}`, 'error');
    } finally {
        progressLine.style.display = 'none';
        btn.disabled = false;
        btn.textContent = SCRAPE_BUTTON_IDLE;
    }
}

// The backend decorates progress messages with emoji; the UI speaks in plain text.
function plainMessage(text) {
    return String(text || '').replace(/[\p{Extended_Pictographic}️‍]/gu, '').replace(/\s{2,}/g, ' ').trim();
}

function updateScrapeProgressUI({ progressText, progressStage, progressSubtext, progressLog, msg, lastLogMessageRef, setLastLogMessage }) {
    const statusMap = {
        searching: { label: 'ค้นหา', mark: 'mark-busy', detail: 'กำลังค้นหาผลลัพธ์จาก Google' },
        scraping: { label: 'กำลังอ่านเว็บ', mark: 'mark-busy', detail: 'กำลังดึงข้อมูลจากเว็บไซต์ปลายทาง' },
        found: { label: 'พบเว็บ', mark: 'mark-ok', detail: 'ได้รายการเว็บไซต์แล้ว กำลังเข้าไปทีละเว็บ' },
        ingesting: { label: 'นำเข้า', mark: 'mark-busy', detail: 'กำลังบันทึกข้อมูลเข้าสู่ระบบ' },
        processing: { label: 'ประมวลผล', mark: 'mark-busy', detail: 'กำลังทำ OCR, แบ่งเนื้อหา และเก็บข้อมูล' },
        ocr: { label: 'OCR', mark: 'mark-busy', detail: 'กำลังอ่านข้อความจากเอกสารที่ดาวน์โหลดมา' },
        warning: { label: 'คำเตือน', mark: 'mark-query', detail: 'มีบางขั้นตอนที่ไม่สำเร็จ แต่ระบบยังทำงานต่อ' },
    };

    const meta = statusMap[msg.status] || { label: msg.status || 'กำลังทำงาน', mark: 'mark-busy', detail: 'กำลังประมวลผลข้อมูล' };
    const message = plainMessage(msg.message);

    progressText.textContent = message;
    progressStage.className = `mark ${meta.mark}`;
    progressStage.textContent = meta.label;
    progressSubtext.textContent = meta.detail;

    if (message === lastLogMessageRef()) return;
    setLastLogMessage(message);
    appendScrapeProgressLog(progressLog, message, msg.status === 'warning');
}

function appendScrapeProgressLog(progressLog, message, isWarning = false) {
    const item = document.createElement('li');
    const time = new Date().toLocaleTimeString('th-TH', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
    if (isWarning) item.className = 'is-warning';
    item.innerHTML = `<time>${time}</time><span>${escapeHtml(plainMessage(message))}</span>`;
    progressLog.prepend(item);

    while (progressLog.children.length > 8) {
        progressLog.removeChild(progressLog.lastChild);
    }
}

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function safeHttpUrl(value) {
    try {
        const url = new URL(String(value || ''));
        return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
    } catch (_) {
        return null;
    }
}

function displayScrapeResults(result) {
    const card = document.getElementById('scrape-results-card');
    const container = document.getElementById('scrape-results');
    card.style.display = 'block';

    const siteResults = (result.results || []).map((r, i) => {
        const filesCount = r.files?.length || 0;
        const linksCount = r.links_found?.length || 0;
        const contentLen = r.content_length || r.page_text?.length || 0;
        const url = r.source_url || r.url || result.urls?.[i] || '';
        const href = safeHttpUrl(url);
        let host = '';
        try { host = new URL(url).hostname.replace(/^www\./, ''); } catch (_) { host = url; }
        const title = r.search_title || r.title || host || '-';
        const textPreview = (r.page_text || '').substring(0, 300);

        return `
            <article class="site-card ${r.success === false ? 'is-failed' : ''}">
                <div class="site-head">
                    <span class="site-mono" aria-hidden="true">${escapeHtml((host || '?').charAt(0).toUpperCase())}</span>
                    <div class="site-text">
                        <div class="site-title">${escapeHtml(truncateLabel(title, 70))}</div>
                        ${href ? `<a class="site-url" href="${escapeHtml(href)}" target="_blank" rel="noopener">${escapeHtml(host)}</a>` : `<span class="site-url">${escapeHtml(host || '-')}</span>`}
                    </div>
                    <span class="mark ${r.success === false ? 'mark-fail' : 'mark-ok'}">${r.success === false ? 'ล้มเหลว' : 'สำเร็จ'}</span>
                </div>
                <div class="site-figures">
                    <span><b>${filesCount}</b> PDF</span>
                    <span><b>${contentLen.toLocaleString()}</b> ตัวอักษร</span>
                    <span><b>${linksCount}</b> ลิงก์</span>
                </div>
                ${textPreview ? `
                    <details>
                        <summary>ดูตัวอย่างเนื้อหา</summary>
                        <div class="code-block" style="font-family:var(--font-thai);max-height:200px">${escapeHtml(textPreview)}${contentLen > 300 ? '...' : ''}</div>
                    </details>
                ` : ''}
                ${r.error ? `<p class="message is-error">${escapeHtml(r.error)}</p>` : ''}
            </article>
        `;
    }).join('');

    container.innerHTML = `
        ${result.output_folder ? `<p class="field-help" style="margin-bottom:16px">ข้อมูลถูกบันทึกที่ <code>${escapeHtml(result.output_folder)}</code></p>` : ''}
        <div class="site-grid">${siteResults}</div>
        ${result.files && result.files.length > 0 ? `
            <h3 class="group-title" style="margin-top:28px">ไฟล์ที่ดาวน์โหลด (${result.files.length})</h3>
            <div class="file-grid">
                ${result.files.map(f => {
                    const name = String(f).split(/[/\\]/).pop();
                    const ext = name.split('.').pop().toUpperCase().slice(0, 4);
                    return `<div class="file-row"><span class="file-chip">${escapeHtml(ext)}</span><span class="file-name">${escapeHtml(name)}</span></div>`;
                }).join('')}
            </div>
        ` : ''}
    `;
}
