"""Explicit evaluation contracts without changing preserved v1.5 scores.

An AI verdict and an auditable quote are separate observations. Retrieved
sources and citations actually emitted by the application are also separate.
This module never treats judge-proposed citations as emitted citations.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re

from backend.eval.comprehensive import fraction, quote_span, source_text
from backend.eval.numeric import numeric_match, quantity_match

VERSION = 'rag-evaluation-contract-v2.0'

TARGETS = {
    'page_hit_at_5': .90, 'factual_precision': .95,
    'factual_recall': .85, 'context_recall': .90,
    'answer_relevancy': .90, 'faithfulness': .95,
    'citation_link_precision': .95, 'citation_claim_recall': .90,
    'strict_numeric_accuracy': .95, 'complete_answer_success': .75,
}


def classify_claim(claim, *, context, reference):
    """Preserve raw AI verdicts; failing quote validation is not contradiction."""
    result={'text':claim['text']}
    for field,quote_field,corpus in (
        ('faithfulness','context_quote',context),
        ('factual','reference_quote',reference)):
        verdict=claim.get(field)
        if verdict not in ('supported','contradicted','insufficient'):
            raise ValueError('Unsupported raw verdict')
        quote=claim.get(quote_field) or ''
        span=quote_span(quote,corpus)
        if verdict=='supported':
            state='supported_quote_verified' if span else 'quote_unverifiable'
        elif verdict=='contradicted':
            state='contradicted_ai_needs_review'
        else:state='insufficient_evidence'
        if span:reason=span['matching']
        elif not quote:reason='judge_did_not_supply_quote'
        elif field=='faithfulness' and quote_span(quote,reference):
            reason='quote_present_in_reference_but_not_actual_context'
        elif field=='factual' and quote_span(quote,context):
            reason='quote_present_in_context_but_not_reference'
        else:reason='quote_not_found_in_audited_text'
        result[field]={'state':state,'ai_verdict':verdict,
            'quote':quote,'evidence_span':span,'reason':reason,
            'human_confirmed':False}
    return result


def actual_citation_metrics(claims, sources, declared_links, *, support_decisions=None):
    """Score only captured claim→source links explicitly emitted by the app.

    support_decisions contains separately audited entailment judgments for
    those exact pairs. Unknown judgments retain an uncertainty count and a
    conservative lower bound, never silently enter an optimistic denominator.
    No captured mapping => N/A, rather than reinterpreting retrieval results.
    """
    if declared_links is None:
        return {'status':'not_measured_actual_claim_citation_mapping_missing',
            'citation_link_precision':None,'citation_claim_recall':None,
            'n_actual_links':None,'n_answer_claims':len(claims),'links':[]}
    decisions={(d['claim_index'],d['source_index']):d for d in (support_decisions or [])}
    links=[]
    for link in declared_links:
        c=link.get('claim_index');s=link.get('source_index')
        valid=(type(c) is int and 0<=c<len(claims) and type(s) is int and 0<=s<len(sources))
        if not valid:state='invalid_claim_or_source_identifier'
        else:
            decision=decisions.get((c,s))
            if not decision:state='entailment_not_audited'
            elif decision.get('verdict')=='supported':
                state='supported_quote_verified' if quote_span(decision.get('quote'),source_text(sources[s])) else 'quote_unverifiable'
            elif decision.get('verdict')=='contradicted':state='contradicted_ai_needs_review'
            elif decision.get('verdict')=='insufficient':state='insufficient_evidence'
            else:raise ValueError('Invalid citation entailment verdict')
        links.append({**deepcopy(link),'state':state})
    supported=[x for x in links if x['state']=='supported_quote_verified']
    unresolved=sum(x['state'] in ('entailment_not_audited','quote_unverifiable') for x in links)
    precision=fraction(len(supported),len(links)) if not unresolved else None
    return {'status':'measured' if not unresolved else 'partial_entailment_audit',
        'citation_link_precision':precision,
        'citation_link_precision_lower_bound':fraction(len(supported),len(links)),
        'citation_claim_recall':fraction(len({x['claim_index'] for x in supported}),len(claims)) if not unresolved else None,
        'citation_claim_recall_lower_bound':fraction(len({x['claim_index'] for x in supported}),len(claims)),
        'n_actual_links':len(links),'n_supported_links':len(supported),
        'n_unresolved_links':unresolved,'n_answer_claims':len(claims),'links':links,
        'decision_scope':'AI entailment plus quote membership; human review separate'}


def validate_numeric_label(label):
    required=('company','measure','value','unit','document','source_pdf_page',
        'source_sha256','year_kind','review_status','comparison_operator')
    for key in required:
        if key not in label or label[key] in (None,''):raise ValueError('Missing numeric label '+key)
    if type(label['source_pdf_page']) is not int or label['source_pdf_page']<1:
        raise ValueError('Physical PDF page must be a positive integer')
    if not re.fullmatch(r'[0-9a-f]{64}',label['source_sha256']):raise ValueError('Invalid PDF hash')
    if not label.get('evidence_quote'):
        if not label.get('visual_evidence_transcript') or not re.fullmatch(r'[0-9a-f]{64}',label.get('image_sha256','')):
            raise ValueError('Need native evidence quote OR transcript with hashed PDF image')
    try:
        if not Decimal(str(label['value']).replace(',','')).is_finite():raise ValueError('Nonfinite value')
    except InvalidOperation as exc:raise ValueError('Invalid value') from exc
    if label['year_kind'] not in ('event_or_performance','report_context_only','not_applicable'):
        raise ValueError('Invalid year scope')
    year=label.get('year_be')
    if label['year_kind']=='event_or_performance' and (type(year) is not int or not 2400<=year<=2700):
        raise ValueError('Performance/event year needs an explicit BE year')
    if label['year_kind']=='not_applicable' and year is not None:raise ValueError('Timeless label has year')
    if label['comparison_operator'] not in ('eq','lt','lte','gt','gte','approx','range'):
        raise ValueError('Invalid quantity comparison operator')
    if label['comparison_operator']=='range':
        try:
            low=Decimal(str(label['range_min']));high=Decimal(str(label['range_max']))
            if not low.is_finite() or not high.is_finite() or low>high:raise ValueError('Invalid range')
        except (KeyError,InvalidOperation) as exc:raise ValueError('Range needs both explicit bounds') from exc
    if label.get('rounding_decimals') is not None and str(label.get('tolerance',0)) not in ('0','0.0'):
        raise ValueError('Choose rounding OR tolerance, not both')
    # Exercise the existing strict numerical parser to reject invalid units/
    # tolerance configurations without granting any label human certification.
    numeric_match(label['value'],str(label['value'])+' '+label['unit'],
        expected_unit=label['unit'],tolerance=label.get('tolerance',0),
        rounding_decimals=label.get('rounding_decimals'))
    return deepcopy(label)


def numeric_fact_result(label, fact, *, allow_provisional=False, identity_checks=None):
    """Compare a bound answer fact, not numbers found elsewhere in its prose.

    Fact annotations must preserve their origin (application structured output
    or independent review). A model-extracted annotation is not a certified
    deterministic answer; its provenance must be reported by the caller.
    """
    validate_numeric_label(label)
    if label['review_status']!='human_confirmed' and not allow_provisional:
        return {'state':'reference_review_pending','correct':None}
    missing=[k for k in ('company','measure','value','unit','year_be','document','source_pdf_page','comparison_operator') if k not in fact]
    if missing:return {'state':'answer_context_unverifiable','correct':None,'missing':missing}
    try:
        actual_value=Decimal(str(fact['value']).replace(',',''))
        if not actual_value.is_finite():raise InvalidOperation
    except InvalidOperation:
        return {'state':'invalid_answer_quantity','correct':False}
    def agrees(key):
        allowed=[label[key]]+label.get(key+'_aliases',[])
        return str(fact[key]).casefold().strip() in {str(x).casefold().strip() for x in allowed}
    checks={'company':agrees('company'),'measure':agrees('measure'),
        'comparison_operator':fact['comparison_operator']==label['comparison_operator'],
        'year':fact['year_be']==label.get('year_be'),
        'document':fact['document']==label['document'],
        'page':fact['source_pdf_page'] in [label['source_pdf_page']]+label.get('alternate_pdf_pages',[]),
        'signed_value_and_explicit_unit':quantity_match(label['value'],actual_value,
            actual_unit=fact['unit'],expected_unit=label['unit'],tolerance=label.get('tolerance',0),
            rounding_decimals=label.get('rounding_decimals'))}
    if label['comparison_operator']=='range':
        checks['range_bounds']=all(key in fact and quantity_match(label[key],fact[key],actual_unit=fact['unit'],
            expected_unit=label['unit'],tolerance=label.get('tolerance',0),
            rounding_decimals=label.get('rounding_decimals')) for key in ('range_min','range_max'))
    literal_checks=deepcopy(checks)
    if identity_checks is not None:
        for key in ('company','measure'):
            if key in identity_checks and (type(identity_checks[key]) is bool or identity_checks[key] is None):
                checks[key]=identity_checks[key]
    correct=(False if any(v is False for v in checks.values()) else
             None if any(v is None for v in checks.values()) else True)
    return {'state':'correct' if correct else 'wrong_bound_numeric_fact',
        'correct':correct,'checks':checks,'reference_review_status':label['review_status'],
        **({'literal_identity_checks':literal_checks,'literal_identity_correct':all(literal_checks.values()),
            'identity_method':'source-quoted AI entity/measure comparison; values/units/years/signs/pages/comparators remain deterministic'}
           if identity_checks is not None else {})}
