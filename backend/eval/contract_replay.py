"""Offline contract integration over saved answers and raw AI decisions.

Unknown dimensions stay unknown. This module cannot generate claims, infer
application citations from judge links, or fill answer facts from reference labels.
"""
from collections import Counter
from copy import deepcopy
from statistics import mean
import json

from backend.eval.comprehensive import fraction, quote_span, validate_judgment
from backend.eval.contracts import (VERSION, TARGETS, actual_citation_metrics,
                                    classify_claim, numeric_fact_result)

REPLAY_VERSION = 'saved-answer-contract-replay-v2.8'
STATES = ('supported_quote_verified', 'contradicted_ai_needs_review',
          'insufficient_evidence', 'quote_unverifiable')


def validate_reference_binding(row, item):
    """A matching bank file hash cannot certify stale labels inside an audit."""
    fields = ('reference_answer', 'answer_components', 'expected_row',
        'expected_column_context', 'document', 'source_pdf_page', 'answerable',
        'reference_quote', 'reference_evidence')
    expected = {k: v for k, v in item.items() if k in fields}
    try:
        captured, _ = json.JSONDecoder().raw_decode(row['reference'])
    except (ValueError, TypeError) as exc:
        raise ValueError('Captured reference has no frozen label prefix') from exc
    if captured != expected or row['question'] != item['question_th']:
        raise ValueError('Judged question/reference differs from frozen bank item')


def numeric_results(labels, full, answer, *, allow_provisional=False, document_registry=None):
    results = []
    facts = full.get('numeric_facts')
    for label in labels:
        if label.get('blind_recheck_reference_conflict'):
            results.append({'quantity_index': label['quantity_index'],
                            'reference_review_status': label['review_status'],
                            'human_confirmed': False,
                            'state': 'reference_conflict_pending', 'correct': None})
            continue
        def identity_matches(fact):
            if fact.get('quantity_index') is not None:
                return fact['quantity_index'] == label['quantity_index']
            # Match emitted identities, never assign gold indices into app output.
            def agrees(key):
                return str(fact.get(key, '')).strip().casefold() in {
                    str(v).strip().casefold() for v in [label[key]] + label.get(key+'_aliases', [])}
            return agrees('company') and agrees('measure')
        matches = [f for f in (facts or []) if isinstance(f, dict) and identity_matches(f)]
        if not matches and len(labels) == 1 and isinstance(facts, list) and len(facts) == 1 and isinstance(facts[0], dict):
            # A fully emitted wrong company/measure is a measurable error for
            # a single-quantity question, not an annotation coverage success gap.
            matches = facts
        if not matches:
            from backend.services.answer_capture import validate_binding
            if (full.get('abstained') is True and full.get('answer_capture', {}).get('status') == 'captured'
                    and validate_binding(full, answer) and facts == []):
                result = {'state': 'explicit_abstention_on_required_quantity', 'correct': False}
            elif (full.get('answer_capture', {}).get('status') == 'captured'
                    and full['answer_capture'].get('claims_cover_answer')
                    and validate_binding(full, answer) and isinstance(facts, list)):
                # Complete emitted annotations contain no matching required
                # relation. This is a measured omission, not a hidden correct
                # number or an invitation to fill output from the reference.
                result = {'state': 'required_relation_not_emitted', 'correct': False}
            else:
                result = {'state': 'answer_numeric_annotation_missing', 'correct': None}
        elif len(matches) != 1:
            from backend.services.answer_capture import validate_binding
            if (full.get('answer_capture', {}).get('status') == 'captured'
                    and full['answer_capture'].get('claims_cover_answer') and validate_binding(full, answer)):
                result = {'state': 'ambiguous_emitted_required_relation', 'correct': False}
            else:
                result = {'state': 'ambiguous_answer_numeric_annotation', 'correct': None}
        else:
            fact = matches[0]
            if full.get('answer_capture'):
                from backend.services.answer_capture import validate_binding
                if not validate_binding(full, answer):
                    results.append({'quantity_index': label['quantity_index'], 'state': 'application_capture_binding_mismatch', 'correct': None})
                    continue
            origin = fact.get('annotation_origin')
            if origin not in ('application_structured_output', 'independent_review'):
                result = {'state': 'answer_annotation_provenance_missing', 'correct': None}
            elif not quote_span(fact.get('answer_quote'), answer):
                result = {'state': 'answer_annotation_quote_unverifiable', 'correct': None}
            else:
                normalized_fact = deepcopy(fact)
                if document_registry:
                    documents = [d for d in document_registry if d.get('source_file') == fact.get('document')]
                    if len(documents) == 1:
                        normalized_fact['document'] = documents[0]['code']
                result = numeric_fact_result(label, normalized_fact, allow_provisional=allow_provisional)
                if normalized_fact.get('document') != fact.get('document'):
                    result['document_identity_resolution'] = {'emitted_filename': fact['document'],
                                                              'registry_code': normalized_fact['document']}
                result['annotation_origin'] = origin
        results.append({'quantity_index': label['quantity_index'],
                        'reference_review_status': label['review_status'],
                        'human_confirmed': label['review_status'] == 'human_confirmed',
                        **result})
    return results


def all_supported(claims, field):
    if not claims:
        return None
    states = [c[field]['state'] for c in claims]
    if all(s == 'supported_quote_verified' for s in states):
        return True
    if 'contradicted_ai_needs_review' in states:
        return False
    return None


def replay_answer(row, raw, record, labels, *, allow_provisional=False,
                  citation_support_decisions=None):
    # Validate the schema while preserving the original raw supported verdicts.
    validated = validate_judgment(deepcopy(raw), context=row['context'],
                                   sources=row['sources'], reference=row['reference'], evidence_blocks=row.get('evidence_blocks'))
    claims = [classify_claim(c, context=row['context'], reference=row['reference'])
              for c in raw['answer_claims']]
    full = record.get('full_result', {})
    aligned = full.get('answer_claims') == [c['text'] for c in raw['answer_claims']]
    # Source indices must also identify exactly the captured application sources.
    sources_aligned = full.get('sources') == row['sources']
    capture = full.get('answer_capture')
    if capture:
        from backend.services.answer_capture import digest, validate_binding
        bound = validate_binding(full, row['answer'])
        aligned = aligned and bound and capture.get('claims_cover_answer', False)
        sources_aligned = sources_aligned and capture.get('sources_sha256') == digest(json.dumps(full.get('sources', []), sort_keys=True, ensure_ascii=False))
    citation = actual_citation_metrics(raw['answer_claims'], row['sources'],
        full.get('claim_citations') if aligned and sources_aligned else None,
        support_decisions=citation_support_decisions)
    citation['captured_claims_aligned'] = aligned
    citation['captured_sources_aligned'] = sources_aligned
    nums = numeric_results(labels, full, row['answer'], allow_provisional=allow_provisional,
                           document_registry=row.get('document_registry'))
    numeric_required = bool(labels) or row.get('numeric_reference', False)
    numeric_gate = (all(n['correct'] is True for n in nums) if nums and
                    all(n['correct'] is not None for n in nums) else
                    (None if numeric_required else True))
    d = row['deterministic']
    gate = {
        'faithfulness': all_supported(claims, 'faithfulness'),
        'factual_precision': all_supported(claims, 'factual'),
        'required_facts_complete_ai': (all(r['answer_covered'] for r in raw['reference_claims'])
                                     if raw['reference_claims'] else None),
        'claim_relevance_ai': (all(c['relevant'] for c in raw['answer_claims']) if claims else None),
        'answer_relevance_ai': raw['relevancy']['score'] == 2,
        'actual_citation_precision': (citation['citation_link_precision'] == 1
                                     if citation['citation_link_precision'] is not None else None),
        'actual_citation_recall': (citation['citation_claim_recall'] == 1
                                  if citation['citation_claim_recall'] is not None else None),
        'numeric_tuple': numeric_gate,
        'physical_page': bool(d.get('page_citation_complete') and d.get('prose_page_consistent')),
        'nonempty_answer': not d['empty_response'] and not d.get('model_error_response', False),
        'answered': not d['abstained'],
    }
    if not row['answerable']:
        # Controls have an abstention contract, not factual/citation gates for
        # assertions they are explicitly required not to make.
        from backend.services.answer_capture import validate_binding
        gate = {'correct_abstention': bool(d.get('expected_abstention_correct')),
                'no_factual_assertions': not claims and not (full.get('numeric_facts') or []),
                'capture_valid': validate_binding(full, row['answer']) if capture else None}
    elif d['abstained'] and not claims and capture and capture.get('status') == 'captured':
        # A bound false refusal is a known complete-answer failure. Precision
        # on no claims is N/A, not an unresolved hidden correct answer.
        gate = {k:v for k,v in gate.items() if k not in (
            'faithfulness','factual_precision','claim_relevance_ai',
            'actual_citation_precision','actual_citation_recall')}
    missing = [k for k, v in gate.items() if v is None]
    failed = [k for k, v in gate.items() if v is False]
    # Preserve incompleteness even when some measured dimensions already fail.
    complete = None if missing else not failed
    return {'id': row['id'], 'key': row['key'], 'answerable': row['answerable'],
            'claims': claims, 'actual_citation': citation, 'numeric': nums,
            'numeric_required': numeric_required, 'complete_gate': gate,
            'missing_dimensions': missing, 'failed_dimensions_ai_provisional': failed,
            'complete_answer_success': complete,
            'complete_answer_could_pass': not failed,
            'legacy_quote_verified_metrics': deepcopy(row.get('claims', {})),
            'reference_claims_context_quote_checked': validated['reference_claims'],
            'n_judge_proposed_links_excluded': sum(len(c.get('citations', [])) for c in raw['answer_claims']),
            'review_status': 'provisional_ai', 'human_confirmed': False,
            'scope': 'Saved AI entailment decisions plus quote membership; no independent human certification'}


def summarize_replay(rows, *, n_total, n_numeric_labels, n_total_answerable=None):
    claims = [c for r in rows for c in r['claims']]
    numeric = [n for r in rows for n in r['numeric']]
    measured = [n for n in numeric if n['correct'] is not None]
    summary = {'method_version': REPLAY_VERSION, 'contract_version': VERSION,
        'targets': TARGETS, 'review_status': 'provisional_ai', 'human_confirmed': False,
        'official_thesis_score_eligible': False, 'n_total_answers': n_total,
        'n_replayed_answers': len(rows), 'n_missing_or_failed_replay': n_total-len(rows),
        'n_answer_claims': len(claims), 'claim_states': {},
        'numeric': {'n_locked_labels': n_numeric_labels, 'n_required_tuples_in_subset': len(numeric),
            'n_questions_with_locked_numeric_labels': sum(bool(r['numeric']) for r in rows),
            'n_measured_tuples': len(measured), 'n_correct_tuples': sum(n['correct'] for n in measured),
            'accuracy_measured_subset': fraction(sum(n['correct'] for n in measured), len(measured)),
            'tuple_evaluation_coverage': fraction(len(measured), len(numeric)),
            'states': dict(Counter(n['state'] for n in numeric))},
        'citation': {'n_questions_actual_mapping_measured': sum(
            r['actual_citation']['status'] == 'measured' for r in rows),
            'statuses': dict(Counter(r['actual_citation']['status'] for r in rows)),
            'n_judge_proposed_links_excluded': sum(r['n_judge_proposed_links_excluded'] for r in rows)},
    }
    for dimension in ('faithfulness', 'factual'):
        counts = Counter(c[dimension]['state'] for c in claims)
        macro = [fraction(sum(c[dimension]['state'] == 'supported_quote_verified' for c in r['claims']),
                          len(r['claims'])) for r in rows]
        macro = [m for m in macro if m is not None]
        summary['claim_states'][dimension] = {
            'counts': {s: counts[s] for s in STATES}, 'n_claims': len(claims),
            'quote_verified_support_fraction_micro': fraction(counts['supported_quote_verified'], len(claims)),
            'quote_verified_support_fraction_macro': mean(macro) if macro else None,
            'n_macro_measured': len(macro),
            'confirmed_wrong_claims': None,
            'limit': 'Quote-unverifiable does not mean hallucinated; contradictions remain provisional AI review.'}
    passed = sum(r['complete_answer_success'] is True for r in rows)
    unresolved = sum(r['complete_answer_success'] is None for r in rows) + n_total-len(rows)
    summary['complete_answer_success'] = {
        'rate_all': fraction(passed, n_total) if not unresolved else None,
        'n_pass': passed, 'n_total': n_total, 'n_unresolved': unresolved,
        'n_fail_fully_measured': sum(r['complete_answer_success'] is False for r in rows),
        'strict_lower_bound_all': fraction(passed, n_total),
        'upper_bound_given_observed_failures_ai_provisional': fraction(
            sum(r['complete_answer_could_pass'] for r in rows) + n_total-len(rows), n_total),
        'missing_dimensions': dict(Counter(k for r in rows for k in r['missing_dimensions']))}
    if n_total_answerable is not None:
        positive=[r for r in rows if r['answerable']]
        controls=[r for r in rows if not r['answerable']]
        for name,part,total in (('answerable_complete_success',positive,n_total_answerable),
                                ('unanswerable_abstention_success',controls,n_total-n_total_answerable)):
            passed=sum(r['complete_answer_success'] is True for r in part)
            unresolved=sum(r['complete_answer_success'] is None for r in part)+total-len(part)
            summary[name]={'n_pass':passed,'n_total':total,'n_unresolved':unresolved,
                           'rate_all':fraction(passed,total) if not unresolved else None,
                           'strict_lower_bound_all':fraction(passed,total)}
    return summary
