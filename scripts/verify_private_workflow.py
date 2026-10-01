"""Isolated real-PDF private API check; saves failures as well as successes.

Configure prefetched LOCAL_OCR_* paths before running. No hosted OCR/generation.
Example: python -m scripts.verify_private_workflow --pdf report.pdf --question ...
         --expected-fragment ... --output outputs/private-check
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import socket
import threading
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--question', required=True)
    parser.add_argument('--expected-fragment', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    result={'question':args.question,'expected_fragment':args.expected_fragment,
            'source_sha256':hashlib.sha256(args.pdf.read_bytes()).hexdigest(),
            'scope':'real PDF, FastAPI TestClient upload/index/query/page-image; process-level outbound block, not OS firewall',
            'status':'running','local_model_calls':[]}
    start=time.perf_counter(); samples=[]; stop=threading.Event()
    def save():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    def sample():
        import psutil
        proc=psutil.Process()
        while not stop.is_set():
            rss=0
            for p in [proc]+proc.children(recursive=True):
                try:rss+=p.memory_info().rss
                except (psutil.NoSuchProcess,psutil.AccessDenied):pass
            samples.append({'elapsed':time.perf_counter()-start,'app_workers_rss_mib':rss/2**20})
            stop.wait(1)
    from backend.config import get_settings
    from sqlalchemy.engine import make_url
    from scripts.benchmark_long_document import _create_test_db, _drop_test_db
    base_url=get_settings().DATABASE_URL
    db_name=f'ragdb_private_check_{os.getpid()}'
    asyncio.run(_create_test_db(base_url,db_name))
    url=make_url(base_url).set(database=db_name)
    os.environ.update(OFFLINE_MODE='true',PRIVATE_DATA_DIR=str(output/'private'),
        DATABASE_URL=url.render_as_string(hide_password=False),
        DATABASE_URL_SYNC=url.set(drivername='postgresql').render_as_string(hide_password=False))
    get_settings.cache_clear()
    thread=threading.Thread(target=sample,daemon=True);thread.start()
    try:
        from fastapi.testclient import TestClient
        import backend.services.llm as llm
        original=llm._generate_ollama
        async def measured(*a,**kw):
            t=time.perf_counter();record={};result['local_model_calls'].append(record)
            try:
                answer=await original(*a,**kw);record['status']='success';return answer
            except Exception as exc:
                record['status']=type(exc).__name__;raise
            finally:record['seconds']=time.perf_counter()-t;save()
        llm._generate_ollama=measured
        from backend.main import app
        with TestClient(app) as client:
            result['health']=client.get('/api/health').json()
            for label,operation in [
                ('external_dns_blocked',lambda:socket.getaddrinfo('example.org',443)),
                ('external_tcp_blocked',lambda:socket.create_connection(('1.1.1.1',443),timeout=2))]:
                try:operation()
                except OSError as exc: result[label]='OFFLINE_MODE blocked' in str(exc)
                else:result[label]=False
                assert result[label],label
            result['scrape_status']=client.post('/api/scrape/url',json={'url':'https://example.org'}).status_code
            assert result['scrape_status']==403
            response=client.post('/api/documents/upload',files={'file':(args.pdf.name,args.pdf.read_bytes(),'application/pdf')})
            response.raise_for_status();doc=response.json();doc_id=doc['id'];pages=doc['page_count']
            result.update(upload=doc,upload_seconds=time.perf_counter()-start);save()
            deadline=time.monotonic()+pages*get_settings().LOCAL_OCR_PAGE_TIMEOUT_SECONDS+120
            while time.monotonic()<deadline:
                detail=client.get(f'/api/documents/{doc_id}').json()
                result.update(document=detail,processing_seconds=time.perf_counter()-start);save()
                if detail['status'] in {'completed','partial','failed'}:break
                time.sleep(2)
            else:raise TimeoutError('Local document did not finish')
            assert detail['status']=='completed',detail.get('error_message')
            assert len(detail['page_statuses'])==pages
            assert all(p['status']=='indexed' for p in detail['page_statuses'])
            response=client.post('/api/query',json={'question':args.question});response.raise_for_status()
            answer=response.json();result['answer']=answer
            result['answer_matches_reference']=args.expected_fragment.replace(',','') in answer['answer'].replace(',','')
            sources=[s for s in answer.get('sources',[]) if s.get('document_id')==doc_id and s.get('page')]
            result['located_sources']=sources
            if sources:
                page=client.get(f'/api/documents/{doc_id}/pages/{sources[0]["page"]}/image')
                result['page_image_status']=page.status_code
                if page.status_code==200:(output/'source-page.png').write_bytes(page.content)
            result['workflow_passed']=bool(result['answer_matches_reference'] and sources and result.get('page_image_status')==200)
            result['status']='passed' if result['workflow_passed'] else 'failed_answer_or_citation'
    except Exception as exc:
        result.update(status='failed',error_type=type(exc).__name__,error=str(exc)[:500])
    finally:
        stop.set();thread.join(3)
        result.update(total_seconds=time.perf_counter()-start,
            peak_app_workers_rss_mib=max((s['app_workers_rss_mib'] for s in samples),default=0))
        (output/'resources.json').write_text(json.dumps(samples),encoding='utf-8')
        save()
        # Only the uniquely named disposable database created by this run.
        asyncio.run(_drop_test_db(base_url,db_name))
        result['test_database_removed']=True;save()
    print(json.dumps({k:result.get(k) for k in ['status','total_seconds','peak_app_workers_rss_mib','answer_matches_reference']},ensure_ascii=False))


if __name__=='__main__':main()
