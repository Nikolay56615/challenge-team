"""Пары совместных записей на курсы из локальной копии для пилота «похожие курсы».

Журнал `CourseUserBindings` читается только на чтение (URI
`mode=ro` и `PRAGMA query_only`) функцией `read_bindings` из `offline_courses.py`, с теми же фильтрами:
без удалённых записей, без пустых пользователя и курса, только с известным статусом. Для каждой
неупорядоченной пары курсов считаются слушатели, записанные на оба курса, для каждого курса — все его
слушатели, включая записанных только на него.

Файл пишется в формате `app/backend/app/catalog/pairs.py`: `{"version", "note", "pairs": [{"a", "b",
"together", "a_total", "b_total"}]}`. Коды курсов — `course:<Id>`, как у материалов источника `sqlite`;
`version` — версия каталога. В файл попадают все пары хотя бы с одним общим слушателем: порог поддержки
применяет приложение (`PAIRS_MIN_SUPPORT`), поэтому его можно менять без пересборки файла. Идентификаторов
пользователей в файле и в выводе нет.

После записи файл проверяется загрузкой каталога приложением, как при запуске с `CATALOG_PAIRS_PATH`:
печатается сводка `course_pairs` при порогах 5, 10 и 20. В консоль выводятся только агрегаты.

Запуск из корня проекта:
  python -X utf8 evaluation/build_pairs.py data/local/catalog.sqlite3 data/local/course-pairs.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from itertools import combinations
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import offline_courses  # noqa: E402
from app.catalog.loader import load_catalog  # noqa: E402
from app.config import Settings  # noqa: E402

THRESHOLDS = (5, 10, 20)
NOTE = (
    "Пары совместных записей на курсы по журналу CourseUserBindings локальной копии без удалённых записей. "
    "together — число слушателей обоих курсов, a_total и b_total — "
    "всех слушателей курса. Записаны все пары хотя бы с одним общим слушателем, порог поддержки применяет "
    "приложение (PAIRS_MIN_SUPPORT). Только коды курсов и счётчики, без идентификаторов пользователей. "
    "Файл построен скриптом evaluation/build_pairs.py."
)

Pair = tuple[str, str]


def count_pairs(users: Iterable[Iterable[str]]) -> tuple[Counter[Pair], Counter[str]]:
    """Совместные записи по неупорядоченным парам (a < b) и число слушателей каждого курса.

    `users` — курсы каждого пользователя; повторы курса у одного пользователя считаются один раз.
    """
    together: Counter[Pair] = Counter()
    totals: Counter[str] = Counter()
    for courses in users:
        unique = sorted(set(courses))
        totals.update(unique)
        together.update(combinations(unique, 2))
    return together, totals


def payload(together: Mapping[Pair, int], totals: Mapping[str, int], version: str, note: str) -> dict:
    """Объект файла пар в формате `app/catalog/pairs.py`: пары с together от 1, по кодам курсов."""
    pairs = [
        {"a": a, "b": b, "together": n, "a_total": totals[a], "b_total": totals[b]}
        for (a, b), n in sorted(together.items())
        if n > 0
    ]
    return {"version": version, "note": note, "pairs": pairs}


def dump(data: dict) -> str:
    """JSON с одной парой на строку, как `course-pairs.synthetic.json`."""
    rows = ",\n".join("    " + json.dumps(row, ensure_ascii=False) for row in data["pairs"])
    head = (
        f'{{\n  "version": {json.dumps(data["version"], ensure_ascii=False)},\n'
        f'  "note": {json.dumps(data["note"], ensure_ascii=False)},\n  "pairs": ['
    )
    return head + ("\n" + rows + "\n  " if rows else "") + "]\n}\n"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    db, out = Path(argv[1]), Path(argv[2])
    catalog = load_catalog(Settings(catalog_source="sqlite", catalog_path=db))
    courses = {mid for mid, m in catalog.materials.items() if m.format == "course"}
    by_user, read_stats = offline_courses.read_bindings(db)
    together, totals = count_pairs([b.course for b in bindings] for bindings in by_user.values())
    data = payload(together, totals, catalog.version, NOTE)
    out.write_text(dump(data), encoding="utf-8")

    outside = sorted({c for c in totals if c not in courses})
    print(f"Каталог: {catalog.source}, версия {catalog.version}; курсов {len(courses)}")
    print(
        f"Записи: строк {read_stats['rows']}, удалённых {read_stats['deleted']}, без пользователя или курса "
        f"{read_stats['no_user_or_course']}, с неизвестным статусом {read_stats['unknown_status']}"
    )
    multi = sum(1 for bindings in by_user.values() if len({b.course for b in bindings}) >= 2)
    print(
        f"Пользователей {len(by_user)}, из них с двумя и более курсами {multi}; курсов с записями {len(totals)}, "
        f"вне каталога {len(outside)}"
    )
    counts = ", ".join(f"от {t} — {sum(1 for n in together.values() if n >= t)}" for t in THRESHOLDS)
    print(f"Пар с общими слушателями {len(data['pairs'])}; с поддержкой {counts}")
    print(f"Файл записан: {out.name}, пар {len(data['pairs'])}\n")

    print("Проверка загрузкой каталога приложением (source=sqlite, CATALOG_PAIRS_PATH):")
    for threshold in THRESHOLDS:
        loaded = load_catalog(
            Settings(catalog_source="sqlite", catalog_path=db, catalog_pairs_path=out, pairs_min_support=threshold)
        )
        summary = loaded.coverage["course_pairs"]
        dropped = ", ".join(f"{k} {v}" for k, v in summary["dropped"].items())
        disabled = "да" if "co_enrollment" in loaded.disabled_features else "нет"
        print(
            f"- PAIRS_MIN_SUPPORT {threshold}: source {summary['source']}, пар {summary['pairs']}, курсов "
            f"{summary['courses']}; отброшено: {dropped}; total_conflicts {summary['total_conflicts']}; "
            f"co_enrollment отключён: {disabled}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
