"""Verifiable model-selected text fragments; no quote copying or inference."""
from copy import deepcopy


def fragments(text,prefix,width=220,overlap=40):
    rows=[];start=0
    while start<len(text):
        end=min(len(text),start+width)
        rows.append({'id':prefix+str(len(rows)), 'start':start,'end':end,'text':text[start:end]})
        if end==len(text):break
        start=end-overlap
    return rows


def banks(row):
    return {'context':fragments(row['context'],'C'), 'reference':fragments(row['reference'],'R'),
        'sources':{i:fragments(__import__('backend.eval.comprehensive',fromlist=['source_text']).source_text(source),f'S{i}_')
            for i,source in enumerate(row['sources'])}}


def adapt_payload(payload,row):
    result=deepcopy(payload);bank=banks(row)
    result['ACTUAL_CONTEXT']={'fragments':bank['context'],'scope':'Complete original text, with overlap'}
    result['INDEPENDENT_REFERENCE']={'fragments':bank['reference'],'scope':'Complete independent reference text, with overlap'}
    result['SOURCES']=[{'index':s['index'],'fragments':bank['sources'][s['index']]} for s in payload['SOURCES']]
    for block in result['EVIDENCE_BLOCKS']:
        block['fragment_ids']=[f['id'] for f in bank['context'] if block['start']<=f['start'] and f['end']<=block['end']]
    result['QUOTE_PROTOCOL']='model-selected-original-fragments-v1'
    return result


def adapt_schema(schema):
    result=deepcopy(schema)
    def replace(obj,old,new):
        obj['properties'][new]=obj['properties'].pop(old)
        obj['required']=[new if k==old else k for k in obj['required']]
    answer=result['properties']['answer_claims']['items']
    replace(answer,'context_quote','context_fragment_id');replace(answer,'reference_quote','reference_fragment_id')
    replace(answer['properties']['citations']['items'],'quote','source_fragment_id')
    replace(result['properties']['reference_claims']['items'],'context_quote','context_fragment_id')
    replace(result['properties']['context_relevance']['items'],'quote','context_fragment_id')
    replace(result['properties']['actual_citation_audit']['items'],'quote','source_fragment_id')
    return result


def resolve(raw,row):
    result=deepcopy(raw);bank=banks(row)
    ctx={f['id']:f['text'] for f in bank['context']};ref={f['id']:f['text'] for f in bank['reference']}
    src={i:{f['id']:f['text'] for f in values} for i,values in bank['sources'].items()}
    def quote(item,id_key,quote_key,pool,required=False):
        ident=item.get(id_key)
        if ident=='':
            if required:raise ValueError('Supported decision requires an original text fragment for '+id_key+
                '; choose an existing ID from the corresponding evidence, or use insufficient/not covered/not useful when no text entails this decision')
            item[quote_key]='';return
        if not isinstance(ident,str) or ident not in pool:raise ValueError('Fragment identifier outside bound evidence')
        item[quote_key]=pool[ident]
    for claim in result['answer_claims']:
        quote(claim,'context_fragment_id','context_quote',ctx,claim['faithfulness']=='supported')
        quote(claim,'reference_fragment_id','reference_quote',ref,claim['factual']=='supported')
        for citation in claim['citations']:
            quote(citation,'source_fragment_id','quote',src.get(citation['source_index'],{}),True)
    for required in result['reference_claims']:
        quote(required,'context_fragment_id','context_quote',ctx,required['context_covered'])
    for block in result['context_relevance']:
        quote(block,'context_fragment_id','quote',ctx,block['useful'])
    for citation in result['actual_citation_audit']:
        quote(citation,'source_fragment_id','quote',src.get(citation['source_index'],{}),citation['verdict']=='supported')
    return result
