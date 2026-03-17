/**
 * Web Scraping Component
 * Simple keyword input + max Google results slider
 */

function renderScraping(container) {
    container.innerHTML = `
        <div class="page-header">
            <h1>Web Scraping</h1>
            <p>ใส่ keyword แล้วระบบจะค้นหาผ่าน Google และดึงเอกสาร PDF/รูปภาพจากเว็บที่เกี่ยวข้องแบบอัตโนมัติ</p>
        </div>

        <!-- Simple keyword scraping card -->
        <div class="card" style="margin-bottom:24px">
            <div class="card-header">
                <div>
                    <div class="card-title">🔍 Scrape by Keyword (Google Search)</div>
                    <div class="card-subtitle">ใส่ keyword และกำหนดจำนวนเว็บผลลัพธ์จาก Google ที่ต้องการดึงข้อมูล</div>
                </div>
            </div>

            <!-- Keyword input -->
            <div class="input-group">
                <label for="scrape-keyword">Keyword</label>
                <input type="text" id="scrape-keyword" class="input-field" placeholder="เช่น เทรนด์ธุรกิจ SME 2025, งบการเงิน PTT">
            </div>

            <!-- Max sites slider -->
            <div class="input-group">
                <label>จำนวนเว็บจาก Google ที่จะ scrape: <strong id="max-sites-label">3</strong></label>
                <input type="range" id="max-sites-slider" min="1" max="10" value="3" class="input-field"
                    style="padding:8px 0;cursor:pointer;accent-color:var(--accent-primary)"
                    oninput="document.getElementById('max-sites-label').textContent = this.value">
                <small class="text-muted" style="display:block;margin-top:4px;font-size:0.75rem">
                    ระบบจะค้นหาใน Google และไล่กดเข้าไปทีละเว็บ (สูงสุดไม่เกินตัวเลขที่เลือก)
                </small>
            </div>

            <!-- Max files per site -->
            <div class="input-group" style="margin-top:20px">
                <label>จำนวนไฟล์เอกสารสูงสุดต่อเว็บ: <strong id="max-files-label">10</strong></label>
                <input type="range" id="max-files-slider" min="1" max="30" value="10" class="input-field"
                    style="padding:8px 0;cursor:pointer;accent-color:var(--accent-primary)"
                    oninput="document.getElementById('max-files-label').textContent = this.value">
            </div>

            <button class="btn btn-primary" id="btn-scrape" onclick="startScraping()" style="width:100%;justify-content:center;padding:14px;margin-top:16px">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                ค้นหาใน Google และเริ่ม Scraping
            </button>
        </div>

        <!-- Progress -->
        <div class="card" id="scrape-progress-card" style="display:none;margin-bottom:24px">
            <div class="card-header">
                <div class="card-title">⏳ Scraping Progress</div>
            </div>
            <div id="scrape-progress">
                <div class="loader">
                    <span class="loader-spinner"></span>
                    <span id="scrape-progress-text">กำลังเริ่มต้นค้นหาใน Google...</span>
                </div>
                <div style="margin-top:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                    <span id="scrape-progress-stage" class="badge badge-info">เริ่มต้น</span>
                    <span id="scrape-progress-subtext" style="font-size:0.78rem;color:var(--text-muted)">ระบบจะอัปเดตสถานะแต่ละขั้นตอนแบบเรียลไทม์</span>
                </div>
                <div id="scrape-progress-log" style="margin-top:14px;display:flex;flex-direction:column;gap:8px;max-height:220px;overflow-y:auto"></div>
            </div>
        </div>

        <!-- Results -->
        <div class="card" id="scrape-results-card" style="display:none">
            <div class="card-header">
                <div class="card-title">📦 Scraping Results</div>
            </div>
            <div id="scrape-results"></div>
        </div>
    `;
}

async function startScraping() {
    const keyword = document.getElementById('scrape-keyword').value.trim();
    if (!keyword) {
        showToast('กรุณาใส่ keyword', 'warning');
        return;
    }

    const maxSites = parseInt(document.getElementById('max-sites-slider').value);
    const maxFiles = parseInt(document.getElementById('max-files-slider').value);

    const btn = document.getElementById('btn-scrape');
    btn.disabled = true;
    btn.innerHTML = '<span class="loader-spinner"></span> กำลังค้นหาและดึงข้อมูล...';

    // Show progress
    const progressCard = document.getElementById('scrape-progress-card');
    const progressText = document.getElementById('scrape-progress-text');
    const progressStage = document.getElementById('scrape-progress-stage');
    const progressSubtext = document.getElementById('scrape-progress-subtext');
    const progressLog = document.getElementById('scrape-progress-log');
    progressCard.style.display = 'block';
    progressText.textContent = `กำลังค้นหา keyword "${keyword}" ใน Google และ scrape Top ${maxSites} เว็บ...`;
    progressStage.textContent = 'กำลังเริ่ม';
    progressSubtext.textContent = 'เตรียมค้นหาใน Google และเริ่ม scraping';
    progressLog.innerHTML = '';
    appendScrapeProgressLog(progressLog, `เริ่มงาน scrape keyword "${keyword}"`);
    progressCard.scrollIntoView({ behavior: 'smooth', block: 'start' });

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
        let finalResult = null;
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
                        progressText.textContent = `Scraping เสร็จแล้ว พบ ${finalResult?.total_files || 0} ไฟล์จาก ${finalResult?.urls_scraped || 0} เว็บ`;
                        progressStage.className = 'badge badge-success';
                        progressStage.textContent = 'เสร็จสิ้น';
                        progressSubtext.textContent = 'นำเข้าข้อมูลเรียบร้อยแล้ว สามารถดูผลลัพธ์และถามต่อใน RAG ได้';
                        appendScrapeProgressLog(progressLog, 'งาน scrape และนำเข้าข้อมูลเสร็จสมบูรณ์');
                    } else if (msg.message) {
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
        
        if (finalResult) {
            displayScrapeResults(finalResult);
            showToast(`Scraping เสร็จ! พบ ${finalResult.total_files || 0} ไฟล์จาก ${finalResult.urls_scraped} เว็บ`, 'success');
        } else {
            showToast(`Scraping เสร็จสิ้นแต่ไม่พบผลลัพธ์ที่ถูกต้อง`, 'warning');
        }

    } catch (e) {
        progressText.textContent = `Scraping ล้มเหลว: ${e.message}`;
        progressStage.className = 'badge badge-danger';
        progressStage.textContent = 'ล้มเหลว';
        progressSubtext.textContent = 'งานหยุดกลางทาง กรุณาตรวจสอบ error และลองใหม่อีกครั้ง';
        appendScrapeProgressLog(progressLog, `เกิดข้อผิดพลาด: ${e.message}`, true);
        showToast(`Scraping ล้มเหลว: ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            ค้นหาใน Google และเริ่ม Scraping
        `;
    }
}

function updateScrapeProgressUI({ progressText, progressStage, progressSubtext, progressLog, msg, lastLogMessageRef, setLastLogMessage }) {
    const statusMap = {
        searching: { label: 'ค้นหา', tone: 'badge-info', detail: 'กำลังค้นหาผลลัพธ์จาก Google' },
        scraping: { label: 'Scraping', tone: 'badge-primary', detail: 'กำลังดึงข้อมูลจากเว็บไซต์ปลายทาง' },
        found: { label: 'พบเว็บ', tone: 'badge-success', detail: 'ได้รายการเว็บไซต์แล้ว กำลังประมวลผลต่อ' },
        ingesting: { label: 'นำเข้า RAG', tone: 'badge-warning', detail: 'กำลังบันทึกข้อมูลเข้าสู่ระบบ RAG' },
        processing: { label: 'ประมวลผล', tone: 'badge-primary', detail: 'กำลังทำ OCR / chunk / เก็บข้อมูล' },
        ocr: { label: 'OCR', tone: 'badge-info', detail: 'กำลังอ่านข้อความจากเอกสารที่ดาวน์โหลดมา' },
        warning: { label: 'คำเตือน', tone: 'badge-danger', detail: 'มีบางขั้นตอนที่ไม่สำเร็จ แต่ระบบยังทำงานต่อ' },
    };

    const meta = statusMap[msg.status] || { label: msg.status || 'กำลังทำงาน', tone: 'badge-info', detail: 'กำลังประมวลผลข้อมูล' };

    progressText.textContent = msg.message;
    progressStage.className = `badge ${meta.tone}`;
    progressStage.textContent = meta.label;
    progressSubtext.textContent = meta.detail;

    if (msg.message === lastLogMessageRef()) return;
    setLastLogMessage(msg.message);
    appendScrapeProgressLog(progressLog, msg.message, msg.status === 'warning');
}

function appendScrapeProgressLog(progressLog, message, isWarning = false) {
    const item = document.createElement('div');
    const time = new Date().toLocaleTimeString('th-TH', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
    item.style.padding = '10px 12px';
    item.style.background = 'var(--bg-secondary)';
    item.style.borderRadius = 'var(--radius-sm)';
    item.style.fontSize = '0.78rem';
    item.style.color = isWarning ? 'var(--accent-danger)' : 'var(--text-secondary)';
    item.style.border = `1px solid ${isWarning ? 'rgba(255, 107, 107, 0.24)' : 'rgba(255,255,255,0.06)'}`;
    item.innerHTML = `
        <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
            <span style="line-height:1.5">${escapeHtml(message)}</span>
            <span style="white-space:nowrap;color:var(--text-muted);font-size:0.72rem">${time}</span>
        </div>
    `;
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

function displayScrapeResults(result) {
    const card = document.getElementById('scrape-results-card');
    const container = document.getElementById('scrape-results');
    card.style.display = 'block';

    // Per-site results
    const siteResults = (result.results || []).map((r, i) => {
        const statusColor = r.success ? 'var(--accent-success)' : 'var(--accent-danger)';
        const statusIcon = r.success ? '✅' : '❌';
        const filesCount = r.files?.length || 0;
        const imagesCount = r.images?.length || 0;
        const linksCount = r.links_found?.length || 0;
        const contentLen = r.content_length || r.page_text?.length || 0;
        const url = r.source_url || r.url || result.urls?.[i] || '—';
        const title = r.search_title || r.title || '';
        const textPreview = (r.page_text || '').substring(0, 300);

        return `
            <div style="padding:16px;background:var(--bg-tertiary);border-radius:var(--radius-md);border-left:3px solid ${statusColor}">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                    <div>
                        <div style="font-size:0.9rem;font-weight:600">${statusIcon} ${title || (url.length > 55 ? url.slice(0, 55) + '...' : url)}</div>
                        <a href="${url}" target="_blank" style="font-size:0.75rem;color:var(--text-muted);text-decoration:none">${url.length > 70 ? url.slice(0, 70) + '...' : url}</a>
                    </div>
                </div>
                <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">
                    <span class="badge badge-primary">📄 ${filesCount} files</span>
                    <span class="badge badge-info">🖼️ ${imagesCount} images</span>
                    <span class="badge badge-success">📝 ${contentLen.toLocaleString()} chars</span>
                    <span class="badge" style="background:var(--bg-secondary);color:var(--text-secondary)">🔗 ${linksCount} links</span>
                </div>
                ${textPreview ? `
                    <details style="margin-top:8px">
                        <summary style="font-size:0.78rem;color:var(--text-secondary);cursor:pointer">ดูตัวอย่างเนื้อหา</summary>
                        <div style="margin-top:8px;font-size:0.78rem;color:var(--text-muted);background:var(--bg-secondary);padding:12px;border-radius:var(--radius-sm);white-space:pre-wrap;max-height:200px;overflow-y:auto">${textPreview}${contentLen > 300 ? '...' : ''}</div>
                    </details>
                ` : ''}
                ${r.error ? `<div style="font-size:0.78rem;color:var(--accent-danger);margin-top:4px">Error: ${r.error}</div>` : ''}
            </div>
        `;
    }).join('');

    container.innerHTML = `
        <div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap">
            <span class="badge badge-success" style="font-size:0.85rem;padding:6px 14px">
                🔍 keyword: "${result.keyword}"
            </span>
            <span class="badge badge-info" style="font-size:0.85rem;padding:6px 14px">
                🌐 ${result.urls_scraped} เว็บ
            </span>
            <span class="badge badge-primary" style="font-size:0.85rem;padding:6px 14px">
                📄 ${result.total_files || 0} ไฟล์
            </span>
            <span class="badge" style="font-size:0.85rem;padding:6px 14px;background:var(--accent-primary);color:white">
                🖼️ ${result.total_images || 0} รูปภาพ
            </span>
        </div>

        ${result.output_folder ? `
            <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:16px;padding:8px 12px;background:var(--bg-tertiary);border-radius:var(--radius-sm)">
                📁 ข้อมูลถูกบันทึกที่: <code style="color:var(--accent-primary)">${result.output_folder}</code>
            </div>
        ` : ''}

        <div style="display:flex;flex-direction:column;gap:10px;margin-bottom:20px">
            ${siteResults}
        </div>

        ${result.files && result.files.length > 0 ? `
            <div style="margin-top:16px">
                <div style="font-size:0.9rem;font-weight:600;margin-bottom:10px">Downloaded Files</div>
                <table class="data-table">
                    <thead>
                        <tr><th>File</th><th>Type</th></tr>
                    </thead>
                    <tbody>
                        ${result.files.map(f => {
                            const name = f.split(/[/\\]/).pop();
                            const ext = name.split('.').pop().toUpperCase();
                            return `<tr>
                                <td style="font-size:0.85rem">${name}</td>
                                <td><span class="badge badge-primary">${ext}</span></td>
                            </tr>`;
                        }).join('')}
                    </tbody>
                </table>
            </div>
        ` : ''}
    `;
}

