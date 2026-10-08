"""Offline/read-only acceptance audit of real mapped upload evidence.

Source-cell references are never supplied to ingestion. Page mapping projects
stored uploaded-page identifiers into the original source only for evaluation.
All omissions, source failures and unmeasurable relationships remain explicit.
"""
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
from pathlib import Path
from sqlalchemy.engine import make_url
from scripts.evaluate_comprehensive import load, save, sha
from scripts.evaluate_gemini_ocr_stage_a import score_fact
from backend.eval.comprehensive import page_metrics


async def run(a):
    import asyncpg
    import duckdb
    import json
    import re
    from backend.config import get_settings
    manifest=load(a.run_dir/'run_manifest.json');plan=load(a.run_dir/'plan_locked.json')
    name=manifest['database_name']
    if not re.fullmatch(r'ragdb_ingest_smoke_v4_\d+',name):raise ValueError('Not an isolated acceptance DB')
    a.output.mkdir(parents=True,exist_ok=False)
    mappings={};source_docs={};stored={}
    for d in plan['documents']:
        if sha(d['sample_pdf'])!=d['sample_sha256'] or sha(d['original_pdf'])!=d['original_sha256']:
            raise ValueError('Mapped sources changed')
        docid=load(a.run_dir/f"upload_{d['code']}.json")['id'];source_docs[docid]=d
        for m in d['page_map']:
            mappings[(docid,m['uploaded_pdf_page'])]=(d['code'],m['original_pdf_page'])
            record=load(a.run_dir/'stored_pages'/f"{d['code']}_{m['uploaded_pdf_page']}.json")
            if record['document_id']!=docid or record['page']!=m['uploaded_pdf_page']:
                raise ValueError('Stored page mapping mismatch')
            stored[(d['code'],m['original_pdf_page'])]=record
    base=make_url(get_settings().DATABASE_URL)
    conn=await asyncpg.connect(host=base.host,port=base.port or 5432,user=base.username,password=base.password,database=name)
    try:
        documents=[dict(x) for x in await conn.fetch('SELECT id,filename,source_sha256,status FROM documents ORDER BY id')]
        pages=[dict(x) for x in await conn.fetch('SELECT document_id,page_number,status,error_stage,error_message FROM document_pages ORDER BY document_id,page_number')]
        chunks=[dict(x) for x in await conn.fetch('SELECT document_id,chunk_index,chunk_text,metadata FROM chunks ORDER BY document_id,chunk_index')]
        rows=[dict(x) for x in await conn.fetch('SELECT document_id,table_name,source_page,row_index,unit,source_sha256,source_provider,quality_status,row_data FROM structured_data ORDER BY document_id,table_name,row_index')]
    finally:await conn.close()
    for c in chunks:
        if isinstance(c['metadata'],str):c['metadata']=json.loads(c['metadata'])
    save(a.output/'database_snapshot.json',{'documents':documents,'pages':pages,'chunks':chunks,'structured_rows':rows})
    doc_hash={d['id']:d['source_sha256'] for d in documents}
    semantics=[c for c in chunks if c['metadata'].get('source_kind','semantic') in ('semantic','table_csv')]
    provenance={'n_documents':len(documents),'n_pages':len(pages),'indexed_pages':sum(p['status']=='indexed' for p in pages),
        'page_statuses':dict(Counter(p['status'] for p in pages)),
        'documents_sample_hash_bound':sum(doc_hash[docid]==d['sample_sha256'] for docid,d in source_docs.items()),
        'n_chunks':len(chunks),'chunks_source_hash_bound':sum(c['metadata'].get('source_sha256')==doc_hash[c['document_id']] for c in chunks),
        'searchable_chunks_page_mapped':sum((c['document_id'],c['metadata'].get('page')) in mappings for c in semantics),
        'n_searchable_chunks':len(semantics),'n_structured_rows':len(rows),
        'structured_rows_hash_bound':sum(r['source_sha256']==doc_hash[r['document_id']] for r in rows),
        'structured_rows_page_mapped':sum((r['document_id'],r['source_page']) in mappings for r in rows),
        'structured_rows_explicit_unit':sum(bool(r['unit']) for r in rows),
        'structured_rows_gemini_provider':sum(r['source_provider']=='gemini' for r in rows),
        'duplicate_chunk_indices':len(chunks)-len({(c['document_id'],c['chunk_index']) for c in chunks}),
        'duplicate_structured_indices':len(rows)-len({(r['document_id'],r['table_name'],r['row_index']) for r in rows})}
    warehouse=Path(manifest['duckdb_path'])
    with duckdb.connect(str(warehouse),read_only=True) as db:
        schemas=db.execute("SELECT table_name,column_name FROM information_schema.columns ORDER BY table_name,ordinal_position").fetchall()
        tables=sorted({t for t,c in schemas})
        counts={t:db.execute('SELECT count(*) FROM "'+t.replace('"','""')+'"').fetchone()[0] for t in tables}
        save(a.output/'warehouse_snapshot.json',{'schemas':schemas,'row_counts':counts,'warehouse_sha256':sha(warehouse)})
    save(a.output/'provenance.json',provenance)
    facts=load(a.cell_reference)['facts'];cell_rows=[]
    for fact in facts:
        code,physical=fact['page_id'].rsplit('_',1);page=stored.get((code,int(physical)))
        for layer,key in [('raw_gemini','raw_ocr_tables'),('stored_accepted','structured_tables')]:
            if not page or page['status']!='indexed': result={'state':'failed_or_unindexed_page','correct':None}
            else:
                tables=deepcopy(page.get(key,[]))
                for t in tables:t['page']=int(physical)
                result=score_fact(fact,tables)
            cell_rows.append({'id':fact['id'],'page_id':fact['page_id'],'layer':layer,**result})
    cell_summary={}
    for layer in ('raw_gemini','stored_accepted'):
        part=[r for r in cell_rows if r['layer']==layer];measured=[r for r in part if r['correct'] is not None];correct=sum(r['correct'] is True for r in part)
        cell_summary[layer]={'n_required':len(part),'n_measured':len(measured),'n_correct':correct,'n_unknown':len(part)-len(measured),
            'accuracy_measured':correct/len(measured) if measured else None,'strict_lower_bound_all':correct/len(part),
            'states':dict(Counter(r['state'] for r in part))}
    save(a.output/'cell_details.json',cell_rows);save(a.output/'cell_summary.json',cell_summary)
    bank=load(a.rag_reference);items={q['id']:q for q in bank['items']};registry={d['code']:d for d in bank['documents']};retrieval=[]
    for answer in load(a.run_dir/'answers.json'):
        hits=[]
        for h in answer['retrieval']:
            key=(h['document_id'],h.get('page'))
            if key not in mappings:raise ValueError('Unmapped actual retrieved source')
            code,page=mappings[key];hits.append({'filename':registry[code]['source_file'],'source_pdf_page':page})
        metrics=page_metrics(items[answer['id']],hits,registry,k=5)
        retrieval.append({'id':answer['id'],'mapped_actual_hits':hits,**metrics,
            'answer_capture_status':answer['full_result'].get('answer_capture',{}).get('status'),
            'n_emitted_sources':len(answer['full_result'].get('sources',[]))})
    save(a.output/'retrieval16_mapped.json',retrieval)
    if a.numeric_labels:
        from backend.eval.contract_replay import numeric_results
        labels=load(a.numeric_labels);numeric=[];views=[]
        original_to_uploaded={(d['code'],m['original_pdf_page']):m['uploaded_pdf_page'] for d in plan['documents'] for m in d['page_map']}
        actual_filenames={source_docs[d['id']]['code']:d['filename'] for d in documents}
        registry_view=[{**d,'source_file':actual_filenames[d['code']]} for d in bank['documents']]
        for answer in load(a.run_dir/'answers.json'):
            for label in [x for x in labels if x['id']==answer['id']]:
                key=(label['document'],label['source_pdf_page'])
                if key not in original_to_uploaded:
                    numeric.append({'id':answer['id'],'quantity_index':label['quantity_index'],'correct':None,'state':'gold_source_outside_selected_page_scope'})
                    continue
                view=deepcopy(label);view['source_pdf_page']=original_to_uploaded[key]
                view['alternate_pdf_pages']=[original_to_uploaded[(label['document'],p)] for p in label.get('alternate_pdf_pages',[]) if (label['document'],p) in original_to_uploaded]
                # Only the citation address changes in this evaluation view.
                # Original labels, model output, binding, facts and aliases stay intact.
                assert {k:v for k,v in view.items() if k not in ('source_pdf_page','alternate_pdf_pages')}=={k:v for k,v in label.items() if k not in ('source_pdf_page','alternate_pdf_pages')}
                views.append({'id':label['id'],'quantity_index':label['quantity_index'],'original_page':label['source_pdf_page'],
                    'uploaded_page':view['source_pdf_page'],'original_alternates':label.get('alternate_pdf_pages',[]),
                    'uploaded_alternates':view['alternate_pdf_pages'],'original_source_sha256':label['source_sha256'],
                    'method':'read-only citation-address projection via verified original/subset map; factual tuple/scorer/aliases unchanged'})
                numeric.extend({'id':answer['id'],**x} for x in numeric_results([view],answer['full_result'],answer['answer'],allow_provisional=True,document_registry=registry_view))
        save(a.output/'numeric_address_projection.json',views);save(a.output/'numeric_details.json',numeric)
        measured=[n for n in numeric if n['correct'] is not None];correct=sum(n['correct'] is True for n in numeric)
        save(a.output/'numeric_summary.json',{'n_required_labels':len(numeric),'n_measured':len(measured),'n_correct':correct,
            'n_unknown':len(numeric)-len(measured),'accuracy_measured':correct/len(measured) if measured else None,
            'strict_lower_bound_all':correct/len(numeric) if numeric else None,'coverage':len(measured)/len(numeric) if numeric else None,
            'states':dict(Counter(n['state'] for n in numeric)),'original_labels_sha256':sha(a.numeric_labels),
            'scope':'only the five existing locked numeric tuples within sixteen questions; does not cover every number in this integration selection',
            'source_page_projection_only':True,'outputs_and_binding_unmodified':True,'human_confirmed':False})
    cp=stored.get(('CPAXT',38),{});raw='\n'.join(r.get('markdown','') for r in cp.get('raw_ocr_pages',[]))
    searchable='\n'.join(c['chunk_text'] for c in semantics if mappings.get((c['document_id'],c['metadata'].get('page')))==('CPAXT',38))
    keys=['จำนวนงานทั้งหมด','มูลค่างานทั้งหมด','มูลค่ารับรู้แล้ว','มูลค่างานคงเหลือที่ยังไม่รับรู้']
    normalized=re.sub(r'\s+','',searchable)
    key_checks={key:bool(re.search(re.escape(key)+r'[^:|]{0,80}[:|]N/A',normalized)) for key in keys}
    provider_raw='\n'.join(r.get('provider_markdown','') for r in cp.get('raw_ocr_pages',[]))
    save(a.output/'source_retention.json',{'CPAXT38_source_has_four_NA_values':True,'transformed_prose_NA_count':raw.count('N/A'),
        'unmodified_provider_markdown_available':bool(provider_raw),'provider_NA_count':provider_raw.count('N/A') if provider_raw else None,
        'searchable_NA_count':searchable.count('N/A'),'per_key_NA_retained':key_checks,
        'status':'all_four_key_relations_detected_requires_visual_confirmation' if all(key_checks.values()) else 'source_NA_retention_failure_or_unmeasurable',
        'raw_excerpt':raw[-2000:],'searchable_excerpt':searchable[-2000:]})
    save(a.output/'method_lock.json',{'plan_sha256':sha(a.run_dir/'plan_locked.json'),'source_cells_sha256':sha(a.cell_reference),
        'rag_reference_sha256':sha(a.rag_reference),'code_sha256':sha(__file__),'new_sdk_attempts':0,'human_confirmed':False,
        'scope':'actual current selected32 mapped acceptance; raw and stored cells separately; page mapping is evaluation-only; no label facts inserted'})
    print(provenance,flush=True);print(cell_summary,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('run-dir','cell-reference','rag-reference','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--numeric-labels',type=Path)
    asyncio.run(run(p.parse_args()))
