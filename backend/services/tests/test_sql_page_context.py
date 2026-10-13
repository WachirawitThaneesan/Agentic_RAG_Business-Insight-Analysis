"""SQL identity context must come from the exact indexed source page."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.services import agent, answer_capture


def test_context_is_scoped_and_visible_without_rewriting_cell_identity():
    source = {'document_id':1, 'page':4, 'filename':'anonymous.pdf', 'row_label':'profit',
              'column':'2568', 'value':'100', 'unit':'ล้านบาท'}
    chunks = [SimpleNamespace(document_id=2, metadata_={'page':4,'source_kind':'semantic'},
                              chunk_text='Another issuer'),
              SimpleNamespace(document_id=1, metadata_={'page':5,'source_kind':'semantic'},
                              chunk_text='Another page'),
              SimpleNamespace(document_id=1, metadata_={'page':4,'source_kind':'raw_ocr_page'},
                              chunk_text='Excluded audit-only raw data'),
              SimpleNamespace(document_id=1, metadata_={'page':4,'source_kind':'semantic'},
                              chunk_text='RAW_OCR_PAGE: anonymous.pdf page 4\nบริษัท ตัวอย่าง จำกัด (มหาชน)\nSource narrative')]
    result = SimpleNamespace(scalars=lambda:SimpleNamespace(all=lambda:chunks))
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    data={'evidence':[source], 'lookup_kind':'exact_measure'}
    asyncio.run(agent._attach_sql_page_context(data,session))
    assert source['value']=='100' and source['column']=='2568'
    assert source['page_context']=='บริษัท ตัวอย่าง จำกัด (มหาชน)\nSource narrative'
    assert 'company' not in source
    sql = str(session.execute.call_args.args[0])
    assert 'document_pages.status' in sql and 'chunks.document_id' in sql
    text, _ = answer_capture.evidence_context([source],[])
    assert source['page_context_source'] in text and 'บริษัท ตัวอย่าง' in text
    assert agent._exact_cell_answer(data,'profit in anonymous.pdf') is None


def test_missing_page_context_does_not_invent_company_or_modify_old_payload():
    source={'filename':'plain.pdf','page':4,'row_label':'profit','column':'2568','value':'100','unit':'บาท'}
    text,_=answer_capture.evidence_context([source],[])
    assert 'page_context' not in text
    assert 'company' not in source
    source['document_id']=1
    assert agent._exact_cell_answer({'lookup_kind':'exact_measure','evidence':[source]},
                                   'plain profit in plain.pdf') is None


def test_generic_entity_guard_retains_explicit_names_and_scope():
    for name in ['ธนาคาร','บริษัทฯ','ธนาคาร และ บริษัทย่อย','บริษัทและบริษัทย่อย']:
        assert answer_capture.is_generic_entity(name)
    for name in ['ธนาคารตัวอย่าง','ธนาคารตัวอย่างและบริษัทย่อย','บริษัท แสงไทย จำกัด','โรงไฟฟ้า A']:
        assert not answer_capture.is_generic_entity(name)
