import json

from backend.services import answer_capture as capture


def result(operator):
    raw = dict(abstained=False, refusal_reason='', claims=[dict(text='', source_indices=[0], numeric=dict(
        entity='Example', measure='สัดส่วนเงินลงทุน', value=80.07, unit='ร้อยละ',
        year_be=2567, source_index=0, document='example.pdf', source_pdf_page=10,
        comparison_operator=operator, qualifiers='ของงบประมาณการลงทุนทั้งหมด'))])
    answer, payload = capture.decode(json.dumps(raw, ensure_ascii=False))
    sources = [dict(filename='example.pdf', page=10, excerpt=answer)]
    context, blocks = capture.evidence_context(sources, [])
    full = capture.finalize(dict(answer=answer, sources=sources), [dict(
        draft=answer, payload=payload, context=context, blocks=blocks,
        origin='model_generation', prompt_sha256=None)])
    return full


def test_budget_noun_is_not_an_approximation_operator():
    full = result('eq')
    assert full['answer_capture']['status'] == 'captured'


def test_actual_approximation_marker_still_binds():
    full = result('approx')
    assert full['answer_capture']['status'] == 'captured'
    assert 'ประมาณ 80.07' in full['answer']
