/**
 * AI Chat Component
 * Chat-style interface for querying the agent with method/source attribution
 */

function renderChat(container) {
    container.innerHTML = `
        <div class="page-header">
            <h1>AI Chat</h1>
            <p>ถามคำถามเกี่ยวกับเอกสารการเงินที่อัปโหลด — Agent จะเลือกใช้ Vector Search หรือ SQL อัตโนมัติ</p>
        </div>

        <div class="chat-container">
            <div class="chat-messages" id="chat-messages">
                <!-- Welcome message -->
                <div class="chat-message assistant">
                    <div class="message-avatar">AI</div>
                    <div>
                        <div class="message-bubble">
                            สวัสดีครับ! ผมเป็น Financial Data Agent 🤖<br><br>
                            ผมสามารถตอบคำถามเกี่ยวกับเอกสารการเงินที่คุณอัปโหลดได้ ทั้ง:
                            <ul style="margin:8px 0 0 20px;line-height:1.8">
                                <li><span class="method-badge vector">Vector</span> ค้นหาเชิงความหมาย (สรุป, อธิบาย, concept)</li>
                                <li><span class="method-badge sql">SQL</span> วิเคราะห์ตัวเลข (รายได้, กำไร, เปรียบเทียบ)</li>
                                <li><span class="method-badge hybrid">Hybrid</span> ทั้งสองแบบรวมกัน</li>
                            </ul>
                        </div>
                        <div class="message-meta">
                            <span>Financial Data Agent</span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="chat-input-area">
                <input type="text" id="chat-input" class="input-field" placeholder="ถามคำถามเกี่ยวกับเอกสารการเงิน..." onkeydown="if(event.key==='Enter') sendMessage()">
                <button class="btn btn-primary" id="btn-send" onclick="sendMessage()">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
                    </svg>
                </button>
            </div>
        </div>
    `;
}

function renderChatSource(source) {
    const documentId = Number(source.document_id);
    const page = Number(source.page);
    const hasPage = Number.isInteger(documentId) && documentId > 0
        && Number.isInteger(page) && page > 0;
    const filename = escapeHtml(String(source.filename || 'Document'));
    const location = `${filename}${hasPage ? ` · PDF page ${page}` : ' · page unresolved'}`;
    const cell = [source.row_label, source.column, source.value]
        .filter(value => value !== null && value !== undefined && String(value).trim())
        .map(value => escapeHtml(String(value))).join(' · ');
    const detail = cell ? ` <small>(${cell})</small>` : '';
    const quality = source.quality_status === 'passed_checks' ? 'internal checks passed'
        : source.quality_status === 'unverified' ? 'no numeric cross-check'
        : source.quality_status === 'unknown' ? 'quality unknown' : '';
    const label = `📄 ${location}${detail}${quality ? ` <small>· ${quality}</small>` : ''}`;
    if (hasPage) {
        return `<a class="method-badge ${source.type === 'sql' ? 'sql' : 'vector'}" style="margin:2px" href="/api/documents/${documentId}/pages/${page}/image" target="_blank" rel="noopener">${label}</a>`;
    }
    if (source.type === 'web' && source.url) {
        try {
            const url = new URL(source.url);
            if (url.protocol === 'https:' || url.protocol === 'http:') {
                return `<a class="method-badge vector" style="margin:2px" href="${escapeHtml(url.href)}" target="_blank" rel="noopener">🌐 ${escapeHtml(String(source.title || url.hostname))}</a>`;
            }
        } catch (_) { /* Invalid URL remains uncited. */ }
    }
    return `<span class="method-badge ${source.type === 'sql' ? 'sql' : 'vector'}" style="margin:2px">${label}</span>`;
}

async function sendMessage() {
    const input = document.getElementById('chat-input');
    const question = input.value.trim();
    if (!question) return;

    const messages = document.getElementById('chat-messages');
    const sendBtn = document.getElementById('btn-send');

    // Add user message
    messages.innerHTML += `
        <div class="chat-message user">
            <div class="message-avatar">You</div>
            <div>
                <div class="message-bubble">${escapeHtml(question)}</div>
            </div>
        </div>
    `;

    input.value = '';
    sendBtn.disabled = true;

    // Add loading indicator
    const loadingId = `loading-${Date.now()}`;
    messages.innerHTML += `
        <div class="chat-message assistant" id="${loadingId}">
            <div class="message-avatar">AI</div>
            <div>
                <div class="message-bubble">
                    <div class="loader">
                        <span class="loader-spinner"></span>
                        <span>กำลังวิเคราะห์คำถาม...</span>
                    </div>
                </div>
            </div>
        </div>
    `;
    messages.scrollTop = messages.scrollHeight;

    try {
        const result = await api.post('/query', { question });

        // Remove loading
        const loadingEl = document.getElementById(loadingId);
        if (loadingEl) loadingEl.remove();

        // Format sources
        let sourcesHtml = '';
        if (result.sources && result.sources.length > 0) {
            sourcesHtml = `
                <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border-primary)">
                    <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:6px">Retrieved evidence — OCR values are not visually verified. Open the PDF page to check them.</div>
                    ${result.sources.map(renderChatSource).join(' ')}
                </div>
            `;
        }

        // SQL details
        let sqlHtml = '';
        if (result.sql_info && result.sql_info.sql) {
            sqlHtml = `
                <details style="margin-top:10px">
                    <summary style="font-size:0.78rem;color:var(--text-muted);cursor:pointer">View SQL Query</summary>
                    <pre style="margin-top:6px;padding:10px;background:var(--bg-tertiary);border-radius:var(--radius-sm);font-family:var(--font-mono);font-size:0.78rem;color:var(--accent-info);overflow-x:auto">${escapeHtml(result.sql_info.sql)}</pre>
                </details>
            `;
        }

        // Add AI response
        messages.innerHTML += `
            <div class="chat-message assistant">
                <div class="message-avatar">AI</div>
                <div>
                    <div class="message-bubble">
                        <div>${formatCapturedAnswer(result)}</div>
                        ${sourcesHtml}
                        ${sqlHtml}
                    </div>
                    <div class="message-meta">
                        <span class="method-badge ${result.method}">${result.method.toUpperCase()}</span>
                        <span>Financial Data Agent</span>
                    </div>
                </div>
            </div>
        `;

    } catch (e) {
        const loadingEl = document.getElementById(loadingId);
        if (loadingEl) loadingEl.remove();

        messages.innerHTML += `
            <div class="chat-message assistant">
                <div class="message-avatar">AI</div>
                <div>
                    <div class="message-bubble" style="border-color:var(--accent-danger)">
                        ⚠️ เกิดข้อผิดพลาด: ${escapeHtml(e.message)}
                    </div>
                </div>
            </div>
        `;
    }

    sendBtn.disabled = false;
    messages.scrollTop = messages.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
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
                output += ` <span data-claim-index="${i}" data-source-index="${link.source_index}">${renderChatSource(source)}</span>`;
            }
        }
        cursor = end;
    }
    return output + formatAnswer(slice(cursor));
}
