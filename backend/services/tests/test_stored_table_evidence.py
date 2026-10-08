import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from backend.services.ocr_artifacts import build_raw_ocr_chunk_payloads
from backend.services.stored_table_evidence import rebuild_page_tables


def fixture(name='page_7_table_0_assets', page=7, value='10831'):
    row = NS(table_name=name, source_page=page, headers=['รายการ','2567'],
             row_data={'รายการ':'สินทรัพย์ (ล้านบาท)','2567':value}, row_index=2,
             unit='ล้านบาท', source_provider='gemini', source_sha256='actualhash', quality_status='verified')
    chunk = NS(metadata_={'source_kind':'table_csv','table_name':name,
                         'table_title':'ฐานะทางการเงิน', 'unit':'บาท (THB)', 'region':'full'})
    return row, chunk


def test_stored_page_preserves_caption_page_provider_and_explicit_row_unit():
    row, chunk = fixture()
    table = rebuild_page_tables([row], [chunk])[0]
    assert table['page'] == 7 and table['title'] == 'ฐานะทางการเงิน'
    assert table['source_provider'] == 'gemini' and table['source_sha256'] == 'actualhash'
    assert table['unit'] == 'บาท (THB)' and table['stored_row_units'] == ['ล้านบาท']
    assert table['source_row_indices'] == [2]


def test_similar_display_names_do_not_merge_distinct_source_tables():
    a, ca = fixture('page_7_table_0_assets')
    b, cb = fixture('page_7_table_0_liabilities', value='999')
    cb.metadata_['table_title'] = 'หนี้สิน'
    result = rebuild_page_tables([a,b], [ca,cb])
    assert len(result) == 2 and {t['title'] for t in result} == {'ฐานะทางการเงิน','หนี้สิน'}


def test_missing_or_conflicting_caption_does_not_use_a_neighbor():
    row, chunk = fixture()
    other = NS(metadata_={**chunk.metadata_, 'table_title':'caption conflict'})
    result = rebuild_page_tables([row], [chunk, other])[0]
    assert result['title'] != 'caption conflict' and result['title'] != 'ฐานะทางการเงิน'
    result = rebuild_page_tables([row], [])[0]
    assert result.get('unit') is None


def test_raw_artifacts_keep_zero_scale_and_crop_provenance():
    raw = {'title':'source', 'headers':['รายการ','2567'], 'rows':[['เงินสด',0]],
           'page':7,'unit':'ล้านบาท','source_provider':'gemini','region':'right','crop_box':[.5,0,1,1]}
    payload = build_raw_ocr_chunk_payloads('actual.pdf', {'raw_tables':[raw]})[0]
    assert payload['metadata']['rows'] == [['เงินสด','0']]
    assert payload['metadata']['unit'] == 'ล้านบาท'
    assert payload['metadata']['crop_box'] == [.5,0,1,1]


def test_header_repair_provenance_survives_normalization_chunking_and_rebuild():
    from backend.services.table_utils import normalize_ocr_tables, build_table_chunk_payloads
    repairs=[{'kind':'empty_audit_status_header_tier','emitted_column_indices':[1,2]}]
    table={'title':'ฐานะทางการเงิน','headers':['รายการ','2567'],
           'rows':[['สินทรัพย์ (ล้านบาท)','10831']],'page':7,'unit':'บาท',
           'source_provider':'gemini','header_repairs':repairs}
    normalized=normalize_ocr_tables('actual.pdf',[table])[0]
    payload=build_table_chunk_payloads('actual.pdf',[normalized])[0]
    row, _=fixture(normalized['table_name'])
    chunk=NS(metadata_={'source_kind':'table_csv','table_title':payload['title'],**payload})
    assert rebuild_page_tables([row],[chunk])[0]['header_repairs']==repairs
    assert build_raw_ocr_chunk_payloads('actual.pdf',{'raw_tables':[normalized]})[0]['metadata']['header_repairs']==repairs


def test_actual_page_endpoint_returns_recorded_gemini_tables_not_reparsed_prose(monkeypatch):
    from backend.routes import documents
    row, table_chunk = fixture()
    raw = NS(metadata_={'source_kind':'raw_ocr_table','page':7,'headers':row.headers,
        'rows':[['สินทรัพย์ (ล้านบาท)','10831']],'unit':'ล้านบาท','source_provider':'gemini'})
    def single(value): return NS(scalar_one_or_none=lambda:value)
    def many(value): return NS(scalars=lambda:NS(all=lambda:value))
    db = NS(execute=AsyncMock(side_effect=[single(NS(filename='actual.pdf')),
        single(NS(status='indexed',error_stage=None,error_message=None)),
        many([raw,table_chunk]), many([row])]))
    result = asyncio.run(documents.get_document_page(1,7,db))
    assert result['raw_ocr_tables'][0]['source_provider'] == 'gemini'
    assert result['structured_tables'][0]['page'] == 7
    assert result['structured_tables'][0]['title'] == 'ฐานะทางการเงิน'
