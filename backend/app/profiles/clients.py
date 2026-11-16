"""Клиенты ленты по профилю: код, подпись, история и анкета (docs/plan.md, 13.7 и 13.9).

Источник клиентов следует за каталогом. У синтетического каталога это вымышленные клиенты из
`data/clients.synthetic.json`. У локальной базы — её журнал записей на курсы: код клиента там псевдоним
из выгрузки, и видит его только тот, кто сам подключил базу. Если база подключена без построчного журнала
или каталог взят из файла, клиентов из источника нет. Профили из `DEMO_PROFILES_PATH`, у которых есть
история, идут в списке первыми: так вымышленные персонажи подключённого каталога открываются в ленте.
Клиенты загружаются только в демо-режиме: история по коду без входа в систему — функция показа.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .. import vocab
from ..catalog.models import Catalog, CatalogError, DemoProfile, HistoryEvent, valid_material_id
from ..config import DATA_DIR, Settings
from ..ranking.explain import plural

log = logging.getLogger("app.catalog")

CLIENTS_PATH = DATA_DIR / "clients.synthetic.json"


@dataclass(frozen=True, slots=True)
class Client:
    id: str
    label: str
    segment: str | None  # подпись сегмента; у журнала локальной базы сегментов нет
    history: tuple[HistoryEvent, ...]
    # Анкета есть только у профилей из файла: в журнале записей сведений о клиенте нет
    stage: str | None = None
    experience: str | None = None
    format_pref: str | None = None
    industry: str | None = None

    @property
    def materials(self) -> int:
        return len({event.material_id for event in self.history})

    @property
    def paid(self) -> bool:
        return any(event.event == "purchase" for event in self.history)


class Clients:
    """Клиенты в порядке показа и поиск по коду без учёта регистра."""

    def __init__(self, source: str, clients: Iterable[Client] = ()) -> None:
        self.source = source  # synthetic | sqlite | profiles | none
        self.by_id = {client.id: client for client in clients}
        # Коды, которые различаются только регистром, остаются разными клиентами
        self._folded: dict[str, list[Client]] = {}
        for code, client in self.by_id.items():
            self._folded.setdefault(code.casefold(), []).append(client)

    def __len__(self) -> int:
        return len(self.by_id)

    def find(self, code: str) -> Client | None:
        """Клиент по коду: точное совпадение, иначе без учёта регистра, если такой клиент один."""
        exact = self.by_id.get(code.strip())
        if exact is not None:
            return exact
        same = self._folded.get(code.strip().casefold(), [])
        return same[0] if len(same) == 1 else None

    def search(self, query: str, limit: int) -> tuple[list[Client], int]:
        """Клиенты, код которых начинается с `query`, и их общее число. Точное совпадение стоит первым."""
        prefix = query.strip().casefold()
        found = [client for code, client in self.by_id.items() if code.casefold().startswith(prefix)]
        exact = self.find(query) if prefix else None
        if exact is not None:
            found.remove(exact)
            found.insert(0, exact)
        return found[:limit], len(found)


def load_json_clients(path: Path = CLIENTS_PATH) -> Clients:
    """Файл клиентов: `segments` — код → подпись, `clients` — код, подпись, сегмент и история."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        segments = {code: row["label"] for code, row in payload.get("segments", {}).items()}
        clients = [
            Client(
                id=row["id"],
                label=row["label"],
                segment=segments.get(row.get("segment")),
                history=tuple(
                    HistoryEvent(event["material_id"], event["event"], int(event["seq"]))
                    for event in row.get("history", [])
                    if event.get("event") in vocab.EVENTS and valid_material_id(event.get("material_id"))
                ),
            )
            for row in payload["clients"]
            if valid_material_id(row.get("id"))
        ]
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise CatalogError(f"Файл клиентов не читается: {Path(path).name}") from exc
    return Clients("synthetic", clients)


def from_course_log(journal: Mapping[str, list[HistoryEvent]]) -> Clients:
    """Клиенты из журнала записей: сначала с длинной историей, затем по коду."""
    clients = [Client(id=code, label="", segment=None, history=tuple(events)) for code, events in journal.items()]
    clients.sort(key=lambda client: (-client.materials, client.id))
    labelled = (
        Client(
            id=client.id,
            label=f"{client.id} · {client.materials} {plural(client.materials, 'курс', 'курса', 'курсов')}",
            segment=None,
            history=client.history,
        )
        for client in clients
    )
    return Clients("sqlite", labelled)


def _from_source(settings: Settings) -> Clients:
    try:
        if settings.catalog_source == "synthetic":
            return load_json_clients()
        if settings.catalog_source == "sqlite" and settings.catalog_path is not None:
            # Импорт по требованию: модуль нужен только локально
            from ..catalog.sqlite_source import read_course_log  # noqa: PLC0415

            return from_course_log(read_course_log(settings.catalog_path, settings.catalog_mapping))
    except CatalogError as exc:
        log.error("clients not loaded: %s", exc)
    return Clients("none")


def load_clients(settings: Settings, catalog: Catalog | None, profiles: Mapping[str, DemoProfile]) -> Clients:
    """Клиенты для загруженного каталога. Ошибка источника оставляет сервис без его клиентов, а не без каталога.

    `profiles` — тестовые профили сервиса. В клиенты они попадают, только если файл профилей задан явно:
    встроенные профили комплекта относятся к подбору по задаче, а у ленты в комплекте свои клиенты.
    """
    if catalog is None or not settings.demo_mode:
        return Clients("none")
    own = _from_source(settings)
    personas = [
        Client(
            id=p.id, label=p.label, segment=None, history=p.history,
            stage=p.stage, experience=p.experience, format_pref=p.format_pref, industry=p.industry,
        )
        for p in profiles.values()
        # Код вне правила запрос ленты отклонил бы: такой профиль в клиенты не попадает
        if p.history and settings.demo_profiles_path is not None and valid_material_id(p.id)
    ]
    source = own.source if len(own) else "profiles" if personas else "none"
    clients = Clients(source, [*personas, *(c for c in own.by_id.values() if c.id not in {p.id for p in personas})])
    log.info("clients loaded source=%s size=%d personas=%d", clients.source, len(clients), len(personas))
    return clients
