"""Reuse unchanged BGE-M3 queries and embed only reviewed wording changes."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import httpx
import numpy as np
from scripts.evaluate_comprehensive import load, save, sha

def fingerprint(questions):
    return hashlib.sha256(('bge-m3\n'+'\n'.join(questions)).encode()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('parent-reference','reviewed-reference','parent-cache','output'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    old=load(a.parent_reference)['items'];new=load(a.reviewed_reference)['items']
    if [x['id'] for x in old]!=[x['id'] for x in new]:raise ValueError('Bank ID/order changed')
    old_questions=[x['question_th'] for x in old]
    with np.load(a.parent_cache) as cached:
        vectors=cached['vectors'].copy();old_fingerprint=str(cached['fingerprint'])
    if old_fingerprint!=fingerprint(old_questions) or vectors.shape!=(len(old),1024):
        raise ValueError('Parent query cache identity mismatch')
    changed=[(i,new[i]['id'],new[i]['question_th']) for i in range(len(new))
             if old_questions[i]!=new[i]['question_th']]
    if changed:
        with httpx.Client(timeout=300,trust_env=False) as client:
            response=client.post('http://127.0.0.1:11434/api/embed',
                json={'model':'bge-m3','input':[x[2] for x in changed],'keep_alive':'30m'})
            response.raise_for_status();embedded=np.asarray(response.json()['embeddings'],dtype=np.float32)
        if embedded.shape!=(len(changed),1024):raise ValueError('Partial/wrong-size embeddings')
        for (index,_,_),v in zip(changed,embedded):vectors[index]=v
    new_fingerprint=fingerprint([x['question_th'] for x in new]);np.savez_compressed(
        a.output,vectors=vectors,fingerprint=new_fingerprint)
    lineage={'model':'bge-m3','parent_reference_sha256':sha(a.parent_reference),
             'reviewed_reference_sha256':sha(a.reviewed_reference),
             'parent_cache_sha256':sha(a.parent_cache),'new_cache_sha256':sha(a.output),
             'n_queries':len(new),'n_reused':len(new)-len(changed),
             'n_embedded_new':len(changed),'changed_ids':[x[1] for x in changed]}
    save(a.output.with_suffix('.lineage.json'),lineage)
    print(json.dumps(lineage,ensure_ascii=False))

if __name__=='__main__':main()
