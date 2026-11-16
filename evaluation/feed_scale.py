"""Время построения ленты на каталоге до 100 000 материалов.

Запуск из корня проекта:
  python -X utf8 evaluation/feed_scale.py
Необязательные аргументы — размеры каталога, по умолчанию 1166, 10000 и 100000.

Вопрос. Лента оценивает каждый допустимый материал и берёт первые 50. Сколько это занимает, когда материалов
100 000, и нужен ли перед оценкой отдельный отбор кандидатов.

Вход синтетический. Каталог комплекта (166 вымышленных материалов) размножается до нужного размера: копия
получает новый код и случайную популярность, признаки содержания остаются от исходного материала, связи блока
«далее» у копий пустые. Пары совместных записей и клиенты берутся из комплекта без изменений. Доли форматов
те же, что в комплекте. Зерно 20261115.

Что измеряется, всё в одном процессе без сети и без API:
- индекс признаков содержания: строится один раз на каталог;
- `feed.rank(catalog, profile, limit=50)`: оценка всех допустимых материалов и отбор первых 50;
- `feed.build_feed(catalog, profile, limit=50)`: то же и фразы-свидетельства для 50 карточек.
На каталоге до LARGE материалов запросы идут по всем клиентам комплекта, на большем по каждому четвёртому;
у каждого клиента REPEATS повторов. В таблице медиана и наибольшее время. Выводятся только агрегаты.
"""

from __future__ import annotations

import random
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.catalog.loader import load_catalog, load_feed_catalog  # noqa: E402
from app.catalog.models import Catalog  # noqa: E402
from app.config import Settings  # noqa: E402
from app.profiles.clients import load_json_clients  # noqa: E402
from app.ranking import feed  # noqa: E402
from app.ranking.base import Profile  # noqa: E402

SEED = 20261115
SIZES = (1166, 10_000, 100_000)
LIMIT = 50
REPEATS = 2
LARGE = 20_000


def expand(base: Catalog, size: int) -> Catalog:
    """Каталог из `size` материалов: исходные и их копии с новым кодом и случайной популярностью."""
    rng = random.Random(SEED)
    originals = list(base.materials.values())
    materials = dict(base.materials)
    n = 0
    while len(materials) < size:
        source = originals[n % len(originals)]
        n += 1
        popularity = rng.random()
        # Своё название: фильтр допустимости оставляет один материал на пару «название и формат»
        materials[f"{source.id}-x{n}"] = replace(
            source, id=f"{source.id}-x{n}", title=f"{source.title}, выпуск {n}", popularity=popularity,
            popularity_raw=popularity, recommended_next=(),
        )
    return Catalog(
        materials=materials, source=base.source, version=f"{base.version}-x{size}",
        disabled_features=base.disabled_features, coverage=base.coverage, course_pairs=base.course_pairs,
    )


def timed(call) -> float:  # noqa: ANN001 - замыкание без аргументов
    start = time.perf_counter()
    call()
    return (time.perf_counter() - start) * 1000


def ms(value: float) -> str:
    return f"{value:.0f}".replace(".", ",") if value >= 10 else f"{value:.1f}".replace(".", ",")


def main(argv: list[str]) -> int:
    sizes = tuple(int(a) for a in argv) or SIZES
    settings = Settings()
    base = load_feed_catalog(settings, load_catalog(settings))
    clients = [Profile(history=client.history, limit=LIMIT) for client in load_json_clients().by_id.values()]
    print(f"Каталог комплекта: {base.size} материалов; клиентов: {len(clients)}; повторов на клиента: {REPEATS}")
    print()
    print("| Материалов | Клиентов | Оценено кандидатов, медиана | Индекс признаков, мс | Оценка и отбор 50: медиана, мс "
          "| наибольшее, мс | С фразами карточек: медиана, мс | наибольшее, мс | На кандидата, мкс |")
    print("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |", flush=True)
    for size in sizes:
        catalog = expand(base, size) if size > base.size else base
        profiles = clients if size <= LARGE else clients[::4]
        index = timed(lambda: feed._index(catalog))  # noqa: B023, SLF001 - индекс считается один раз на каталог
        pool = statistics.median(feed.rank(catalog, p, limit=LIMIT).pool for p in profiles)
        rank = [
            timed(lambda: feed.rank(catalog, p, limit=LIMIT))  # noqa: B023
            for p in profiles for _ in range(REPEATS)
        ]
        full = [
            timed(lambda: feed.build_feed(catalog, p, limit=LIMIT))  # noqa: B023
            for p in profiles for _ in range(REPEATS)
        ]
        median = statistics.median(rank)
        print(
            f"| {catalog.size} | {len(profiles)} | {pool:.0f} | {ms(index)} | {ms(median)} | {ms(max(rank))} "
            f"| {ms(statistics.median(full))} | {ms(max(full))} | {ms(median * 1000 / pool)} |",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
