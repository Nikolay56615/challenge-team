"""Нагрузочный прогон в открытой модели с постоянной частотой прибытий.

В закрытой модели `load_local.py` клиент отправляет следующий запрос только после ответа на предыдущий.
Замедление сервиса само снижает нагрузку и прячет хвост задержек — это coordinated omission
(research/literature-web.md, 5.6). Здесь запросы уходят по расписанию независимо от ответов, а задержка
считается от запланированного момента отправки. Если генератор не успел отправить запрос вовремя или ждал
свободный поток, это ожидание тоже входит в задержку.

Форма нагрузки: проверочный запрос каждого тела, прогрев на частоте первой ступени (в отчёт не входит),
затем ступени с постоянной частотой, по умолчанию 20 → 50 → 100 запросов в секунду по 60 с без пауз.
Расписание всего прогона строится заранее. Запрос относится к ступени, на которую пришёлся его
запланированный момент.

Тела `POST /api/recommend` — анкеты и история тестовых профилей по кругу. Список берётся из
`GET /api/profiles` запущенного сервиса, без демо-режима — из `app/backend/data/profiles.synthetic.json`.
Пустая форма входит как профиль P03. На каталоге не из синтетики идентификаторы истории заменяются
материалами из выдачи сервиса тому же профилю без истории: так ветка истории работает и на копии.
Идентификаторы остаются в памяти и не выводятся.

Ошибка — таймаут, обрыв или отказ в соединении, ответ не 2xx, включая 503 сверх предела uvicorn. Пороги
на каждой ступени: p95 < 200 мс, p99 < 500 мс, ошибок < 1 % и ни одного запроса, который ждал свободный
поток генератора: это аналог `dropped_iterations == 0` в k6. Справочно по каждой ступени выводится SLO-2
из W15: доля 5xx, таймаутов и обрывов не выше 0,1 %; на код выхода она не влияет.

Условие остановки: если на ступени генератор исчерпал потоки или больше половины запросов, завершённых
к её концу, закончились ошибкой, следующие ступени не выполняются, а итог — FAIL. Код выхода 1, если порог
не выполнен или прогон остановлен; 2 — сервис не прошёл проверку или параметры неверны.

Закон Литтла L = λ·W (research/literature-web.md, 5.7): среднее число запросов в системе равно частоте,
умноженной на среднюю задержку. «В системе» — запросы, чей запланированный момент наступил, а ответа ещё
нет; счёт идёт по расписанию, поэтому включает и опоздание генератора. Отчёт сравнивает расчёт с замером
и с пределами сервиса из app/backend/app/serve.py: `limit_concurrency` 64 и пул AnyIO из 40 потоков для
синхронных маршрутов. С ключом `--pid` добавляются процессорное время и рабочий набор процесса сервиса
на этой же машине; без него предел процессора не оценивается.

Соединения генератор держит открытыми и переиспользует, как браузер. Соединение без запроса закрывается
через 4–4,5 с, раньше, чем это сделает сервис через `timeout_keep_alive` 5 с. Если сервис всё же закрыл
простаивающее соединение, запрос один раз повторяется на новом; такие повторы считаются отдельно.

Выводятся только агрегаты: число запросов, доли, процентили, оценки ёмкости. Только стандартная
библиотека Python 3.12 и новее.
"""

from __future__ import annotations

import argparse
import ctypes
import http.client
import json
import math
import os
import random
import re
import sys
import threading
import time
import urllib.parse
from array import array
from bisect import bisect_right
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

# Пределы сервиса: app/backend/app/serve.py; пул потоков AnyIO по умолчанию — 40
LIMIT_CONCURRENCY = 64
ANYIO_THREADS = 40
# Пороги кандидата W08 (research/literature-web.md, 5.6)
P95_MS = 200.0
P99_MS = 500.0
MAX_ERROR_SHARE = 0.01
# SLO-2 кандидата W15 (research/literature-web.md, 5.2), здесь справочно
SLO2_SHARE = 0.001
# Условие остановки: доля ошибок среди запросов ступени, завершённых к её концу
STOP_ERROR_SHARE = 0.5
# Правило для предела соединений: частота × p99 плюс 30 % (research/literature-web.md, 5.7)
LIMIT_MARGIN = 1.3
# Отставание отправки от расписания, при котором замер искажает сам генератор
LAG_WARN_MS = 10.0
# Простаивающее соединение закрывается раньше timeout_keep_alive сервиса (5 с)
IDLE_CLOSE_S = 4.0
SAMPLE_EVERY_S = 0.02
PROCESS_EVERY = 25  # замер процесса сервиса и очистка пула — каждые 25 отсчётов, то есть раз в 0,5 с
MAX_PLANNED = 2_000_000  # запросов в расписании: смещения занимают 8 байт на запрос
PROFILES_FILE = Path(__file__).resolve().parent.parent / "app" / "backend" / "data" / "profiles.synthetic.json"
BODY_FIELDS = ("task", "stage", "experience", "format_pref", "industry")
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}
# Исход запроса без HTTP-статуса
TIMEOUT = -1
NETWORK = 0
REFUSED = -2  # отказ в соединении: очередь подключений сервиса переполнена или он не слушает порт

Json = dict[str, Any]


class CheckError(Exception):
    """Сервис не прошёл проверку перед прогоном."""


@dataclass(frozen=True)
class Target:
    host: str
    port: int
    prefix: str

    @property
    def recommend(self) -> str:
        return self.prefix + "/api/recommend"


@dataclass(frozen=True)
class Stage:
    rate: float
    seconds: float
    warmup: bool = False

    @property
    def name(self) -> str:
        return "прогрев" if self.warmup else f"{self.rate:g}/с"


def parse_url(url: str) -> Target:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "http" or not parts.hostname:
        raise ValueError("нужен адрес вида http://хост:порт")
    return Target(parts.hostname, parts.port or 80, parts.path.rstrip("/"))


def parse_stages(text: str, default_seconds: float) -> list[Stage]:
    """«20,50:30,100» — частоты в запросах в секунду, после двоеточия — своя длительность ступени в секундах."""
    stages = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        rate_text, _, seconds_text = part.partition(":")
        try:
            rate = float(rate_text)
            seconds = float(seconds_text) if seconds_text else default_seconds
        except ValueError:
            raise ValueError(f"ступень «{part}»: нужны числа, например 50 или 50:60") from None
        if not (0 < rate <= 10_000 and 0 < seconds <= 3_600):
            raise ValueError(
                f"ступень «{part}»: частота больше 0 и не больше 10 000 в секунду, "
                "длительность больше 0 и не больше 3 600 с"
            )
        stages.append(Stage(rate, seconds))
    if not stages:
        raise ValueError("нет ни одной ступени")
    return stages


def parse_limits(text: str) -> list[int]:
    try:
        limits = [int(x) for x in text.split(",") if x.strip()]
    except ValueError:
        raise ValueError("размер выдачи — целые числа через запятую, например 5 или 5,10") from None
    if not limits or any(not 1 <= x <= 10 for x in limits):
        raise ValueError("размер выдачи — от 1 до 10")
    return limits


def build_schedule(plan: list[Stage], poisson: bool, seed: int) -> tuple[array[float], list[tuple[int, int]]]:
    """Смещения запланированных моментов от начала прогона в секундах и диапазон индексов каждой ступени."""
    rng = random.Random(seed)
    offsets: array[float] = array("d")
    spans = []
    base = 0.0
    for stage in plan:
        first = len(offsets)
        if poisson:
            moment = 0.0
            while moment < stage.seconds:
                offsets.append(base + moment)
                moment += rng.expovariate(stage.rate)
        else:
            i = 0
            while i / stage.rate < stage.seconds:
                offsets.append(base + i / stage.rate)
                i += 1
        spans.append((first, len(offsets)))
        base += stage.seconds
    return offsets, spans


def time_mean(points: list[tuple[float, int]]) -> float:
    """Среднее по времени методом трапеций: замеры, отложенные паузой или борьбой за GIL, весят по интервалу."""
    if len(points) < 2:
        return float(points[0][1]) if points else math.nan
    area = sum((t1 - t0) * (v0 + v1) / 2 for (t0, v0), (t1, v1) in pairwise(points))
    return area / (points[-1][0] - points[0][0])


def percentile(ordered: list[float], p: float) -> float:
    """Процентиль по ближайшему рангу, как в load_local.py."""
    n = len(ordered)
    return ordered[min(n - 1, round(p * (n - 1)))] if n else math.nan


def fmt(value: float | None, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    return f"{value:.{digits}f}"


# --- Процесс сервиса -------------------------------------------------------------------------------------


class ProcessProbe:
    """Процессорное время и рабочий набор процесса сервиса на этой машине, без psutil: Windows и Linux."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        if sys.platform == "win32":
            from ctypes import wintypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            k32.GetProcessTimes.restype = wintypes.BOOL
            k32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(ctypes.c_ulonglong),) * 4
            k32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
            k32.K32GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD)
            query_limited, vm_read = 0x1000, 0x0010
            handle = k32.OpenProcess(query_limited | vm_read, False, pid) or k32.OpenProcess(query_limited, False, pid)
            if not handle:
                raise OSError(f"процесс {pid} недоступен, код {ctypes.get_last_error()}")
            self._k32, self._handle = k32, handle
        elif not Path(f"/proc/{pid}/stat").exists():
            raise OSError(f"процесс {pid} не найден или замер не поддерживается: нужны Windows или Linux")
        self.sample()

    def sample(self) -> tuple[float, int]:
        """Процессорное время в секундах (пользователь и ядро) и рабочий набор в байтах."""
        if sys.platform == "win32":
            times = [ctypes.c_ulonglong() for _ in range(4)]
            if not self._k32.GetProcessTimes(self._handle, *[ctypes.byref(t) for t in times]):
                raise OSError(f"процесс {self.pid}: GetProcessTimes, код {ctypes.get_last_error()}")
            counters = _MemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            if not self._k32.K32GetProcessMemoryInfo(self._handle, ctypes.byref(counters), counters.cb):
                raise OSError(f"процесс {self.pid}: GetProcessMemoryInfo, код {ctypes.get_last_error()}")
            # FILETIME — сотни наносекунд
            return (times[2].value + times[3].value) / 1e7, int(counters.WorkingSetSize)
        stat = Path(f"/proc/{self.pid}/stat").read_text()
        fields = stat[stat.rindex(")") + 2 :].split()
        cpu = (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
        rss = 0
        for line in Path(f"/proc/{self.pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1]) * 1024
        return cpu, rss


class _MemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


# --- HTTP ------------------------------------------------------------------------------------------------


class _Connection(http.client.HTTPConnection):
    """Соединение, которое сообщает пулу о каждом новом TCP-подключении, в том числе об автоматическом."""

    on_connect: Any = None

    def connect(self) -> None:
        super().connect()
        if self.on_connect is not None:
            self.on_connect()


class Pool:
    """Соединения с повторным использованием: последнее отпущенное берётся первым, простаивающие закрываются.

    Очередь простаивающих упорядочена по времени возврата: старые лежат с начала. Старше IDLE_CLOSE_S
    закрываются и при выдаче соединения, и при очистке раз в 0,5 с из потока замеров.
    """

    def __init__(self, target: Target, timeout: float) -> None:
        self.target, self.timeout = target, timeout
        self._idle: deque[tuple[_Connection, float]] = deque()
        self._lock = threading.Lock()
        self.alive = 0  # соединений у генератора: в работе и в простое
        self.connects = 0  # установлено TCP-соединений

    def _count_connect(self) -> None:
        with self._lock:
            self.connects += 1

    def _take_stale(self, now: float) -> list[_Connection]:
        """Под блокировкой: снять с начала очереди соединения старше IDLE_CLOSE_S."""
        stale = []
        while self._idle and now - self._idle[0][1] >= IDLE_CLOSE_S:
            stale.append(self._idle.popleft()[0])
            self.alive -= 1
        return stale

    def sweep(self) -> None:
        with self._lock:
            stale = self._take_stale(time.perf_counter())
        for conn in stale:
            conn.close()

    def acquire(self) -> tuple[_Connection, bool]:
        """Соединение и признак повторного использования."""
        found: _Connection | None = None
        with self._lock:
            stale = self._take_stale(time.perf_counter())
            while self._idle:
                conn, _ = self._idle.pop()
                if conn.sock is not None:
                    found = conn
                    break
                stale.append(conn)
                self.alive -= 1
            if found is None:
                self.alive += 1
        for conn in stale:
            conn.close()
        if found is not None:
            return found, True
        conn = _Connection(self.target.host, self.target.port, timeout=self.timeout)
        conn.on_connect = self._count_connect
        return conn, False

    def release(self, conn: _Connection, healthy: bool) -> None:
        # После ответа с Connection: close, например 503 сверх предела, http.client уже закрыл сокет
        if healthy and conn.sock is not None:
            with self._lock:
                self._idle.append((conn, time.perf_counter()))
            return
        conn.close()
        with self._lock:
            self.alive -= 1

    def close_all(self) -> None:
        with self._lock:
            idle, self._idle = self._idle, deque()
            self.alive -= len(idle)
        for conn, _ in idle:
            conn.close()


def exchange(conn: http.client.HTTPConnection, path: str, body: bytes) -> tuple[int, bytes]:
    conn.request("POST", path, body=body, headers=HEADERS)
    response = conn.getresponse()
    return response.status, response.read()


def post_once(target: Target, body: Json, timeout: float) -> tuple[int, Any]:
    """Отдельный запрос для проверки: статус и разобранное тело или None."""
    conn = http.client.HTTPConnection(target.host, target.port, timeout=timeout)
    try:
        status, raw = exchange(conn, target.recommend, json.dumps(body, ensure_ascii=False).encode("utf-8"))
    except TimeoutError:
        return TIMEOUT, None
    except (OSError, http.client.HTTPException):
        return NETWORK, None
    finally:
        conn.close()
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, None


def get_once(target: Target, path: str, timeout: float) -> tuple[int, Any]:
    conn = http.client.HTTPConnection(target.host, target.port, timeout=timeout)
    try:
        conn.request("GET", target.prefix + path, headers={"Accept": "application/json"})
        response = conn.getresponse()
        raw = response.read()
        status = response.status
    except TimeoutError:
        return TIMEOUT, None
    except (OSError, http.client.HTTPException):
        return NETWORK, None
    finally:
        conn.close()
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, None


# --- Тела запросов и проверка ----------------------------------------------------------------------------


def load_profiles(target: Target, path: Path | None, timeout: float) -> tuple[list[Json], str]:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))["profiles"], f"файл {path.name}"
    status, payload = get_once(target, "/api/profiles", timeout)
    if (
        status == 200
        and isinstance(payload, dict)
        and isinstance(payload.get("profiles"), list)
        and payload["profiles"]
    ):
        return payload["profiles"], "GET /api/profiles"
    if not PROFILES_FILE.is_file():
        raise CheckError(
            f"GET /api/profiles вернул {status}, а файла {PROFILES_FILE.name} рядом нет: задайте --profiles"
        )
    return json.loads(PROFILES_FILE.read_text(encoding="utf-8"))["profiles"], f"файл {PROFILES_FILE.name}"


def base_body(row: Json) -> Json:
    """Тело как у формы интерфейса: анкета и явная история; profile_id не передаётся."""
    body: dict[str, Any] = {key: row.get(key) for key in BODY_FIELDS}
    body["task"] = body["task"] or ""
    body["history"] = [
        {"material_id": e["material_id"], "event": e["event"], "seq": e["seq"]} for e in row.get("history") or []
    ]
    return body


def checked(target: Target, body: Json, timeout: float) -> Json:
    status, payload = post_once(target, body, timeout)
    if status == TIMEOUT:
        raise CheckError("проверочный запрос не получил ответа за таймаут")
    if status == NETWORK:
        raise CheckError(f"нет соединения с {target.host}:{target.port}")
    if status != 200 or not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise CheckError(f"проверочный запрос вернул статус {status} без списка items")
    return payload


def prepare(
    target: Target, rows: list[Json], limits: list[int], timeout: float, remap: bool
) -> tuple[list[bytes], dict[str, Any]]:
    """Проверочный запрос каждого тела. Возвращает тела для прогона и агрегаты проверки."""
    bodies = [base_body(row) for row in rows]
    first = checked(target, {**bodies[0], "limit": limits[0]}, timeout)
    catalog = first.get("catalog") or {}
    source = str(catalog.get("source", "?"))
    remapped = 0
    if remap and source != "synthetic":
        for body in bodies:
            if not body["history"]:
                continue
            items = checked(target, {**body, "history": [], "limit": 10}, timeout)["items"]
            ids = [item["material_id"] for item in items]
            body["history"] = [
                {**event, "material_id": ids[j]} for j, event in enumerate(body["history"]) if j < len(ids)
            ]
            remapped += 1
    statuses: Counter[str] = Counter()
    encoded = []
    for limit in limits:
        for body in bodies:
            final = {**body, "limit": limit}
            statuses[str(checked(target, final, timeout).get("status"))] += 1
            encoded.append(json.dumps(final, ensure_ascii=False).encode("utf-8"))
    info = {
        "catalog_source": source,
        "catalog_size": catalog.get("size"),
        "catalog_version": catalog.get("version"),
        "profiles": len(rows),
        "with_history": sum(1 for b in bodies if b["history"]),
        "history_remapped": remapped,
        "limits": limits,
        "bodies": len(encoded),
        "statuses": dict(sorted(statuses.items())),
    }
    return encoded, info


# --- Прогон ----------------------------------------------------------------------------------------------


class Runner:
    def __init__(
        self,
        target: Target,
        bodies: list[bytes],
        timeout: float,
        workers: int,
        poisson: bool,
        seed: int,
        probe: ProcessProbe | None,
    ) -> None:
        self.target, self.bodies, self.poisson, self.seed, self.probe = target, bodies, poisson, seed, probe
        self.workers = workers
        self.pool = Pool(target, timeout)
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="load")
        self.lock = threading.Lock()
        self.offsets: array[float] = array("d")  # расписание: смещения от t0, с
        self.t0 = 0.0
        self.cutoff = 0  # запланированных запросов с учётом остановки
        self.submitted = 0  # переданы рабочим потокам; пишет только поток расписания
        self.completed = 0  # получен ответ или ошибка
        self.active = 0  # отправлены и ещё без ответа
        self.retries = 0
        self.done: list[int] = []  # завершено по ступеням
        self.failed: list[int] = []  # из них ошибок
        self.waited: list[int] = []  # по ступеням: запросов, которые ждали свободный поток генератора
        self.stop_reason: str | None = None
        # (ступень, запланировано, отправлено, получен ответ, статус); время — perf_counter
        self.records: list[tuple[int, float, float, float, int]] = []
        self.samples: list[tuple[float, int, int, int]] = []  # (время, в системе, в работе, соединений)
        self.process: list[tuple[float, float, int]] = []  # (время, CPU, рабочий набор)
        self.marks: list[tuple[float, float, int] | None] = []  # замер процесса на границах ступеней
        self.own: list[tuple[float, float]] = []  # (время, CPU генератора) на границах ступеней
        self.probe_error: str | None = None

    def _probe(self) -> tuple[float, float, int] | None:
        if self.probe is None or self.probe_error:
            return None
        try:
            cpu, rss = self.probe.sample()
        except OSError as exc:
            self.probe_error = str(exc)
            return None
        return time.perf_counter(), cpu, rss

    def _one(self, stage: int, scheduled: float, body: bytes) -> None:
        status, sent, healthy = NETWORK, scheduled, False
        conn: _Connection | None = None
        retried = False
        try:
            conn, reused = self.pool.acquire()
            sent = time.perf_counter()
            with self.lock:
                self.active += 1
            try:
                try:
                    status, _ = exchange(conn, self.target.recommend, body)
                except (http.client.RemoteDisconnected, ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                    if not reused:
                        raise
                    # Сервис закрыл простаивающее соединение раньше генератора: один повтор на новом соединении
                    conn.close()
                    retried = True
                    status, _ = exchange(conn, self.target.recommend, body)
                healthy = True
            except TimeoutError:
                status = TIMEOUT
            except ConnectionRefusedError:
                status = REFUSED
            except (OSError, http.client.HTTPException):
                status = NETWORK
            finally:
                with self.lock:
                    self.active -= 1
        except Exception:  # noqa: BLE001 — сбой генератора считается обрывом, а не теряется в Future
            status = NETWORK
        finally:
            done = time.perf_counter()
            if conn is not None:
                self.pool.release(conn, healthy)
            with self.lock:
                self.completed += 1
                self.done[stage] += 1
                self.failed[stage] += 0 if 200 <= status < 300 else 1
                self.retries += retried
                self.records.append((stage, scheduled, sent, done, status))

    def _sample(self, stop: threading.Event) -> None:
        tick = 0
        while not stop.wait(SAMPLE_EVERY_S):
            now = time.perf_counter()
            # В системе — запросы, чей момент по расписанию наступил, а ответа нет: опоздание генератора тоже
            scheduled = min(bisect_right(self.offsets, now - self.t0), self.cutoff)
            with self.lock:
                row = (now, scheduled - self.completed, self.active, self.pool.alive)
            self.samples.append(row)
            tick += 1
            if tick % PROCESS_EVERY == 0:
                self.pool.sweep()
                mark = self._probe()
                if mark is not None:
                    self.process.append(mark)

    @staticmethod
    def _sleep_until(moment: float) -> None:
        delay = moment - time.perf_counter()
        if delay > 0:
            time.sleep(delay)

    def _stop_check(self, index: int, stage: Stage) -> str | None:
        """Условие остановки после ступени: генератор исчерпал потоки или больше половины ошибок."""
        with self.lock:
            done, failed = self.done[index], self.failed[index]
        where = "на прогреве" if stage.warmup else f"на ступени {stage.name}"
        if self.waited[index]:
            return f"{where} генератор исчерпал {self.workers} потоков"
        if done and failed / done > STOP_ERROR_SHARE:
            return (
                f"{where} ошибкой закончились {failed} из {done} запросов, "
                f"завершённых к концу ступени, — больше {STOP_ERROR_SHARE * 100:g} %"
            )
        return None

    def run(self, plan: list[Stage]) -> list[tuple[float, float]]:
        """Отправка по расписанию; возвращает окна выполненных ступеней (начало, конец)."""
        self.offsets, spans = build_schedule(plan, self.poisson, self.seed)
        self.cutoff = len(self.offsets)
        self.done, self.failed, self.waited = [0] * len(plan), [0] * len(plan), [0] * len(plan)
        self.t0 = time.perf_counter() + 0.1
        windows = []
        stop = threading.Event()
        sampler = threading.Thread(target=self._sample, args=(stop,), daemon=True)
        sampler.start()
        base = 0.0
        for index, stage in enumerate(plan):
            start, end = self.t0 + base, self.t0 + base + stage.seconds
            base += stage.seconds
            self._sleep_until(start)
            if index > 0:
                self.stop_reason = self._stop_check(index - 1, plan[index - 1])
                if self.stop_reason is not None:
                    self.cutoff = spans[index][0]
                    break
            self.marks.append(self._probe())
            self.own.append((time.perf_counter(), time.process_time()))
            windows.append((start, end))
            first, last = spans[index]
            for k in range(first, last):
                moment = self.t0 + self.offsets[k]
                self._sleep_until(moment)
                with self.lock:
                    busy = self.submitted - self.completed
                    self.submitted += 1
                if busy >= self.workers:
                    self.waited[index] += 1
                self.executor.submit(self._one, index, moment, self.bodies[k % len(self.bodies)])
        else:
            self._sleep_until(self.t0 + base)
        self.marks.append(self._probe())
        self.own.append((time.perf_counter(), time.process_time()))
        self.executor.shutdown(wait=True)
        stop.set()
        sampler.join()
        self.pool.close_all()
        return windows


# --- Отчёт -----------------------------------------------------------------------------------------------


def summarize(runner: Runner, plan: list[Stage], windows: list[tuple[float, float]]) -> list[dict[str, Any]]:
    by_stage: dict[int, list[tuple[int, float, float, float, int]]] = {}
    for record in runner.records:
        by_stage.setdefault(record[0], []).append(record)
    result = []
    for index, stage in enumerate(plan[: len(windows)]):
        if stage.warmup:
            continue
        start, end = windows[index]
        seconds = end - start
        records = by_stage.get(index, [])
        n = len(records)
        latencies = sorted((r[3] - r[1]) * 1000 for r in records)
        # От фактической отправки — без опоздания генератора; для сравнения, пороги считаются от расписания
        service = sorted((r[3] - r[2]) * 1000 for r in records)
        lags = sorted((r[2] - r[1]) * 1000 for r in records)
        statuses = [r[4] for r in records]
        ok = sum(1 for s in statuses if 200 <= s < 300)
        timeouts = sum(1 for s in statuses if s == TIMEOUT)
        network = sum(1 for s in statuses if s == NETWORK)
        refused = sum(1 for s in statuses if s == REFUSED)
        server = sum(1 for s in statuses if 500 <= s < 600)
        rejected = sum(1 for s in statuses if s == 503)
        client = sum(1 for s in statuses if 400 <= s < 500)
        errors = n - ok
        unanswered = server + timeouts + network + refused
        sent = sum(1 for r in runner.records if start <= r[2] < end)
        good = sum(1 for r in runner.records if 200 <= r[4] < 300 and start <= r[3] < end)
        answered = sum(1 for r in runner.records if start <= r[3] < end)
        rate = n / seconds if seconds else math.nan
        w_mean = sum(latencies) / n / 1000 if n else math.nan
        window = [s for s in runner.samples if start <= s[0] < end]
        p99 = percentile(latencies, 0.99)
        row: dict[str, Any] = {
            "stage": stage.name,
            "target_rps": stage.rate,
            "seconds": round(seconds, 1),
            "requests": n,
            "sent_rps": round(sent / seconds, 1),
            "ok_rps": round(good / seconds, 1),
            "p50_ms": round(percentile(latencies, 0.50), 1),
            "p95_ms": round(percentile(latencies, 0.95), 1),
            "p99_ms": round(p99, 1),
            "max_ms": round(latencies[-1], 1) if n else math.nan,
            "mean_ms": round(w_mean * 1000, 1),
            "errors": errors,
            "error_share": errors / n if n else 1.0,
            "http_5xx": server,
            "http_503": rejected,
            "http_4xx": client,
            "timeouts": timeouts,
            "network": network,
            "refused": refused,
            "slo2_share": unanswered / n if n else 1.0,
            "waited_for_worker": runner.waited[index],
            "sent_mean_ms": round(sum(service) / n, 1) if n else math.nan,
            "sent_p95_ms": round(percentile(service, 0.95), 1),
            "sent_p99_ms": round(percentile(service, 0.99), 1),
            "lag_p99_ms": round(percentile(lags, 0.99), 1),
            "lag_max_ms": round(lags[-1], 1) if n else math.nan,
            "little_l": round(rate * w_mean, 2),
            "in_system_mean": round(time_mean([(s[0], s[1]) for s in window]), 2),
            "in_system_max": max((s[1] for s in window), default=0),
            "in_flight_max": max((s[2] for s in window), default=0),
            "connections_max": max((s[3] for s in window), default=0),
            "limit_needed": round(rate * p99 / 1000 * LIMIT_MARGIN, 1),
        }
        little, measured = row["little_l"], row["in_system_mean"]
        # Расхождение меньше одного запроса или 20 % — погрешность отсчётов, а не рост очереди
        row["steady"] = bool(
            math.isfinite(little)
            and math.isfinite(measured)
            and abs(little - measured) <= max(1.0, 0.2 * max(little, measured))
        )
        (own_t0, own_c0), (own_t1, own_c1) = runner.own[index], runner.own[index + 1]
        row["generator_cpu_cores"] = round((own_c1 - own_c0) / (own_t1 - own_t0), 2)
        before, after = runner.marks[index], runner.marks[index + 1]
        if before is not None and after is not None:
            cpu = after[1] - before[1]
            peaks = [p[2] for p in runner.process if start <= p[0] < end] + [before[2], after[2]]
            row.update(
                {
                    "cpu_s": round(cpu, 1),
                    "cpu_cores": round(cpu / (after[0] - before[0]), 2),
                    "cpu_ms_per_answer": round(cpu * 1000 / answered, 2) if answered else math.nan,
                    "cpu_bound_rps": round(answered / cpu, 0) if cpu > 0 else math.nan,
                    "rss_end_mb": round(after[2] / 2**20, 1),
                    "rss_max_mb": round(max(peaks) / 2**20, 1),
                }
            )
        row["checks"] = {
            "p95": row["p95_ms"] < P95_MS,
            "p99": row["p99_ms"] < P99_MS,
            "errors": row["error_share"] < MAX_ERROR_SHARE,
            "generator": row["waited_for_worker"] == 0,
        }
        row["slo2"] = row["slo2_share"] <= SLO2_SHARE
        result.append(row)
    return result


def skipped_stages(plan: list[Stage], windows: list[tuple[float, float]]) -> list[str]:
    return [stage.name for stage in plan[len(windows) :] if not stage.warmup]


def print_report(
    rows: list[dict[str, Any]], runner: Runner, info: dict[str, Any], probe: ProcessProbe | None, skipped: list[str]
) -> bool:
    print()
    if not rows:
        print("Ни одна ступень не выполнялась: " + (runner.stop_reason or "нет ступеней"))
        print()
        print("Итог: FAIL — прогон остановлен")
        return False
    print(
        "Задержка от запланированного момента отправки, мс; "
        "ошибки — таймауты, обрывы, отказы в соединении и ответы не 2xx"
    )
    print()
    print(
        "| Ступень | Запросов | Отправлено/с | Успешно/с | p50 | p95 | p99 | max | Ошибок, % | 5xx (из них 503) "
        "| 4xx | Таймаутов | Обрывов | Отказов в соединении |"
    )
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in rows:
        print(
            f"| {r['stage']} | {r['requests']} | {fmt(r['sent_rps'])} | {fmt(r['ok_rps'])} | {fmt(r['p50_ms'])} "
            f"| {fmt(r['p95_ms'])} | {fmt(r['p99_ms'])} | {fmt(r['max_ms'])} | {fmt(r['error_share'] * 100, 2)} "
            f"| {r['http_5xx']} ({r['http_503']}) | {r['http_4xx']} | {r['timeouts']} | {r['network']} "
            f"| {r['refused']} |"
        )
    print()
    print(
        f"Параллельность и закон Литтла L = λ·W; пул AnyIO — {ANYIO_THREADS} потоков, "
        f"limit_concurrency — {LIMIT_CONCURRENCY} соединения"
    )
    print()
    print(
        "| Ступень | W, мс | L = λ·W | В системе: среднее | В системе: max | У сервиса: max | Соединений: max "
        f"| λ·p99·{LIMIT_MARGIN:g} | Ждали поток генератора | Опоздание отправки p99 / max, мс "
        "| От отправки: среднее / p95 / p99, мс |"
    )
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in rows:
        print(
            f"| {r['stage']} | {fmt(r['mean_ms'])} | {fmt(r['little_l'], 2)} | {fmt(r['in_system_mean'], 2)} "
            f"| {r['in_system_max']} | {r['in_flight_max']} | {r['connections_max']} | {fmt(r['limit_needed'])} "
            f"| {r['waited_for_worker']} | {fmt(r['lag_p99_ms'])} / {fmt(r['lag_max_ms'])} "
            f"| {fmt(r['sent_mean_ms'])} / {fmt(r['sent_p95_ms'])} / {fmt(r['sent_p99_ms'])} |"
        )
    print()
    print(
        "«В системе» — запросы, чей запланированный момент наступил, а ответа ещё нет, включая опоздание "
        "генератора; в установившемся режиме среднее совпадает с L. «У сервиса» — отправленные без ответа. "
        "«От отправки» — задержка без опоздания генератора, только для сравнения. "
        f"При {LIMIT_CONCURRENCY - 1} открытых соединениях следующее получает 503 (app/backend/app/serve.py)."
    )
    if probe is not None:
        print()
        if any("cpu_s" in r for r in rows):
            print(f"Процесс сервиса, PID {probe.pid}: процессорное время и рабочий набор")
            print()
            print(
                "| Ступень | CPU, с | Ядер в среднем | CPU на ответ, мс | Предел процесса 1/CPU, запр./с "
                "| Память конец / max, МБ |"
            )
            print("| --- | ---: | ---: | ---: | ---: | ---: |")
            for r in rows:
                if "cpu_s" in r:
                    print(
                        f"| {r['stage']} | {fmt(r['cpu_s'])} | {fmt(r['cpu_cores'], 2)} "
                        f"| {fmt(r['cpu_ms_per_answer'], 2)} "
                        f"| {fmt(r['cpu_bound_rps'], 0)} | {fmt(r['rss_end_mb'])} / {fmt(r['rss_max_mb'])} |"
                    )
        if runner.probe_error:
            print(f"Замер процесса прерван: {runner.probe_error}")

    print()
    print(
        f"Пороги на ступени: p95 < {P95_MS:g} мс, p99 < {P99_MS:g} мс, ошибок < {MAX_ERROR_SHARE * 100:g} %, "
        f"ни один запрос не ждал поток генератора. SLO-2 — доля 5xx, таймаутов и обрывов не выше "
        f"{SLO2_SHARE * 100:g} %, справочно, на итог не влияет"
    )
    print()
    print("| Ступень | p95 | p99 | Ошибок | Генератор | SLO-2, справочно |")
    print("| --- | --- | --- | --- | --- | --- |")
    passed = not skipped and runner.stop_reason is None
    for r in rows:
        checks = r["checks"]
        passed = passed and all(checks.values())
        print(
            f"| {r['stage']} | {_verdict(checks['p95'])} {fmt(r['p95_ms'])} "
            f"| {_verdict(checks['p99'])} {fmt(r['p99_ms'])} "
            f"| {_verdict(checks['errors'])} {fmt(r['error_share'] * 100, 2)} % "
            f"| {_verdict(checks['generator'])} {r['waited_for_worker']} "
            f"| {_verdict(r['slo2'])} {fmt(r['slo2_share'] * 100, 3)} % |"
        )
    print()
    for line in observations(rows, runner, skipped):
        print(line)
    print()
    if skipped:
        print("Итог: FAIL — прогон остановлен, порог не выполнен")
    else:
        print("Итог: " + ("PASS — все пороги выполнены" if passed else "FAIL — порог не выполнен"))
    return passed


def _verdict(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def capacity_line(rows: list[dict[str, Any]]) -> str:
    """Ёмкость по закону Литтла: λ_max = L / W для пула и предела соединений, плюс предел процессора."""
    basis = next(
        (r for r in rows if all(r["checks"].values()) and r["steady"] and r["sent_mean_ms"] > 0),
        None,
    )
    if basis is None:
        return (
            "Ёмкость по закону Литтла не оценивается: ни одна ступень не выполнила пороги в установившемся режиме, "
            "а время обслуживания под перегрузкой включает очередь."
        )
    s = basis["sent_mean_ms"] / 1000
    bounds = {
        f"пул из {ANYIO_THREADS} потоков": ANYIO_THREADS / s,
        f"limit_concurrency {LIMIT_CONCURRENCY}": LIMIT_CONCURRENCY / s,
    }
    text = (
        f"Ёмкость по закону Литтла при неизменном времени обслуживания {fmt(basis['sent_mean_ms'])} мс "
        f"(от отправки, ступень {basis['stage']}): "
        + ", ".join(f"{name} — до {value:.0f} запр./с" for name, value in bounds.items())
        + "."
    )
    cpu_rows = [r for r in rows if math.isfinite(r.get("cpu_ms_per_answer", math.nan)) and r["cpu_ms_per_answer"] > 0]
    if not cpu_rows:
        return text + (
            " Предел процессора не измерен: нужен --pid для процесса на этой машине или docker stats для контейнера."
            " Без него ближайший предел не называется."
        )
    # Самая нагруженная ступень без ошибок: постоянные расходы процесса там меньше на ответ, а дешёвые
    # ответы 503 не занижают оценку
    clean = [r for r in cpu_rows if r["error_share"] < MAX_ERROR_SHARE] or cpu_rows[:1]
    chosen = clean[-1]
    cpu_ms = chosen["cpu_ms_per_answer"]
    bounds["процессор"] = 1000 / cpu_ms
    nearest = min(bounds, key=lambda name: bounds[name])
    return text + (
        f" По процессору на ступени {chosen['stage']} — {fmt(cpu_ms, 2)} мс CPU на ответ: один процесс Python "
        f"с GIL успеет не больше {1000 / cpu_ms:.0f} запр./с. Ближайший из учтённых пределов — {nearest}, "
        f"около {bounds[nearest]:.0f} запр./с; фактический предел показывают ступени, где пороги не выполнены."
    )


def observations(rows: list[dict[str, Any]], runner: Runner, skipped: list[str]) -> list[str]:
    lines = []
    if runner.stop_reason is not None:
        lines.append(f"Условие остановки: {runner.stop_reason}. Не выполнялись ступени {', '.join(skipped)}.")
    first = rows[0]
    saturated = next((r for r in rows[1:] if first["p95_ms"] and r["p95_ms"] >= 2 * first["p95_ms"]), None)
    lines.append(
        f"Насыщение: p95 удвоилась относительно первой ступени на ступени {saturated['stage']}."
        if saturated
        else "Насыщение: p95 не удвоилась относительно первой ступени ни на одной выполненной ступени."
    )
    lines.append(capacity_line(rows))
    for r in rows:
        if not r["steady"] and math.isfinite(r["little_l"]) and math.isfinite(r["in_system_mean"]):
            lines.append(
                f"Ступень {r['stage']} не в установившемся режиме: L = λ·W = {fmt(r['little_l'], 2)}, а в среднем "
                f"в системе {fmt(r['in_system_mean'], 2)}. Очередь росла или запросы ступени завершались уже после "
                f"её конца; оценка ёмкости по этой ступени не строится. Успешных ответов на ней {fmt(r['ok_rps'])} "
                f"в секунду при заданных {r['target_rps']:g}."
            )
    for r in rows:
        if r["waited_for_worker"]:
            lines.append(
                f"Ступень {r['stage']}: генератор исчерпал {runner.workers} потоков; запросов, которые ждали свободный "
                f"поток, — {r['waited_for_worker']}. Это аналог dropped_iterations в k6: задержка учитывает ожидание, "
                "но к сервису запросы уходили реже заданного."
            )
    lagging = [r["stage"] for r in rows if r["lag_p99_ms"] > LAG_WARN_MS and not r["waited_for_worker"]]
    if lagging:
        lines.append(
            f"Внимание: на ступенях {', '.join(lagging)} генератор отправлял с опозданием больше {LAG_WARN_MS:g} мс "
            "в 1 % запросов, хотя свободные потоки были: это таймер или пауза машины. Задержка учитывает опоздание, "
            "но часть хвоста создал генератор."
        )
    small = [r["stage"] for r in rows if r["requests"] < 100]
    if small:
        lines.append(f"Меньше 100 запросов на ступенях {', '.join(small)}: p99 по малой выборке.")
    lines.append(
        f"TCP-соединений открыто за прогон: {runner.pool.connects}; повторов после закрытия простаивающего "
        f"соединения: {runner.retries}. Генератор занимал ядер в среднем: "
        + ", ".join(f"{r['stage']} — {fmt(r['generator_cpu_cores'], 2)}" for r in rows)
        + "."
    )
    return lines


# --- Командная строка ------------------------------------------------------------------------------------


class _Help(argparse.RawDescriptionHelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):  # type: ignore[no-untyped-def]
        super().add_usage(usage, actions, groups, "Запуск: " if prefix is None else prefix)


# Частые сообщения argparse по-русски; остальные выводятся как есть
_ARGPARSE_RU = (
    (re.compile(r"^the following arguments are required: (.+)$"), r"не заданы обязательные аргументы: \1"),
    (re.compile(r"^unrecognized arguments: (.+)$"), r"неизвестные аргументы: \1"),
    (re.compile(r"^ambiguous option: (\S+) could match (.+)$"), r"параметр \1 неоднозначен, подходят: \2"),
    (
        re.compile(r"^argument (\S+): invalid choice: (.+?) \(choose from (.+)\)$"),
        r"параметр \1: недопустимое значение \2, допустимы: \3",
    ),
    (re.compile(r"^argument (\S+): invalid \w+ value: (.+)$"), r"параметр \1: недопустимое значение \2"),
    (re.compile(r"^argument (\S+): expected one argument$"), r"параметру \1 нужно значение"),
    (re.compile(r"^argument (\S+): (.+)$"), r"параметр \1: \2"),
)


def _russian(message: str) -> str:
    for pattern, replacement in _ARGPARSE_RU:
        if pattern.match(message):
            return pattern.sub(replacement, message)
    return message


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(2, f"Ошибка параметров: {_russian(message)}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="python -X utf8 evaluation/load_open.py",
        formatter_class=_Help,
        add_help=False,
        description=(
            "Нагрузочный прогон POST /api/recommend в открытой модели.\n"
            "Запросы уходят с постоянной частотой независимо от ответов; задержка считается от запланированного\n"
            "момента отправки. Пороги на каждой ступени: p95 < 200 мс, p99 < 500 мс, ошибок < 1 % и ни одного\n"
            "запроса, который ждал свободный поток генератора. SLO-2 (5xx, таймауты и обрывы не выше 0,1 %)\n"
            "выводится справочно. Если на ступени генератор исчерпал потоки или больше половины запросов\n"
            "закончились ошибкой, следующие ступени не выполняются."
        ),
        epilog=(
            "Коды выхода: 0 — пороги выполнены, 1 — порог не выполнен или прогон остановлен,\n"
            "2 — сервис не прошёл проверку или параметры неверны.\n\n"
            "Примеры из корня проекта при работающем сервисе:\n"
            "  python -X utf8 evaluation/load_open.py http://127.0.0.1:8000\n"
            "  python -X utf8 evaluation/load_open.py http://127.0.0.1:8000 --stages 20:30,50:30 --warmup 5\n"
            "  python -X utf8 evaluation/load_open.py http://127.0.0.1:8000 --pid 1234 --json load.json\n\n"
            "PID процесса, который слушает порт, в Windows PowerShell:\n"
            "  (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess\n"
            "Лаунчер python.exe из venv запускает второй процесс: нужен PID того, кто слушает порт.\n"
            "Без --pid предел процессора не оценивается; для контейнера снимайте docker stats."
        ),
    )
    parser._positionals.title = "аргументы"
    parser._optionals.title = "параметры"
    parser.add_argument("url", help="адрес сервиса, например http://127.0.0.1:8000")
    parser.add_argument("-h", "--help", action="help", help="показать эту справку и выйти")
    parser.add_argument(
        "--stages",
        default="20,50,100",
        metavar="ЧАСТОТЫ",
        help="ступени: запросов в секунду через запятую; после двоеточия — своя длительность ступени в секундах, "
        "например 20:30,50,100. По умолчанию 20,50,100",
    )
    parser.add_argument(
        "--duration", type=float, default=60.0, metavar="С", help="длительность ступени без своей, с; по умолчанию 60"
    )
    parser.add_argument(
        "--warmup",
        type=float,
        default=10.0,
        metavar="С",
        help="прогрев на частоте первой ступени, с; в отчёт не входит; 0 — без прогрева. По умолчанию 10",
    )
    parser.add_argument(
        "--arrivals",
        choices=("uniform", "poisson"),
        default="uniform",
        help="расписание: uniform — через равные промежутки, как constant-arrival-rate в k6; poisson — "
        "случайные промежутки с той же средней частотой. По умолчанию uniform",
    )
    parser.add_argument("--seed", type=int, default=1, metavar="N", help="зерно расписания poisson; по умолчанию 1")
    parser.add_argument(
        "--limit",
        default="5",
        metavar="N[,N]",
        help="размер выдачи в теле запроса; через запятую — по очереди, например 5,10. По умолчанию 5",
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0, metavar="С", help="таймаут чтения и подключения, с; по умолчанию 10"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=256,
        metavar="N",
        help="потоков генератора — предел одновременных запросов с его стороны; по умолчанию 256",
    )
    parser.add_argument(
        "--profiles",
        type=Path,
        metavar="ФАЙЛ",
        help="профили из файла вместо GET /api/profiles; формат profiles.synthetic.json",
    )
    parser.add_argument(
        "--history",
        choices=("auto", "as-is"),
        default="auto",
        help="auto — на каталоге не из синтетики история берётся из выдачи сервиса; as-is — история как в профиле. "
        "По умолчанию auto",
    )
    parser.add_argument(
        "--pid", type=int, help="PID процесса сервиса на этой машине: процессорное время и память по ступеням"
    )
    parser.add_argument("--json", type=Path, metavar="ФАЙЛ", help="записать сводку с агрегатами в JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        target = parse_url(args.url)
        stages = parse_stages(args.stages, args.duration)
        limits = parse_limits(args.limit)
    except ValueError as exc:
        parser.error(str(exc))
    if args.warmup < 0 or args.timeout <= 0 or not 1 <= args.workers <= 2048:
        parser.error("прогрев не меньше 0, таймаут больше 0, потоков от 1 до 2048")
    planned = sum(s.rate * s.seconds for s in stages) + stages[0].rate * args.warmup
    if planned > MAX_PLANNED:
        parser.error(
            f"в расписании около {planned:,.0f} запросов, предел {MAX_PLANNED:,}".replace(",", "\N{NO-BREAK SPACE}")
        )
    # Короткий интервал переключения GIL: поток расписания не ждёт рабочие потоки по 5 мс
    sys.setswitchinterval(0.0005)

    probe = None
    if args.pid is not None:
        try:
            probe = ProcessProbe(args.pid)
        except OSError as exc:
            print(f"Замер процесса невозможен: {exc}", file=sys.stderr)
            return 2
    try:
        rows, profile_source = load_profiles(target, args.profiles, args.timeout)
        bodies, info = prepare(target, rows, limits, args.timeout, args.history == "auto")
    except (CheckError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"Сервис не прошёл проверку: {exc}", file=sys.stderr)
        return 2
    statuses = ", ".join(f"{k} {v}" for k, v in info["statuses"].items())
    print(
        f"Проверка: каталог {info['catalog_source']}, материалов {info['catalog_size']}, "
        f"версия {info['catalog_version']}; "
        f"профилей {info['profiles']} ({profile_source}), из них с историей {info['with_history']}, "
        f"история взята из выдачи у {info['history_remapped']}; размер выдачи {','.join(map(str, limits))}; "
        f"тел запросов {info['bodies']}, статусы выдачи: {statuses}"
    )
    plan = ([Stage(stages[0].rate, args.warmup, warmup=True)] if args.warmup > 0 else []) + stages
    total = sum(s.seconds for s in plan)
    print(
        f"Расписание {args.arrivals}: "
        + " → ".join(
            f"{s.name} {s.seconds:g} с" if not s.warmup else f"прогрев {s.rate:g}/с {s.seconds:g} с" for s in plan
        )
        + f"; всего {total:g} с, потоков генератора {args.workers}, таймаут {args.timeout:g} с"
    )
    sys.stdout.flush()

    runner = Runner(target, bodies, args.timeout, args.workers, args.arrivals == "poisson", args.seed, probe)
    windows = runner.run(plan)
    summary = summarize(runner, plan, windows)
    skipped = skipped_stages(plan, windows)
    passed = print_report(summary, runner, info, probe, skipped)

    if args.json is not None:
        payload = {
            "generator": {
                "model": "open",
                "arrivals": args.arrivals,
                "stages": [{"rate": s.rate, "seconds": s.seconds} for s in stages],
                "warmup_s": args.warmup,
                "timeout_s": args.timeout,
                "workers": args.workers,
                "python": sys.version.split()[0],
            },
            "service": {**info, "limit_concurrency": LIMIT_CONCURRENCY, "anyio_threads": ANYIO_THREADS},
            "thresholds": {
                "p95_ms": P95_MS,
                "p99_ms": P99_MS,
                "error_share": MAX_ERROR_SHARE,
                "waited_for_worker": 0,
                "slo2_share_info": SLO2_SHARE,
            },
            "stages": summary,
            "stopped": runner.stop_reason,
            "skipped_stages": skipped,
            "capacity": capacity_line(summary) if summary else None,
            "connections_opened": runner.pool.connects,
            "retries": runner.retries,
            "passed": passed,
        }
        text = json.dumps(_finite(payload), ensure_ascii=False, indent=2, allow_nan=False, default=str)
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0 if passed else 1


def _finite(value: Any) -> Any:
    """NaN и бесконечность в JSON — null."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    return value


if __name__ == "__main__":
    sys.exit(main())
