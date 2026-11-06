"""Mevcut üretim sıralayıcısının sabit baseline'a göre gerileyip gerilemediğini ölçer.

Eski kabul testi scripts/semantic_eval.py ayrı olarak başarısız kalabilir.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import semantic_eval as fixed


def compare(ranks, baseline):
    if ranks.keys() != baseline.keys():
        raise ValueError("Soru kimlikleri baseline ile eşleşmiyor.")
    return [key for key in ranks if ranks[key] > baseline[key]]


def main():
    baseline = json.loads((ROOT/'evaluation/legacy12_regression_baseline.json').read_text())
    if hashlib.sha256((ROOT/'scripts/semantic_eval.py').read_bytes()).hexdigest() != baseline['script_sha256']:
        raise ValueError("Sabit kalite verisi veya eşikleri değişmiş; baseline yeniden incelenmeli.")
    current = {code:fixed.rank(fixed.similarities(query,fixed.TEXTS),target)
               for code,kind,query,target in fixed.QUERIES}
    regressions = compare(current,baseline['gold_ranks'])
    metrics = fixed.metrics(list(current.values()))
    limits = baseline['acceptance']
    acceptance = (metrics['top1'] >= limits['min_top1'] and metrics['top3'] >= limits['min_top3']
                  and metrics['mrr'] >= limits['min_mrr'])
    report = {'baseline_commit':baseline['baseline_commit'], 'current':metrics,
              'baseline':fixed.metrics(list(baseline['gold_ranks'].values())),
              'regressed_questions':regressions, 'new_regression':bool(regressions),
              'minimum_quality_dimensions_pass':acceptance,
              'note':'Nihai kabul için ayrı scripts/semantic_eval.py kontrolü de gereklidir.'}
    print(json.dumps(report,ensure_ascii=False),flush=True)
    if regressions:
        sys.exit('Yeni semantik sıralama regresyonu bulundu.')


if __name__ == '__main__':
    main()
