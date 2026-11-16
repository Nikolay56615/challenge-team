"""Предварительный нагрузочный прогон L1 на машине разработки без Docker.

План — docs/plan.md, 7.2, L1 и guides/recommender-reliability.md. Граница измерения — полный HTTP-запрос
`POST /api/recommend` с выдачей из пяти карточек. Форма нагрузки: прогрев из 10 запросов, один клиент
на заданное время, затем N одновременных клиентов на то же время. Смесь запросов по кругу: задача с
анкетой без истории (как P01), задача с историей (как P02), задача на две темы (как P05), пустая форма.
Выводятся число запросов, пропускная способность, p50, p95 и максимум задержки, доля ошибок сервиса и
таймаутов. Порог зафиксирован до прогона как допущение: при пяти клиентах p95 не выше 250 мс на
синтетическом каталоге и 500 мс на копии, ошибок сервиса 0.

Режим приёмки `--slo` (кандидат W15; research/literature-web.md, 5.2) выводит ту же таблицу и затем
критерии со словами PASS или FAIL:
- SLO-1: p95 `POST /api/recommend` при пяти одновременных клиентах не выше 150 мс;
- SLO-2: доля ответов 5xx не выше 0,1 % от всех запросов обоих этапов. Таймаут и обрыв соединения считаются
  как 5xx: сервис не ответил;
- условия замера: ответов 4xx нет, иначе смесь запросов разошлась с контрактом; запросов не меньше 1000,
  иначе один отказ уже больше 0,1 % и SLO-2 по такой выборке не проверить.
Критерии заданы для пяти клиентов, другое число в этом режиме не принимается. SLO-2 здесь проверяется
только в закрытой модели; долю 5xx при постоянной частоте прибытий показывает evaluation/load_open.py.

Коды выхода: 0 — прогон выполнен, а с `--slo` все критерии и условия замера выполнены; 1 — с `--slo`
критерий или условие замера не выполнены; 2 — сервис не прошёл проверку или параметры неверны.

Открытая модель с постоянной частотой прибытий — evaluation/load_open.py (W08).

Режим `--feed` меряет той же формой нагрузки ленту по профилю, `POST /api/feed`. Смесь по кругу: восемь
клиентов из начала списка `GET /api/users` с лентой из 20 карточек, первый из них с лентой из 50 и новый
клиент без истории. Порог записан до первого прогона как допущение и повторяет L1: при пяти клиентах p95
не выше 250 мс на синтетическом каталоге и 500 мс на копии, ошибок сервиса 0. Критерии `--slo` заданы для
подбора по задаче, с `--feed` они не применяются. В вывод идут только агрегаты, коды клиентов не печатаются.

Запуск из корня проекта при работающем сервисе:
  python -X utf8 evaluation/load_local.py http://127.0.0.1:8000 [клиентов=5] [секунд=30]
  python -X utf8 evaluation/load_local.py http://127.0.0.1:8000 --slo [5] [секунд=30]
  python -X utf8 evaluation/load_local.py http://127.0.0.1:8000 --feed [клиентов=5] [секунд=30]
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

TIMEOUT_S = 10
WARMUP = 10
# Критерии приёмки (кандидат W15)
SLO_CLIENTS = 5
SLO_P95_MS = 150.0
SLO_5XX_SHARE = 0.001
SLO_MIN_REQUESTS = 1000

BODIES = [
    {"task": "Хочу начать продвигать свою кофейню, с чего начать?", "stage": "start", "experience": "none",
     "industry": "horeca", "history": []},
    {"task": "Как настроить рекламу, чтобы она окупалась", "stage": "growth", "experience": "some",
     "format_pref": "course", "history": [
         {"material_id": "M01", "event": "view", "seq": 1},
         {"material_id": "M03", "event": "complete", "seq": 2},
         {"material_id": "M07", "event": "view", "seq": 3},
     ]},
    {"task": "Хочу больше клиентов"},
    {},
]


FEED_CLIENTS = 8


def feed_bodies(base: str) -> list[dict]:
    """Смесь запросов ленты: клиенты из начала списка, лента из 50 карточек и новый клиент без истории."""
    with urllib.request.urlopen(f"{base}/api/users?limit={FEED_CLIENTS}", timeout=TIMEOUT_S) as response:
        users = json.loads(response.read().decode("utf-8"))["users"]
    bodies: list[dict] = [{"user_id": user["id"]} for user in users]
    if users:
        bodies.append({"user_id": users[0]["id"], "limit": 50})
    return [*bodies, {"history": []}]


def call(base: str, body: dict, endpoint: str = "/api/recommend") -> tuple[float, int, dict | None]:
    """Задержка в миллисекундах, статус (0 — таймаут или сбой сети) и тело ответа."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base + endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return (time.perf_counter() - started) * 1000, response.status, payload
    except urllib.error.HTTPError as exc:
        exc.read()
        return (time.perf_counter() - started) * 1000, exc.code, None
    except (urllib.error.URLError, TimeoutError, OSError):
        return (time.perf_counter() - started) * 1000, 0, None


def phase(base: str, clients: int, seconds: float, bodies: list[dict], endpoint: str) -> dict:
    latencies: list[float] = []
    statuses: list[int] = []
    lock = threading.Lock()
    deadline = time.perf_counter() + seconds

    def worker(offset: int) -> None:
        i = offset
        while time.perf_counter() < deadline:
            latency, status, _ = call(base, bodies[i % len(bodies)], endpoint)
            with lock:
                latencies.append(latency)
                statuses.append(status)
            i += 1

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(clients)]
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - started
    ordered = sorted(latencies)
    n = len(ordered)

    def pct(p: float) -> float:
        return ordered[min(n - 1, int(round(p * (n - 1))))] if n else float("nan")

    return {
        "clients": clients,
        "seconds": round(elapsed, 1),
        "requests": n,
        "rps": round(n / elapsed, 1) if elapsed else 0.0,
        "p50": round(pct(0.5), 1),
        "p95": round(pct(0.95), 1),
        "max": round(ordered[-1], 1) if n else float("nan"),
        "errors": sum(1 for s in statuses if s not in (0, 200)),
        "timeouts": sum(1 for s in statuses if s == 0),
        "server_errors": sum(1 for s in statuses if 500 <= s < 600),
        "client_errors": sum(1 for s in statuses if 400 <= s < 500),
    }


def slo_verdict(results: list[dict[str, Any]]) -> int:
    """Критерии W15 по этапам прогона: PASS или FAIL на строку, код выхода 1 при любом FAIL."""
    loaded = results[-1]
    total = sum(r["requests"] for r in results)
    failed = sum(r["server_errors"] + r["timeouts"] for r in results)
    client = sum(r["client_errors"] for r in results)
    share = failed / total if total else 1.0
    checks = [
        (
            loaded["requests"] > 0 and loaded["p95"] <= SLO_P95_MS,
            f"SLO-1: p95 POST /api/recommend при {loaded['clients']} клиентах ≤ {SLO_P95_MS:g} мс",
            f"{loaded['p95']} мс по {loaded['requests']} запросам",
        ),
        (
            total > 0 and share <= SLO_5XX_SHARE,
            f"SLO-2: доля 5xx, таймаутов и обрывов ≤ {SLO_5XX_SHARE * 100:g} %",
            f"{share * 100:.3f} %, {failed} из {total}",
        ),
        (client == 0, "Условие замера: ответов 4xx нет", f"{client} из {total}"),
        (
            total >= SLO_MIN_REQUESTS,
            (
                f"Условие замера: запросов не меньше {SLO_MIN_REQUESTS}, "
                f"иначе один отказ уже больше {SLO_5XX_SHARE * 100:g} %"
            ),
            f"{total}",
        ),
    ]
    print()
    print("Критерии приёмки SLO (кандидат W15):")
    for ok, name, observed in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {observed}")
    passed = all(ok for ok, _, _ in checks)
    print("Итог: " + ("PASS" if passed else "FAIL"))
    return 0 if passed else 1


def main(argv: list[str]) -> int:
    positional = [a for a in argv[1:] if not a.startswith("--")]
    flags = [a for a in argv[1:] if a.startswith("--")]
    if not positional or any(f not in ("--slo", "--feed") for f in flags) or len(flags) > 1:
        print(__doc__)
        return 2
    slo = "--slo" in flags
    feed = "--feed" in flags
    base = positional[0].rstrip("/")
    try:
        clients = int(positional[1]) if len(positional) > 1 else 5
        seconds = float(positional[2]) if len(positional) > 2 else 30.0
    except ValueError:
        clients, seconds = 0, 0.0
    if len(positional) > 3 or not 1 <= clients <= 256 or not 0 < seconds <= 3600:
        print(__doc__)
        print("Ошибка параметров: клиентов — целое от 1 до 256, секунд — число больше 0 и не больше 3600")
        return 2
    if slo and clients != SLO_CLIENTS:
        print(f"Критерии --slo заданы для {SLO_CLIENTS} клиентов, получено {clients}")
        return 2

    endpoint = "/api/feed" if feed else "/api/recommend"
    try:
        bodies = feed_bodies(base) if feed else BODIES
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError):
        print("Список клиентов недоступен: для --feed нужен сервис с демо-режимом")
        return 2

    # Прогрев и проверка, что ожидаемая выдача на месте
    latency, status, payload = call(base, bodies[0], endpoint)
    if status != 200 or payload is None:
        print(f"Сервис не отвечает: статус {status}")
        return 2
    print(
        f"Проверка {endpoint}: статус {payload['status']}, карточек {len(payload['items'])}, "
        f"каталог {payload['catalog']['source']} {payload['catalog']['version']}, первая задержка {latency:.1f} мс"
    )
    for i in range(WARMUP - 1):
        call(base, bodies[(i + 1) % len(bodies)], endpoint)

    print("| Клиентов | Секунд | Запросов | Запросов/с | p50, мс | p95, мс | max, мс | Ошибок | Таймаутов |")
    print("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    results: list[dict[str, Any]] = []
    for c in (1, clients):
        r = phase(base, c, seconds, bodies, endpoint)
        results.append(r)
        print(
            f"| {r['clients']} | {r['seconds']} | {r['requests']} | {r['rps']} | {r['p50']} | {r['p95']} | {r['max']} | "
            f"{r['errors']} | {r['timeouts']} |"
        )
    return slo_verdict(results) if slo else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
