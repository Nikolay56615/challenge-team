"""Поиск действия и объекта задачи в карточках локального каталога."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import log1p
from statistics import mean

from .models import Material
from .text_search import ABBREVIATIONS, QUALIFIERS, STOP_WORDS, _stems, _words


@dataclass(frozen=True, slots=True)
class Intent:
    object: re.Pattern[str]
    action: re.Pattern[str]
    conflict: re.Pattern[str] | None = None

    def matches(self, text: str) -> bool:
        return bool(
            self.object.search(text)
            and self.action.search(text)
            and (self.conflict is None or not self.conflict.search(text))
        )


INTENTS = (
    Intent(
        re.compile(r"\b(?:налогов\w* режим\w*|(?:систем|вариант)\w* налогообложен\w*)\b"),
        re.compile(r"\b(?:выбр\w*|выбор\w*|подобр\w*|подход\w*|сравн\w*|перейти|смен\w*|режимы|системы)\b"),
    ),
    Intent(
        re.compile(r"\b(?:сотрудник\w*|работник\w*|персонал\w*|человек\w*|штат\w*|на работ\w*)\b"),
        re.compile(r"\b(?:наня\w*|наем\w*|найм\w*|наним\w*|трудоустр\w*|прием\w*|оформ\w*)\b"),
        re.compile(r"\b(?:отпуск|увол|больничн|командиров|ндфл|сокращен)\w*"),
    ),
    Intent(
        re.compile(r"\b(?:маркетплейс\w*|маркет плейс\w*|селлер\w*)\b"),
        re.compile(
            r"\b(?:нача\w*|выход\w*|выйти|старт\w*|с нуля|как прода\w* на маркет\w*|перв\w* (?:онлайн )?витрин\w*)\b"
        ),
    ),
    Intent(
        re.compile(r"\b(?:оквэд|код\w* (?:вид\w* )?деятельност\w*|вид\w* деятельности)\b"),
        re.compile(r"\b(?:выбр\w*|выбор\w*|указ\w*|обознач\w*|поменя\w*|регистрац\w*|запуск\w*)\b"),
    ),
    Intent(
        re.compile(r"\b(?:штатн\w* расписан\w*|ставк\w* сотрудник\w*|должност\w* и оклад\w*)\b"),
        re.compile(r"\b(?:состав\w*|перечисл\w*|опис\w*|форма т 3)\b"),
    ),
    Intent(
        re.compile(r"\b(?:трудов\w* договор\w*|сотрудник\w*|работник\w*|работодатель\w*|штат\w*|увольнен\w*)\b"),
        re.compile(r"\b(?:увол\w*|расторг\w*|расторж\w*|уход\w* из штат\w*)\b"),
    ),
)

TITLE = "в названии"
ARTICLE_DESCRIPTION = "в описании статьи"
COURSE_DESCRIPTION = "в кратком описании курса"
COURSE_AUDIENCE = "в разделе «Кому подойдёт»"
COURSE_OUTCOMES = "в результатах обучения"
ARTICLE_PARAGRAPH = "в тексте статьи"


def _intents(text: str) -> frozenset[int]:
    normalized = " ".join(_words(text))
    return frozenset(i for i, intent in enumerate(INTENTS) if intent.matches(normalized))


@dataclass(frozen=True, slots=True)
class Evidence:
    field: str
    intent: bool = False
    score: float = 0.0


@dataclass(frozen=True, slots=True)
class Field:
    label: str
    weight: float
    terms: Counter[str]
    intents: frozenset[int]

    @classmethod
    def prepare(cls, text: str, label: str, weight: float) -> Field:
        terms = Counter(_stems(word for word in _words(text) if word not in STOP_WORDS and word not in QUALIFIERS))
        return cls(label, weight, terms, _intents(text))

    def bm25(self, weights: Mapping[str, float], average_length: float) -> float:
        normalization = 1.2 * (0.25 + 0.75 * self.terms.total() / average_length)
        return self.weight * sum(
            weights[key] * (2.2 * count) / (count + normalization) for key in weights if (count := self.terms[key])
        )


def _fields(material: Material, description: str | None, metadata: bool) -> Iterable[Field]:
    yield Field.prepare(material.title, TITLE, 3)
    if metadata and description:
        yield Field.prepare(description, ARTICLE_DESCRIPTION, 1)
    if metadata and (details := material.course_details):
        if details.description:
            yield Field.prepare(details.description, COURSE_DESCRIPTION, 1)
        for label, values in ((COURSE_AUDIENCE, details.audiences), (COURSE_OUTCOMES, details.outcomes)):
            for text in values:
                yield Field.prepare(text, label, 0.5)


MIN_KEYWORDS = 2


class TaskIndex:
    def __init__(
        self,
        materials: Iterable[Material],
        descriptions: Mapping[str, str] | None = None,
        *,
        metadata: bool = True,
        passages: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        descriptions = descriptions or {}
        self.fields: dict[str, tuple[Field, ...]] = {}
        self.terms: dict[str, frozenset[str]] = {}
        self.metadata = metadata
        lengths: dict[str, list[int]] = {}
        self.frequencies: Counter[str] = Counter()
        self.passages: dict[str, tuple[Field, ...]] = {}
        for material in materials:
            if not material.available:
                continue
            description = (
                descriptions.get(material.id) if material.format == "article" and material.access == "open" else None
            )
            fields = tuple(_fields(material, description, metadata))
            self.fields[material.id] = fields
            terms = frozenset().union(*(field.terms for field in fields))
            self.terms[material.id] = terms
            self.frequencies.update(terms)
            for field in fields:
                if field.terms:
                    lengths.setdefault(field.label, []).append(field.terms.total())
            if passages and material.format == "article" and material.access == "open":
                article = []
                for text in passages.get(material.id, ()):
                    field = Field.prepare(text, ARTICLE_PARAGRAPH, 1)
                    if field.intents and field.terms:
                        article.append(field)
                        lengths.setdefault(field.label, []).append(field.terms.total())
                if article:
                    self.passages[material.id] = tuple(article)
        self.lengths = {label: mean(values) for label, values in lengths.items()}

    def match(self, query: str, candidates: Iterable[str]) -> dict[str, Evidence]:
        if not query.strip():
            return {}
        intents = _intents(query)
        words = set(_words(query)) - STOP_WORDS - QUALIFIERS
        keys = sorted(set(_stems(words)))
        if not intents and (not self.metadata or len(keys) < MIN_KEYWORDS):
            return {}
        required = max(2, (2 * len(keys) + 2) // 3)
        abbreviations = {f"={word}" for word in words & ABBREVIATIONS}
        weights = {
            key: log1p((len(self.fields) - count + 0.5) / (count + 0.5))
            for key in keys
            if (count := self.frequencies[key])
        }
        found = {}
        for material_id in candidates:
            terms = self.terms.get(material_id)
            if terms is None or not abbreviations <= terms:
                continue
            fields = self.fields[material_id]
            confirmed = next((field for field in fields if intents & field.intents), None)
            if confirmed:
                found[material_id] = Evidence(confirmed.label, intent=True)
            elif self.metadata and sum(key in terms for key in keys) >= required:
                # Each field contributes at most once, including repeated course bullets.
                scores: dict[str, float] = {}
                for field in fields:
                    score = field.bm25(weights, self.lengths.get(field.label, 1))
                    scores[field.label] = max(score, scores.get(field.label, 0))
                label = max(scores, key=scores.__getitem__)
                confirmed_words = sum(any(field.label == label and key in field.terms for field in fields)
                                      for key in keys)
                if confirmed_words < MIN_KEYWORDS:
                    label = "в данных карточки"
                found[material_id] = Evidence(label, score=sum(scores.values()))
            else:
                paragraphs = (p for p in self.passages.get(material_id, ()) if intents & p.intents)
                score = max((1 + p.bm25(weights, self.lengths[ARTICLE_PARAGRAPH]) for p in paragraphs), default=0)
                if score:
                    found[material_id] = Evidence(ARTICLE_PARAGRAPH, score=score)
        return found
