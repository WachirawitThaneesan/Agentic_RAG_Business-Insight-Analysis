"""Versioned evaluation mathematics. No model calls or application imports.

Page metrics use binary relevance from locked PDF labels. Claim metrics use
auditable judge decisions with verbatim evidence. Custom claim metrics follow
RAG evaluation definitions; they are not official Ragas implementation scores.
"""
from __future__ import annotations

import math
import re
import unicodedata
from functools import lru_cache
from statistics import mean
from backend.eval.score_layers import _evidence_options, _hit_key, _answer_fact
from backend.eval.numeric import numeric_match,mentions_in,years_in

VERSION = 'comprehensive-rag-v1.9-bound-claims-font-audit'


def average(values):
    values = [v for v in values if v is not None]
    return mean(values) if values else None


def fraction(n, d):
    return n / d if d else None


def f1(p, r):
    return None if p is None or r is None else (2*p*r/(p+r) if p+r else 0.0)


def wilson(successes, n):
    if not n:
        return None
    z = 1.959963984540054
    p = successes/n
    center = (p + z*z/(2*n))/(1+z*z/n)
    half = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    return [max(0., center-half), min(1., center+half)]


def page_metrics(item, hits, documents, *, k=5, depth=None):
    """Duplicates consume rank slots and never earn a second relevance credit.

    Precision uses the union of valid alternative pages; recall uses the most
    completely recovered valid evidence set. nDCG/MAP use the union as qrels.
    Empty retrieval is a measured failure. Missing retrieval is handled by caller.
    """
    if depth is not None and k > depth:
        return {'k': k, 'status': 'not_measured', 'reason': 'saved_depth_below_k'}
    options = _evidence_options(item)
    relevant = set.union(*options)
    keys = [_hit_key(h, [item], documents, 'source') for h in hits[:k]]
    seen = set()
    binary = []
    for key in keys:
        binary.append(int(key in relevant and key not in seen))
        seen.add(key)
    recovered = {x for x in keys if x is not None}
    recall = max(len(recovered & o)/len(o) for o in options)
    total = sum(binary)
    ap = sum(sum(binary[:i+1])/(i+1) for i, v in enumerate(binary) if v)/len(relevant)
    dcg = sum(v/math.log2(i+2) for i, v in enumerate(binary))
    idcg = sum(1/math.log2(i+2) for i in range(min(k, len(relevant))))
    first = next((i+1 for i, v in enumerate(binary) if v), None)
    return {'k': k, 'status': 'measured', 'hit': int(total > 0),
            'precision': total/k, 'recall': recall, 'f1': f1(total/k, recall),
            'mrr': 1/first if first else 0., 'map': ap, 'ndcg': dcg/idcg,
            'complete_evidence': int(recall == 1), 'returned': len(keys),
            'unique_pages': len(recovered), 'relevant_unique_pages': total,
            'duplicate_slots': len([x for x in keys if x is not None])-len(recovered),
            'unlocatable_slots': sum(x is None for x in keys),
            'first_relevant_rank': first, 'rank_relevance': binary}


def is_abstention(answer):
    return bool(re.search(r'ไม่พบ(?:ข้อมูล|หลักฐาน)|หลักฐาน(?:ยัง)?ไม่(?:เพียง)?พอ|'
                          r'ไม่สามารถ(?:ระบุ|ตอบ|ยืนยัน)|insufficient evidence|'
                          r'not enough (?:information|evidence)|cannot determine|ยังไม่มีข้อมูล|'
                          r'^(?:หลักฐาน|เอกสาร|ข้อมูลที่(?:ให้|ค้น)).{0,80}ไม่มีข้อมูล(?:เกี่ยวกับ|เพียงพอ)', answer, re.I))


def deterministic_answer(item, record, documents):
    answer = record.get('answer') or ''
    answerable = item.get('answerable', True)
    refused = is_abstention(answer)
    model_error=bool(record.get('full_result',{}).get('error_type')) or bool(re.search(
        r'^(?:AGENT_ERROR|GENERATION_ERROR)|โมเดลไม่ส่งคำตอบกลับมา|โมเดลท้องถิ่นไม่สามารถสร้างคำตอบ',answer))
    citations = record.get('citations') or []
    full = record.get('full_result', {})
    if full.get('answer_capture'):
        from backend.services.answer_capture import validate_binding
        # Actual app links use the captured source registry. Returned sources
        # alone do not establish that the app cited any of them.
        citations = []
        if validate_binding(full, answer):
            sources = full.get('sources', [])
            claims = full.get('answer_claims') or []
            for link in full.get('claim_citations') or []:
                c, s = link.get('claim_index'), link.get('source_index')
                if (type(c) is int and 0 <= c < len(claims) and type(s) is int
                        and 0 <= s < len(sources)
                        and link.get('source_id') == sources[s].get('source_id')):
                    citations.append(sources[s])
    if not answerable:
        years=years_in(answer)
        values=[m for m in mentions_in(answer) if not any(m.start==s and m.end==e for s,e,_ in years)]
        # These controls ask for unavailable financial/count values. Calendar
        # years and page locations may explain missing scope, but alternative
        # answer quantities cannot turn a refusal marker into a passing answer.
        correct=refused and not values and bool(answer.strip()) and not model_error
        return {'fact_status': 'not_applicable', 'answerable': False,
                'abstained': refused, 'empty_response': not bool(answer.strip()),
                'model_error_response':model_error,
                'negative_noncalendar_quantities':len(values),
                'expected_abstention_correct': correct,
                'strict_correct': correct}
    quantities=item.get('answer_components',{}).get('multiple_quantities')
    if quantities:
        checks=[numeric_match(q['value'],answer,expected_unit=q['unit'],expected_year=q.get('year_be'),
            allowed_other_quantities=[(other['value'],other['unit']) for j,other in enumerate(quantities) if j!=i])
            for i,q in enumerate(quantities)]
        status='correct' if all(checks) else 'incorrect';reason='all_required_quantities_checked'
    else:
        status, reason = _answer_fact(item, answer)
    options = _evidence_options(item)
    relevant = set.union(*options)
    keys = {_hit_key(c, [item], documents, 'source') for c in citations}
    valid = {key for key in keys if key is not None}
    page_recall = max(len(valid & o)/len(o) for o in options)
    # Prose page numbers must agree with physical PDF qrels; source-list
    # membership alone is insufficient (e.g. the old F05 false positive).
    stated_pages = {int(p) for p in re.findall(
        r'(?:PDF\s*(?:หน้า|p(?:age)?\.?)[\s.:]*|หน้า\s*(?:PDF)?[\s.:]*|\bp\.[\s:]?)(\d+)', answer, re.I)}
    allowed_pages = {page for _, page in relevant}
    # UI source links count as citations; an omitted prose page is reported,
    # not treated as a wrong citation. An explicitly wrong page always fails.
    prose_consistent = not stated_pages or stated_pages <= allowed_pages
    return {'fact_status': status, 'fact_reason': reason, 'answerable': True,
            'abstained': refused, 'empty_response': not bool(answer.strip()),
            'model_error_response':model_error,
            'page_citation_precision': fraction(len(valid & relevant), len(keys)),
            'page_citation_recall': page_recall, 'page_citation_complete': page_recall == 1,
            'prose_page_present': bool(stated_pages), 'prose_pages': sorted(stated_pages),
            'prose_page_consistent': prose_consistent,
            'explicit_page_citation_complete': bool(stated_pages) and prose_consistent and page_recall == 1,
            'strict_correct': (status == 'correct' and page_recall == 1 and prose_consistent)
                if status in ('correct','incorrect') else None}


def source_text(source):
    if source.get('excerpt'):
        return str(source['excerpt'])
    if source.get('value') is not None:
        import json
        return json.dumps({k: source.get(k) for k in (
            'filename', 'page', 'row_label', 'column', 'value', 'unit',
            'quality_status')}, ensure_ascii=False)
    return str(source.get('text') or '')


@lru_cache(maxsize=64)
def _quote_index(text):
    """Map conservative font/whitespace normalization back to original chars.

    Digits, signs, units and punctuation are retained. Only whitespace,
    duplicated Thai vowel/tone marks and short Latin font intrusions between
    Thai characters are normalized. Every accepted span remains inspectable.
    """
    chars=[];positions=[]
    for i,char in enumerate(text):
        # Confirmed PDF encoding artifact: Sara Am is already complete, then
        # the font adds U+FFFD (e.g. สำ�คัญ). Retain every real Thai letter,
        # number/sign/unit and all other replacement characters.
        if (char == '\ufffd' and i > 0 and text[i-1] == '\u0e33'
                and i+1 < len(text) and 'ก' <= text[i+1] <= 'ฮ'):
            continue
        for c in unicodedata.normalize('NFKC',char):
            if not c.isspace():chars.append(c);positions.append(i)
    joined=''.join(chars)
    remove=set()
    for m in re.finditer(r'(?<=[ก-๙])[A-Za-zÀ-ÿĚ]{1,2}(?=[ก-๙])',joined):
        remove.update(range(m.start(),m.end()))
    for m in re.finditer(r'([เแาิีึืุู็่้๊๋์ํ๎])\1+',joined):
        remove.update(range(m.start()+1,m.end()))
    return ''.join(c for i,c in enumerate(chars) if i not in remove), [p for i,p in enumerate(positions) if i not in remove]


def quote_span(quote,corpus):
    if not isinstance(quote,str) or not quote.strip():return None
    start=corpus.find(quote)
    if start>=0:return {'original':quote,'start':start,'end':start+len(quote),'matching':'verbatim'}
    needle,_=_quote_index(quote);haystack,mapping=_quote_index(corpus)
    if len(needle)<8:return None
    start=haystack.find(needle)
    if start<0:return None
    a=mapping[start];b=mapping[start+len(needle)-1]+1
    return {'original':corpus[a:b],'start':a,'end':b,'matching':'mapped_font_whitespace_normalization'}


def validate_judgment(judgment, *, context, sources, reference, evidence_blocks=None, captured_claims=None,
                      actual_citations=None):
    """Reject supported verdicts with missing/invented quotes and invalid IDs.

    Quotation membership is an audit constraint, not an entailment proof.
    Entailment itself remains an explicitly AI-judged decision.
    """
    if not isinstance(judgment, dict):
        raise ValueError('Judge output must be an object')
    required = {'answer_claims', 'reference_claims', 'context_relevance', 'relevancy'}
    if not required <= judgment.keys():
        raise ValueError('Incomplete judge output')
    warnings = []
    repairs=0
    for name in ('answer_claims', 'reference_claims', 'context_relevance'):
        if not isinstance(judgment[name], list):
            raise ValueError(f'{name} must be an array')
    if captured_claims is not None and [c.get('text') for c in judgment['answer_claims']] != captured_claims:
        raise ValueError('Judge claims differ from captured application claim identities')
    if actual_citations is not None:
        decisions = judgment.get('actual_citation_audit')
        if not isinstance(decisions, list):
            raise ValueError('Actual citation entailment audit missing')
        expected = {(x['claim_index'], x['source_index']) for x in actual_citations}
        seen_links = set()
        for decision in decisions:
            pair = (decision.get('claim_index'), decision.get('source_index'))
            if (any(type(i) is not int for i in pair) or pair not in expected or pair in seen_links
                or decision.get('verdict') not in ('supported', 'contradicted', 'insufficient')):
                raise ValueError('Invalid/duplicate/unemitted citation audit pair')
            seen_links.add(pair)
            if decision.get('verdict') == 'supported' and not quote_span(decision.get('quote'), source_text(sources[pair[1]])):
                warnings.append('Actual citation quote unverifiable; retain unresolved entailment')
        if seen_links != expected:
            raise ValueError('Must explicitly audit every emitted citation pair')
    for claim in judgment['answer_claims']:
        if not isinstance(claim.get('text'), str) or not claim['text'].strip():
            raise ValueError('Each claim needs text')
        for field, quote_field, corpus in (
                ('faithfulness', 'context_quote', context),
                ('factual', 'reference_quote', reference)):
            if claim.get(field) not in ('supported', 'contradicted', 'insufficient'):
                raise ValueError(f'Invalid {field} verdict')
            claim[field+'_ai_verdict']=claim[field]
            quote = claim.get(quote_field) or ''
            span=quote_span(quote,corpus)
            if span:
                claim[quote_field+'_evidence_span']=span
                repairs+=span['matching']!='verbatim'
            if claim[field] == 'supported' and not span:
                claim[field] = 'insufficient'
                warnings.append(f'{field}: rejected quote for {claim["text"]}')
        accepted = []
        for citation in claim.get('citations', []):
            idx = citation.get('source_index')
            quote = citation.get('quote') or ''
            span=quote_span(quote,source_text(sources[idx])) if type(idx) is int and 0<=idx<len(sources) else None
            if span and claim['faithfulness_ai_verdict']!='contradicted':
                citation['evidence_span']=span
                repairs+=span['matching']!='verbatim'
                accepted.append(citation)
            else:
                warnings.append('Rejected citation with invalid source/quote or contradicted claim')
        claim['citations'] = accepted
        if type(claim.get('relevant')) is not bool:
            raise ValueError('Claim relevant must be boolean')
    if judgment['relevancy'].get('score') not in (0, 1, 2):
        raise ValueError('Relevancy score must be 0, 1 or 2')
    for rc in judgment['reference_claims']:
        if not isinstance(rc.get('text'), str) or not rc['text'].strip():
            raise ValueError('Each reference claim needs nonempty text')
        for field in ('answer_covered', 'context_covered'):
            if type(rc.get(field)) is not bool:
                raise ValueError(f'{field} must be boolean')
        span=quote_span(rc.get('context_quote'),context)
        if span:
            rc['context_evidence_span']=span
            repairs+=span['matching']!='verbatim'
        if rc['context_covered'] and not span:
            rc['context_covered'] = False
            warnings.append('Rejected reference coverage quote')
    # Context indices identify exactly the supplied prompt blocks. Returned
    # sources retain their separate indices for citation entailment auditing.
    context_sources = sources if evidence_blocks is None else [
        {'excerpt': block['text']} for block in evidence_blocks]
    seen = set()
    for row in judgment['context_relevance']:
        idx = row.get('context_index')
        if type(idx) is not int or idx in seen or not 0 <= idx < len(context_sources):
            raise ValueError('Invalid/duplicate context_index')
        seen.add(idx)
        if type(row.get('useful')) is not bool:
            raise ValueError('Context useful must be boolean')
        span=quote_span(row.get('quote'),source_text(context_sources[idx]))
        if span:
            row['evidence_span']=span
            repairs+=span['matching']!='verbatim'
        if row['useful'] and not span:
            row['useful'] = False
            warnings.append('Rejected context relevance quote')
    if seen != set(range(len(context_sources))):
        raise ValueError('Must judge all supplied contexts')
    judgment['validation_warnings'] = warnings
    judgment['mapped_quote_repairs']=repairs
    return judgment


def claim_metrics(judgment):
    claims = judgment['answer_claims']
    refs = judgment['reference_claims']
    supported = sum(c['faithfulness'] == 'supported' for c in claims)
    factual = sum(c['factual'] == 'supported' for c in claims)
    contradicted = sum(c['factual'] == 'contradicted' for c in claims)
    unknown = sum(c['factual'] == 'insufficient' for c in claims)
    covered = sum(c['answer_covered'] for c in refs)
    cp = fraction(factual, len(claims))
    cr = fraction(covered, len(refs))
    citation_links = [link for c in claims for link in c['citations']]
    cited_claims = sum(bool(c['citations']) for c in claims)
    context_rows = sorted(judgment['context_relevance'], key=lambda r:r['context_index'])
    rel = [int(row['useful']) for row in context_rows]
    ap = (fraction(sum(sum(rel[:i+1])/(i+1) for i,v in enumerate(rel) if v), sum(rel))
          if sum(rel) else (0.0 if rel else None))
    return {'claim_count': len(claims), 'reference_claim_count': len(refs),
            'supported_claim_count': supported, 'factual_supported_claim_count': factual,
            'reference_claims_covered': covered,
            'context_reference_claims_covered': sum(c['context_covered'] for c in refs),
            'claims_with_supporting_citation': cited_claims,
            'faithfulness': fraction(supported, len(claims)),
            'faithfulness_ai_judged': fraction(sum(c.get('faithfulness_ai_verdict',c['faithfulness'])=='supported' for c in claims),len(claims)),
            'factual_precision_ai_judged': fraction(sum(c.get('factual_ai_verdict',c['factual'])=='supported' for c in claims),len(claims)),
            'unsupported_claim_rate': fraction(len(claims)-supported, len(claims)),
            'unverified_or_unsupported_claim_rate': fraction(len(claims)-supported, len(claims)),
            'factual_precision': cp, 'factual_recall': cr, 'factual_f1': f1(cp, cr),
            'factual_precision_determined': fraction(factual,factual+contradicted),
            'contradiction_rate': fraction(contradicted, len(claims)),
            'unverifiable_claim_rate': fraction(unknown, len(claims)),
            'claim_relevance_precision': fraction(sum(c['relevant'] for c in claims), len(claims)),
            'answer_relevancy_rubric': judgment['relevancy']['score']/2,
            'context_usefulness_precision': fraction(sum(rel), len(rel)),
            'context_precision_ap': ap,
            'context_recall': fraction(sum(c['context_covered'] for c in refs), len(refs)),
            'citation_claim_recall': fraction(cited_claims, len(claims)),
            'citation_source_precision': fraction(len({link['source_index'] for link in citation_links}), len(context_rows)),
            'citation_f1': f1(fraction(len({link['source_index'] for link in citation_links}), len(context_rows)),fraction(cited_claims,len(claims))),
            'supported_citation_link_count': len(citation_links),
            'all_claims_supported': bool(claims) and supported == len(claims),
            'all_claims_cited': bool(claims) and cited_claims == len(claims),
            'quote_validation_warnings': len(judgment['validation_warnings']),
            'mapped_quote_repairs':judgment.get('mapped_quote_repairs',0)}


def aggregate(rows):
    numeric_keys = {key for row in rows for key, value in row.items()
                    if isinstance(value, (float, int, bool)) or value is None}
    return {key: {'mean': average([r.get(key) for r in rows]),
                  'n_measured': sum(r.get(key) is not None for r in rows),
                  'n_total': len(rows)} for key in sorted(numeric_keys)}
