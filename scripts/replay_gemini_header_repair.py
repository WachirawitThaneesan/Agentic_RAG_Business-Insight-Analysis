"""Replay deterministic header repair against exact saved Gemini outputs.

Never regenerates output or recovers a failed region using a different response.
"""
import argparse
from copy import deepcopy
import importlib.util
from pathlib import Path

from backend.services import gemini_tables as candidate
from scripts.evaluate_comprehensive import load, save, sha
from scripts.evaluate_gemini_ocr_stage_a import score_run


def run(source, output, baseline_code, references):
    if output.exists(): raise ValueError('Use a new replay output directory')
    output.mkdir(parents=True)
    spec=importlib.util.spec_from_file_location('locked_old_table_normalizer',baseline_code)
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    reads=load(source/'raw_component_reads.json')
    lineage=[]
    for path in sorted((source/'pages').glob('*.json')):
        record=load(path);updated=deepcopy(record)
        matches=[r for r in reads if r['image_sha256']==record['image_sha256']]
        matched=False
        if not record.get('error') and matches:
            data=matches[-1]['response']
            try:
                matched=old._normalize_gemini_tables(data,record['physical_page'],record['region'])==record['tables']
                if matched:
                    updated['tables']=candidate._normalize_gemini_tables(data,record['physical_page'],record['region'])
            except ValueError: pass
        updated['projection']={'method':'unchanged raw generation; deterministic header normalization only',
            'source_run':source.name,'raw_exactly_reproduces_saved_tables':matched}
        save(output/'pages'/path.name,updated)
        lineage.append({'id':record['id'],'matched':matched,'baseline_error_preserved':record.get('error'),
            'n_header_repairs':sum(len(t.get('header_repairs',[])) for t in updated.get('tables',[]))})
    save(output/'method_lock.json',{'source':str(source.resolve()),'source_raw_sha256':sha(source/'raw_component_reads.json'),
        'references_sha256':sha(references),'normalizer_sha256':sha(Path(candidate.__file__)),
        'new_sdk_attempts':0,'raw_lineage':lineage})
    print(score_run(output,load(references)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','baseline-code','references'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();run(a.source,a.output,a.baseline_code,a.references)
