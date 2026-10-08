"""Retain an exact frozen paired prefix in a larger preflighted run.

Clone its owned isolated database. Both databases and all prefix outcomes,
including provider errors, are retained. No answers are generated here.
"""
import argparse
import asyncio
import os
from pathlib import Path
import re
import shutil
from scripts.evaluate_comprehensive import load,save,sha


async def run(a):
    old=load(a.parent/'manifest.json');new=load(a.output/'manifest.json')
    assert load(a.output/'preflight.json')['passed']
    assert old['code_sha256']==new['code_sha256']
    for field in ('arms','n_chunks','pdfs_sha256','alternative_corpus_sha256','evaluation_scope'):
        if old[field]!=new[field]:raise ValueError('Inference conditions changed: '+field)
    assert new['selected_ids'][:len(old['selected_ids'])]==old['selected_ids']
    before={k:v for k,v in old['inputs_sha256'].items() if 'selection' not in Path(k).name}
    after={k:v for k,v in new['inputs_sha256'].items() if 'selection' not in Path(k).name}
    assert before==after
    records=load(a.parent/'paired_answers.json')
    assert [r['id'] for r in records]==old['selected_ids']
    assert all(set(r['arms'])==set(old['arms']) for r in records)
    if (a.output/'isolated_storage.json').exists():raise ValueError('Target already has owned storage')
    source=load(a.parent/'isolated_storage.json')['database']
    target=f'ragdb_capture_paired_{os.getpid()}'
    if not all(re.fullmatch(r'ragdb_capture_paired_\d+',name) for name in (source,target)):
        raise ValueError('Not owned paired databases')
    from backend.config import get_settings
    from scripts.benchmark_long_document import _admin_connect
    conn=await _admin_connect(get_settings().DATABASE_URL)
    try:
        if await conn.fetchval('SELECT 1 FROM pg_database WHERE datname=$1',target):
            raise ValueError('Refusing overwrite')
        await conn.execute(f'CREATE DATABASE "{target}" TEMPLATE "{source}"')
    finally:await conn.close()
    for filename in ('paired_answers.json','followup_query_vectors.json','model_configuration.json','isolated_warehouse.duckdb'):
        if (a.parent/filename).exists():shutil.copy2(a.parent/filename,a.output/filename)
    save(a.output/'isolated_storage.json',{'database':target,'production_database_touched':False,
        'retained':True,'duckdb':str(a.output/'isolated_warehouse.duckdb')})
    save(a.output/'PREFIX_EXTENSION_LOCK.json',{'parent_manifest_sha256':sha(a.parent/'manifest.json'),
        'parent_answers_sha256':sha(a.parent/'paired_answers.json'),'retained_answers_sha256':sha(a.output/'paired_answers.json'),
        'target_manifest_sha256':sha(a.output/'manifest.json'),'script_sha256':sha(__file__),
        'source_database':source,'cloned_database':target,'n_prefix_pairs':len(records),
        'n_remaining_pairs':len(new['selected_ids'])-len(records),'all_prefix_outcomes_retained':True,
        'same_code_inputs_corpus_policies_ordering':True,'new_sdk_attempts':0,
        'scope':'Same frozen development conditions; prefix reuse does not make any question unseen/final'})
    print('Retained',len(records),'paired outcomes; remaining',len(new['selected_ids'])-len(records))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    asyncio.run(run(p.parse_args()))
