from argparse import ArgumentParser
from collections import Counter, defaultdict
from pathlib import Path
from random import Random
from statistics import mean

import feed_eval as ev
from app.catalog.loader import load_catalog
from app.config import Settings
from app.ranking import feed
from app.ranking.base import Profile

parser = ArgumentParser(description="Сравнение смешанной ленты с редакционным сигналом.")
parser.add_argument("catalog", type=Path)
parser.add_argument("signals", type=Path)
args = parser.parse_args()
state = ev.o1.evaluate(args.catalog)
catalog = load_catalog(Settings(catalog_source="sqlite", catalog_path=args.catalog, catalog_signals_path=args.signals))
prepared = ev.parts(state, catalog)
print("Loaded materials:", catalog.size, "course cases:", len(state.results), flush=True)

groups = defaultdict(list)
allowed = {key for key, m in catalog.materials.items() if m.available}
formats = {"article", "document"}
for source in sorted(allowed):
    group = (set(catalog.materials[source].recommended_next) & allowed) | {source}
    if len(group) < 2:
        continue
    targets = {k for k in group if catalog.materials[k].format in formats}
    for anchor in group - {source}:
        groups[anchor].append(targets)

strength = {
    anchor: {target: n / len(blocks) for target, n in Counter(t for block in blocks for t in block).items()}
    for anchor, blocks in groups.items()
}
weights = (0, 0.5, 1, 2, 4)
results = {w: {} for w in weights}
with_signal = set()
folds = {}
for part in prepared:
    for result in part.results:
        case = result.case
        ranking = feed.rank(part.catalog, Profile(history=ev.pilot.history(case)))
        gains = defaultdict(float)
        for binding in case.inputs:
            for item, match in strength.get(binding.course, {}).items():
                gains[item] = max(gains[item], match)
        if any(gains.get(x.material.id, 0) > 0 for x in ranking.items):
            with_signal.add(case.user)
        folds[case.user] = part.fold
        for w in weights:
            first = sorted(
                ranking.items,
                key=lambda it: (
                    -round(it.score + round(w * gains.get(it.material.id, 0), 2), 2),
                    -it.material.popularity,
                    it.material.id,
                ),
            )[:10] if w else ranking.items[:10]
            results[w][case.user] = (
                any(it.material.id == case.target for it in first),
                sum(it.material.format == "course" for it in first),
                sum(it.material.format in formats for it in first),
            )

print("Cases with an applicable article/document signal:", len(with_signal), flush=True)
for label, users in [("all", list(folds)), ("confirmation", [u for u in folds if folds[u] in ev.CONFIRM_FOLDS])]:
    print(
        label, len(users),
        "cases. Columns: weight, hit@10, courses@10, articles_docs@10, delta_pp, 95% CI_pp, lost, gained",
    )
    rng = Random(47)
    for w in weights:
        current = results[w]
        diff = [int(current[u][0]) - int(results[0][u][0]) for u in users]
        sampled = sorted(mean(rng.choices(diff, k=len(users))) for _ in range(2000)) if w else [0] * 2000
        vals = [mean(current[u][i] for u in users) for i in range(3)]
        print(
            w, *[round(v, 4) for v in vals], round(mean(diff) * 100, 2),
            [round(sampled[50] * 100, 2), round(sampled[1949] * 100, 2)],
            diff.count(-1), diff.count(1), flush=True,
        )
