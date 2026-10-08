from types import SimpleNamespace
import pytest
from backend.scripts.reocr_tables import _read_page_once
from backend.services.gemini_tables import _normalize_gemini_tables


@pytest.mark.parametrize('text',['[1,2,3]','broken JSON',''])
def test_failed_table_response_preserves_exact_raw_output_without_valid_cells(text):
    response=SimpleNamespace(text=text,usage_metadata=None)
    client=SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs:response))
    result=_read_page_once(client,'synthetic-test-model',b'not-dispatched-to-cloud')
    assert result['_raw_response_text']==text
    assert result['_error']
    assert result['tables']==[]


def test_recording_raw_table_response_does_not_repair_misaligned_columns():
    text='{"tables":[{"columns":["รายการ","2567"],"rows":[{"row_label":"เงินสด","values":["1","2","3","4"]}]}]}'
    client=SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs:SimpleNamespace(text=text,usage_metadata=None)))
    result=_read_page_once(client,'synthetic-test-model',b'not-dispatched-to-cloud')
    assert result['_raw_response_text']==text
    with pytest.raises(ValueError,match='header width'):
        _normalize_gemini_tables(result,1,{'region':'full'})
