import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from backend.services.retrieval_rank import matched_document_aliases, without_document_aliases
from backend.services.rag import _expand_page_evidence, _explicit_section
from backend.services.agent import _answer_context, _extract_sources


def test_short_issuer_symbol_does_not_match_longer_issuer():
    docs=[(1,'abc_2569_th.pdf'),(2,'abcdef_2569_th.pdf')]
    assert matched_document_aliases('ABC ปี 2569',docs)[0]=={1}
    assert matched_document_aliases('ABCDEF ปี 2569',docs)[0]=={2}
    assert 'ABCDEF' in without_document_aliases('ABC และ ABCDEF',('abc',))


def test_page_expansion_keeps_late_value_and_named_section():
    chunks=[SimpleNamespace(document_id=1,metadata_={'page':3},chunk_text='จุดเด่นการดำเนินงาน '+('ข้อความ '*300)),
            SimpleNamespace(document_id=1,metadata_={'page':3},chunk_text='ค่า ณ สิ้นปี 456 ล้านบาท'),
            SimpleNamespace(document_id=1,metadata_={'page':4},chunk_text='ส่วนอื่น 789 ล้านบาท')]
    db=SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda:chunks)))
    hits=[{'document_id':1,'page':3,'text':'จุดเด่นการดำเนินงาน'}, {'document_id':1,'page':4,'text':'ส่วนอื่น'}]
    result=asyncio.run(_expand_page_evidence('ในรายงาน ส่วนจุดเด่นการดำเนินงาน เงินสดเท่าไร',hits,db))
    assert len(result)==1 and '456 ล้านบาท' in result[0]['text']
    assert '789' not in result[0]['text']
    context=_answer_context([{'filename':'a.pdf','page':3,'excerpt':result[0]['text']}],[])
    assert '456 ล้านบาท' in context
    sql=str(db.execute.call_args.args[0])
    assert 'source_kind' in str(db.execute.call_args.args[0].compile().params)
    assert 'document_pages.status' in sql


def test_metric_phrase_is_not_a_section_request():
    assert _explicit_section('กำไรสุทธิส่วนที่เป็นของธนาคารปี 2569') is None


def test_page_tail_survives_tool_source_and_answer_context():
    chunks = [{'filename': 'a.pdf', 'page': i, 'context_kind': 'page',
               'text': 'หัวตาราง ' + ('ข้อความ ' * 450) + f'ปลายตาราง {i} ล้านบาท'}
              for i in range(1, 6)]
    sources = _extract_sources('vector_search', {'chunks': chunks})
    context = _answer_context(sources, [])
    assert 'ปลายตาราง 1 ล้านบาท' in context
    assert len(context) <= 16000
