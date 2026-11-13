"""Оценка подбора на локальной разметке. В stdout выводятся только агрегаты."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from statistics import mean, quantiles
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "scripts")]

from app.catalog.models import Catalog
from app.catalog.sqlite_source import load_sqlite_catalog
from app.ranking.base import Profile
from app.ranking.metrics import hit_at_k, ndcg_at_k
from app.ranking.policy import recommend
from import_alfa_backup import ImportErrorDetail, read_article_paragraphs

GROUPS = ("exact", "broad", "paraphrase", "empty")


def variants(args: argparse.Namespace) -> dict[str, Catalog]:
    legacy = load_sqlite_catalog(args.catalog, signals_path=args.signals)
    if not (args.split or args.pool or args.backup):
        return {"rules": replace(legacy, text_index=None), "text": legacy}
    result = {"legacy": legacy}
    for variant in ("titles", "metadata"):
        result[variant] = load_sqlite_catalog(args.catalog, signals_path=args.signals, relevance=variant)
    if args.backup:
        paragraphs = read_article_paragraphs(args.backup, legacy)
        result["paragraphs"] = load_sqlite_catalog(
            args.catalog, signals_path=args.signals, relevance="metadata", passages=paragraphs
        )
    return result


def read_cases(path: Path, catalog: Catalog, *, pooling: bool) -> list[dict]:
    cases = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Разметка должна содержать непустой список запросов")
    families: dict[str, str] = {}
    for index, case in enumerate(cases, 1):
        if (
            not isinstance(case, dict) or case.get("group") not in GROUPS
            or not isinstance(case.get("task"), str) or not case["task"].strip()
        ):
            raise ValueError(f"Неверный формат запроса №{index}")
        if "split" in case or "family" in case:
            split, family = case.get("split"), case.get("family")
            if split not in ("dev", "test") or not isinstance(family, str) or not family:
                raise ValueError(f"Укажите split и family в запросе №{index}")
            if families.setdefault(family, split) != split:
                raise ValueError(f"Семейство запроса №{index} попало в обе части набора")
        labels = case.get("manual", []) if pooling else case.get("grades")
        if pooling:
            if not isinstance(labels, list):
                raise ValueError(f"Неверный список ручных кандидатов запроса №{index}")
        elif (
            not isinstance(labels, dict)
            or any(type(grade) is not int or not 0 <= grade <= 3 for grade in labels.values())
            or any(grade >= 2 for grade in labels.values()) == (case["group"] == "empty")
        ):
            raise ValueError(f"Неверная шкала или группа в разметке запроса №{index}")
        if any(not isinstance(key, str) or key not in catalog.materials or not catalog.materials[key].available
               for key in labels):
            raise ValueError(f"В разметке запроса №{index} есть недоступный материал")
    return cases


def collect(catalog: Catalog, task: str) -> tuple[list[str], set[str], str]:
    candidates: set[str] = set()
    outcome = recommend(
        catalog, Profile(task=task, limit=20), observe=lambda pool: candidates.update(m.id for m in pool)
    )
    ranked = [item.material.id for item in outcome.items] if outcome.status in ("strong", "weak") else []
    return ranked, candidates, outcome.status


def write_pool(path: Path, cases: list[dict], catalogs: dict[str, Catalog]) -> None:
    catalog = next(iter(catalogs.values()))
    review = []
    for case in cases:
        keys = set(case.get("manual", []))
        for variant in catalogs.values():
            keys.update(collect(variant, case["task"])[0])
        # Стабильный порядок без подсказок о методе, позиции и ручном отборе.
        ordered = sorted(keys, key=lambda key: sha256(f"{case['task']}\0{key}".encode()).digest())
        review.append({
            **{key: value for key, value in case.items() if key in {"task", "group", "split", "family"}},
            "grades": dict.fromkeys(ordered),
            "cards": {key: catalog.materials[key].title for key in ordered},
        })
    with path.open("x", encoding="utf-8") as output:
        json.dump(review, output, ensure_ascii=False, indent=2)


def evaluate(catalog: Catalog, cases: list[dict]) -> tuple[dict, set[int]]:
    rows = []
    for index, case in enumerate(cases, 1):
        ranked, candidates, status = collect(catalog, case["task"])
        grades = case["grades"]
        if "split" in case and not set(ranked) <= grades.keys():
            raise ValueError(f"В запросе №{index} есть карточки без оценки. Обновите пул разметки.")
        relevant = {key for key, grade in grades.items() if grade >= 2}
        rows.append((
            case["group"], hit_at_k(ranked, grades), ndcg_at_k(ranked, grades),
            len(relevant & candidates), len(relevant), status, len(candidates),
        ))
    report = {}
    for group in ("all", *GROUPS, "broad_and_paraphrase"):
        groups = ("broad", "paraphrase") if group == "broad_and_paraphrase" else (group,)
        subset = [row for row in rows if group == "all" or row[0] in groups]
        ndcg = [row[2] for row in subset if row[2] is not None]
        relevant = sum(row[4] for row in subset)
        found = sum(row[3] for row in subset)
        candidates = sum(row[6] for row in subset)
        report[group] = {
            "queries": len(subset),
            "graded_queries": len(ndcg),
            "hit_at_3": sum(row[1] for row in subset),
            "mean_ndcg_at_5": round(mean(ndcg), 6) if ndcg else None,
            "candidate_recall": round(found / relevant, 6) if relevant else None,
            "candidate_relevant_share": round(found / candidates, 6) if candidates else None,
            "false_strong": sum(row[0] == "empty" and row[5] == "strong" for row in subset),
        }
    return report, {i for i, row in enumerate(rows) if row[0] == "empty" and row[5] == "strong"}


def gates(report: dict, errors: dict[str, set[int]]) -> dict:
    def passes(candidate: str, reference: str, gain: float) -> dict:
        old, new = report[reference], report[candidate]
        groups = ("exact", "broad", "paraphrase", "empty")
        if not all(new[group]["queries"] for group in groups):
            return {"passed": False, "complete_groups": False}
        key = "broad_and_paraphrase"
        delta = round(new[key]["mean_ndcg_at_5"] - old[key]["mean_ndcg_at_5"], 6)
        new_errors = len(errors[candidate] - errors[reference])
        checks = {
            "ndcg_gain": delta >= gain,
            "hit_at_3_preserved": all(new[g]["hit_at_3"] >= old[g]["hit_at_3"] for g in groups[:-1]),
            "no_new_false_strong": not new_errors,
        }
        return {"passed": all(checks.values()), **checks, "ndcg_delta": delta, "new_false_strong": new_errors}

    result = {name: passes(name, "legacy", 0.05) for name in ("titles", "metadata")}
    available = [name for name in ("titles", "metadata") if result[name]["passed"]]
    best = max(available, key=lambda name: report[name]["broad_and_paraphrase"]["mean_ndcg_at_5"], default=None)
    result["best_card_variant"] = best
    if "paragraphs" in report:
        reference = best or max(("titles", "metadata"),
                                key=lambda name: report[name]["broad_and_paraphrase"]["mean_ndcg_at_5"] or 0)
        result["paragraphs"] = {"reference": reference, **passes("paragraphs", reference, 0.02)}
    return result


def benchmark(catalogs: dict[str, Catalog], cases: list[dict], repeats: int) -> dict[str, float]:
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    app = create_app(Settings(log_level="warning"))
    requests = [{"task": case["task"]} for case in cases]
    times = {name: [] for name in catalogs}
    with TestClient(app) as client:
        for iteration in range(repeats + 1):
            for name, catalog in catalogs.items():
                app.state.catalog = catalog
                for body in requests:
                    start = perf_counter()
                    client.post("/api/recommend", json=body).raise_for_status()
                    if iteration:
                        times[name].append(1000 * (perf_counter() - start))
    return {name: round(quantiles(ms, n=100, method="inclusive")[94] if len(ms) > 1 else ms[0], 3)
            for name, ms in times.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("--signals", type=Path)
    parser.add_argument("--backup", type=Path, help="Опциональный локальный эксперимент с абзацами")
    parser.add_argument("--pool", type=Path, help="Новый локальный файл для слепой разметки")
    parser.add_argument("--split", choices=("dev", "test"))
    parser.add_argument("--benchmark", type=int, default=0, metavar="ПОВТОРЫ")
    args = parser.parse_args()
    if args.benchmark < 0:
        parser.error("Число повторов должно быть неотрицательным")
    try:
        catalogs = variants(args)
        cases = read_cases(args.labels, next(iter(catalogs.values())), pooling=bool(args.pool))
        if args.split:
            cases = [case for case in cases if case.get("split") == args.split]
        if not cases:
            parser.error("Для выбранной части нет запросов")
        if args.pool:
            write_pool(args.pool, cases, catalogs)
            print(json.dumps({"pooled_queries": len(cases)}))
            return
    except (ValueError, OSError, ImportErrorDetail):
        parser.error("Не удалось прочитать локальную разметку или подготовить эксперимент. Проверьте пути и формат.")
    report, errors = {}, {}
    try:
        for name, catalog in catalogs.items():
            report[name], errors[name] = evaluate(catalog, cases)
    except ValueError as error:
        parser.error(str(error))
    if "legacy" in report:
        report["quality_gates"] = gates(report, errors)
    if args.benchmark:
        report["p95_http_ms"] = benchmark(catalogs, cases, args.benchmark)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
