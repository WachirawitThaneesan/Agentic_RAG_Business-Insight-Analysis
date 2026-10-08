import asyncio
from unittest.mock import AsyncMock, patch
from backend.services.ocr import TyphoonOCRService, _unconfirmed_na_text
from backend.services.tests.test_gemini_table_routing import _png


def test_explicit_na_preserves_year_scope_without_restoring_wrong_numeric_cells():
    text=_unconfirmed_na_text([{'title':'งานคงเหลือ','headers':['รายการ','2567','2566'],
        'rows':[['จำนวนงาน','N/A','999'],['มูลค่า','-','N/A']]}])
    assert 'งานคงเหลือ / จำนวนงาน / 2567: N/A' in text
    assert 'งานคงเหลือ / มูลค่า / 2566: N/A' in text
    assert '999' not in text and ': -' not in text


def test_actual_ocr_routing_retains_na_when_gemini_declines_key_value_layout():
    service=TyphoonOCRService();service.api_key='test'
    markdown='หัวข้อ\n<table><tr><th>จำนวนงานทั้งหมด</th><th>N/A</th></tr><tr><td>มูลค่างานทั้งหมด</td><td>N/A</td></tr><tr><td>ค่าที่ไม่ยืนยัน</td><td>999</td></tr></table>'
    with patch('backend.services.ocr.settings.PDF_TABLE_OCR_PROVIDER','gemini'), \
         patch.object(service,'_render_pdf_page_to_png',return_value=_png()), \
         patch('backend.services.ocr.plan_pdf_regions',return_value=[{'region':'full','crop_box':[0,0,1,1],'rotation':0}]), \
         patch('backend.services.gemini_tables.image_has_table_hint',return_value=False), \
         patch.object(service,'_ocr_png_bytes_async',new_callable=AsyncMock,return_value=markdown), \
         patch('backend.services.gemini_tables.extract_tables_from_png',new_callable=AsyncMock,return_value=([],{})):
        result=asyncio.run(service.extract_from_pdf_path('fixture.pdf',pages=[1]))
    prose='\n'.join(result['text_blocks'])
    assert 'จำนวนงานทั้งหมด: N/A' in prose and 'มูลค่างานทั้งหมด: N/A' in prose
    assert '999' not in prose and result['tables']==[]
    assert result['raw_pages'][0]['provider_markdown']==markdown


def test_numeric_only_unconfirmed_table_never_becomes_semantic_evidence():
    assert _unconfirmed_na_text([{'headers':['รายการ','2567'],'rows':[['กำไร','999'],['หนี้','0']]}])==''


def test_provider_transcript_is_retained_only_in_nonsearchable_raw_artifact():
    from types import SimpleNamespace
    from backend.routes.documents import _add_raw_page_chunk
    saved=[]
    _add_raw_page_chunk(SimpleNamespace(add=saved.append),1,'fixture.pdf',1,
        {'markdown':'จำนวนงาน: N/A','provider_markdown':'<table>unconfirmed 999</table>'},0,'source-hash')
    assert saved[0].embedding is None
    assert saved[0].metadata_['source_kind']=='raw_ocr_page'
    assert saved[0].metadata_['provider_markdown']=='<table>unconfirmed 999</table>'
    assert '999' not in saved[0].chunk_text


def test_real_indented_key_value_html_keeps_first_header_relation_and_body_rows():
    service=TyphoonOCRService()
    tables,_=service._extract_structured_tables('<table><tr><td></td><td>จำนวนงานทั้งหมด :</td><td>N/A</td></tr><tr><td></td><td>มูลค่างานทั้งหมด :</td><td>N/A</td></tr><tr><td></td><td>มูลค่ารับรู้แล้ว :</td><td>N/A</td></tr><tr><td></td><td>มูลค่างานคงเหลือที่ยังไม่รับรู้ :</td><td>N/A</td></tr></table>')
    text=_unconfirmed_na_text(tables)
    assert text.count('N/A')==4
    assert all(key+': N/A' in text for key in ['จำนวนงานทั้งหมด','มูลค่างานทั้งหมด','มูลค่ารับรู้แล้ว','มูลค่างานคงเหลือที่ยังไม่รับรู้'])


def test_numeric_preceding_cell_is_never_recovered_as_na_label():
    assert _unconfirmed_na_text([{'headers':['','รายการ','ค่า'],'rows':[['','999 ล้านบาท','N/A']]}])==''
