/**
 * Demo answers for the Ask page, used while the answering model is offline.
 *
 * Nothing here is invented. A figure question is answered from the
 * warehouse (fact_financial_metrics), the same rows the overview charts use,
 * and cites the PDF page recorded in the table name ("[p23] ..."). Any other
 * question gets the closest passage from the stored chunks, quoted as is.
 * Every result is flagged `demo: true` so the page can label it.
 */

const DEMO_STORAGE_KEY = 'ba-demo-answers';
let demoLabels = null;     // row labels that have figures in ล้านบาท on a known page
let demoChunks = null;     // { documentId, filename, chunks }

function demoModeOn() {
    try {
        const saved = localStorage.getItem(DEMO_STORAGE_KEY);
        return saved === null ? true : saved === 'on';
    } catch (_) { return true; }
}

function setDemoMode(on) {
    try { localStorage.setItem(DEMO_STORAGE_KEY, on ? 'on' : 'off'); } catch (_) { /* storage blocked */ }
}

function sqlText(value) {
    return `'${String(value).replace(/'/g, "''")}'`;
}

function pageFromTable(tableName) {
    const m = /^\[p(\d+)\]/.exec(String(tableName || ''));
    return m ? Number(m[1]) : null;
}

async function demoLoadLabels() {
    if (demoLabels) return demoLabels;
    const data = await api.post('/warehouse/query', {
        sql: `SELECT DISTINCT row_label FROM fact_financial_metrics
              WHERE unit = 'ล้านบาท' AND numeric_value IS NOT NULL AND table_name LIKE '[p%'`,
    });
    demoLabels = (data.rows || []).map(r => String(r.row_label || '')).filter(Boolean);
    return demoLabels;
}

// The longest row label the question mentions. Labels like
// "กำไรสุทธิ (ส่วนที่เป็นของธนาคาร)" also match on the part before the bracket.
function demoMatchLabel(question, labels) {
    const q = question.replace(/\s+/g, '');
    let best = null;
    labels.forEach(label => {
        const keys = [label, label.replace(/\s*\(.*\)\s*$/, '')].map(k => k.replace(/\s+/g, ''));
        keys.forEach(k => {
            if (k.length >= 4 && q.includes(k) && (!best || k.length > best.key.length)) best = { label, key: k };
        });
    });
    return best ? best.label : null;
}

async function demoFigureAnswer(question, label) {
    const sql = `SELECT document_id, table_name, row_label, metric_year, raw_value, numeric_value, unit, quality_status
FROM fact_financial_metrics
WHERE row_label = ${sqlText(label)} AND unit = 'ล้านบาท' AND numeric_value IS NOT NULL AND table_name LIKE '[p%'
ORDER BY table_name, metric_year`;
    const data = await api.post('/warehouse/query', { sql });
    const groups = {};
    (data.rows || []).forEach(r => {
        (groups[r.table_name] ||= []).push(r);
    });
    const rows = Object.values(groups).sort((a, b) => b.length - a.length)[0];
    if (!rows || !rows.length) return null;

    const years = rows.map(r => String(r.metric_year)).sort();
    const asked = (/25\d\d/.exec(question) || [])[0];
    const year = asked && years.includes(asked) ? asked : years[years.length - 1];
    const cur = rows.find(r => String(r.metric_year) === year);
    const prev = rows.find(r => String(r.metric_year) === String(Number(year) - 1));
    const docs = await api.get('/documents');
    const doc = (docs.documents || []).find(d => d.id === cur.document_id);
    const page = pageFromTable(cur.table_name);
    const source = (r, id) => ({
        source_id: id,
        type: 'sql',
        document_id: r.document_id,
        filename: doc ? doc.filename : `document ${r.document_id}`,
        page,
        row_label: r.row_label,
        column: `ปี ${r.metric_year}`,
        value: r.raw_value,
        quality_status: r.quality_status || 'unknown',
        table_name: r.table_name,
    });

    const c1 = `${cur.raw_value} ${cur.unit}`;
    let answer = `${label} ปี ${year} เท่ากับ ${c1}`;
    const claims = [c1];
    const sources = [source(cur, 'demo-0')];
    if (prev) {
        const c2 = `${prev.raw_value} ${prev.unit}`;
        const dir = Number(cur.numeric_value) >= Number(prev.numeric_value) ? 'เพิ่มขึ้น' : 'ลดลง';
        const pct = Math.abs((Number(cur.numeric_value) - Number(prev.numeric_value)) / Math.abs(Number(prev.numeric_value)) * 100);
        answer += ` ${dir} ${pct.toFixed(1)}% จากปี ${prev.metric_year} ที่ ${c2}`;
        claims.push(c2);
        sources.push(source(prev, 'demo-1'));
    }
    const points = Array.from(answer);
    const spans = claims.map(c => {
        const at = answer.indexOf(c);
        const start = Array.from(answer.slice(0, at)).length;
        return { start, end: start + Array.from(c).length };
    });
    if (points.length < spans[spans.length - 1].end) return null;

    return {
        demo: true,
        answer,
        method: 'sql',
        answer_claims: claims,
        claim_spans: spans,
        claim_citations: claims.map((_, i) => ({ claim_index: i, source_index: i, source_id: sources[i].source_id })),
        sources,
        sql_info: { sql },
        series: {
            title: label,
            unit: cur.unit,
            page,
            year,
            points: rows.map(r => ({ x: String(r.metric_year), y: Number(r.numeric_value) }))
                .sort((a, b) => a.x.localeCompare(b.x)),
        },
    };
}

async function demoLoadChunks() {
    if (demoChunks) return demoChunks;
    const docs = await api.get('/documents');
    const doc = (docs.documents || [])
        .filter(d => ['completed', 'partial'].includes(d.status) && d.chunk_count > 0)
        .sort((a, b) => (b.chunk_count || 0) - (a.chunk_count || 0))[0];
    if (!doc) return null;
    const data = await api.get(`/chunks/${doc.id}`);
    demoChunks = { documentId: doc.id, filename: doc.filename, chunks: data.chunks || [] };
    return demoChunks;
}

// Thai has no spaces between words, so match on character trigrams.
function trigrams(text) {
    const s = String(text).toLowerCase().replace(/[\s\p{P}]+/gu, '');
    const out = new Set();
    for (let i = 0; i + 3 <= s.length; i++) out.add(s.slice(i, i + 3));
    return out;
}

function coverage(qg, text) {
    const g = trigrams(text);
    let hit = 0;
    qg.forEach(t => { if (g.has(t)) hit++; });
    return hit / Math.max(1, qg.size);
}

async function demoPassageAnswer(question) {
    const corpus = await demoLoadChunks();
    if (!corpus) return null;
    const qg = trigrams(question.replace(/(เท่าไร|อย่างไร|ภายในปีใด|ปีใด|เมื่อไร|อะไร|ไหม|หรือไม่|มี)/g, ''));
    // Latin terms ("Net Zero", "ESG") are strong signals; a question that asks
    // for a year should land on a passage that states one.
    const latin = (question.match(/[A-Za-z][A-Za-z-]*(?:\s+[A-Za-z][A-Za-z-]*)*/g) || []).map(w => w.toLowerCase().replace(/[\s-]+/g, ''));
    const wantsYear = /(ปีใด|ปีไหน|เมื่อไร|ภายในปี)/.test(question);
    const bonus = (text) => {
        const flat = text.toLowerCase().replace(/[\s-]+/g, '');
        let b = latin.length && latin.every(w => flat.includes(w)) ? 0.5 : 0;
        if (wantsYear && /(25[5-9]\d|20[2-6]\d)/.test(text)) b += 0.3;
        return b;
    };

    const ranked = corpus.chunks
        .map(c => ({ c, text: String(c.chunk_text || '').replace(/\s+/g, ' ').trim() }))
        .filter(x => x.text.length >= 60)
        .map(x => ({ ...x, score: coverage(qg, x.text) + bonus(x.text) }))
        .sort((a, b) => b.score - a.score)
        .slice(0, 25);
    let best = null;
    ranked.forEach(x => {
        for (let i = 0; i < x.text.length; i += 40) {
            const win = x.text.slice(i, i + 220);
            const score = coverage(qg, win) + bonus(win);
            if (!best || score > best.score) best = { score, chunk: x.c, text: x.text, at: i };
            if (i + 220 >= x.text.length) break;
        }
    });
    if (!best || best.score < 0.25) return null;

    // Cut the passage down to the clause that answers: anchor on the
    // question's Latin term (or the middle of the best window), walk left by
    // whole phrases until a clause opener, and for a "which year" question
    // end right after the year.
    const text = best.text;
    let anchor = best.at + 110;
    for (const w of latin) {
        const re = new RegExp(w.split('').join('[\\s-]*'), 'i');
        const m = re.exec(text.slice(Math.max(0, best.at - 40)));
        if (m) { anchor = Math.max(0, best.at - 40) + m.index; break; }
    }
    let yearMatch = null;
    if (wantsYear) {
        const years = [...text.matchAll(/(25[5-9]\d|20[2-6]\d)/g)];
        yearMatch = years.find(m => m.index >= anchor && m.index - anchor < 160)
            || years.sort((a, b) => Math.abs(a.index - anchor) - Math.abs(b.index - anchor))[0] || null;
    }
    const OPENERS = /^(ในขณะเดียวกัน|นอกจากนี้|ทั้งนี้|ขณะที่|อย่างไรก็ตาม|โดยใน|ซึ่ง|เพื่อ)/;
    let from = anchor;
    while (from > 0 && text[from - 1] !== ' ') from--;
    while (from > 0 && anchor - from < 110) {
        let k = from - 1;
        while (k > 0 && text[k - 1] !== ' ') k--;
        if (anchor - k > 130) break;
        from = k;
        if (OPENERS.test(text.slice(from))) break;
    }
    let to = yearMatch ? yearMatch.index + yearMatch[0].length : Math.min(text.length, anchor + 90);
    if (!yearMatch) while (to < text.length && text[to] !== ' ') to++;
    const sentence = text.slice(from, to).trim();

    // A year question gets a short answer lifted from the text: "ภายในปี 2593".
    let short = '';
    if (yearMatch) {
        const before = text.slice(0, yearMatch.index).trimEnd().split(' ').pop() || '';
        short = /ปี$/.test(before) ? `${before} ${yearMatch[0]}` : `ปี ${yearMatch[0]}`;
    }
    const marks = [...latin.map(w => {
        const m = new RegExp(w.split('').join('[\\s-]*'), 'i').exec(sentence);
        return m ? m[0] : null;
    }), short && sentence.includes(short) ? short : (yearMatch ? yearMatch[0] : null)].filter(Boolean);

    const source = {
        source_id: 'demo-p0',
        type: 'vector',
        document_id: corpus.documentId,
        filename: corpus.filename,
        page: null,
        excerpt: sentence,
        context: text,
        chunk_index: best.chunk.chunk_index,
        quality_status: 'unknown',
    };
    const answer = short || 'พบข้อความที่ตรงกับคำถามในเอกสาร';
    return {
        demo: true,
        answer,
        method: 'vector',
        answer_claims: short ? [short] : [],
        claim_spans: short ? [{ start: 0, end: Array.from(short).length }] : [],
        claim_citations: short ? [{ claim_index: 0, source_index: 0, source_id: 'demo-p0' }] : [],
        sources: [source],
        quote: { text: sentence, marks, source },
    };
}

async function demoAnswer(question) {
    const label = demoMatchLabel(question, await demoLoadLabels());
    const figure = label ? await demoFigureAnswer(question, label) : null;
    if (figure) return figure;
    const passage = await demoPassageAnswer(question);
    if (passage) return passage;
    return {
        demo: true,
        answer: 'ไม่พบหลักฐานเพียงพอในโหมดจำลอง โหมดนี้ตอบได้เฉพาะตัวเลขที่อยู่ในตารางงบการเงิน และยกข้อความที่ใกล้เคียงจากเอกสารเท่านั้น',
        method: 'vector',
        sources: [],
    };
}
