"""Локальный индекс словоформ в названиях и кратких описаниях курсов."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

import snowballstemmer  # type: ignore[import-untyped]

from .lexicon import tokenize

if TYPE_CHECKING:
    from .models import Material

ABBREVIATIONS = frozenset("оквэд усн осно нпд ндс ндфл енп енс crm kpi seo".split())
QUALIFIERS = frozenset("ип ооо ао".split())
STOP_WORDS = frozenset(
    """
    как где что какой какую какие какое для по на в во о об про и или с со из к у за от до при мне мы
    хочу нужно нужна нужен нужны надо подскажите выбрать подобрать найти взять составить оформить
    заполнить посчитать рассчитать шаблон образец документ курс вебинар статья видео подкаст
    """.split()
)


def _words(text: str) -> Iterator[str]:
    for token in tokenize(text):
        yield from token.split("-")


def _stems(words: Iterable[str]) -> Iterator[str]:
    stemmer = snowballstemmer.stemmer("russian")
    for word in words:
        yield f"={word}" if word in ABBREVIATIONS or word in QUALIFIERS else stemmer.stemWord(word)


def _keys(words: Iterable[str]) -> set[str]:
    return set(_stems(words))


def _intersection(index: dict[str, set[str]], keys: set[str]) -> frozenset[str]:
    postings = sorted((index.get(key, set()) for key in keys), key=len)
    return frozenset(postings[0].intersection(*postings[1:])) if postings else frozenset()


@dataclass(frozen=True, slots=True)
class TextMatches:
    titles: frozenset[str] = frozenset()
    descriptions: frozenset[str] = frozenset()
    qualified: frozenset[str] = frozenset()

    def priority(self, material_id: str) -> int:
        if material_id in self.titles:
            return 3 if material_id in self.qualified else 2
        return 1 if material_id in self.descriptions else 0


MIN_KEYWORDS = 2


class TextIndex:
    def __init__(self, materials: Iterable[Material]) -> None:
        self.titles: dict[str, set[str]] = defaultdict(set)
        self.descriptions: dict[str, set[str]] = defaultdict(set)
        for material in materials:
            if not material.available:
                continue
            for key in _keys(_words(material.title)):
                self.titles[key].add(material.id)
            if material.format == "course" and material.course_details and material.course_details.description:
                for key in _keys(_words(material.course_details.description)):
                    self.descriptions[key].add(material.id)

    def match(self, query: str) -> TextMatches:
        words = set(_words(query))
        keys = _keys(words - STOP_WORDS - QUALIFIERS)
        if len(keys) < MIN_KEYWORDS and not words.intersection(ABBREVIATIONS):
            return TextMatches()
        titles = _intersection(self.titles, keys)
        descriptions = _intersection(self.descriptions, keys) if len(keys) >= MIN_KEYWORDS else frozenset()
        qualified = titles & _intersection(self.titles, _keys(words & QUALIFIERS))
        return TextMatches(titles, descriptions, qualified)
