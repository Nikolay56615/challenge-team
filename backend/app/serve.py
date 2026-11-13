"""Запуск сервиса: проверка окружения и uvicorn с пределами (docs/plan.md, 4.5; кандидаты W07 и W13).

Dockerfile вызывает модуль в exec-форме: `python -m app.serve --host 0.0.0.0 --port 8000`. Оболочки между
Docker и Python нет, процесс Python — PID 1, и SIGTERM от `docker stop` получает сам uvicorn.

До запуска uvicorn читаются все переменные из `config.py`. Регистр `LOG_LEVEL` не важен, uvicorn получает
тот же уровень, что и приложение. Неверное значение любой из этих переменных останавливает запуск с кодом 1
и сообщением, где названа переменная; uvicorn при этом не стартует.

Параметры uvicorn:
- `limit_concurrency` 64. Сверх предела uvicorn сразу отвечает 503 и не ставит запрос в очередь. Маршруты
  подбора синхронные и идут в пуле AnyIO из 40 потоков, так что запросы сверх 40 всё равно ждут поток.
  Даже если при 100 запросах в секунду каждый длится 0,5 с — порог p99 нагрузочного прогона W08, — по закону
  Литтла в работе одновременно 50 запросов, меньше предела. Браузер держит до 6 соединений на источник,
  предел вмещает 10 браузеров. Буферы запросов ограничены: 64 соединения × (16 КБ заголовков h11 + 64 КБ
  тела) — около 5 МБ.
  uvicorn считает и простаивающие соединения, вместе с соединением самого запроса: при 63 открытых
  соединениях следующий запрос получает 503. Соединение без запроса uvicorn сам не закрывает, поэтому в сети
  сервис ставится за обратный прокси с таймаутом заголовков. Ответ 503 сверх предела формирует uvicorn:
  text/plain, без заголовков безопасности и X-Request-Id.
- `timeout_keep_alive` 5 с: простаивающее соединение браузера закрывается и освобождает место под пределом.
- `timeout_graceful_shutdown` 10 с: после SIGTERM начатые запросы завершаются, а не завершённые за 10 с
  отменяются, и uvicorn пишет в журнал ошибку с трассировкой. `stop_grace_period` в compose.yaml — 15 с,
  после него Docker послал бы SIGKILL. Без Docker в Windows предел тоже нужен: цикл Proactor изредка
  не освобождает соединение, сброшенное клиентом, и без предела остановка ждала бы его без ограничения.
- `server_header` выключен: ответы без заголовка `Server: uvicorn`.
- `proxy_headers` выключены: X-Forwarded-For и X-Forwarded-Proto не меняют адрес клиента и схему запроса.

Без Docker модуль слушает 127.0.0.1, как и `uvicorn app.main:app`; порт задаёт ключ `--port`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from typing import Any

import uvicorn

from .config import load_settings

APP = "app.main:app"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
LIMIT_CONCURRENCY = 64
TIMEOUT_KEEP_ALIVE = 5
TIMEOUT_GRACEFUL_SHUTDOWN = 10
CONFIG_ERROR = 1


def uvicorn_options(
    env: Mapping[str, str] | None = None, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> dict[str, Any]:
    """Аргументы `uvicorn.run`; неверное окружение даёт ValueError с именем переменной."""
    settings = load_settings(env)
    return {
        "host": host,
        "port": port,
        "log_level": settings.log_level,
        "limit_concurrency": LIMIT_CONCURRENCY,
        "timeout_keep_alive": TIMEOUT_KEEP_ALIVE,
        "timeout_graceful_shutdown": TIMEOUT_GRACEFUL_SHUTDOWN,
        "server_header": False,
        "proxy_headers": False,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.serve", description="Запуск сервиса подбора с пределами uvicorn."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"адрес, по умолчанию {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"порт, по умолчанию {DEFAULT_PORT}")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        options = uvicorn_options(host=args.host, port=args.port)
    except ValueError as exc:
        print(f"Запуск остановлен: {exc}", file=sys.stderr)
        return CONFIG_ERROR
    uvicorn.run(APP, **options)
    return 0


if __name__ == "__main__":
    sys.exit(main())
