import json

from backend.services import answer_capture as capture


def raw():
    return dict(abstained=False, refusal_reason='', claims=[dict(text='', source_indices=[0], numeric=dict(
        entity='Example', measure='อัตราเติบโตเฉลี่ยต่อปี', value=8,
        range_min=7, range_max=9, unit='ร้อยละ', year_be=None,
        period_start_be=2568, period_end_be=2570,
        document='example.pdf', source_pdf_page=10, source_index=0,
        comparison_operator='range'))])


def test_source_range_and_calendar_horizon_bind_without_midpoint_quantity():
    answer, payload = capture.decode(json.dumps(raw(), ensure_ascii=False))
    assert 'ช่วงปี 2568–2570' in answer
    assert 'ระหว่าง 7 ถึง 9 ร้อยละ' in answer
    fact = payload['numeric_facts'][0]
    assert fact['value'] == 7 and fact['range_scalar_role'] == 'lower_bound'
    source = dict(filename='example.pdf', page=10, excerpt=answer)
    context, blocks = capture.evidence_context([source], [])
    full = capture.finalize(dict(answer=answer, sources=[source]), [dict(
        draft=answer, payload=payload, context=context, blocks=blocks,
        origin='model_generation', prompt_sha256=None)])
    assert full['answer_capture']['status'] == 'captured'


def test_partial_period_or_reversed_range_is_rejected():
    p = raw()
    del p['claims'][0]['numeric']['period_end_be']
    assert capture.decode(json.dumps(p))[1] is None
    p = raw()
    p['claims'][0]['numeric']['range_min'] = 12
    assert capture.decode(json.dumps(p))[1] is None


def test_unmarked_four_digit_quantity_is_not_a_calendar_year():
    assert capture._quantity_values('จำนวน 2570 คน') == [2570]
    assert capture._quantity_values('ช่วงปี 2568–2570 ระหว่าง 7 ถึง 9 ร้อยละ') == [7, 9]


def test_absent_calendar_period_accepts_null_instead_of_placeholder_zero():
    p = raw()
    fact = p['claims'][0]['numeric']
    fact.update(year_be=2567, period_start_be=None, period_end_be=None)
    answer, decoded = capture.decode(json.dumps(p))
    assert decoded is not None and 'ปี 2567' in answer
    assert 'ช่วงปี' not in answer
    # The period-generation experiment was not selected. Historical explicit
    # null periods remain decodable; the selected v16 native schema omits them.
    for key in ('period_start_be', 'period_end_be'):
        assert key not in capture._NUMERIC_SCHEMA['properties']
    fact.update(period_start_be=0, period_end_be=0)
    assert capture.decode(json.dumps(p))[1] is None
