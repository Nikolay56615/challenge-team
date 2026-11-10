"""Гипотеза этапа 2 (протокол первого прогона, наблюдение 1): для задачи с темой добавлять в кандидаты
материалы других тем с тем же понятием признака, без вклада темы.

Скрипт не меняет приложение: вариант собирается из функций `ranking` поверх загруженного каталога и
сравнивается с текущей выдачей на профилях P01–P10. Понятия берутся как в политике для задач без темы —
`parsed.concepts`, конкретные слова признака. Для синтетического каталога выводятся коды материалов,
для копии — только агрегаты.

Запуск из корня проекта:
  python -X utf8 evaluation/signal_candidates.py synthetic
  python -X utf8 evaluation/signal_candidates.py sqlite data/local/catalog.sqlite3 data/local/catalog-signals.sqlite3
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.catalog.lexicon import parse_task  # noqa: E402
from app.catalog.loader import load_catalog  # noqa: E402
from app.config import Settings  # noqa: E402
from app.profiles.synthetic import load_profiles  # noqa: E402
from app.ranking import personal  # noqa: E402
from app.ranking.base import Context, HistoryIndex, Profile  # noqa: E402
from app.ranking.policy import eligible, recommend  # noqa: E402

LIMIT = 5


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in {"synthetic", "sqlite"}:
        print(__doc__)
        return 2
    if argv[1] == "synthetic":
        catalog = load_catalog(Settings())
        show_ids = True
    else:
        if len(argv) < 3:
            print(__doc__)
            return 2
        catalog = load_catalog(Settings(catalog_source="sqlite", catalog_path=Path(argv[2]),
                                        catalog_signals_path=Path(argv[3]) if len(argv) > 3 else None))
        show_ids = False
    print(f"Каталог: {catalog.source}, версия {catalog.version}, {catalog.size} материалов\n")
    header = "| Профиль | Понятия | Кандидатов сейчас | Добавлено | Изменилось позиций в пятёрке | Добавленных в пятёрке |"
    print(header + (" Пятёрка сейчас → вариант |" if show_ids else ""))
    print("| --- | --- | ---: | ---: | ---: | ---: |" + (" --- |" if show_ids else ""))
    disabled = frozenset(catalog.disabled_features)
    for pid, demo in load_profiles().items():
        history = demo.history if show_ids else ()  # история тестовых профилей ссылается на синтетические коды
        profile = Profile(task=demo.task, stage=demo.stage, experience=demo.experience, format_pref=demo.format_pref,
                          industry=demo.industry, history=history, limit=LIMIT)
        parsed = parse_task(profile.task)
        index = HistoryIndex.build(profile.history)
        pool = eligible(catalog, index)
        topics = parsed.topics
        if not topics or parsed.topics_from_signals or not parsed.concepts:
            print(f"| {pid} | {', '.join(parsed.concepts) or '—'} | — | — | не применимо | — |" + (" |" if show_ids else ""))
            continue
        current = recommend(catalog, profile, "personal")
        current_ids = [i.material.id for i in current.items]
        by_topic = [m for m in pool if set(m.topics) & set(topics)]
        wanted = set(parsed.concepts)
        added = [m for m in pool if m not in by_topic and wanted & {code for code, _ in m.signals}]
        covered = tuple(t for t in topics if any(t in m.topics for m in by_topic))
        ctx = Context(profile=profile, parsed=parsed, topics=covered, history=index, disabled=disabled,
                      catalog=catalog.materials)
        variant = [s.material.id for s in personal.rank(by_topic + added, ctx)][:LIMIT]
        changed = sum(1 for a, b in zip(current_ids, variant) if a != b) + abs(len(current_ids) - len(variant))
        added_ids = {m.id for m in added}
        entered = sum(1 for i in variant if i in added_ids)
        row = (f"| {pid} | {', '.join(parsed.concepts)} | {len(by_topic)} | {len(added)} | {changed} | {entered} |")
        if show_ids:
            row += f" {', '.join(current_ids)} → {', '.join(variant)} |"
        print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
