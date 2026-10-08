"""Subsidiary evidence in a parent report must remain discoverable."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from backend.services import rag


def test_distinctive_entity_can_supply_lexical_evidence_from_parent_report(monkeypatch):
    parent=SimpleNamespace(id=10,document_id=1,chunk_index=0,summary='',
        chunk_text='ปตท.สผ. ขยายการลงทุนผลิต Clean Hydrogen ในประเทศโอมาน',
        metadata_={'page':84,'source_kind':'semantic'})
    class DB:
        def __init__(self):self.statements=[]
        async def execute(self, statement):
            self.statements.append(statement)
            if len(self.statements)==1:return SimpleNamespace(all=lambda:[(1,'ptt_2567_th.pdf'),(2,'pttep_2567_th.pdf')])
            if len(self.statements)==2:return SimpleNamespace(all=lambda:[])
            if len(self.statements)==3:return SimpleNamespace(all=lambda:[(parent,'ptt_2567_th.pdf')])
            return SimpleNamespace(scalars=lambda:[parent])
    monkeypatch.setattr(rag,'get_embedding',AsyncMock(return_value=[0.0]*1024))
    db=DB();hits=asyncio.run(rag.vector_search('ปตท.สผ. ลงทุนผลิต Clean Hydrogen ในประเทศใด',db))
    assert hits[0]['filename']=='ptt_2567_th.pdf' and hits[0]['page']==84
    statement=db.statements[2];params=statement.compile().params
    assert any('ปตท.สผ.' in v for v in params.values() if isinstance(v,str))
    assert 'document_pages.status' in str(statement) and 'source_kind' in str(params)
    assert 'โอมาน' in hits[0]['text']


def test_short_parent_abbreviation_cannot_expand_scope_by_substring(monkeypatch):
    statements=[]
    class DB:
        async def execute(self,statement):
            statements.append(statement)
            return SimpleNamespace(all=lambda:[(1,'ptt_2567_th.pdf'),(2,'pttep_2567_th.pdf')]
                if len(statements)==1 else [])
    monkeypatch.setattr(rag,'get_embedding',AsyncMock(return_value=[0.0]*1024))
    assert asyncio.run(rag.vector_search('ปตท. มีวิสัยทัศน์อย่างไร',DB()))==[]
    assert not any('%ปตท' in v for v in statements[2].compile().params.values() if isinstance(v,str))
