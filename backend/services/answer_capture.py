"""Capture generation annotations; never infer citations from retrieved sources.

Span checks establish binding to emitted prose, not factual correctness.
Unverifiable annotations remain explicit errors rather than invented mappings.
"""
from contextvars import ContextVar
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

VERSION = 'application-answer-capture-v1.22'
CURRENT = ContextVar('application_answer_capture', default=None)
INSTRUCTION = '''\nReturn a JSON object with answer (short Thai prose), answer_claims
(array of exact non-overlapping factual substrings of answer, in order),
claim_citations (array of {claim_index, source_index}; cite only source indices
explicitly shown in supplied evidence), and numeric_facts (array of
{claim_index, source_index, answer_quote, company, measure, value, unit,
year_be, document, source_pdf_page, comparison_operator}).
Each numeric fact must be stated in its answer_quote, an exact substring of
the corresponding claim: company, measure, signed value, unit, performance
year (BE or null for timeless), comparator (eq/lt/lte/gt/gte/approx/range),
and PDF page. document must equal the cited evidence filename. Never fill
missing fields from the question or other sources. Include only fully bound
facts; leave unresolved facts out. Keep approx/bounds when evidence has them.
Do not call every returned source a citation. Abstentions have empty arrays.
No markdown fences. Source indices are zero-based and stable in this request.
answer_claims ต้องคัดลอกข้อความจาก answer ของคุณเท่านั้น ห้ามคัดลอกจากหลักฐาน
หรือเขียนคำอธิบายใหม่ answer_quote ต้องคัดลอกจาก claim ที่อ้างถึงและต้องมี
บริษัท รายการ ค่า หน่วย และปีที่คำตอบพูดจริง หากเป็นคำถามตัวเลข ให้ตอบเต็ม
ความสัมพันธ์นั้นในประโยคเดียว พร้อมหน้า PDF อย่านำปีรายงานมาแทนปีเหตุการณ์
abstained เป็น true เฉพาะคำตอบที่ระบุว่าหลักฐานไม่เพียงพอ และต้องส่งทั้งสาม
array ว่าง มิฉะนั้นเป็น false หากตอบข้อเท็จจริงต้องมี answer_claims ครอบคลุม
answer ทุกประโยค รวม qualifiers เช่น ประมาณ/ไม่เกิน ห้ามใช้ข้อความหลักฐานแทน
'''

_STRING = {'type': 'STRING'}
_INTEGER = {'type': 'INTEGER'}
SCHEMA = {'type': 'OBJECT', 'required': ['answer', 'abstained', 'answer_claims', 'claim_citations', 'numeric_facts'],
    'properties': {
        'answer': _STRING, 'abstained': {'type': 'BOOLEAN'},
        'answer_claims': {'type': 'ARRAY', 'items': _STRING},
        'claim_citations': {'type': 'ARRAY', 'items': {'type': 'OBJECT',
            'required': ['claim_index', 'source_index'], 'properties': {
                'claim_index': _INTEGER, 'source_index': _INTEGER}}},
        'numeric_facts': {'type': 'ARRAY', 'items': {'type': 'OBJECT',
            'required': ['claim_index', 'source_index', 'answer_quote', 'company', 'measure',
                         'value', 'unit', 'year_be', 'document', 'source_pdf_page', 'comparison_operator'],
            'properties': {'claim_index': _INTEGER, 'source_index': _INTEGER, 'answer_quote': _STRING,
                'company': _STRING, 'measure': _STRING, 'value': {'type': 'NUMBER'}, 'unit': _STRING,
                'year_be': {'type': 'INTEGER', 'nullable': True}, 'document': _STRING,
                'source_pdf_page': _INTEGER,
                'comparison_operator': {'type': 'STRING', 'enum': ['eq', 'lt', 'lte', 'gt', 'gte', 'approx', 'range']},
                'range_min': {'type': 'NUMBER'}, 'range_max': {'type': 'NUMBER'}}}}}}

# One canonical representation avoids making the model copy its answer into
# multiple independent fields. Metadata is still model-generated, never gold.
_NUMERIC_SCHEMA = deepcopy(SCHEMA['properties']['numeric_facts']['items'])
_NUMERIC_SCHEMA['required'] = [k for k in _NUMERIC_SCHEMA['required'] if k not in ('claim_index', 'answer_quote')]
_NUMERIC_SCHEMA['properties'] = {k: v for k,v in _NUMERIC_SCHEMA['properties'].items() if k not in ('claim_index', 'answer_quote')}
_NUMERIC_SCHEMA['properties']['value'] = {'type': 'NUMBER', 'description': 'Signed decimal quantity only, no unit; ratings such as AAA/AA/A must be qualitative claims with numeric=null'}
_NUMERIC_SCHEMA['properties']['qualifiers'] = {'type': 'STRING', 'description':
    'Optional source-supported scope, project, exclusion or timing details. No extra quantities; never repeat the primary value. Empty if unnecessary.'}
_NUMERIC_SCHEMA['required'] = ['entity' if k == 'company' else k for k in _NUMERIC_SCHEMA['required']]
_NUMERIC_SCHEMA['properties'].pop('company')
_NUMERIC_SCHEMA['properties']['entity'] = {'type': 'STRING', 'description': (
    'Actual subject owning this quantity, as named in QUESTION when supported: issuer, subsidiary, plant, project or person. '
    'Use the requested plant/person instead of its report issuer. Issuer-wide financial/staff/board metrics belong to the named issuer.')}
_NUMERIC_SCHEMA['properties']['measure'] = {'type': 'STRING', 'description': (
    'Concise requested quantity noun phrase, retaining ratio denominator and before/after/target roles. '
    'Keep explanatory installation/project/exclusion/timing details in qualifiers, not a rewritten long measure.')}
_NUMERIC_SCHEMA['properties']['comparison_operator']['description'] = (
    'Preserve source bound: ภายใน or ไม่เกิน means lte; อย่างน้อย means gte; ประมาณ means approx. '
    'A maximum permitted deadline is not an exact equality.')
_NUMERIC_SCHEMA['nullable'] = True
SCHEMA = {'type': 'OBJECT', 'required': ['abstained', 'refusal_reason', 'claims'],
    'properties': {'render_contract': {'type': 'STRING', 'enum': ['canonical-claims-v1']},
        'abstained': {'type': 'BOOLEAN'}, 'refusal_reason': _STRING,
        'claims': {'type': 'ARRAY', 'items': {'type': 'OBJECT',
            'required': ['text', 'source_indices', 'numeric'], 'properties': {
                'text': _STRING, 'source_indices': {'type': 'ARRAY', 'items': _INTEGER},
                'numeric': _NUMERIC_SCHEMA}}}}}
INSTRUCTION = '''\nReturn JSON following canonical-claims-v1, not a free-text answer.
Answer ONLY the facts required by QUESTION, usually one to three claims. Do
not summarize all supplied evidence, add strategy/history/forecasts or include
unrelated quantities. If asked for Vision, answer the Vision wording alone.
The application renders claims in order and appends citation links.
abstained=true requires claims=[] and a concise Thai refusal_reason. Otherwise
refusal_reason="" and provide every factual assertion as a separate claim.
For a qualitative claim, text is short Thai prose and numeric=null.
For EACH quantitative relation, text MUST be empty and numeric contains entity,
measure, signed decimal value as a JSON number, unit, performance/event year_be (null
only for timeless facts), comparison_operator, evidence filename document,
physical source_pdf_page and source_index. range requires range_min/range_max.
Native schema uses entity for the requested subject; the renderer maps that
explicit emitted entity into the historical company annotation field. This
is not necessarily the legal company publishing the report. Preserve the
plant, project, person or subsidiary whose value the question requests.
The application renders the numeric relation directly from these fields; do
not supply answer, answer_quote or another prose copy of a numeric claim.
source_indices lists only evidence indices supporting THIS claim. The numeric
source_index must also be in that list. All indices are zero-based from the
actual supplied evidence. Do not cite every returned source. Use ONE strongest
source for a quantity; include another only if required to support the claim.
Keep company/measure/year/scale/sign/comparator exactly as the evidence states.
Use the named entity and core quantity wording requested in QUESTION when it
denotes the same entity/relation in the supplied evidence. Keep measure concise:
do not prepend explanatory phrases such as number of days needed to prepare,
or append project descriptions. Put source-supported project, installation,
exclusion and timing-anchor details in optional numeric.qualifiers, rendered
with the same claim and citation. Keep ratio denominators and before/after
roles IN measure: distinguish a production share from a production amount.
Use source wording for units, retaining per-year/month/vehicle and rank bases.
For process questions describe the requested process and responsible actors;
omit unrelated course totals, awards, strategy and history. Every numeric
relation is rendered once; do not also paraphrase it in qualitative text.
Counts, durations (e.g. 30 days), ratios and percentages are quantities too;
do not hide them in qualitative text. Name the actual entity: resolve บริษัทฯ
using the supplied document issuer/context and use that specific name/code.
Never substitute report year for event year or equate forecasts with actuals.
Use year_be=null when the evidence has only a report-edition year and does not
bind the requested quantity to a performance/event year. Timeless reporting
deadlines are not annual results. A dated target uses its target year, even if
the question introduces another report year. Preserve Thai bounds explicitly:
ไม่เกิน/ภายใน => lte; อย่างน้อย/ไม่น้อยกว่า => gte; มากกว่า => gt;
น้อยกว่า => lt; ประมาณ => approx. Do not render a target as an actual result;
the measure must retain เป้าหมาย/ตั้งเป้า when that is what the source states.
Dates/report years alone are not quantities. Preserve approximate/bound/range.
If you cannot determine a relation, explicitly explain the missing part in a
qualitative claim, without inventing quantities. Do not copy evidence as answer.
หากถามวิสัยทัศน์ อย่าใช้พันธกิจแทน เมื่อหัวข้อจาก PDF เสียลำดับให้ตรวจ
บริบทและข้อความที่ระบุ Vision/วิสัยทัศน์จริง ไม่เดาจากประโยคธุรกิจทั่วไป
Ratings such as AAA, AA, A and credit grades are CATEGORIES, not decimal values:
use qualitative text and numeric=null. A statement containing a group count
(e.g. 2 groups) must render that count as a numeric claim, then explain each
group in separate qualitative claims WITHOUT repeating the count. Equipment
identifiers (Unit 5, 6 / หน่วยที่ 5, 6) in a measure name are context identifiers,
not additional quantities. Preserve them as part of the measure.
'''


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def annotation_digest(result, version=VERSION):
    fields = ('answer_claims', 'claim_spans', 'claim_citations', 'numeric_facts')
    if version != 'application-answer-capture-v1': fields += ('abstained',)
    return digest(json.dumps({key: result.get(key) for key in fields},
        sort_keys=True, ensure_ascii=False))


def validate_binding(full, answer):
    capture = full.get('answer_capture', {})
    version = capture.get('version')
    if version not in ('application-answer-capture-v1', 'application-answer-capture-v1.1', 'application-answer-capture-v1.2', 'application-answer-capture-v1.3', 'application-answer-capture-v1.4', 'application-answer-capture-v1.5', 'application-answer-capture-v1.6', 'application-answer-capture-v1.7', 'application-answer-capture-v1.8', 'application-answer-capture-v1.9', 'application-answer-capture-v1.10', 'application-answer-capture-v1.11', 'application-answer-capture-v1.12', 'application-answer-capture-v1.13', 'application-answer-capture-v1.14', 'application-answer-capture-v1.15', 'application-answer-capture-v1.16', 'application-answer-capture-v1.17', 'application-answer-capture-v1.18', 'application-answer-capture-v1.19', 'application-answer-capture-v1.20', 'application-answer-capture-v1.21', VERSION): return False
    blocks_bound = (version == 'application-answer-capture-v1' or
        capture.get('evidence_blocks_sha256') == digest(json.dumps(
            full.get('evidence_blocks'), sort_keys=True, ensure_ascii=False)))
    return (capture.get('answer_sha256') == digest(answer) and full.get('answer') == answer
            and capture.get('annotations_sha256') == annotation_digest(full, version)
            and capture.get('sources_sha256') == digest(json.dumps(
                full.get('sources', []), sort_keys=True, ensure_ascii=False))
            and capture.get('context_sha256') == digest(full.get('evidence_context') or '')
            and blocks_bound)


def validate_evidence_blocks(context, blocks):
    previous = 0
    for i, block in enumerate(blocks):
        start, end = block.get('start'), block.get('end')
        if (block.get('context_index') != i or type(start) is not int or type(end) is not int
            or start < previous or end <= start or end > len(context)
            or context[start:end] != block.get('text') or context[previous:start].strip()):
            raise ValueError('Invalid exact evidence block span')
        previous = end
    if context[previous:].strip():
        raise ValueError('Uncaptured evidence tail')
    return blocks


def evidence_context(sources, observations, *, max_chars=16000):
    """Preserve existing selection/truncation and expose exact visible blocks."""
    blocks, seen = [], set()
    for i, source in enumerate(sources):
        if source.get('page') is None and not source.get('url'):
            continue
        if source.get('value') is not None:
            payload = {k: source.get(k) for k in
                       ('filename', 'page', 'table_name', 'row_label', 'column',
                        'value', 'unit', 'quality_status')}
            text = json.dumps(payload, ensure_ascii=False)
        else:
            excerpt = str(source.get('excerpt') or '')
            if not excerpt:
                continue
            text = f"[{source.get('filename')} PDF page {source.get('page')}]\n{excerpt[:12000]}"
        if text in seen:
            continue
        seen.add(text)
        blocks.append({'source_index': i, 'body': text})
    if not blocks:
        text = '\n\n'.join(observations)[:max_chars]
        return text, ([{'context_index': 0, 'source_index': None, 'text': text,
                       'start': 0, 'end': len(text)}] if text else [])
    per_source = (None if any(s.get('context_kind') == 'page' for s in sources)
                  else min(12000, max(800, max_chars // len(blocks))))
    context, visible = '', []
    for block in blocks:
        body = block['body'] if per_source is None else block['body'][:per_source]
        rendered = f"[source_index={block['source_index']}]\n{body}"
        separator = '\n\n' if context else ''
        start = len(context) + len(separator)
        rendered = rendered[:max(0, max_chars-start)]
        if not rendered:
            break
        context += separator + rendered
        visible.append({'context_index': len(visible), 'source_index': block['source_index'],
                        'text': rendered, 'start': start, 'end': len(context)})
    return context, visible


def decode(raw):
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip())
    try:
        # Native NUMBER schema excludes category strings before generation.
        # Read the original decimal lexeme without a binary-float round trip;
        # normalization changes representation only, never the emitted value.
        payload = json.loads(text, parse_float=Decimal)
        if isinstance(payload, dict):
            raw_facts = payload.get('numeric_facts')
            facts = list(raw_facts) if isinstance(raw_facts, list) else []
            raw_claims = payload.get('claims')
            for claim in raw_claims if isinstance(raw_claims, list) else []:
                if isinstance(claim, dict) and isinstance(claim.get('numeric'), dict):
                    facts.append(claim['numeric'])
            for fact in facts:
                if isinstance(fact, dict):
                    for key in ('value', 'range_min', 'range_max'):
                        if isinstance(fact.get(key), Decimal):
                            fact[key] = format(fact[key], 'f')
    except (ValueError, TypeError):
        return raw.strip(), None
    canonical = (isinstance(payload, dict) and isinstance(payload.get('claims'), list)
                 and type(payload.get('abstained')) is bool
                 and payload.get('render_contract') in (None, 'canonical-claims-v1'))
    if canonical:
        try:
            # The renderer identifier is application configuration, not a
            # factual model annotation. Actual claims/numbers/links still must
            # be explicitly emitted and satisfy the same binding contract.
            payload['render_contract'] = 'canonical-claims-v1'
            payload = render_claims(payload)
        except (ValueError, TypeError, KeyError, InvalidOperation):
            return 'รูปแบบคำตอบจากโมเดลไม่ถูกต้อง กรุณาลองใหม่', None
    if not isinstance(payload, dict) or not isinstance(payload.get('answer'), str):
        if isinstance(payload, dict) and any(k in payload for k in ('claims', 'render_contract', 'refusal_reason')):
            return 'รูปแบบคำตอบจากโมเดลไม่ถูกต้อง กรุณาลองใหม่', None
        return raw.strip(), None
    return payload['answer'].strip(), payload


def render_claims(payload):
    """Render the emitted model data once; do not reconstruct saved old answers."""
    if type(payload.get('abstained')) is not bool or not isinstance(payload.get('claims'), list):
        raise ValueError('Invalid canonical payload')
    if payload['abstained']:
        if payload['claims'] or not isinstance(payload.get('refusal_reason'), str) or not payload['refusal_reason'].strip():
            raise ValueError('Abstention must have no factual claims')
        return {'answer': payload['refusal_reason'].strip(), 'abstained': True, 'render_contract': 'canonical-claims-v1',
                'answer_claims': [], 'claim_citations': [], 'numeric_facts': []}
    claims, links, facts = [], [], []
    operators = {'eq': 'เท่ากับ', 'lt': 'น้อยกว่า', 'lte': 'ไม่เกิน', 'gt': 'มากกว่า',
                 'gte': 'อย่างน้อย', 'approx': 'ประมาณ', 'range': 'ระหว่าง'}
    def number(value):
        decimal = Decimal(str(value))
        if not decimal.is_finite(): raise ValueError('Nonfinite number')
        return format(decimal, 'f')
    for i, item in enumerate(payload['claims']):
        if not isinstance(item, dict) or not isinstance(item.get('source_indices'), list):
            raise ValueError('Invalid canonical claim')
        fact = item.get('numeric')
        if fact is None:
            text = item['text']
            if not isinstance(text, str) or not text.strip(): raise ValueError('Empty claim')
            text = text.strip()
        else:
            if item.get('text') != '' or not isinstance(fact, dict):
                raise ValueError('Conflicting numeric prose')
            if 'entity' in fact:
                if 'company' in fact and fact['company'] != fact['entity']:
                    raise ValueError('Conflicting quantity entity')
                fact = {**fact, 'company': fact['entity']}
            if any(not isinstance(fact.get(k), str) or not fact[k].strip() for k in ('company', 'measure', 'unit', 'document')):
                raise ValueError('Missing numeric metadata')
            year = fact['year_be']; page = fact['source_pdf_page']
            if year is not None and (type(year) is not int or not 2400 <= year <= 2700): raise ValueError('Invalid year')
            if type(page) is not int or page < 1: raise ValueError('Invalid page')
            op = fact['comparison_operator']
            value = (number(fact['range_min'])+' ถึง '+number(fact['range_max'])
                     if op == 'range' else number(fact['value']))
            if op == 'range':
                # The historical scalar slot for a range represents the
                # explicitly emitted lower endpoint, never an unrendered
                # midpoint. Both bounds remain the model's actual output.
                if Decimal(str(fact['range_min'])) > Decimal(str(fact['range_max'])):
                    raise ValueError('Reversed numeric range')
                fact = {**fact, 'value': fact['range_min'], 'range_scalar_role': 'lower_bound'}
            period = (fact.get('period_start_be'), fact.get('period_end_be'))
            if any(y is not None for y in period):
                if (year is not None or any(type(y) is not int or not 2400 <= y <= 2700 for y in period)
                        or period[0] > period[1]):
                    raise ValueError('Invalid multi-year period')
                time_text = f' ช่วงปี {period[0]}–{period[1]}'
            else:
                time_text = f' ปี {year}' if year is not None else ''
            text = f"{fact['company']} {fact['measure']}" + time_text
            text += f" {operators[op]} {value} {fact['unit']}"
            # Bind the explicitly rendered primary relation rather than
            # mixing it with context quantities or dates in qualifiers.
            # All qualifier prose remains in the full claim, and global
            # quantity coverage still rejects unannotated extra numbers.
            primary_quote = text
            qualifier = fact.get('qualifiers', '')
            if not isinstance(qualifier, str): raise ValueError('Invalid numeric qualifiers')
            if qualifier.strip(): text += f" — {qualifier.strip()}"
            text += f" (PDF หน้า {page})"
            facts.append({**fact, 'claim_index': i, 'answer_quote': primary_quote})
        claims.append(text)
        links += [{'claim_index': i, 'source_index': s} for s in item['source_indices']]
    if not claims: raise ValueError('No answer claims')
    return {'answer': '\n'.join(claims), 'abstained': False, 'render_contract': 'canonical-claims-v1', 'answer_claims': claims,
            'claim_citations': links, 'numeric_facts': facts}


def record_generation(answer, payload, context, blocks, prompt=None, origin='model_generation'):
    state = CURRENT.get()
    if state is not None:
        state.append({'draft': answer, 'payload': deepcopy(payload), 'context': context,
                      'blocks': deepcopy(blocks), 'prompt_sha256': digest(prompt) if prompt else None,
                      'origin': origin})


def _span(text, corpus):
    if not isinstance(text, str) or not text.strip():
        return None
    start = corpus.find(text)
    return {'start': start, 'end': start+len(text)} if start >= 0 else None


def _number_tokens(text):
    result = []
    for token in re.findall(r'(?<![\d.,])(?:\(\s*-?\d[\d,]*(?:\.\d+)?\s*\)|-?\d[\d,]*(?:\.\d+)?)(?![\d.,])', text):
        try:
            cleaned = token.strip().replace(',', '')
            result.append(-Decimal(cleaned[1:-1].strip()) if cleaned.startswith('(')
                          else Decimal(cleaned))
        except InvalidOperation:
            pass
    return result


def _unit_variants(unit):
    return {'%': ('%', 'เปอร์เซ็นต์', 'ร้อยละ'), 'เปอร์เซ็นต์': ('%', 'เปอร์เซ็นต์', 'ร้อยละ'),
            'ร้อยละ': ('%', 'เปอร์เซ็นต์', 'ร้อยละ')}.get(unit, (unit,))


def _value_unit_in_quote(value, unit, quote):
    number = r'(?:\(\s*-?\d[\d,]*(?:\.\d+)?\s*\)|-?\d[\d,]*(?:\.\d+)?)'
    for match in re.finditer(r'(?<![\d.,])'+number+r'(?![\d.,])', quote):
        values = _number_tokens(match.group())
        if values != [value]:
            continue
        tail = quote[match.end():].lstrip()
        # Match longer currency/scaled units before substrings such as บาท.
        stated = re.match(r'(?:(?:ล้าน|พัน|หมื่น|แสน)?บาท|(?:ล้าน|พัน)?ดอลลาร์(?:สหรัฐ(?:อเมริกา)?|ออสเตรเลีย|ฮ่องกง|สิงคโปร์|แคนาดา|นิวซีแลนด์|\s*สรอ\.?)?|USD|THB)'
                          r'(?:(?:ต่อ[ก-๙]+)|(?:/[ก-๙A-Za-z]+))*|(?:เปอร์เซ็นต์(?:แรก)?|ร้อยละ|%)'
                          r'(?:(?:ต่อ[ก-๙]+)|(?:/[ก-๙A-Za-z]+))*', tail, re.I)
        if stated:
            if stated.group().casefold() in {u.casefold() for u in _unit_variants(unit)}:
                return True
        elif tail.startswith(unit) and not tail[len(unit):].startswith('/'):
            return True
        head = quote[:match.start()].rstrip()
        if any(head.endswith(u) for u in _unit_variants(unit)) and unit in ('%', 'ร้อยละ', 'เปอร์เซ็นต์'):
            return True
    return False


def _quantity_values(quote, company=None):
    """Exclude explicitly written calendar/page locations, not arbitrary 4-digit values."""
    ignored = []
    for pattern in (r'(?:ปี(?:ฐาน)?|พ\.?ศ\.?)\s*\d{4}\s*(?:[-–—]|ถึง)\s*\d{4}',
                    r'(?:ปี(?:ฐาน)?|พ\.?ศ\.?)\s*\d{4}',
                    r'(?:PDF\s*)?(?:หน้า(?:เอกสาร)?(?:ที่)?|pages?)\s*\d+',
                    r'(?:หน่วยที่|ตารางที่|เครื่องที่|รุ่นที่|ครั้งที่|ลำดับที่|\bUnit|\bGeneration|\bGen)\s*\d+(?:\s*(?:,|และ|and)\s*\d+)*',
                    r'(?:วันที่\s*)?\d{1,2}\s*(?:มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม)(?:\s*(?:พ\.?ศ\.?\s*)?\d{4})?'):
        ignored.extend((m.start(), m.end()) for m in re.finditer(pattern, quote, re.I))
    # A terminal number in an emitted proper name is an identifier (e.g.
    # เซ็นทรัล ซิตี้ เรสซิเดนซ์ 1). Do not mask quantities in the measure:
    # "63 แห่ง" and "9 เดือน" still require their own numeric annotations.
    if isinstance(company, str) and re.search(r'[^\d]\s+\d+$', company):
        identity = _span(company, quote)
        tail = re.search(r'\d+$', company)
        if identity:
            ignored.append((identity['start']+tail.start(), identity['start']+tail.end()))
    values = []
    for match in re.finditer(r'(?<![\d.,])(?:\(\s*-?\d[\d,]*(?:\.\d+)?\s*\)|-?\d[\d,]*(?:\.\d+)?)(?![\d.,])', quote):
        if not any(start <= match.start() and match.end() <= end for start, end in ignored):
            values.extend(_number_tokens(match.group()))
    return values


def numeric_binding_errors(fact, claim, source, links):
    errors = []
    quote = fact.get('answer_quote')
    if not _span(quote, claim):
        return ['numeric_quote_not_in_claim']
    for key in ('company', 'measure'):
        if not isinstance(fact.get(key), str) or not fact[key].strip() or fact[key] not in quote:
            errors.append('numeric_'+key+'_not_in_answer')
    unit = fact.get('unit')
    if not isinstance(unit, str) or not unit.strip() or not any(u in quote for u in _unit_variants(unit)):
        errors.append('numeric_unit_not_in_answer')
    company = fact.get('company')
    if isinstance(company, str) and re.fullmatch(r'[A-Za-z0-9 ]+', company) and not re.search(
        r'(?<![A-Za-z0-9])'+re.escape(company)+r'(?![A-Za-z0-9])', quote):
        errors.append('numeric_company_not_bound')
    try:
        value = Decimal(str(fact.get('value')).replace(',', ''))
        if not value.is_finite() or value not in _number_tokens(quote):
            errors.append('numeric_value_not_in_answer')
        elif not isinstance(fact.get('unit'), str) or not _value_unit_in_quote(value, fact['unit'], quote):
            if fact.get('comparison_operator') != 'range':
                errors.append('numeric_value_unit_not_bound')
        allowed = {value}
        if fact.get('comparison_operator') == 'range':
            for key in ('range_min', 'range_max'):
                try: allowed.add(Decimal(str(fact.get(key))))
                except InvalidOperation: pass
        quantities = _quantity_values(quote, company=fact.get('company'))
        expected_count = 2 if fact.get('comparison_operator') == 'range' else 1
        if not set(quantities) <= allowed or len(quantities) != expected_count:
            errors.append('numeric_quote_contains_other_quantities')
    except InvalidOperation:
        errors.append('invalid_numeric_value')
    year = fact.get('year_be')
    explicit_years = {int(y) for y in re.findall(r'(?:ปี|พ\.?ศ\.?)\s*(\d{4})(?!\d)', quote)}
    period = (fact.get('period_start_be'), fact.get('period_end_be'))
    if any(y is not None for y in period):
        if (year is not None or any(type(y) is not int or not 2400 <= y <= 2700 for y in period)
                or period[0] > period[1] or not re.search(
                    r'(?:ปี|พ\.?ศ\.?)\s*'+str(period[0])+r'\s*(?:[-–—]|ถึง)\s*'+str(period[1])+r'(?!\d)', quote)):
            errors.append('numeric_period_not_bound')
    elif ('year_be' not in fact or (year is None and explicit_years) or (year is not None and
       (type(year) is not int or not 2400 <= year <= 2700 or
        explicit_years != {year}))):
        errors.append('numeric_year_not_in_answer')
    page = fact.get('source_pdf_page')
    prose_pages = [int(p) for p in re.findall(r'(?:PDF\s*)?(?:หน้า(?:เอกสาร)?(?:ที่)?|pages?)\s*(\d+)', quote, re.I)]
    if (type(page) is not int or page < 1 or page != source.get('page') or
        (prose_pages and set(prose_pages) != {page})):
        errors.append('numeric_page_not_bound')
    if not source.get('filename') or fact.get('document') != source['filename']:
        errors.append('numeric_document_not_bound')
    operator = fact.get('comparison_operator')
    markers = {'lt': r'(?<!ไม่)น้อยกว่า|(?<!ไม่)ต่ำกว่า|(?<![<])<(?![=])',
               'lte': r'ไม่เกิน|ไม่มากกว่า|ไม่สูงกว่า|≤|<=', 'gt': r'(?<!ไม่)มากกว่า|(?<!ไม่)สูงกว่า|(?<![>])>(?![=])',
               'gte': r'อย่างน้อย|ไม่น้อยกว่า|ไม่ต่ำกว่า|≥|>=', 'approx': r'(?<!งบ)ประมาณ|ราว|approximately|about|≈',
               'range': r'ถึง|ระหว่าง|\bto\b'}
    # Comparator words in the entity/measure are nouns, e.g. งบประมาณ.
    # Check the relation outside those explicitly emitted identity spans.
    relation = quote
    for key in ('company', 'measure'):
        if isinstance(fact.get(key), str) and fact[key]:
            relation = relation.replace(fact[key], '', 1)
    found = {key for key, pattern in markers.items() if re.search(pattern, relation, re.I)}
    if len(found) > 1:
        errors.append('numeric_comparator_ambiguous')
    if operator not in ('eq', *markers) or (operator == 'eq' and found) or (operator != 'eq' and operator not in found):
        errors.append('numeric_comparator_not_in_answer')
    if operator == 'range':
        for key in ('range_min', 'range_max'):
            try:
                if Decimal(str(fact.get(key))) not in _number_tokens(quote):
                    errors.append('numeric_'+key+'_not_in_answer')
            except InvalidOperation:
                errors.append('numeric_'+key+'_not_in_answer')
        try:
            low, high = Decimal(str(fact.get('range_min'))), Decimal(str(fact.get('range_max')))
            if low > high or not _value_unit_in_quote(high, fact.get('unit') or '', quote):
                errors.append('numeric_range_unit_or_order_not_bound')
        except InvalidOperation:
            errors.append('numeric_range_unit_or_order_not_bound')
    pair = (fact.get('claim_index'), fact.get('source_index'))
    if pair not in links:
        errors.append('numeric_citation_not_declared')
    return errors


def finalize(result, events):
    result = deepcopy(result)
    answer, sources = result.get('answer', ''), result.get('sources', [])
    for i, source in enumerate(sources):
        source['source_index'] = i
        source['source_id'] = digest(json.dumps({k: v for k, v in source.items()
                                               if k not in ('source_index', 'source_id')},
                                              sort_keys=True, ensure_ascii=False))
    event = events[-1] if events else None
    result.update(answer_claims=None, claim_citations=None, numeric_facts=None,
                  evidence_context=None, evidence_blocks=None)
    capture = {'version': VERSION, 'answer_sha256': digest(answer),
               'sources_sha256': digest(json.dumps(sources, sort_keys=True, ensure_ascii=False)),
               'status': 'generation_annotations_missing', 'errors': [],
               'human_confirmed': False}
    result['answer_capture'] = capture
    if event is None:
        return result
    result.update(evidence_context=event['context'], evidence_blocks=event['blocks'])
    capture.update(origin=event['origin'], prompt_sha256=event['prompt_sha256'],
                   draft_sha256=digest(event['draft']), context_sha256=digest(event['context']),
                   evidence_blocks_sha256=digest(json.dumps(event['blocks'], sort_keys=True, ensure_ascii=False)))
    # The only permitted guard addition is the known OCR qualification suffix.
    suffix = ' (ค่าถอดจาก OCR; ยังไม่ตรวจเทียบ PDF)'
    if answer not in (event['draft'], event['draft']+suffix):
        capture['status'] = 'discarded_after_answer_guard'
        return result
    payload = event['payload']
    if payload is None:
        return result
    capture['render_contract'] = payload.get('render_contract', 'duplicated-prose-annotations')
    claims = payload.get('answer_claims')
    declared = payload.get('claim_citations')
    facts = payload.get('numeric_facts')
    if type(payload.get('abstained')) is bool:
        result['abstained'] = payload['abstained']
    if not all(isinstance(x, list) for x in (claims, declared, facts)):
        capture['status'] = 'invalid_generation_annotations'
        capture['errors'].append('annotation_arrays_missing')
        return result
    spans, end = [], 0
    for claim in claims:
        span = _span(claim, answer)
        if span is None or span['start'] < end:
            capture['status'] = 'invalid_generation_annotations'
            capture['errors'].append('claim_not_in_answer_or_overlapping')
            return result
        spans.append(span); end = span['end']
    if not claims and any(declared+facts):
        capture['status'] = 'invalid_generation_annotations'
        capture['errors'].append('annotations_without_claims')
        return result
    if payload.get('abstained') is True and (claims or declared or facts):
        capture['status'] = 'invalid_generation_annotations'
        capture['errors'].append('abstention_has_factual_annotations')
        return result
    if payload.get('abstained') is False and not claims:
        capture['status'] = 'invalid_generation_annotations'
        capture['errors'].append('non_abstention_has_no_claims')
        return result
    visible = {b['source_index'] for b in event['blocks'] if b['source_index'] is not None}
    links, pairs = [], set()
    for link in declared:
        if not isinstance(link, dict):
            capture['errors'].append('invalid_citation'); continue
        c, s = link.get('claim_index'), link.get('source_index')
        if type(c) is not int or not 0 <= c < len(claims) or type(s) is not int or s not in visible or not 0 <= s < len(sources):
            capture['errors'].append('citation_identifier_not_in_prompt'); continue
        if (c, s) not in pairs:
            pairs.add((c, s)); links.append({'claim_index': c, 'source_index': s,
                                           'source_id': sources[s]['source_id']})
    accepted = []
    for fact in facts:
        if not isinstance(fact, dict):
            capture['errors'].append('invalid_numeric_fact'); continue
        c, s = fact.get('claim_index'), fact.get('source_index')
        if type(c) is not int or not 0 <= c < len(claims) or type(s) is not int or not 0 <= s < len(sources):
            capture['errors'].append('numeric_invalid_identifier'); continue
        errors = numeric_binding_errors(fact, claims[c], sources[s], pairs)
        if payload.get('render_contract') == 'canonical-claims-v1' and fact.get('company') in ('บริษัทฯ', 'บริษัท', 'กลุ่มบริษัท'):
            errors.append('numeric_company_ambiguous')
        if errors:
            capture['errors'].extend(errors); continue
        accepted.append({**fact, 'annotation_origin': 'application_structured_output',
                         'binding_origin': event['origin'], 'source_id': sources[s]['source_id'],
                         'answer_span': _span(fact['answer_quote'], answer)})
    if payload.get('render_contract') == 'canonical-claims-v1':
        from collections import Counter
        explicit_quantity = r'(?:\d[\d,]*(?:\.\d+)?\s*(?:(?:ล้าน|พัน)?บาท|(?:ล้าน|พัน)?ดอลลาร์|%|เปอร์เซ็นต์|ร้อยละ|วัน|เดือน|เท่า|ตัน|สาขา|คน|กลุ่ม|คะแนน|แห่ง|เมกะวัตต์|MW)(?![A-Za-z])|ร้อยละ\s*\d)'
        for c,claim in enumerate(claims):
            local = [f for f in accepted if f['claim_index'] == c]
            if not re.search(explicit_quantity,claim,re.I):
                continue
            declared_values = []
            for f in local:
                keys = ('range_min', 'range_max') if f.get('comparison_operator') == 'range' else ('value',)
                declared_values.extend(Decimal(str(f[k])) for k in keys)
            company = local[0].get('company') if local else None
            # A bound primary tuple cannot license extra numbers in its
            # qualifier. Keep the primary tuple but reject incomplete coverage.
            if not local or Counter(_quantity_values(claim, company=company)) != Counter(declared_values):
                capture['errors'].append('unannotated_numeric_quantity')
    result.update(answer_claims=claims, claim_spans=spans, claim_citations=links, numeric_facts=accepted)
    capture['status'] = 'captured_with_errors' if capture['errors'] else 'captured'
    capture['claims_cover_answer'] = bool(claims) and answer[:spans[0]['start']].strip() == '' and all(
        not answer[left['end']:right['start']].strip(' \n.,;:()') for left, right in zip(spans, spans[1:])) and not answer[spans[-1]['end']:].replace(suffix, '').strip(' \n.,;:()')
    # An explicit refusal has no factual assertions to annotate. It remains a
    # failed answer for answerable questions and is reported in refusal counts.
    if payload.get('abstained') is True and not (claims or declared or facts):
        capture['claims_cover_answer'] = True
    if claims and not capture['claims_cover_answer']:
        capture['errors'].append('answer_has_unannotated_text')
        capture['status'] = 'captured_with_errors'
    capture['annotations_sha256'] = annotation_digest(result)
    return result
