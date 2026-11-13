"""Слепая разметка, калибровка и проверка глобального поиска."""

import argparse
import json
import random
from contextlib import ExitStack
from copy import copy
from collections import defaultdict
from dataclasses import replace
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory

from search_relevance import GROUPS, read_cases

from app.catalog.article_text import article_description
from app.catalog.global_search import DEFAULT_THRESHOLDS, SearchIndex, build, digest, fingerprint, read_policy
from app.catalog.sqlite_source import load_sqlite_catalog, search_cards
from app.ranking.base import Profile
from app.ranking.metrics import hit_at_k, ndcg_at_k
from app.ranking.policy import recommend
from import_alfa_backup import pseudonym, read_backup_rows


def rankings(catalog, cases):
    results = []
    for case in cases:
        outcome = recommend(catalog, Profile(task=case["task"], limit=30))
        ranked = [item.material.id for item in outcome.items] if outcome.status in ("weak", "strong") else []
        results.append((ranked, outcome.status))
    return results


def measures(cases, results):
    report = {}
    for group in (*GROUPS, "broad_and_paraphrase"):
        groups = {"broad", "paraphrase"} if group == "broad_and_paraphrase" else {group}
        rows = [(case["grades"], ranked, status) for case, (ranked, status) in zip(cases, results, strict=True)
                if case["group"] in groups]
        if not rows:
            continue
        ndcg = [score for grades, ranked, _ in rows if (score := ndcg_at_k(ranked, grades)) is not None]
        recalls = []
        for grades, ranked, _ in rows:
            relevant = {key for key, grade in grades.items() if grade >= 2}
            if relevant:
                recalls.append(len(relevant.intersection(ranked[:30])) / len(relevant))
        report[group] = {
            "queries": len(rows),
            "hit_at_3": sum(hit_at_k(ranked, grades) for grades, ranked, _ in rows) / len(rows),
            "ndcg_at_5": mean(ndcg) if ndcg else None,
            "recall_at_30": mean(recalls) if recalls else None,
            "strong": sum(status == "strong" for _, _, status in rows),
            "weak_with_cards": sum(status == "weak" and bool(ranked) for _, ranked, status in rows),
        }
    return report


def confidence_interval(cases, current, proposed):
    families = defaultdict(list)
    for case, (before, _), (after, _) in zip(cases, current, proposed, strict=True):
        if case["group"] in ("broad", "paraphrase"):
            grades = case["grades"]
            families[case["family"]].append(ndcg_at_k(after, grades) - ndcg_at_k(before, grades))
    clusters = list(families.values())
    randomizer = random.Random(1234)
    samples = sorted(mean(value for cluster in randomizer.choices(clusters, k=len(clusters)) for value in cluster)
                     for _ in range(2000))
    return [samples[50], samples[1949]]


def review_pool(cases, runs, cards, second):
    rows = []
    for i, case in enumerate(cases):
        keys = set() if second else set(case.get("manual", []))
        for results in runs.values():
            keys.update(results[i][0][:5 if second else 10])
        ordered = sorted(keys, key=lambda key: sha256(f"{case['task']}\0{key}".encode()).digest())
        rows.append({
            **{key: case[key] for key in ("task", "group", "split", "family")},
            "grades": dict.fromkeys(ordered),
            "cards": {key: cards[key].text for key in ordered},
        })
    return rows


def calibrate(catalog, cases, thresholds):
    index = catalog.search_index
    lexical, semantic = index._lexical, index._semantic

    @lru_cache(maxsize=None)
    def lex(terms, allowed):
        return lexical(dict(terms), allowed)

    @lru_cache(maxsize=None)
    def sem(query, allowed):
        return semantic(query, allowed)

    index._lexical = lambda terms, allowed: lex(tuple(terms.items()), frozenset(allowed))
    index._semantic = lambda query, allowed: sem(query, frozenset(allowed))
    try:
        grids = {
            "lexical": ([0.45, 0.55, 0.65, 0.75, 0.85, 1.0], [0.7, 0.8, 0.9, 0.95, 1.0]),
            "semantic": ([0.78, 0.82, 0.86, 0.9, 0.94, 1.0], [0.88, 0.92, 0.95, 0.98, 1.0]),
        }
        modes = ("lexical",) if index.mode == "lexical" else ("semantic",)
        for mode in modes:
            best = None
            for low in grids[mode][0]:
                for high in grids[mode][1]:
                    if low > high:
                        continue
                    thresholds[mode] = [low, high]
                    metrics = measures(cases, rankings(catalog, cases))
                    empty, quality = metrics["empty"], metrics["broad_and_paraphrase"]
                    if empty["strong"] > empty["queries"] * 0.10 or empty["weak_with_cards"] > empty["queries"] * 0.25:
                        continue
                    key = (quality["hit_at_3"], quality["ndcg_at_5"], -empty["strong"], -empty["weak_with_cards"])
                    if best is None or key > best[0]:
                        best = key, [low, high]
            if best is None:
                raise ValueError("Пороги не прошли ограничения на калибровке")
            thresholds[mode] = best[1]
        empty = measures(cases, rankings(catalog, cases))["empty"]
        if empty["strong"] > empty["queries"] * 0.10 or empty["weak_with_cards"] > empty["queries"] * 0.25:
            raise ValueError("Комбинация порогов не прошла ограничения на калибровке")
    finally:
        index._lexical, index._semantic = lexical, semantic


def write_new(path, data):
    with path.open("x", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2)


def expanded_cards(catalog, cards, backup):
    tables = {"Documents": "document", "Webinars": "webinar", "Podcasts": "podcast"}
    _, rows = read_backup_rows(backup.resolve(), lambda schema: {
        table: ("Id", "Description", "DescriptionTag", "NoIndex") for table in tables
    })
    descriptions = {}
    for table, fmt in tables.items():
        for ref, description, fallback, no_index in rows[table]:
            key = f"{fmt}:{pseudonym(ref)}"
            material = catalog.materials.get(key)
            if material and material.available and material.access == "open" and no_index is False:
                text = article_description(description) or article_description(fallback)
                if text:
                    descriptions[key] = text
    return [replace(card, description=descriptions[card.id]) if card.id in descriptions else card for card in cards]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("--signals", type=Path)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--pool", type=Path)
    parser.add_argument("--second-pool", type=Path)
    parser.add_argument("--second-review", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--calibrate", type=Path)
    parser.add_argument("--diagnostic", action="store_true")
    parser.add_argument("--extra-backup", type=Path, help="Локальная проверка дополнительных описаний на dev")
    args = parser.parse_args()
    legacy = load_sqlite_catalog(args.catalog, signals_path=args.signals)
    task = load_sqlite_catalog(args.catalog, signals_path=args.signals, relevance="task")
    cards = search_cards(args.catalog, legacy)
    card_map = {card.id: card for card in cards}
    cases = [case for case in read_cases(args.labels, legacy, pooling=bool(args.pool or args.second_pool))
             if case.get("split") == args.split]
    if not args.diagnostic and any(sum(case["group"] == g for case in cases) != 20 for g in GROUPS):
        parser.error("Для этого прогона нужны четыре группы по 20 запросов")
    thresholds = read_policy(args.policy, cards, args.index)["thresholds"] if args.policy else dict(DEFAULT_THRESHOLDS)
    catalogs = {"legacy": legacy, "task": task}
    lexical = SearchIndex(args.index, cards, "lexical", thresholds=thresholds)
    catalogs["lexical"] = replace(legacy, search_index=lexical)
    if args.model:
        hybrid = SearchIndex(args.index, cards, "hybrid", args.model, thresholds)
        semantic = copy(hybrid)
        semantic.mode = "semantic"
        catalogs.update(semantic=replace(legacy, search_index=semantic), hybrid=replace(legacy, search_index=hybrid))
    if args.calibrate:
        if args.split != "dev":
            parser.error("Для калибровки укажите dev")
        calibrate(catalogs["lexical"], cases, thresholds)
        if args.model:
            calibrate(catalogs["hybrid"], cases, thresholds)
        write_new(args.calibrate, {"catalog": fingerprint(cards), "index": digest(args.index / "manifest.json"),
                                   "thresholds": thresholds, "lexical_released": False})
    with ExitStack() as stack:
        if args.extra_backup:
            if args.split != "dev" or not args.diagnostic:
                parser.error("Дополнительные описания оцениваются на dev с --diagnostic")
            expanded = expanded_cards(legacy, cards, args.extra_backup)
            directory = Path(stack.enter_context(TemporaryDirectory()))
            build(directory, expanded, None)
            index = SearchIndex(directory, expanded, "lexical", thresholds=thresholds)
            catalogs["lexical_with_extra_descriptions"] = replace(legacy, search_index=index)
        runs = {name: rankings(catalog, cases) for name, catalog in catalogs.items()}
    if args.pool or args.second_pool:
        for path, second in ((args.pool, False), (args.second_pool, True)):
            if path:
                write_new(path, review_pool(cases, runs, card_map, second))
        print(json.dumps({"pooled_queries": len(cases)}))
        return
    reviewers = json.loads(args.second_review.read_text(encoding="utf-8-sig")) if args.second_review else []
    required = review_pool(cases, runs, card_map, True)
    checked = len(reviewers) == len(required) and bool(required) and all(
        a["task"] == b["task"] and a["grades"].keys() <= b["grades"].keys()
        and all(type(b["grades"][key]) is int and 0 <= b["grades"][key] <= 3 for key in a["grades"])
        for a, b in zip(required, reviewers)
    )
    disagreements = sum(
        sum(c["grades"].get(key) != b["grades"][key] for key in a["grades"])
        for c, a, b in zip(cases, required, reviewers)
    ) if checked else None
    ungraded = sum(len(set(row[0][:10]) - case["grades"].keys())
                   for results in runs.values() for case, row in zip(cases, results, strict=True))
    report = {name: measures(cases, result) for name, result in runs.items()}
    gates = {}
    group = "broad_and_paraphrase"
    reference = report["legacy"]
    for mode in ("lexical", "hybrid"):
        if mode not in report:
            continue
        candidate = report[mode]
        gain = {key: candidate[group][key] - reference[group][key] for key in (
            "ndcg_at_5", "hit_at_3", "recall_at_30"
        )}
        interval = confidence_interval(cases, runs["legacy"], runs[mode])
        gates[mode] = {
            **gain, "ndcg_ci95": interval,
            "passed": args.split == "test" and not args.diagnostic and checked and not disagreements
            and not ungraded and bool(args.policy)
            and gain["ndcg_at_5"] >= 0.10 and gain["hit_at_3"] >= 0.15 and gain["recall_at_30"] >= 0.15
            and interval[0] > 0 and candidate["exact"]["hit_at_3"] >= reference["exact"]["hit_at_3"]
            and candidate["empty"]["strong"] <= 2,
        }
    selected = "legacy"
    if gates["lexical"]["passed"]:
        selected = "lexical"
    if gates.get("hybrid", {}).get("passed") and (
        selected == "legacy" or report["hybrid"][group]["ndcg_at_5"] - report["lexical"][group]["ndcg_at_5"] >= 0.02
    ):
        selected = "hybrid"
    print(json.dumps({"results": report, "ungraded_top10": ungraded, "second_review_checked": checked,
                      "review_disagreements": disagreements, "quality_gates": gates, "quality_winner": selected},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
