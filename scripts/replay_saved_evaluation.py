"""Recompute metric arithmetic from frozen per-question audit decisions.

No model, database, embeddings, network or source PDF required. This does not
regenerate answers or certify AI judgments; it checks reproducible scoring.
"""
from pathlib import Path
import argparse
from scripts.evaluate_comprehensive import load,save,summarize

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--expected-summary',type=Path)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    result=summarize(load(a.audit/'details.json'),load(a.audit/'retrieval_details.json'))
    save(a.output/'summary.json',result)
    if a.expected_summary and result!=load(a.expected_summary):
        raise ValueError('Replayed metrics differ from saved summary; inspect version and inputs')
    print('Replay matches saved summary' if a.expected_summary else 'Offline metric replay complete')

if __name__=='__main__':main()
