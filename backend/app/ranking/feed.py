"""Лента по профилю: все допустимые материалы по убыванию оценки (docs/plan.md, раздел 13, этап 4).

Оценка материала m для клиента — сумма вкладов источников, и на экране показана та же сумма:

    курс по журналу записей:  S1 + популярность + общие слагаемые
    материал по содержанию:   S2 + S3 + популярность + общие слагаемые
    общие слагаемые:          анкета + задача + доступ и цена + начатое − уже открывали

- S1, выбор слушателей: w1 · Σ B(a, m) по курсам истории a. B — веса модели EASE по журналу записей
  в единицах доли слушателей (`catalog/ease.py`). Свидетельством служит запись с наибольшим весом: c(a, m)
  слушателей обоих курсов из c(a) слушателей курса a. Без весов модели S1 = w1 · min(1, Σ c(a, m) / c(a)).
- S2, похожее содержание: w2 · косинус между профилем интересов и материалом. Профиль — сумма признаков
  материалов истории с весами по редкости признака в каталоге.
- S3, совет редакции: w3, если материал стоит в блоке «далее» у материала истории.
- Популярность: w4 · нормированная популярность, вес один для всех материалов.
- Анкета и задача — вклады `personal.score_material`, тот же код, что у подбора по задаче.
- Доступ и цена: у платного материала надбавка, если у клиента есть оплаты, и вычет, если их нет; бесплатный
  материал этого слагаемого не имеет.

Порядок — строго по оценке, затем по популярности и коду: место карточки объясняется только её оценкой.
Штраф за повтор темы проверен и не включён: он стоил точности и на журнале, и на псевдоэталоне, а без него
в первой десятке ленты на копии уже в среднем больше пяти тем.

Почему два набора слагаемых. Журнал записей есть только у курсов. На нём порядок курсов задают совместные
записи; сходство содержания его ухудшает, совет редакции и вес глубины события (открыл, начал, прошёл)
не улучшают. Поэтому курс оценивается по журналу, если в истории клиента есть курс, на который записано
не меньше порога слушателей. Материалы других форматов оцениваются по содержанию и редакционным связям:
журнала у них нет. Так же оцениваются курсы для клиента без курсов в истории и все материалы каталога,
к которому не подключены пары совместных записей. Новый курс без записей у клиента с курсами в истории
получает только общие слагаемые. Отдельного места на пробу у новых курсов нет: это тема отдельного
эксперимента (решение 13.9).

Почему модель, а не доля слушателей. В ленте с весами EASE скрытый курс стоит первым у 0,45 пользователей
журнала против 0,42 с долей слушателей: разница +0,030 [+0,011; +0,050] на 803 пользователях, обе группы выше.
Отдельно от ленты, по первой пятёрке, методы не различались. Фраза на карточке осталась записью журнала,
а о том, что величину вклада считает модель, говорит пояснение в расчёте карточки.

Откуда веса. Вес выбора слушателей выбран на журнале записей по порядку курсов. Сходство содержания относится
к популярности как 5 : 3: это отношение выбрано на псевдоэталоне редакционных связей. Вес популярности общий
для всех материалов и задаёт взаимное положение курсов и статей: популярный курс и популярная статья без
личных свидетельств получают равную оценку. Доля курсов в ленте не задаётся: курсы и статьи идут одной
лентой (решение 13.9). Среди одних курсов на частях выбора журнал выбирает нулевой вес популярности; на частях
подтверждения лента с общим весом 1,0 не ниже ленты с выбранными весами. Знак и размер вклада доступа приняты
решением 13.9. Данными не проверены взаимное положение курсов и статей, вес совета редакции, доступ, анкета
и задача: журнал и псевдоэталон их не оценивают. Протокол и числа записаны в evaluation/feed_eval.py
и evaluation/track1-feed.md.

Пройденный материал в ленту не входит и остаётся в истории (решение 13.9).
"""

from __future__ import annotations

import heapq
import math
from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass, field

from .. import vocab
from ..catalog.lexicon import parse_task
from ..catalog.models import Catalog, CoursePairs, HistoryEvent, Material
from . import explain, personal
from .base import CoEnrollment, Context, HistoryIndex, Profile, Scored, sort_key
from .policy import eligible

FEED_MAX_LIMIT = 50
FEED_WEIGHTS: dict[str, float] = {
    "co_enrollment": 12.0,  # курсы с журналом записей
    "content": 1.7,  # материалы без журнала
    "continuation": 0.5,  # материалы без журнала
    "popularity": 1.0,
    "access": 0.2,
}
# Сколько общих признаков называет фраза о сходстве с историей и сколько тем показывает профиль интересов
CONTENT_EVIDENCE_FEATURES = 2
INTEREST_TOPICS = 5

# Источник → подпись и вклады, которые в него входят. Порядок — порядок легенды на экране
SOURCES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("progress", "Начатое", ("in_progress",)),
    ("history", "Выбор слушателей", ("co_enrollment",)),
    ("content", "Похожее содержание", ("content",)),
    ("links", "Совет редакции", ("continuation",)),
    ("task", "Задача", ("topic", "signal")),
    ("profile", "Анкета", ("stage", "level", "industry", "format", "effort")),
    ("access", "Доступ и цена", ("access",)),
    ("popularity", "Популярность", ("popularity",)),
    ("seen", "Уже открывали", ("viewed",)),
)
SOURCE_LABELS: dict[str, str] = {code: label for code, label, _ in SOURCES}
# Источники, одинаковые для всех клиентов: в строке причины они уступают источникам о самом клиенте
GENERAL_SOURCES = frozenset({"popularity", "access"})
PROFILE_FIELDS: dict[str, str] = {
    "stage": "стадия", "level": "уровень", "industry": "сфера", "format": "формат", "effort": "короткий материал",
}
_EVENT_ORDER = ("purchase", "complete", "start", "view")
EVENT_LABELS: dict[str, str] = {"purchase": "Куплено", "complete": "Пройдено", "start": "Начато", "view": "Открывали"}


@dataclass(frozen=True, slots=True)
class Part:
    """Вклад одного источника в оценку карточки и фраза-свидетельство."""

    source: str
    value: float
    evidence: str | None
    note: str | None = None  # как считается вклад, если его считает модель, а не формула из свидетельства


@dataclass(frozen=True, slots=True)
class FeedItem:
    scored: Scored
    parts: tuple[Part, ...]

    @property
    def reason(self) -> str:
        """Одна строка для карточки: свидетельство источника с наибольшим положительным вкладом.

        Первым берётся источник, который говорит о самом клиенте: история, анкета или задача. Популярность
        и доступ называются, только если таких вкладов у карточки нет.
        """
        positive = [part for part in self.parts if part.value > 0 and part.evidence]
        personal_first = sorted(positive, key=lambda part: part.source in GENERAL_SOURCES)  # сортировка устойчива
        return personal_first[0].evidence or "" if personal_first else ""


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    material_id: str
    title: str | None  # None — материала нет в каталоге
    format: str | None
    event: str


@dataclass(slots=True)
class Feed:
    status: str  # history — в истории есть материалы каталога; cold — истории нет
    items: list[FeedItem]
    total_candidates: int
    history: list[HistoryEntry] = field(default_factory=list)
    interests: list[tuple[str, float]] = field(default_factory=list)  # подпись темы → доля в профиле интересов
    facts: list[tuple[str, str | None, str]] = field(default_factory=list)  # поле, значение, происхождение
    sources: list[tuple[str, float]] = field(default_factory=list)  # источник → доля в оценках показанных карточек


def _features(material: Material) -> tuple[str, ...]:
    """Признаки содержания: темы, признаки текста, стадии, уровень и сферы."""
    out = [f"topic:{t}" for t in material.topics]
    out += [f"signal:{code}" for code, _ in material.signals]
    out += [f"stage:{s}" for s in material.stages]
    if material.level:
        out.append(f"level:{material.level}")
    out += [f"industry:{i}" for i in material.industries]
    return tuple(dict.fromkeys(out))


def _feature_label(feature: str) -> tuple[bool, str]:
    """(это тема?, подпись). Темой для пользователя называются и каноническая тема, и признак текста."""
    kind, _, code = feature.partition(":")
    if kind == "topic":
        return True, f"«{vocab.topic_label(code)}»"
    if kind == "signal":
        return True, f"«{vocab.signal_label(code)}»"
    if kind == "stage":
        return False, f"стадия «{vocab.STAGES[code][1]}»" if code in vocab.STAGES else f"стадия «{code}»"
    if kind == "level":
        return False, f"уровень «{vocab.level_label(code)}»"
    return False, f"сфера «{vocab.INDUSTRIES[code][1]}»" if code in vocab.INDUSTRIES else f"сфера «{code}»"


@dataclass(frozen=True, slots=True)
class _Index:
    """Признаки содержания каталога и их редкость. Считается один раз на каталог, а не на запрос."""

    features: dict[str, tuple[str, ...]]
    idf: dict[str, float]
    norms: dict[str, float]  # длина вектора редкостей материала
    unseen: float  # редкость признака, которого нет у доступных материалов

    @classmethod
    def build(cls, materials: dict[str, Material]) -> _Index:
        features = {code: _features(material) for code, material in materials.items()}
        available = [code for code, material in materials.items() if material.available]
        frequency = Counter(f for code in available for f in features[code])
        total = max(len(available), 1)
        idf = {f: math.log(1 + total / n) for f, n in frequency.items()}
        norms = {code: math.sqrt(sum(idf.get(f, 0.0) ** 2 for f in own)) for code, own in features.items()}
        return cls(features=features, idf=idf, norms=norms, unseen=math.log(1 + total))


# Каталог загружается при запуске и не меняется, поэтому индекс хранится по объекту словаря материалов.
# Несколько записей: каталог ленты, каталог подбора по задаче и каталоги частей в офлайн-оценке
_INDEX_CACHE: dict[int, tuple[dict[str, Material], _Index]] = {}
_INDEX_CACHE_SIZE = 8


def _index(catalog: Catalog) -> _Index:
    cached = _INDEX_CACHE.get(id(catalog.materials))
    if cached is not None and cached[0] is catalog.materials:
        return cached[1]
    index = _Index.build(catalog.materials)
    if len(_INDEX_CACHE) >= _INDEX_CACHE_SIZE:
        _INDEX_CACHE.pop(next(iter(_INDEX_CACHE)))
    _INDEX_CACHE[id(catalog.materials)] = (catalog.materials, index)
    return index


@dataclass(frozen=True, slots=True)
class _Interests:
    """Профиль интересов: сумма признаков материалов истории с весами по редкости признака в каталоге."""

    index: _Index
    weights: dict[str, float]  # признак → вес в профиле
    counts: dict[str, int]  # признак → число материалов истории с ним
    norm: float

    @classmethod
    def build(cls, history: list[str], index: _Index) -> _Interests:
        weights: dict[str, float] = {}
        counts: dict[str, int] = {}
        for material_id in sorted(history):
            for f in index.features.get(material_id, ()):
                weights[f] = weights.get(f, 0.0) + index.idf.get(f, index.unseen)
                counts[f] = counts.get(f, 0) + 1
        norm = math.sqrt(sum(w * w for w in weights.values()))
        return cls(index=index, weights=weights, counts=counts, norm=norm)

    def _shared(self, material: Material) -> dict[str, float]:
        """Общие признаки профиля и материала: признак → его доля в скалярном произведении."""
        idf, weights = self.index.idf, self.weights
        return {f: weights[f] * idf[f] for f in self.index.features.get(material.id, ()) if f in weights and f in idf}

    def cosine(self, material: Material) -> float:
        """Косинус между профилем интересов и материалом; 0 без истории и без общих признаков."""
        norm = self.index.norms.get(material.id, 0.0)
        if not self.norm or not norm:
            return 0.0
        return sum(self._shared(material).values()) / (self.norm * norm)

    def shared(self, material: Material) -> list[str]:
        """Общие признаки по убыванию их доли в скалярном произведении: для фразы-свидетельства."""
        shared = self._shared(material)
        return sorted(shared, key=lambda f: (-shared[f], f))

    def leading(self, kind: str) -> list[str]:
        """Коды признака вида `kind`, которые чаще всего встречаются у материалов истории; при равенстве — все."""
        own = {f.partition(":")[2]: n for f, n in self.counts.items() if f.startswith(kind + ":")}
        top = max(own.values(), default=0)
        return [code for code, n in own.items() if n == top]

    def topics(self) -> list[tuple[str, float]]:
        own = {f.partition(":")[2]: w for f, w in self.weights.items() if f.startswith("topic:")}
        total = sum(own.values())
        ordered = sorted(own, key=lambda t: (-own[t], t))[:INTEREST_TOPICS]
        return [(vocab.topic_label(t), round(own[t] / total, 2)) for t in ordered] if total else []


def _client_wording(phrase: str | None) -> str | None:
    """Фразы подбора по задаче обращены к пользователю; ленту смотрят со стороны, поэтому история — клиента."""
    return phrase.replace("из вашей истории", "из истории клиента") if phrase else phrase


def _content_phrase(shared: list[str]) -> str:
    """«Похоже на материалы из истории: темы «A» и «B»» или «…: тема «A» и стадия «…»».

    Называются самые весомые общие признаки. Число признаков — CONTENT_EVIDENCE_FEATURES.
    """
    labels = [_feature_label(f) for f in shared[:CONTENT_EVIDENCE_FEATURES]]
    topics = [label for is_topic, label in labels if is_topic]
    parts = [f"{'темы' if len(topics) > 1 else 'тема'} {explain.join_ru(topics)}"] if topics else []
    parts += [label for is_topic, label in labels if not is_topic]
    return f"Похоже на материалы из истории: {explain.join_ru(parts)}"


def _popularity_phrase(material: Material, same_format: list[float], measured: bool) -> str:
    """Место среди допустимых материалов того же формата и то, что измеряет популярность.

    `measured` — источник каталога сам считает популярность: в выгрузке SQLite у курсов это записи, у остальных
    форматов — редакционные ссылки на материал (docs/plan.md, 2.2). Просмотров статей в данных нет, и фраза
    этого не скрывает. У каталога из JSON мера популярности неизвестна, фраза её не называет.
    """
    place = 1 + sum(1 for value in same_format if value > material.popularity)
    course, count = material.format == "course", len(same_format)
    # После «из» стоит родительный падеж: «из 21 курса», «из 31 материала», «из 5 курсов»
    among = (
        f"{count} {explain.plural(count, 'курса', 'курсов', 'курсов')}" if course
        else f"{count} {explain.plural(count, 'материала', 'материалов', 'материалов')} того же формата"
    )
    if not measured:
        return f"По популярности {place}-е место из {among}"
    return f"По числу {'записей' if course else 'редакционных ссылок'} {place}-е место из {among}"


def _access_phrase(material: Material, payer: bool) -> str:
    label = vocab.ACCESS[material.access]
    if payer:
        return f"В истории есть оплаченная запись, поэтому материал с доступом «{label}» получает надбавку"
    return f"Оплаченных записей в истории нет, поэтому оценка материала с доступом «{label}» снижена"


def _by_log(material: Material, signals: _Signals) -> bool:
    """Курс оценивается выбором слушателей, а не содержанием: в истории клиента есть курс с журналом записей."""
    return material.format == "course" and signals.behaviour


def _co_enrollment(
    material: Material, anchors: list[str], pairs: CoursePairs | None
) -> tuple[float, CoEnrollment | None]:
    """S1: выбор слушателей курсов истории в единицах доли слушателей.

    С весами модели EASE (`catalog/ease.py`) это сумма весов курсов истории для кандидата. Верхней границы у неё
    нет, отрицательная сумма остаётся вычетом. Без весов это сумма долей слушателей, записанных и на кандидата,
    не больше 1: так считаются пары, заданные без файла, и каталог, где курсов больше предела модели.
    Учитываются курсы истории не меньше чем с CO_ENROLLMENT_MIN_ANCHOR_USERS слушателями. Для фразы берётся курс
    истории с наибольшим слагаемым, при равенстве тот, у которого событие позже: якоря идут от последнего события.
    Числа N из M во фразе остаются счётчиками этой пары. У пары ниже порога поддержки N равно нулю, и фраза чисел
    не называет.
    """
    if pairs is None or material.format != "course":
        return 0.0, None
    modelled = bool(pairs.weights)
    total, best = 0.0, None
    for anchor in anchors:
        users = pairs.totals.get(anchor, 0)
        if anchor == material.id or users < personal.CO_ENROLLMENT_MIN_ANCHOR_USERS:
            continue
        together = pairs.neighbours(anchor).get(material.id, 0)
        term = pairs.weight(anchor, material.id) if modelled else together / users
        if not term:
            continue
        total += term
        if best is None or term > best[0]:
            best = (term, CoEnrollment(anchor=anchor, together=together, total=users))
    if best is None:
        return 0.0, None
    return (total if modelled else min(1.0, total)), best[1]


def _listeners_phrase(item: Scored, ctx: Context) -> str | None:
    """Свидетельство вклада «Выбор слушателей»: запись журнала с наибольшим весом.

    Положительный вклад с парой от порога поддержки называет счётчики N из M. Пара ниже порога чисел не называет.
    У вычета счётчиков нет: он говорит, что слушатели курсов истории берут этот курс реже ожидаемого.
    """
    pair = item.co_enrollment
    if pair is None:
        return None
    if item.contributions.get("co_enrollment", 0.0) < 0:
        return "Слушатели курсов из истории клиента выбирают этот курс реже, чем следует из остальных их записей"
    if pair.together > 0:
        return _client_wording(explain.feature_phrase("co_enrollment", item, ctx))
    source = ctx.catalog.get(pair.anchor)
    if source is None:
        return None
    return f"По журналу записей курс связан с курсом «{explain.course_name(source.title)}» из истории клиента"


# Пояснение к вкладу, который считает модель: фраза-свидетельство называет запись, а не формулу вклада
LISTENERS_NOTE = (
    "Величину вклада считает модель по журналу записей. Она учитывает все курсы истории и то, как часто этот "
    "курс выбирают слушатели остальных курсов, поэтому вклад не равен доле из свидетельства"
)


def _parts(
    item: Scored, ctx: Context, evidence: dict[str, str | None], notes: dict[str, str] | None = None
) -> tuple[Part, ...]:
    """Вклады по источникам. Сумма значений равна оценке: и вклады, и оценка округлены до сотых.

    `notes` — пояснения к источникам, вклад которых считает модель: источник → текст.
    """
    parts: list[Part] = []
    for source, _, features in SOURCES:
        present = {f: item.contributions[f] for f in features if f in item.contributions}
        if not present:
            continue
        # Свидетельство — фраза признака с наибольшим вкладом, у которого она есть. Уровень при точном
        # совпадении, формат и усилие своих фраз не имеют: тогда источник называет совпавшие поля анкеты
        ordered = sorted(present, key=lambda f: (-abs(present[f]), f))
        phrases = (evidence.get(f) or explain.feature_phrase(f, item, ctx) for f in ordered)
        phrase = next((p for p in phrases if p), None)
        if phrase is None and source == "profile":
            phrase = f"Совпадает с анкетой: {explain.join_ru([PROFILE_FIELDS[f] for f in ordered])}"
        note = notes.get(source) if notes else None
        parts.append(Part(source=source, value=round(sum(present.values()), 2), evidence=phrase, note=note))
    parts.sort(key=lambda p: -p.value)
    return tuple(parts)


def _history_entries(history: tuple[HistoryEvent, ...], catalog: Catalog) -> list[HistoryEntry]:
    latest: dict[str, int] = {}
    events: dict[str, set[str]] = {}
    for e in history:
        latest[e.material_id] = max(latest.get(e.material_id, e.seq), e.seq)
        events.setdefault(e.material_id, set()).add(e.event)
    entries = []
    for material_id in sorted(latest, key=lambda m: (-latest[m], m)):
        material = catalog.materials.get(material_id)
        event = next(code for code in _EVENT_ORDER if code in events[material_id])
        entries.append(HistoryEntry(
            material_id=material_id, title=material.title if material else None,
            format=material.format if material else None, event=event,
        ))
    return entries


FACT_STATED, FACT_INFERRED, FACT_UNKNOWN = "указано в анкете", "выведено из истории", "не указано"


def _fact(
    name: str, stated: str | None, inferred: list[str], labels: dict[str, tuple[str, str]]
) -> tuple[str, str | None, str]:
    """Поле профиля с подписью происхождения: анкета важнее вывода из истории.

    Выведенных значений может быть несколько: у курса истории бывают две стадии. Порядок — как в словаре.
    """
    if stated in labels:
        return name, labels[stated][1], FACT_STATED
    found = [labels[code][1] for code in labels if code in inferred]
    if found:
        return name, ", ".join(found), FACT_INFERRED
    return name, None, FACT_UNKNOWN


@dataclass(frozen=True, slots=True)
class _Signals:
    """Что история клиента даёт оценке: якоря S1, профиль S2, связи S3, признак оплат."""

    history: HistoryIndex
    interests: _Interests
    pairs: CoursePairs | None
    anchors: list[str]  # курсы истории от последнего события к первому
    behaviour: bool  # среди них есть курс с журналом: не меньше порога слушателей в файле пар
    linked: dict[str, str]  # материал → материал истории, который на него ссылается
    payer: bool
    access_weight: float


@dataclass(slots=True)
class Ranking:
    """Кандидаты ленты по убыванию оценки и то, что нужно для объяснения и офлайн-оценки."""

    items: list[Scored]
    ctx: Context
    signals: _Signals
    entries: list[HistoryEntry]
    pool: int  # допустимых материалов, из которых отобрана лента
    popularity: dict[str, list[float]]  # формат → популярность допустимых материалов
    measured: bool  # источник каталога считает популярность по записям и редакционным ссылкам

    @property
    def order(self) -> list[str]:
        return [item.material.id for item in self.items]

    def evidence(self, item: Scored) -> dict[str, str | None]:
        """Фразы-свидетельства вкладов карточки. Считаются только для показанных карточек."""
        material, present = item.material, item.contributions
        own: dict[str, str | None] = {}
        if "co_enrollment" in present:
            own["co_enrollment"] = _listeners_phrase(item, self.ctx)
        if "continuation" in present:
            own["continuation"] = _client_wording(explain.feature_phrase("continuation", item, self.ctx))
        if "content" in present:
            own["content"] = _content_phrase(self.signals.interests.shared(material))
        if "popularity" in present:
            own["popularity"] = _popularity_phrase(material, self.popularity[material.format], self.measured)
        if "access" in present:
            own["access"] = _access_phrase(material, self.signals.payer)
        if "in_progress" in present:
            own["in_progress"] = "Материал начат и не пройден"
        if "viewed" in present:
            own["viewed"] = "Материал уже открывали"
        return own


def _select(scored: list[Scored], limit: int | None) -> list[Scored]:
    """Первые `limit` кандидатов по оценке, затем по популярности и коду; без предела — все."""
    return heapq.nsmallest(len(scored) if limit is None else limit, scored, key=sort_key)


def _score(material: Material, ctx: Context, signals: _Signals) -> Scored:
    """Оценка одного кандидата: вклады общего кода и источники ленты, округлённые до сотых."""
    item = personal.score_material(material, ctx)
    if signals.history.of(material.id):
        pass  # материал из истории сам себе не свидетельство
    elif _by_log(material, signals):
        share, pair = _co_enrollment(material, signals.anchors, signals.pairs)
        if pair is not None:
            item.co_enrollment = pair
            item.add("co_enrollment", FEED_WEIGHTS["co_enrollment"] * share)
    else:
        item.add("content", FEED_WEIGHTS["content"] * signals.interests.cosine(material))
        if material.id in signals.linked:
            item.continuation_of = signals.linked[material.id]
            item.add("continuation", FEED_WEIGHTS["continuation"])
    item.add("popularity", FEED_WEIGHTS["popularity"] * material.popularity)
    if material.is_paid:
        # Вклад несут только платные материалы: надбавка у клиента с оплатами, вычет у клиента без оплат.
        # Порядок тот же, что при надбавке бесплатным, а у большинства карточек на одно слагаемое меньше
        item.add("access", signals.access_weight if signals.payer else -signals.access_weight)
    # Оценка ленты — сумма вкладов, округлённых до сотых: числа на экране сходятся без остатка,
    # а порядок задаёт та же сумма, что видит пользователь
    item.contributions = {f: round(v, 2) for f, v in item.contributions.items() if round(v, 2)}
    item.score = round(sum(item.contributions.values()), 2)
    return item


def rank(
    catalog: Catalog,
    profile: Profile,
    price_weight: float | None = None,
    *,
    limit: int | None = None,
    only: Collection[str] | None = None,
) -> Ranking:
    """Оценка допустимых материалов и отбор ленты. `only` ограничивает кандидатов кодами, каталог остаётся целым.

    Офлайн-оценка задаёт `only` курсами: так редкость признаков и пары считаются по тому же каталогу, что в продукте.
    """
    payer = any(event.event == "purchase" for event in profile.history)
    parsed = parse_task(profile.task)
    history = HistoryIndex.build(profile.history)
    pool = [m for m in eligible(catalog, history) if "complete" not in history.of(m.id)]
    candidates = pool if only is None else [m for m in pool if m.id in only]
    # Вклады анкеты, задачи и пометок истории считает общий код. Совместные записи и редакционные связи лента
    # считает сама, со своими весами: поэтому пары и якоря в контекст не передаются
    ctx = Context(
        profile=profile, parsed=parsed, topics=(profile.topic,) if profile.topic else parsed.topics,
        history=history, disabled=frozenset(catalog.disabled_features) | {"continuation"}, catalog=catalog.materials,
    )
    entries = _history_entries(profile.history, catalog)
    known = [e.material_id for e in entries if e.material_id in catalog.materials]  # от последнего события
    linked: dict[str, str] = {}
    if "continuation" not in catalog.disabled_features:
        for code in known:
            for target in catalog.materials[code].recommended_next:
                linked.setdefault(target, code)
    pairs = None if "co_enrollment" in catalog.disabled_features else catalog.course_pairs
    anchors = [code for code in known if catalog.materials[code].format == "course"]
    enough = personal.CO_ENROLLMENT_MIN_ANCHOR_USERS
    signals = _Signals(
        history=history,
        interests=_Interests.build(known, _index(catalog)),
        pairs=pairs,
        anchors=anchors,
        behaviour=pairs is not None and any(pairs.totals.get(code, 0) >= enough for code in anchors),
        linked=linked,
        payer=payer,
        access_weight=FEED_WEIGHTS["access"] if price_weight is None else price_weight,
    )
    popularity: dict[str, list[float]] = {}
    for material in pool:
        popularity.setdefault(material.format, []).append(material.popularity)
    selected = _select([_score(material, ctx, signals) for material in candidates], limit)
    return Ranking(
        items=selected, ctx=ctx, signals=signals, entries=entries, pool=len(pool), popularity=popularity,
        measured=catalog.source == "sqlite",
    )


def build_feed(catalog: Catalog, profile: Profile, limit: int = 20, price_weight: float | None = None) -> Feed:
    """Лента: первые `limit` допустимых материалов, кроме пройденных, по истории, анкете и задаче профиля.

    `price_weight` — вес источника «доступ и цена», по умолчанию FEED_WEIGHTS["access"]; ноль выключает учёт цены.
    У клиента с оплаченной записью платные и подписочные материалы получают надбавку, у клиента без оплат —
    вычет: при равной пользе выше бесплатный материал.
    """
    if not 1 <= limit <= FEED_MAX_LIMIT:
        raise ValueError(f"limit вне диапазона 1–{FEED_MAX_LIMIT}")
    ranking = rank(catalog, profile, price_weight, limit=limit)
    pairs = ranking.signals.pairs
    notes = {"history": LISTENERS_NOTE} if pairs is not None and pairs.weights else None
    items = [
        FeedItem(scored=item, parts=_parts(item, ranking.ctx, ranking.evidence(item), notes)) for item in ranking.items
    ]
    positive: dict[str, float] = {}
    for entry in items:
        for part in entry.parts:
            if part.value > 0:
                positive[part.source] = positive.get(part.source, 0.0) + part.value
    total = sum(positive.values())
    shares = [(code, round(positive[code] / total, 2)) for code, _, _ in SOURCES if code in positive] if total else []
    interests = ranking.signals.interests
    facts = [
        _fact("Стадия бизнеса", profile.stage, interests.leading("stage"), vocab.STAGES),
        _fact("Сфера", profile.industry, interests.leading("industry"), vocab.INDUSTRIES),
    ]
    return Feed(
        status="history" if any(e.title is not None for e in ranking.entries) else "cold",
        items=items, total_candidates=ranking.pool, history=ranking.entries, interests=interests.topics(),
        sources=shares, facts=facts,
    )
