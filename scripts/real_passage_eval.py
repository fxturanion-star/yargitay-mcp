"""Offline, agent-labelled diagnostic on three real CGK source texts.

Usage: python scripts/real_passage_eval.py --source /path/source.json \
       --model-cache /path/pinned-model-cache
Source format: [{"id": "bedesten:...", "metin": "full exact source text"}].
Full texts are intentionally not redistributed. Obtain them separately from the
listed official URLs. SHA-256 and exact character spans must match the gold file.
No legal-expert validation or general ranking-performance claim is made.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LIMIT = 20


def uniform_passages(text, _question, limit=LIMIT):
    """Exact old semantik._passages algorithm, with the same 20-passage cap."""
    size, stride = 680, 500
    last = max(0, len(text) - size)
    count = min(limit, 1 + (last + stride - 1) // stride)
    return [(last * i // max(1, count - 1),
             text[last * i // max(1, count - 1):last * i // max(1, count - 1) + size])
            for i in range(count)]


def current_rss_mib():
    """Current Linux process RSS, not parent/child or container aggregate."""
    try:
        for line in Path('/proc/self/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                return round(int(line.split()[1]) / 1024, 3)
    except OSError:
        pass
    return None


def peak_rss_mib():
    # This benchmark targets Linux (ru_maxrss is KiB there).
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 3)


def offline_similarity(model_cache):
    """Use production E5 inference but forbid any implicit model download."""
    for module in ('onnxruntime', 'tokenizers'):
        if importlib.util.find_spec(module) is None:
            raise ModuleNotFoundError(f'Offline inference dependency missing: {module}')
    import semantik
    cache = Path(model_cache or os.getenv('SEMANTIK_MODEL_CACHE',
                                         Path.home() / '.cache' / 'yargitay-mcp'))

    def local_asset(name):
        path = cache / semantik.REVISION / Path(name).name
        if not path.is_file():
            raise FileNotFoundError(f'Offline model asset missing: {path}')
        with path.open('rb') as file:
            if hashlib.file_digest(file, 'sha256').hexdigest() != semantik.FILES[name]:
                raise ValueError(f'Offline model checksum mismatch: {path}')
        return path

    for name in semantik.FILES:
        local_asset(name)
    semantik._asset = local_asset
    return semantik.similarities


def contained(passage, span):
    start, excerpt = passage
    return start <= span['start'] and span['end'] <= start + len(excerpt)


def worker(args):
    gold_bytes = Path(args.gold).read_bytes()
    gold = json.loads(gold_bytes)
    source = {row['id']: row['metin'] for row in json.loads(Path(args.source).read_text())}
    # Verify every annotation before loading the model or inspecting selection.
    for case in gold['cases']:
        text = source[case['document_id']]
        assert hashlib.sha256(text.encode()).hexdigest() == case['source_sha256'], case['id']
        assert len(text) == case['source_characters'], case['id']
        for span in case['acceptable_evidence_spans']:
            assert text[span['start']:span['end']] == span['quote'], case['id']
    from passage_selection import select_passages
    selector = uniform_passages if args.worker == 'baseline_uniform' else select_passages
    scorer = None
    semantic_status = 'skipped_by_request'
    if not args.skip_semantic:
        try:
            scorer = offline_similarity(args.model_cache)
            semantic_status = 'offline_pinned_e5'
        except (ImportError, OSError, ValueError) as exc:
            semantic_status = f'unavailable: {type(exc).__name__}: {exc}'
    rss_before = current_rss_mib()
    started = time.perf_counter()
    rows = []
    for index, case in enumerate(gold['cases']):
        text = source[case['document_id']]
        selected_at = time.perf_counter()
        passages = list(selector(text, case['question'], limit=LIMIT))
        selection_ms = (time.perf_counter() - selected_at) * 1000
        assert len(passages) <= LIMIT
        assert all(len(excerpt) <= 680 and text[start:start + len(excerpt)] == excerpt
                   for start, excerpt in passages)
        spans = case['acceptable_evidence_spans']
        found = [any(contained(p, span) for p in passages) for span in spans]
        row = {'id': case['id'], 'document_id': case['document_id'],
               'passages': len(passages), 'selected_characters': sum(len(p[1]) for p in passages),
               'gold_span_hits': sum(found), 'gold_span_count': len(spans),
               'any_gold_span_contained': any(found),
               'selection_ms': round(selection_ms, 3),
               'selected_offsets': [[start, start + len(excerpt)] for start, excerpt in passages]}
        if scorer is not None:
            scored_at = time.perf_counter()
            scores = scorer(case['question'], [p[1] for p in passages])
            row['e5_ms'] = round((time.perf_counter() - scored_at) * 1000, 3)
            row['e5_model_load_included'] = index == 0
            assert len(scores) == len(passages) and all(math.isfinite(s) for s in scores)
            best = max(range(len(scores)), key=lambda i: scores[i])
            start, excerpt = passages[best]
            row['e5_top1'] = {'start': start, 'end': start + len(excerpt),
                              'score': scores[best],
                              'contains_gold_span': any(contained(passages[best], span) for span in spans)}
        rows.append(row)
    result = {'method': args.worker, 'budget_per_document': LIMIT,
              'gold_sha256': hashlib.sha256(gold_bytes).hexdigest(),
              'semantic_status': semantic_status, 'cases': rows,
              'containment_recall': sum(r['any_gold_span_contained'] for r in rows) / len(rows),
              'exact_span_recall': sum(r['gold_span_hits'] for r in rows) / sum(r['gold_span_count'] for r in rows),
              'e5_top1_containment': (sum(r['e5_top1']['contains_gold_span'] for r in rows) / len(rows)
                                      if scorer is not None else None),
              'latency_ms': round((time.perf_counter() - started) * 1000, 3),
              'process_rss_before_mib': rss_before, 'process_rss_after_mib': current_rss_mib(),
              'process_peak_rss_mib': peak_rss_mib()}
    print(json.dumps(result, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--gold', default=str(ROOT / 'evaluation' / 'real_passage_gold.json'))
    parser.add_argument('--model-cache', help='Cache root containing the pinned revision directory.')
    parser.add_argument('--skip-semantic', action='store_true')
    parser.add_argument('--worker', choices=['baseline_uniform', 'query_aware'], help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args)
        return
    methods = []
    for method in ['baseline_uniform', 'query_aware']:
        command = [sys.executable, str(Path(__file__).resolve()), '--source', args.source,
                   '--gold', args.gold, '--worker', method]
        if args.model_cache:
            command += ['--model-cache', args.model_cache]
        if args.skip_semantic:
            command.append('--skip-semantic')
        completed = subprocess.run(command, check=True, text=True, capture_output=True)
        methods.append(json.loads(completed.stdout))
    print(json.dumps({
        'status': 'agent_assisted_not_expert_validated',
        'evaluation': 'three fixed question/document pairs; no cross-document ranking',
        'metric': 'A question succeeds if any selected passage fully contains any labelled source span; exact_span_recall separately counts all labelled occurrences.',
        'e5_metric': 'Best-scoring passage within its own document fully contains any gold span; no voice classifier is applied.',
        'timing': 'Separate fresh process per method; one sequential pass. First E5 call includes model loading, later calls are warm. Host caches/load and execution order may affect timing.',
        'limitations': [
            'Purposive n=3, six short agent-labelled spans; no expert review, hidden test set, confidence interval or generalization claim.',
            'Questions and labels fixed before this diagnostic run; selector design already existed. This is not an independent blind evaluation of selector development.',
            'Containment is an exact-coordinate proxy. Other valid unlabelled quotations or paraphrases count as misses; retrieval of quoted lower-court reasoning is not majority attribution.',
            'Both methods use at most 20 source passages of at most 680 characters, but their boundaries and total selected character counts differ.',
            'Full verified source texts must be supplied separately and match their SHA-256 hashes; this script makes no network requests.'
        ], 'methods': methods}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
