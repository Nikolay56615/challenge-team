"""Локальная оценка отбора и переранжирования на общем слепом пуле."""

import argparse
import json
from collections import defaultdict
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from statistics import mean
from types import SimpleNamespace

from hybrid_search import confidence_interval, measures, rankings, review_pool, write_new
from search_relevance import GROUPS, read_cases

from app.catalog.global_search import SearchIndex, _terms, digest, fingerprint, read_policy
from app.catalog.neural_rank import LocalModel
from app.catalog.reranked_search import RerankedIndex, corpus_cards, model_checksums
from app.catalog.sqlite_source import load_sqlite_catalog, search_cards
from app.catalog.lexicon import parse_task
from app.ranking.base import HistoryIndex
from app.ranking.metrics import hit_at_k, ndcg_at_k
from app.ranking.policy import eligible


def retrieve(index, catalog, cases):
    allowed = {item.id for item in eligible(catalog, HistoryIndex.build(()))}
    rows = []
    for case in cases:
        query = case["task"]
        parsed = parse_task(query)
        exact = catalog.text_index.match(query).titles
        gaps = parsed.gaps if not parsed.concepts else ()
        candidates, fragments, states = index.retrieve(query, allowed, exact, gaps)
        scores = index.score(query, candidates, fragments) if index.model and candidates else None
        rows.append((candidates, scores, states, exact))
    return rows


def render_retrieval(rows):
    return [(list(row[0]), "weak" if row[0] else "none") for row in rows]


def renderer(catalog, cases, rows):
    cached = {case["task"]: row for case, row in zip(cases, rows, strict=True)}
    index = RerankedIndex(None)

    def match(query, allowed, exact, gaps):
        _, scores, states, _ = cached[query]
        return index.hits(query, exact, scores or {}, {}, states)

    def render(low, high, protect):
        index.low, index.high = low, high
        proxy = SimpleNamespace(mode="reranked", match=match, protect_exact=protect)
        return rankings(replace(catalog, search_index=proxy), cases)

    return render


def calibrate(cases, render):
    best = None
    values = [0.05, 0.15, 0.25, 0.35, 0.50, 0.65, 0.80, 0.90, 0.95, 0.99, 0.999]
    for low in values:
        for high in (0.65, 0.75, 0.85, 0.90, 0.95, 0.99, 0.999):
            if high < low:
                continue
            for protect in (True, False):
                report = measures(cases, render(low, high, protect))
                empty = report["empty"]
                if empty["strong"] > empty["queries"] * 0.10 or empty["weak_with_cards"] > empty["queries"] * 0.25:
                    continue
                quality = report["broad_and_paraphrase"]
                key = (report["exact"]["hit_at_3"], quality["ndcg_at_5"], quality["hit_at_3"])
                if best is None or key > best[0]:
                    best = key, low, high, protect
    if best is None:
        raise ValueError("Пороговые значения не прошли калибровку")
    return best[1:]


def candidate_metrics(cases, pools):
    rows = defaultdict(list)
    for case, pool in zip(cases, pools, strict=True):
        grades = case["grades"]
        gold = {key for key, value in grades.items() if value >= 2}
        if not gold:
            continue
        metrics = {
            f"recall_at_{k}": len(set(pool[:k]) & gold) / len(gold) for k in (30, 50)
        }
        metrics["oracle_ndcg_at_5"] = ndcg_at_k(sorted(pool, key=lambda key: -grades.get(key, 0)), grades)
        rows[case["group"]].append(metrics)
        if case["group"] in ("broad", "paraphrase"):
            rows["broad_and_paraphrase"].append(metrics)
    return {group: {key: mean(row[key] for row in values) for key in values[0]} for group, values in rows.items()}


def release_gains(current, proposed, current_candidates, proposed_candidates, interval):
    group = "broad_and_paraphrase"
    gain = {
        "ndcg_at_5": proposed[group]["ndcg_at_5"] - current[group]["ndcg_at_5"],
        "hit_at_3": proposed[group]["hit_at_3"] - current[group]["hit_at_3"],
        "recall_at_50": proposed_candidates[group]["recall_at_50"] - current_candidates[group]["recall_at_50"],
    }
    passed = (
        gain["ndcg_at_5"] >= 0.10 and gain["hit_at_3"] >= 0.15 and gain["recall_at_50"] >= 0.15
        and interval[0] > 0 and proposed["exact"]["hit_at_3"] >= current["exact"]["hit_at_3"]
        and proposed["empty"]["strong"] <= 2 and proposed["empty"]["weak_with_cards"] <= 5
    )
    return gain, passed


def exact_baseline_candidates(catalog, index, cases, allowed):
    result = []
    for case in cases:
        task = case["task"]
        exact = catalog.text_index.match(task).titles
        hits = index.match(task, allowed, exact)
        result.append(sorted(hits, key=lambda key: (key not in exact, not hits[key].strong, -hits[key].score, key)))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("--signals", type=Path)
    parser.add_argument("--hybrid-index", type=Path, required=True)
    parser.add_argument("--hybrid-model", type=Path, required=True)
    parser.add_argument("--hybrid-policy", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--encoder", type=Path)
    parser.add_argument("--reranker", type=Path)
    parser.add_argument("--model", choices=("qwen", "bge"))
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--pool", type=Path)
    parser.add_argument("--second-pool", type=Path)
    parser.add_argument("--second-review", type=Path)
    parser.add_argument("--calibrate", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--budget", type=int, choices=(30, 50, 80))
    parser.add_argument("--reformulate", action="store_true")
    parser.add_argument("--case-limit", type=int, help="Размер диагностического прогона")
    parser.add_argument("--no-fragments", action="store_true", help="Оценить тот же корпус без открытых фрагментов")
    parser.add_argument("--models", nargs="+", metavar="KIND=PATH", help="Добавить модели к одному слепому пулу")
    parser.add_argument("--merge-pool", type=Path, action="append", default=[])
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    catalog = load_sqlite_catalog(args.catalog, signals_path=args.signals)
    base = search_cards(args.catalog, catalog)
    cases = [case for case in read_cases(args.labels, catalog, pooling=bool(args.pool or args.second_pool))
             if case.get("split") == args.split]
    if not args.diagnostic and any(sum(case["group"] == g for case in cases) != 20 for g in GROUPS):
        parser.error("Нужно четыре группы по 20 запросов")
    if args.case_limit:
        if not args.diagnostic or args.case_limit < 4:
            parser.error("Укажите не менее четырёх запросов и --diagnostic")
        grouped = [[case for case in cases if case["group"] == group] for group in GROUPS]
        cases = [case for batch in zip(*grouped) for case in batch][:args.case_limit]
    if not cases:
        parser.error("Выбранная часть пуста")
    thresholds = read_policy(args.hybrid_policy, base, args.hybrid_index)["thresholds"] if args.hybrid_policy else None
    hybrid = SearchIndex(args.hybrid_index, base, "hybrid", args.hybrid_model, thresholds)
    runs = {"legacy": rankings(catalog, cases), "hybrid": rankings(replace(catalog, search_index=hybrid), cases)}
    allowed = {item.id for item in eligible(catalog, HistoryIndex.build(()))}
    pools = {"hybrid_admitted": exact_baseline_candidates(catalog, hybrid, cases, allowed)}
    raw_hybrid = retrieve(RerankedIndex(hybrid, budget=50), catalog, cases)
    pools["hybrid"] = [list(row[0]) for row in raw_hybrid]
    cards = base
    index = hybrid
    config = {}
    fragments = None
    if args.index:
        config = json.loads((args.policy or args.index / "rerank.json").read_text(encoding="utf-8"))
        if (config["snapshot"] != digest(args.catalog) or config["catalog"] != fingerprint(base)
                or config["index"] != digest(args.index / "manifest.json")
                or config["descriptions"] != digest(args.index / "descriptions.json")):
            parser.error("Индекс относится к другому снимку каталога")
        cards = corpus_cards(base, args.index, catalog)
        index = SearchIndex(args.index, cards, "hybrid", args.encoder or args.hybrid_model)
        fragments = args.index / "passages.sqlite3" if config["passages"] else None
        if fragments and config["passages"] != digest(fragments):
            parser.error("Индекс фрагментов повреждён")
        if args.no_fragments:
            fragments = None
            config.update(passages=None, calibrated=False)
    reranker = None
    if args.calibrate and not args.reranker:
        parser.error("Для калибровки нужен --reranker")
    if args.models and (not args.index or not (args.pool or args.second_pool) or args.reranker):
        parser.error("--models используется с --index и сборкой слепого пула")
    if args.reranker:
        if not args.index:
            parser.error("Для модели нужен --index")
        kind = args.model or config["model"]
        if args.model:
            config.update(model=kind, weights=model_checksums(args.reranker, kind), calibrated=False)
        if config["weights"] != model_checksums(args.reranker, kind):
            parser.error("Политика относится к другим весам модели")
        reranker = LocalModel(args.reranker, kind)
    rows = retrieve(RerankedIndex(index, budget=80), catalog, cases)
    for budget in (30, 50, 80):
        results = [(dict(list(a.items())[:budget]), b, c, d) for a, b, c, d in rows]
        name = f"retrieval_{budget}"
        runs[name] = render_retrieval(results)
        pools[name] = [list(row[0]) for row in results]
    if fragments:
        rows = retrieve(RerankedIndex(index, passages=fragments, budget=80), catalog, cases)
        runs["passages"] = render_retrieval(rows)
        pools["passages"] = [list(row[0]) for row in rows]
    if reranker:
        if args.budget:
            config.update(budget=args.budget, calibrated=False)
        if args.reformulate:
            config.update(reformulate=True, calibrated=False)
        rows = retrieve(RerankedIndex(index, passages=fragments, model=reranker, budget=config["budget"],
                                      reformulate=config.get("reformulate", False)), catalog, cases)
        render = renderer(catalog, cases, rows)
        pools["reranked"] = [list(row[0]) for row in rows]
        low, high = config["thresholds"]
        protect = config["protect_exact"]
        runs["reranked_protected"] = render(low, high, True)
        runs["reranked_exact_bonus"] = render(low, high, False)
        if args.calibrate:
            if args.split != "dev" or args.pool or args.second_pool:
                parser.error("Для калибровки нужны оценки dev")
            if not args.diagnostic and any(
                (set(row[0]) - case["grades"].keys())
                for case, row in zip(cases, rows, strict=True)
            ):
                parser.error("Заполните оценки для всех кандидатов калибровки")
            low, high, protect = calibrate(cases, render)
            write_new(args.calibrate, {**config, "thresholds": [low, high], "protect_exact": protect, "calibrated": True})
        runs["reranked"] = render(low, high, protect)
    for spec in args.models or ():
        kind, separator, directory = spec.partition("=")
        if not separator or kind not in {"qwen", "bge"} or not directory:
            parser.error("Формат модели для слепого пула — qwen=путь или bge=путь")
        model = LocalModel(Path(directory), kind)
        expanded = RerankedIndex(index, passages=fragments, model=model, budget=args.budget or config["budget"])
        rows = retrieve(expanded, catalog, cases)
        render = renderer(catalog, cases, rows)
        runs[kind] = render(*config["thresholds"], config["protect_exact"])
        pools[kind] = [list(row[0]) for row in rows]
        del expanded, model
    if args.pool or args.second_pool:
        card_map = {card.id: card for card in cards}
        if fragments:
            source = RerankedIndex(index, passages=fragments)
            # Reviewers see matching evidence in a separate field, with no scores or method names.
            by_case = []
            allowed = set(card_map)
            for case in cases:
                found = source.fragments(dict.fromkeys(_terms(case["task"]), 1), allowed)
                by_case.append({key: " — ".join(part for part in section if part) for key, section in found.items()})
        else:
            by_case = [{} for _ in cases]
        if args.pool:
            packet = review_pool(cases, runs, card_map, False, depth=30, candidate_pools=pools,
                                 candidate_depth=80 if args.split == "dev" else 50)
            for path in args.merge_pool:
                previous = json.loads(path.read_text(encoding="utf-8-sig"))
                for row, extra in zip(packet, previous, strict=True):
                    if any(row[key] != extra[key] for key in ("task", "family", "split", "group")):
                        parser.error("Пакеты относятся к разным запросам")
                    for key in extra["grades"]:
                        if key not in card_map:
                            parser.error("Пакеты относятся к разным каталогам")
                        row["grades"].setdefault(key, None)
                        row["cards"].setdefault(key, card_map[key].text)
            for row in packet:
                keys = sorted(row["grades"], key=lambda key: sha256(f"{row['task']}\0{key}".encode()).digest())
                row["grades"] = dict.fromkeys(keys)
                row["cards"] = {key: row["cards"][key] for key in keys}
            for row, evidence in zip(packet, by_case, strict=True):
                row["passages"] = {key: evidence[key] for key in row["grades"] if key in evidence}
            write_new(args.pool, packet)
        if args.second_pool:
            packet = review_pool(cases, runs, card_map, True)
            for row, evidence in zip(packet, by_case, strict=True):
                row["passages"] = {key: evidence[key] for key in row["grades"] if key in evidence}
            write_new(args.second_pool, packet)
        print(json.dumps({"pooled_queries": len(cases)}))
        return
    report = {name: measures(cases, results) for name, results in runs.items()}
    for name, results in runs.items():
        for group, row in report[name].items():
            groups = ("broad", "paraphrase") if group == "broad_and_paraphrase" else (group,)
            row["hit_at_1"] = sum(hit_at_k(ranked, case["grades"], k=1)
                                  for case, (ranked, _) in zip(cases, results, strict=True)
                                  if case["group"] in groups) / row["queries"]
            row["none"] = sum(status == "none" for case, (_, status) in zip(cases, results, strict=True)
                              if case["group"] in groups)
    metrics = {name: candidate_metrics(cases, values) for name, values in pools.items()}
    needed = [{key for results in runs.values() for key in results[i][0][:5]} for i in range(len(cases))]
    ungraded = sum(len(({key for results in runs.values() for key in results[i][0][:30]}
                       | {key for values in pools.values() for key in values[i][:50]}) - case["grades"].keys())
                   for i, case in enumerate(cases))
    review = json.loads(args.second_review.read_text(encoding="utf-8-sig")) if args.second_review else []
    agreed = len(review) == len(cases) and all(
        row["task"] == case["task"] and all(key in row["grades"] and row["grades"][key] == case["grades"].get(key)
                                            for key in keys)
        for case, row, keys in zip(cases, review, needed, strict=True)
    )
    gates = None
    if "reranked" in report:
        current, proposed = report["hybrid"], report["reranked"]
        interval = confidence_interval(cases, runs["hybrid"], runs["reranked"])
        gain, passed = release_gains(current, proposed, metrics["hybrid"], metrics["reranked"], interval)
        gates = {**gain, "ndcg_ci95": interval, "passed": (
            args.split == "test" and config.get("calibrated") is True and not args.diagnostic and agreed and not ungraded
            and passed
        )}
    print(json.dumps({"displayed": report, "candidates": metrics, "ungraded_top30": ungraded,
                      "second_review_agreed": agreed, "quality_gates": gates}, indent=2))


if __name__ == "__main__":
    main()
