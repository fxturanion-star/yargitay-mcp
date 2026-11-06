"""Offline, synthetic Turkish retrieval comparison with frozen dev/holdout splits.

Run from the repository root with the installed production environment:
    python scripts/quality_compare.py --stage dev
    python scripts/quality_compare.py --stage holdout
or --stage all. No legal service is queried and no additional model is installed.
Gold labels are used only by metrics, never by a ranker. Selection reads dev only.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import types
from scripts import semantic_eval as old

DIRECTORY = ROOT / 'evaluation'
# Frozen production source prevents concurrent passage-pipeline edits changing this study.
_frozen = json.loads((DIRECTORY/'frozen_e5_source.json').read_text())
if hashlib.sha256(_frozen['source'].encode()).hexdigest() != _frozen['sha256']:
    raise RuntimeError('Frozen E5 source changed')
semantik = types.ModuleType('frozen_production_semantik')
exec(compile(_frozen['source'], 'frozen_production_semantik.py', 'exec'), semantik.__dict__)
CONFIGS = [
    {'name':'e5','method':'e5'},
    {'name':'bm25','method':'bm25'},
    {'name':'char4','method':'char4'},
    {'name':'rrf_bm25_w05','method':'rrf','lex':'bm25','weight':0.5,'k':60},
    {'name':'rrf_bm25_w1','method':'rrf','lex':'bm25','weight':1.0,'k':60},
    {'name':'rrf_bm25_w2','method':'rrf','lex':'bm25','weight':2.0,'k':60},
    {'name':'rrf_char4_w1','method':'rrf','lex':'char4','weight':1.0,'k':60},
    {'name':'linear_bm25_015','method':'linear','lex':'bm25','weight':0.15},
    {'name':'linear_bm25_030','method':'linear','lex':'bm25','weight':0.30},
    {'name':'rerank_char4_top5_015','method':'rerank','lex':'char4','weight':0.15,'top_n':5},
]


def dump(name, value):
    (DIRECTORY/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_hashes():
    return {str(path.relative_to(ROOT)):digest(path) for path in
            [ROOT/'scripts/quality_compare.py', ROOT/'scripts/semantic_eval.py', DIRECTORY/'frozen_e5_source.json',
             DIRECTORY/'dev.json', DIRECTORY/'holdout.json', DIRECTORY/'protocol.json']}


def check_assets():
    # Fail locally rather than silently downloading a missing/unverified model.
    cache = Path(os.getenv('SEMANTIK_MODEL_CACHE', Path.home()/'.cache/yargitay-mcp'))/semantik.REVISION
    for asset, expected in semantik.FILES.items():
        path = cache/Path(asset).name
        if not path.is_file() or digest(path) != expected:
            raise RuntimeError(f'Verified cached model asset required: {path}')
    import onnxruntime as ort
    ort.disable_telemetry_events()


def normalize(text):
    return ' '.join(re.findall(r'[^\W\d_]+', text.lower().replace('ı','i').replace('i\u0307','i')))


def char_scores(query, texts):
    """Character 4-gram TF-IDF cosine. No language model or fitted relevance labels."""
    def grams(text):
        text = ' '+normalize(text)+' '
        return Counter(text[i:i+4] for i in range(len(text)-3))
    docs = [grams(t) for t in texts]
    q = grams(query)
    df = Counter(k for doc in docs for k in doc)
    idf = {term:math.log((1+len(docs))/(1+count))+1 for term,count in df.items()}
    def vector(doc):
        return {term:(1+math.log(n))*idf.get(term,math.log(1+len(docs))+1) for term,n in doc.items()}
    qv=vector(q); qnorm=math.sqrt(sum(v*v for v in qv.values()))
    scores=[]
    for doc in docs:
        v=vector(doc); norm=math.sqrt(sum(x*x for x in v.values()))
        scores.append(sum(x*v.get(k,0) for k,x in qv.items())/(qnorm*norm) if qnorm*norm else 0.)
    return scores


def order(scores):
    if not all(math.isfinite(float(s)) for s in scores):
        raise ValueError('Non-finite ranking score')
    return sorted(range(len(scores)),key=lambda i:-scores[i])


def scaled(scores):
    lo,hi=min(scores),max(scores)
    return [(s-lo)/(hi-lo) if hi>lo else 0. for s in scores]


def fused(config, scores):
    method=config['method']
    if method in ('e5','bm25','char4'):
        return order(scores[method])
    lexical=scores[config['lex']]; semantic=scores['e5']; w=config['weight']
    if method=='rrf':
        er={idx:rank for rank,idx in enumerate(order(semantic),1)}
        lr={idx:rank for rank,idx in enumerate(order(lexical),1)}
        return order([1/(config['k']+er[i])+w/(config['k']+lr[i]) for i in range(len(semantic))])
    combined=[(1-w)*a+w*b for a,b in zip(scaled(semantic),scaled(lexical))]
    if method=='linear':
        return order(combined)
    if method=='rerank':
        initial=order(semantic); pool=initial[:config['top_n']]
        return sorted(pool,key=lambda i:(-combined[i],initial.index(i)))+initial[config['top_n']:]
    raise ValueError(method)


def metrics(rows):
    n=len(rows)
    result={'queries':n,'top1_count':sum(r['rank']==1 for r in rows),
            'top3_count':sum(r['rank']<=3 for r in rows),
            'mrr':sum(1/r['rank'] for r in rows)/n}
    for k in (1,3,5,10):
        result[f'recall@{k}']=sum(r['rank']<=k for r in rows)/n
        result[f'precision@{k}']=sum((r['rank']<=k)/k for r in rows)/n
        result[f'ndcg@{k}']=sum(1/math.log2(r['rank']+1) if r['rank']<=k else 0 for r in rows)/n
    result['foil_above_gold_count']=sum(r['foil_above_gold'] for r in rows)
    return {k:round(v,6) if isinstance(v,float) else v for k,v in result.items()}


def evaluate(data, configs):
    ids=sorted(data['passages'],key=lambda key:hashlib.sha256(key.encode()).digest())
    texts=[data['passages'][i] for i in ids]
    rows={c['name']:[] for c in configs}; times={'e5':[],'bm25':[],'char4':[]}
    fusion={c['name']:[] for c in configs}; start=time.perf_counter()
    for question in data['questions']:
        scores={}
        for method,fn in [('e5',semantik.similarities),('bm25',old.lexical),('char4',char_scores)]:
            t=time.perf_counter(); scores[method]=fn(question['query'],texts); times[method].append(time.perf_counter()-t)
        for config in configs:
            t=time.perf_counter(); ranked=[ids[i] for i in fused(config,scores)]; fusion[config['name']].append(time.perf_counter()-t)
            gold=question['gold'][0]; rank=ranked.index(gold)+1
            foils=question.get('foil',[])
            rows[config['name']].append({'id':question['id'],'kind':question['kind'],'rank':rank,
                 'foil_above_gold':any(ranked.index(f)<rank-1 for f in foils),'ranking':ranked})
        print(f"scored {question['id']}",flush=True)
    results={}
    for config in configs:
        name=config['name']; method=config['method']; lexical=config.get('lex')
        components=[method] if method in ('e5','bm25','char4') else ['e5',lexical]
        # The first query may include cold initialization. Report it separately.
        costs=[sum(times[m][i] for m in components)+fusion[name][i] for i in range(len(data['questions']))]
        results[name]={'metrics':metrics(rows[name]),'by_kind':{},'rows':rows[name],
            'median_warm_query_seconds':round(statistics.median(costs[1:] or costs),6),
            'total_measured_component_seconds':round(sum(costs),6)}
        for kind in sorted({r['kind'] for r in rows[name]}):
            results[name]['by_kind'][kind]=metrics([r for r in rows[name] if r['kind']==kind])
    return {'candidate_count':len(ids),'results':results,'wall_seconds':round(time.perf_counter()-start,6),
            'first_e5_query_seconds':round(times['e5'][0],6),
            'peak_process_rss_mib':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,3),
            'resource_note':'Peak RSS is the shared whole-process Linux high-water mark, not isolated per ranker. Pipeline latency sums measured required components and fusion. E5 encodes the entire identical candidate pool using production similarities; model and tokenizer load are in the first query. No cross-query passage embedding cache.'}


def load(name):
    return json.loads((DIRECTORY/name).read_text())


def dev():
    manifest=load('frozen_manifest.json')
    if manifest['sha256']!=input_hashes():
        raise RuntimeError('Frozen implementation/data changed; create a new independent experiment instead')
    result=evaluate(load('dev.json'),CONFIGS)
    # A deterministic dev-only selection rule, with original E5 preferred on ties.
    selected=max(CONFIGS,key=lambda c:(result['results'][c['name']]['metrics']['mrr'],
                  result['results'][c['name']]['metrics']['recall@1'],
                  result['results'][c['name']]['metrics']['recall@3'], c['name']=='e5',-CONFIGS.index(c)))
    result['selected_config']=selected
    result['input_sha256']=input_hashes()
    result['selection_rule']='Max dev MRR, then Recall@1, Recall@3, prefer E5, then declared configuration order; no holdout inspection.'
    dump('dev_results.json',result)
    dump('selection.json',{'selected_config':selected,'input_sha256':input_hashes(),
                           'dev_result_sha256':digest(DIRECTORY/'dev_results.json')})
    print('Dev selection:',selected['name'],flush=True)


def holdout():
    selection=load('selection.json')
    if selection['input_sha256']!=input_hashes() or selection['dev_result_sha256']!=digest(DIRECTORY/'dev_results.json'):
        raise RuntimeError('Selection inputs changed')
    selected=selection['selected_config']; configs=[c for c in CONFIGS if c['name'] in {'e5','bm25',selected['name']}]
    # Only locked selection and fixed baselines on holdout; no choosing among holdout configs.
    result=evaluate(load('holdout.json'),configs)
    result['selected_config']=selected; result['input_sha256']=input_hashes()
    result['selection_sha256']=digest(DIRECTORY/'selection.json')
    result['claim']='Synthetic exact-target retrieval only; not legal correctness, real-case retrieval, or a statistically conclusive estimate.'
    dump('holdout_results.json',result)
    old_data={'passages':old.PASSAGES,'questions':[{'id':code,'kind':kind,'query':query,'gold':[gold]}
         for code,kind,query,gold in old.QUERIES]}
    legacy=evaluate(old_data,configs)
    e5=legacy['results']['e5']['metrics']; bm=legacy['results']['bm25']['metrics']
    legacy['original_thresholds']={'top1_at_least':8,'top3_at_least':10,'mrr_at_least':0.75,'mrr_at_least_bm25':True}
    legacy['original_thresholds_pass']=e5['top1_count']>=8 and e5['top3_count']>=10 and e5['mrr']>=0.75 and e5['mrr']>=bm['mrr']
    legacy['original_script_sha256']=digest(ROOT/'scripts/semantic_eval.py')
    legacy['role']='Untouched original 12 diagnostic queries. Not used for configuration selection.'
    dump('legacy12_results.json',legacy)
    summary={name:entry['metrics'] for name,entry in result['results'].items()}
    print(json.dumps({'holdout':summary,'legacy_thresholds_pass':legacy['original_thresholds_pass']},ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=['dev','holdout','all'],default='all')
    args=parser.parse_args(); check_assets()
    if args.stage in ('dev','all'): dev()
    if args.stage in ('holdout','all'): holdout()


if __name__=='__main__': main()
