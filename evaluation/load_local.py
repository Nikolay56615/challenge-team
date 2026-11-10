"""Предварительный нагрузочный прогон L1 на машине разработки без Docker.

План — docs/PLAN.md, 7.2, L1. Граница измерения — полный HTTP-запрос
`POST /api/recommend` с выдачей из пяти карточек. Форма нагрузки: прогрев из 10 запросов, один клиент
на заданное время, затем N одновременных клиентов на то же время. Смесь запросов по кругу: задача с
анкетой без истории (как P01), задача с историей (как P02), задача на две темы (как P05), пустая форма.
Выводятся число запросов, пропускная способность, p50, p95 и максимум задержки, доля ошибок сервиса и
таймаутов. Порог зафиксирован до прогона как допущение: при пяти клиентах p95 не выше 250 мс на
синтетическом каталоге и 500 мс на копии, ошибок сервиса 0.

Запуск из корня проекта при работающем сервисе:
  python -X utf8 evaluation/load_local.py http://127.0.0.1:8000 [клиентов=5] [секунд=30]
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request

TIMEOUT_S = 10
WARMUP = 10

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


def call(base: str, body: dict) -> tuple[float, int, dict | None]:
    """Задержка в миллисекундах, статус (0 — таймаут или сбой сети) и тело ответа."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base + "/api/recommend", data=data, headers={"Content-Type": "application/json"}, method="POST"
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


def phase(base: str, clients: int, seconds: float) -> dict:
    latencies: list[float] = []
    statuses: list[int] = []
    lock = threading.Lock()
    deadline = time.perf_counter() + seconds

    def worker(offset: int) -> None:
        i = offset
        while time.perf_counter() < deadline:
            latency, status, _ = call(base, BODIES[i % len(BODIES)])
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
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    base = argv[1].rstrip("/")
    clients = int(argv[2]) if len(argv) > 2 else 5
    seconds = float(argv[3]) if len(argv) > 3 else 30.0

    # Прогрев и проверка, что ожидаемая выдача на месте
    latency, status, payload = call(base, BODIES[0])
    if status != 200 or payload is None:
        print(f"Сервис не отвечает: статус {status}")
        return 1
    print(
        f"Проверка: статус {payload['status']}, карточек {len(payload['items'])}, каталог {payload['catalog']['source']} "
        f"{payload['catalog']['version']}, первая задержка {latency:.1f} мс"
    )
    for i in range(WARMUP - 1):
        call(base, BODIES[(i + 1) % len(BODIES)])

    print("| Клиентов | Секунд | Запросов | Запросов/с | p50, мс | p95, мс | max, мс | Ошибок | Таймаутов |")
    print("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for c in (1, clients):
        r = phase(base, c, seconds)
        print(
            f"| {r['clients']} | {r['seconds']} | {r['requests']} | {r['rps']} | {r['p50']} | {r['p95']} | {r['max']} | "
            f"{r['errors']} | {r['timeouts']} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
