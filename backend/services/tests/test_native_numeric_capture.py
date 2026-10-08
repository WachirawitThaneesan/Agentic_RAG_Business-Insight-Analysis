import json

from google.genai import types

from backend.services import answer_capture as capture


def test_native_schema_excludes_category_strings_from_quantities():
    config = types.GenerateContentConfig(response_schema=capture.SCHEMA)
    schema = types.Schema.model_validate(config.response_schema)
    numeric = schema.properties['claims'].items.properties['numeric']
    assert numeric.properties['value'].type == types.Type.NUMBER
    rating = {'abstained': False, 'refusal_reason': '', 'claims': [
        {'text': 'บริษัทได้รับ SET ESG Rating ระดับ AAA', 'source_indices': [0], 'numeric': None}]}
    answer, payload = capture.decode(json.dumps(rating))
    assert answer == rating['claims'][0]['text']
    assert payload['numeric_facts'] == []


def test_json_decimal_is_not_rounded_through_binary_float():
    raw = '''{"abstained":false,"refusal_reason":"","claims":[
      {"text":"","source_indices":[0],"numeric":{"source_index":0,
       "company":"Example","measure":"มูลค่า","value":123456789012345.123456789,
       "unit":"บาท","year_be":2567,"document":"example.pdf",
       "source_pdf_page":1,"comparison_operator":"eq"}}]}'''
    answer, payload = capture.decode(raw)
    assert '123456789012345.123456789 บาท' in answer
    assert payload['numeric_facts'][0]['value'] == '123456789012345.123456789'
    json.dumps(payload)  # No Decimal leaks into persisted capture artifacts.


def test_decimal_range_bounds_preserve_the_emitted_values():
    raw = '''{"abstained":false,"refusal_reason":"","claims":[
      {"text":"","source_indices":[0],"numeric":{"source_index":0,
       "company":"Example","measure":"ช่วงมูลค่า","value":0.1000000000000000001,
       "range_min":0.1000000000000000001,"range_max":0.2000000000000000002,
       "unit":"บาท","year_be":null,"document":"example.pdf",
       "source_pdf_page":1,"comparison_operator":"range"}}]}'''
    answer, payload = capture.decode(raw)
    assert '0.1000000000000000001 ถึง 0.2000000000000000002 บาท' in answer
    json.dumps(payload)
