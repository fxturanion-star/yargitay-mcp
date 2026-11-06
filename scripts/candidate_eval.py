"""Kaynak çağrısı yapmadan, önceden belirli havuzlarda aday erişimini ölçer."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from semantik import _candidate_pool


def old(groups, count):
    found = {}
    for i in range(count):
        for group in groups:
            if i < len(group):
                found.setdefault(group[i]["id"], group[i])
    return list(found.values())[:count]


def groups(rows):
    return [[{"id":key} for key in row] for row in rows]


SCENARIOS = [
    ([['target','a','b'],['c','d','e'],['f','g','h']], 'target'),
    ([['a','b','c'],['target','d','e'],['f','g','h']], 'target'),
    ([['a','b','c'],['d','e','f'],['target','g','h']], 'target'),
    ([['a','target','b'],['c','target','d'],['e','target','f']], 'target'),
    ([['a','b','c','d','target','x'],['e','f','g','h','target','y'],['i','j','k']], 'target'),
    ([['a','b','c'],['d','e','f'],['g','target','h']], 'target'),
    ([['a','b','c'],['d','e','f'],['g','h','i']], 'target'),
    ([['target','a','b'],['target','c','d'],['target','e','f']], 'target'),
]


def main():
    hits = {"before":0,"after":0}
    for rows, target in SCENARIOS:
        previous = old(groups([row[:3] for row in rows]), 3)
        current = _candidate_pool(groups([row[:6] for row in rows]), 18)[:3]
        hits["before"] += target in {r["id"] for r in previous}
        hits["after"] += target in {r["id"] for r in current}
    print(json.dumps({"synthetic":True,"scenarios":len(SCENARIOS), "document_budget":3,
                      "source_query_budget":3, "candidate_recall":hits},ensure_ascii=False))

if __name__ == "__main__":
    main()
