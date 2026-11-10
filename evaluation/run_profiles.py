"""Прогон тестовых профилей P01–P10 для протокола (PLAN.md, 6, шаги 8–9).

Синтетический каталог: порядок выдачи обоих методов, NDCG@5 и hit@3 по разметке
backend/tests/relevance.json.

Локальная копия (sqlite): только агрегаты — статус, число кандидатов, свойства выдачи из
PLAN.md 2.8 и число позиций пятёрки, изменившихся при отключении признаков из текстов.
Идентификаторы и названия материалов копии не выводятся.

Запуск из корня проекта:
  python -X utf8 evaluation/run_profiles.py synthetic
  python -X utf8 evaluation/run_profiles.py sqlite data/local/catalog.sqlite3 data/local/catalog-signals.sqlite3
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.catalog.loader import load_catalog  # noqa: E402
from app.config import Settings  # noqa: E402
from app.profiles.synthetic import load_profiles  # noqa: E402
from app.ranking.base import Profile  # noqa: E402
from app.ranking.metrics import hit_at_k, ndcg_at_k  # noqa: E402
from app.ranking.policy import recommend  # noqa: E402

RELEVANCE = BACKEND / "tests" / "relevance.json"


def as_profile(demo, limit: int = 5) -> Profile:
    return Profile(
        task=demo.task,
        stage=demo.stage,
        experience=demo.experience,
        format_pref=demo.format_pref,
        industry=demo.industry,
        history=demo.history,
        limit=limit,
    )


def fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}".replace(".", ",")


def synthetic_report() -> None:
    catalog = load_catalog(Settings())
    profiles = load_profiles()
    labels = json.loads(RELEVANCE.read_text(encoding="utf-8"))["labels"] if RELEVANCE.exists() else {}
    print(f"Каталог: {catalog.source}, версия {catalog.version}, {catalog.size} материалов\n")
    print("| Профиль | Статус | Персональный | Бейзлайн | NDCG@5 перс. | NDCG@5 бейзл. | hit@3 перс. | hit@3 бейзл. |")
    print("| --- | --- | --- | --- | ---: | ---: | --- | --- |")
    totals = {"personal": [], "baseline": []}
    for pid, demo in profiles.items():
        personal = recommend(catalog, as_profile(demo), "personal")
        baseline = recommend(catalog, as_profile(demo), "baseline")
        p_ids = [i.material.id for i in personal.items]
        b_ids = [i.material.id for i in baseline.items]
        grades = labels.get(pid, {})
        p_ndcg = ndcg_at_k(p_ids, grades) if grades else None
        b_ndcg = ndcg_at_k(b_ids, grades) if grades else None
        if p_ndcg is not None and b_ndcg is not None:
            totals["personal"].append(p_ndcg)
            totals["baseline"].append(b_ndcg)
        p_hit = "да" if grades and hit_at_k(p_ids, grades) else "нет"
        b_hit = "да" if grades and hit_at_k(b_ids, grades) else "нет"
        print(
            f"| {pid} | {personal.status} | {', '.join(p_ids)} | {', '.join(b_ids)} | {fmt(p_ndcg)} | {fmt(b_ndcg)} | "
            f"{p_hit} | {b_hit} |"
        )
    if totals["personal"]:
        mean_p = sum(totals["personal"]) / len(totals["personal"])
        mean_b = sum(totals["baseline"]) / len(totals["baseline"])
        print(f"\nСреднее NDCG@5 по {len(totals['personal'])} профилям с определённой метрикой: "
              f"персональный {fmt(mean_p)}, бейзлайн {fmt(mean_b)}")


def sqlite_report(db: Path, signals: Path | None) -> None:
    with_signals = load_catalog(Settings(catalog_source="sqlite", catalog_path=db, catalog_signals_path=signals))
    without = load_catalog(Settings(catalog_source="sqlite", catalog_path=db))
    profiles = load_profiles()
    print(f"Каталог: {with_signals.source}, версия {with_signals.version}, {with_signals.size} материалов")
    print(f"Отключённые признаки: с признаками из текстов — {', '.join(with_signals.disabled_features) or 'нет'}; "
          f"без них — {', '.join(without.disabled_features) or 'нет'}\n")
    print("| Профиль | Статус | Кандидатов | Форматы пятёрки | Открытых в тройке | Тема запроса в тройке | "
          "Позиций пятёрки изменилось без признаков |")
    print("| --- | --- | ---: | --- | ---: | ---: | ---: |")
    for pid, demo in profiles.items():
        # История тестовых профилей ссылается на синтетические коды и в копии не действует
        profile = Profile(task=demo.task, stage=demo.stage, experience=demo.experience, format_pref=demo.format_pref,
                          industry=demo.industry, limit=5)
        a = recommend(with_signals, profile, "personal")
        b = recommend(without, profile, "personal")
        formats = Counter(i.material.format for i in a.items)
        top3 = a.items[:3]
        open_top3 = sum(1 for i in top3 if not i.material.is_paid)
        topical = sum(1 for i in top3 if set(i.material.topics) & set(a.detected_topics)) if a.detected_topics else 0
        a_ids = [i.material.id for i in a.items]
        b_ids = [i.material.id for i in b.items]
        changed = sum(1 for x, y in zip(a_ids, b_ids) if x != y) + abs(len(a_ids) - len(b_ids))
        formats_text = ", ".join(f"{k} {v}" for k, v in sorted(formats.items())) or "—"
        print(f"| {pid} | {a.status} | {a.total_candidates} | {formats_text} | {open_top3} из {len(top3)} | "
              f"{topical} из {len(top3)} | {changed} |")
    print("\nПокрытие (агрегаты загрузчика):")
    print(json.dumps(with_signals.coverage, ensure_ascii=False, indent=2))


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in {"synthetic", "sqlite"}:
        print(__doc__)
        return 2
    if argv[1] == "synthetic":
        synthetic_report()
    else:
        if len(argv) < 3:
            print(__doc__)
            return 2
        sqlite_report(Path(argv[2]), Path(argv[3]) if len(argv) > 3 else None)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
