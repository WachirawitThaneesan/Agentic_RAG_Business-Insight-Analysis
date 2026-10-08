import json

from backend.services import answer_capture as capture


def payload(qualifiers=None):
    fact = dict(company='Example', measure='รายงานการมีส่วนได้เสียครั้งแรก',
                value=30, unit='วัน', year_be=None, source_index=0,
                document='example.pdf', source_pdf_page=10, comparison_operator='lte')
    if qualifiers is not None:
        fact['qualifiers'] = qualifiers
    return dict(abstained=False, refusal_reason='', claims=[
        dict(text='', source_indices=[0], numeric=fact)])


def captured(raw):
    answer, data = capture.decode(json.dumps(raw, ensure_ascii=False))
    sources = [dict(filename='example.pdf', page=10, excerpt=answer)]
    context, blocks = capture.evidence_context(sources, [])
    full = capture.finalize(dict(answer=answer, sources=sources), [dict(
        draft=answer, payload=data, context=context, blocks=blocks,
        origin='model_generation', prompt_sha256=None)])
    return answer, data, full


def test_qualifier_keeps_timing_scope_in_the_emitted_bound_claim():
    answer, data, full = captured(payload('นับจากวันที่เข้าดำรงตำแหน่ง'))
    assert 'ไม่เกิน 30 วัน' in answer
    assert 'นับจากวันที่เข้าดำรงตำแหน่ง' in answer
    assert data['numeric_facts'][0]['measure'] == 'รายงานการมีส่วนได้เสียครั้งแรก'
    quote = data['numeric_facts'][0]['answer_quote']
    assert answer.startswith(quote)
    assert 'Example รายงานการมีส่วนได้เสียครั้งแรก ไม่เกิน 30 วัน' == quote
    assert full['answer_capture']['status'] == 'captured'
    assert capture.validate_binding(full, answer)


def test_optional_qualifier_does_not_change_old_numeric_rendering():
    a, _, _ = captured(payload())
    b, _, _ = captured(payload(''))
    assert a == b


def test_extra_quantity_cannot_be_hidden_in_qualifier():
    _, _, full = captured(payload('และจัดประชุม 2 ครั้ง'))
    assert full['answer_capture']['status'] != 'captured'
    assert 'unannotated_numeric_quantity' in full['answer_capture']['errors']
    assert len(full['numeric_facts']) == 1  # Primary30-day relation stays bound.


def test_nontext_qualifier_is_rejected():
    _, data = capture.decode(json.dumps(payload(123)))
    assert data is None
