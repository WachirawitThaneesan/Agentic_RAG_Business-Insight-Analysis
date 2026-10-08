import json
import pytest
from backend.services import answer_capture as c


def capture(company, measure, value='3.53', unit='ร้อยละต่อปี'):
    raw = {'abstained': False, 'refusal_reason': '', 'claims': [{'text': '', 'source_indices':[0],
        'numeric': {'source_index':0,'company':company,'measure':measure,'value':value,'unit':unit,
                    'year_be':2567,'source_pdf_page':267,'document':'actual.pdf','comparison_operator':'eq'}}]}
    answer, payload = c.decode(json.dumps(raw,ensure_ascii=False))
    sources=[{'filename':'actual.pdf','page':267,'excerpt':'source data only'}]
    context, blocks = c.evidence_context(sources, [])
    return c.finalize({'answer':answer,'sources':sources}, [{'draft':answer,'payload':payload,
        'context':context,'blocks':blocks,'prompt_sha256':None,'origin':'model_generation'}])


@pytest.mark.parametrize('company,measure', [
    ('WHAUP','อัตราดอกเบี้ยหุ้นกู้ลำดับที่ 10'),
    ('บริษัท บีเอสจีเอฟ จำกัด','ทุนจดทะเบียนใหม่จากการออกหุ้นเพิ่มทุนครั้งที่ 1'),
    ('เซ็นทรัล ซิตี้ เรสซิเดนซ์ 1','พื้นที่')])
def test_numbered_identity_is_not_a_second_amount(company,measure):
    full = capture(company,measure)
    assert full['answer_capture']['status']=='captured'
    assert len(full['numeric_facts'])==1 and c.validate_binding(full,full['answer'])


@pytest.mark.parametrize('measure',['ปริมาณขยะจากสถานที่ทั้ง 63 แห่ง','เงินปันผลสำหรับ 9 เดือนแรก'])
def test_real_count_or_duration_cannot_be_hidden_inside_measure(measure):
    full=capture('CPN',measure)
    assert full['numeric_facts']==[]
    assert 'numeric_quote_contains_other_quantities' in full['answer_capture']['errors']


def test_percent_rate_cannot_be_rescored_as_plain_percent():
    assert c._value_unit_in_quote(c.Decimal('3.53'),'ร้อยละต่อปี','3.53 ร้อยละต่อปี')
    assert not c._value_unit_in_quote(c.Decimal('3.53'),'ร้อยละ','3.53 ร้อยละต่อปี')
