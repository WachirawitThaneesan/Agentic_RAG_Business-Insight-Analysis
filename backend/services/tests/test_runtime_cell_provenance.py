"""Regressions from integrated diagnostics, using independent miniature values."""
import asyncio
from unittest.mock import AsyncMock
import duckdb
from backend.services import agent, tools, duckdb_warehouse as warehouse


def cell(**kwargs):
    return dict(type='sql', page=7, document_id=1, table_name='income',
                row_label='กำไรสุทธิ (ส่วนที่เป็นของธนาคาร)', column='ปี 2569',
                value='321', unit='ล้านบาท', **kwargs)


def test_exact_cell_overrides_conflicting_prose_but_not_wrong_year():
    q='กำไรสุทธิส่วนที่เป็นของธนาคารปี 2569 เท่าไร'
    sources=[cell(), {'page':7,'excerpt':'กำไรสุทธิ 322 ล้านบาท ปี 2569'}]
    assert 'ไม่พบหลักฐาน' in agent._grounded_answer('322 ล้านบาท',q,sources)
    assert agent._grounded_answer('321 ล้านบาท',q,sources)=='321 ล้านบาท'
    assert 'ไม่พบหลักฐาน' in agent._grounded_answer('321 ล้านบาท',q.replace('2569','2568'),sources)


def test_eps_unit_overrides_unrelated_table_unit():
    sources=[dict(type='sql',page=7,row_label='กำไรต่อหุ้นขั้นพื้นฐาน (บาท) (1)',
                  value='12.35',column='ปี 2569',unit='บาท'),cell()]
    q='กำไรต่อหุ้นขั้นพื้นฐานปี 2569 กี่บาท'
    assert agent._grounded_answer('12.35 บาท',q,sources)=='12.35 บาท'
    assert 'หน่วย' in agent._grounded_answer('12.35 ล้านบาท',q,sources)


def test_page_list_is_not_a_competing_financial_value():
    sources=[cell(),{**cell(),'page':8}]
    assert agent._grounded_answer('321 ล้านบาท (หน้า 7, 8)','กำไรสุทธิปี 2569 เท่าไร',sources).startswith('321')
    assert 'ไม่พบหลักฐาน' in agent._grounded_answer('321 ล้านบาท (หน้า 7, 9)','กำไรสุทธิปี 2569 เท่าไร',sources)


def test_sql_repairs_projection_without_source_identity_once(monkeypatch):
    conn=duckdb.connect(':memory:');warehouse._init_schema(conn)
    monkeypatch.setattr(warehouse,'_get_conn',lambda:conn)
    warehouse.load_document_dim(9,'sample.pdf')
    warehouse.load_table_into_warehouse(9,'p7', ['รายการ','ปี 2569'],[['กำไร','321']],
        source_page=7,unit='ล้านบาท',source_provider='gemini')
    model=AsyncMock(side_effect=[
        'SELECT col_value FROM dim_table_rows',
        'SELECT document_id,table_name,row_label,col_name,col_value,unit FROM dim_table_rows'])
    monkeypatch.setattr(tools,'llm_generate',model)
    result=asyncio.run(tools.SQLTool().execute('กำไรจาก sample.pdf'))
    assert result.success and result.data['evidence'][0]['page']==7
    assert model.call_count==2
    assert 'document_id is INTEGER' in model.call_args.args[0]
    assert 'fact_financial_metrics is EMPTY' in model.call_args.args[0]
    conn.close()


def test_exact_lookup_does_not_replace_compound_measure_with_component(monkeypatch):
    conn=duckdb.connect(':memory:');warehouse._init_schema(conn)
    monkeypatch.setattr(warehouse,'_get_conn',lambda:conn)
    warehouse.load_document_dim(9,'sample.pdf')
    warehouse.load_table_into_warehouse(9,'p7',['รายการ','ปี 2569'],[['เงินให้สินเชื่อ','321']],
        source_page=7,unit='ล้านบาท',source_provider='gemini')
    assert warehouse.exact_measure_cells('จากไฟล์ sample.pdf เงินให้สินเชื่อปี 2569 กี่ล้านบาท')
    assert warehouse.exact_measure_cells('จากไฟล์ sample.pdf เงินให้สินเชื่อและดอกเบี้ยค้างรับรวมปี 2569 กี่ล้านบาท') is None
    assert warehouse.exact_measure_cells('จากไฟล์ missing.pdf เงินให้สินเชื่อปี 2569 กี่ล้านบาท') is None
    conn.close()


def test_model_failure_is_visible_instead_of_empty_answer():
    assert 'โมเดลไม่ส่งคำตอบ' in agent._grounded_answer('', 'กำไรเท่าไร', [cell()])


def test_duplicate_uploads_do_not_displace_later_table_evidence():
    first={'page':1,'filename':'same.pdf','excerpt':'ข้อความยาว '*500}
    final={'page':2,'filename':'same.pdf','excerpt':'CSV:\nรายการ,ปี 2569\nรายการเป้าหมาย,765'}
    context=agent._answer_context([first]*8+[final],['irrelevant SQL '*1000])
    assert 'รายการเป้าหมาย,765' in context
    assert context.count('[same.pdf PDF page 1]')==1


def test_citation_renderer_works_without_any_ocr_service(tmp_path):
    import pymupdf
    from backend.services.pdf_render import render_pdf_page
    pdf=pymupdf.open();pdf.new_page().insert_text((72,72),'Local evidence')
    path=tmp_path/'evidence.pdf';pdf.save(path);pdf.close()
    rendered=render_pdf_page(str(path),1,72)
    assert rendered.startswith(b'\x89PNG\r\n\x1a\n')


def test_exact_cell_answer_does_not_need_model():
    c=cell();c['evidence_status']='ocr_extracted_unverified'
    answer=agent._exact_cell_answer({'lookup_kind':'exact_measure','evidence':[c]},
        'กำไรสุทธิส่วนที่เป็นของธนาคารปี 2569 กี่ล้านบาท')
    assert '321 ล้านบาท' in answer and 'PDF หน้า 7' in answer and 'OCR' in answer


def test_candidate_selection_preserves_maturity_column_and_rejects_invented_ids(monkeypatch):
    conn=duckdb.connect(':memory:');warehouse._init_schema(conn)
    monkeypatch.setattr(warehouse,'_get_conn',lambda:conn)
    warehouse.load_document_dim(9,'sample.pdf')
    warehouse.load_table_into_warehouse(9,'maturity',['ระยะเวลา','สินเชื่อ 2569','สินเชื่อ ร้อยละ 2569'],
        [['> 10 ปี','765','25']],source_page=9,unit='ล้านบาท',source_provider='gemini')
    model=AsyncMock(return_value='{"cell_ids":[0]}')
    monkeypatch.setattr(tools,'llm_generate',model)
    result=asyncio.run(tools.SQLTool().execute('จากไฟล์ sample.pdf สินเชื่อเกิน 10 ปี ในปี 2569 กี่ล้านบาท'))
    assert result.success and result.data['evidence'][0]['value']=='765'
    assert result.data['evidence'][0]['unit']=='ล้านบาท'
    assert result.data['evidence'][0]['page']==9
    model.return_value='{"cell_ids":["0"]}'
    result=asyncio.run(tools.SQLTool().execute('จากไฟล์ sample.pdf สินเชื่อเกิน 10 ปี ในปี 2569 กี่ล้านบาท'))
    assert result.success and result.data['evidence'][0]['value']=='765'
    for invalid in ('true', '0.5', '"-1"', '"1e0"'):
        model.return_value='{"cell_ids":['+invalid+']}'
        result=asyncio.run(tools.SQLTool().execute('จากไฟล์ sample.pdf สินเชื่อเกิน 10 ปี ในปี 2569 กี่ล้านบาท'))
        assert not result.success
    model.return_value='{"cell_ids":[9999]}'
    result=asyncio.run(tools.SQLTool().execute('จากไฟล์ sample.pdf สินเชื่อเกิน 10 ปี ในปี 2569 กี่ล้านบาท'))
    assert not result.success
    conn.close()
