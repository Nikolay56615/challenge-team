"""Сравнение локального подбора с поиском по словам и без него. Выводятся агрегаты."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.catalog.sqlite_source import load_sqlite_catalog
from app.ranking.base import Profile
from app.ranking.metrics import hit_at_k, ndcg_at_k
from app.ranking.policy import recommend

GROUPS = ("exact", "broad", "empty")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("--signals", type=Path)
    args = parser.parse_args()
    catalog = load_sqlite_catalog(args.catalog, signals_path=args.signals)
    cases = json.loads(args.labels.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        parser.error("Разметка должна содержать непустой список запросов")
    for index, case in enumerate(cases, 1):
        if (
            not isinstance(case, dict) or case.get("group") not in GROUPS
            or not isinstance(case.get("task"), str) or not case["task"].strip()
            or not isinstance(case.get("grades"), dict)
        ):
            parser.error(f"Неверный формат запроса №{index}")
        grades = case["grades"]
        if bool(grades) == (case["group"] == "empty") or any(
            material_id not in catalog.materials or not catalog.materials[material_id].available
            or type(grade) is not int or not 1 <= grade <= 3
            for material_id, grade in grades.items()
        ):
            parser.error(f"Неверная разметка запроса №{index}")

    report = {}
    for name, variant in (("rules", replace(catalog, text_index=None)), ("text", catalog)):
        measurements = []
        for case in cases:
            outcome = recommend(variant, Profile(task=case["task"]))
            ranked = [item.material.id for item in outcome.items] if outcome.status in ("strong", "weak") else []
            grades = case["grades"]
            measurements.append((
                case["group"], hit_at_k(ranked, grades), ndcg_at_k(ranked, grades), outcome.status,
            ))
        report[name] = {}
        for group in ("all", *GROUPS):
            subset = [row for row in measurements if group == "all" or row[0] == group]
            ndcg = [value for _, _, value, _ in subset if value is not None]
            report[name][group] = {
                "queries": len(subset),
                "graded_queries": len(ndcg),
                "hit_at_3": sum(hit for _, hit, _, _ in subset),
                "mean_ndcg_at_5": round(mean(ndcg), 4) if ndcg else None,
                "false_strong": sum(category == "empty" and status == "strong" for category, _, _, status in subset),
            }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
