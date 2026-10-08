"""Necessary year-presence check over saved source/extraction audit decisions.

Rejecting missing years cannot establish that a present year is correctly bound.
No answer labels, source correction or model generation is involved.
"""
import argparse
from collections import Counter
from copy import deepcopy
from pathlib import Path
import re
from scripts.evaluate_comprehensive import load, save, sha


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','audit','output'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    pages=deepcopy(load(a.audit/'details.json'))
    demoted=[]
    for page in pages:
        probe=load(a.audit/'source_probes'/(page['id']+'.json'))
        relations={r['index']:r for r in (probe.get('parsed') or {}).get('relations',[])}
        record=load(a.source/'stored_pages'/f"{page['document']}_{page['uploaded_pdf_page']}.json")
        evidence='\n'.join([r.get('markdown','') for r in record.get('raw_ocr_pages',[])]+
                           [t.get('csv_text','') for t in record.get('structured_tables',[])])
        for decision in page['relations']:
            year=relations[decision['index']].get('year_be')
            if decision['state'] not in ('correct','quote_unverifiable') or type(year) is not int:
                continue
            present=any(re.search(r'(?<!\d)'+str(y)+r'(?!\d)',evidence) for y in (year,year-543))
            decision['required_year_presence_necessary_check']={'year_be':year,'present':bool(present),
                'present_does_not_certify_binding':True}
            if not present:
                demoted.append({'id':page['id'],'index':decision['index'],'previous_state':decision['state'],
                    'required_year_be':year,'original_probe_sha256':sha(a.audit/'source_probes'/(page['id']+'.json'))})
                decision['state']='required_year_absent_from_extraction'
    known=[r for page in pages if page['audit_valid'] for r in page['relations']
           if r['state'] in ('correct','wrong_relationship','omitted')]
    all_required=sum(page['source_probe_count'] for page in pages if page['source_probes_valid'])
    a.output.mkdir(parents=True,exist_ok=False)
    save(a.output/'details.json',pages)
    save(a.output/'demotions.json',demoted)
    save(a.output/'summary.json',{'n_pages':len(pages),'n_valid_page_audits':sum(x['audit_valid'] for x in pages),
        'n_required_relations_valid_source_probes':all_required,'n_measured_relations':len(known),
        'n_correct':sum(r['state']=='correct' for r in known),
        'accuracy_measured':sum(r['state']=='correct' for r in known)/len(known) if known else None,
        'strict_lower_bound_all_valid_source_probes':sum(r['state']=='correct' for r in known)/all_required,
        'n_unknown_including_missing_years':all_required-len(known),'n_missing_year_demotions':len(demoted),
        'states':dict(Counter(r['state'] for x in pages if x['audit_valid'] for r in x['relations'])),
        'not_exhaustive_cell_accuracy':True,'human_confirmed':False})
    save(a.output/'method_lock.json',{'parent_details_sha256':sha(a.audit/'details.json'),
        'source_plan_sha256':sha(a.source/'plan_locked.json'),'script_sha256':sha(__file__),
        'source_probe_values_and_extraction_unchanged':True,'new_sdk_attempts':0,
        'scope':'Conservative necessary condition; present year does not prove relation; absent required year cannot be accepted as correct'})
    print('Missing-year demotions:',demoted)


if __name__=='__main__':main()
