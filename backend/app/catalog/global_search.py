"""FTS5 и опциональные векторы карточек одного снимка SQLite."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from hashlib import file_digest, sha256
from math import log1p
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any

from ..config import Settings
from .models import Catalog
from .neural_rank import LocalModel
from .semantic import Encoder
from .text_search import ABBREVIATIONS, QUALIFIERS, STOP_WORDS, _stems, _words

log = logging.getLogger(__name__)
INDEX_SCHEMA = 3
MODES = ("lexical", "semantic", "hybrid")
MODEL_FILES = ("model.onnx", "tokenizer.json")
DEFAULT_THRESHOLDS = {"lexical": [0.58, 0.88], "semantic": [0.84, 0.93]}
ALIASES = (
    ("озон", "ozon"),
    ("wildberries", "вайлдберриз", "вб"),
    ("яндекс маркет", "яндекс маркете"),
    ("мегамаркет", "мегамаркете"),
    ("усн", "упрощенная система налогообложения", "упрощенной системе налогообложения", "упрощенка"),
    ("ндс", "налог на добавленную стоимость"),
    ("нпд", "налог на профессиональный доход"),
    ("россия", "рф", "россии"),
    ("казахстан", "казахстане"),
    ("беларусь", "беларуси", "белоруссия"),
    ("сша", "соединенные штаты"),
    ("техас", "техасе"),
    ("китай", "китае"),
    ("канада", "канаде"),
    ("квебек", "квебеке"),
    ("исландия", "исландии"),
    ("фиджи",),
    ("япония", "японии", "японскую", "японская", "японский", "японском"),
    ("токио",),
    ("новая зеландия", "новой зеландии", "новозеландский"),
    ("финляндия", "финляндии"),
    ("франция", "франции"),
    ("австралия", "австралии"),
    ("швейцария", "швейцарии"),
    ("дания", "дании"),
    ("норвегия", "норвегии"),
    ("португалия", "португалии"),
    ("мексика", "мексике"),
    ("индонезия", "индонезии"),
    ("сингапур", "сингапуре"),
    ("чили",),
    ("юар",),
    ("rakuten",),
    ("mercado libre",),
)
NORMALIZED_ALIASES = {form: group[0] for group in ALIASES for form in group}
ALIAS_PATTERN = re.compile(
    r"\b(?:"
    + "|".join(re.escape(form) for form in sorted(NORMALIZED_ALIASES, key=lambda form: (-len(form), form)))
    + r")\b"
)
NEGATION = re.compile(r"\bбез (?:уплаты |учета )?(ндс|ндфл)\b")
YEAR = re.compile(r"\b20\d\d\b")


def _terms(text: str) -> list[str]:
    normalized = " ".join(_words(text))
    normalized = ALIAS_PATTERN.sub(lambda match: NORMALIZED_ALIASES[match[0]], normalized)
    return [
        term.removeprefix("=")
        for term in _stems(word for word in normalized.split() if word not in STOP_WORDS and word not in QUALIFIERS)
    ]


def _constraints(text: str) -> tuple[frozenset[str], frozenset[str]]:
    words = " ".join(_words(text))
    padded = f" {words} "
    negated = frozenset(NEGATION.findall(words))
    aliases = {group[0] for group in ALIASES if any(f" {form} " in padded for form in group)}
    return frozenset((set(words.split()) & ABBREVIATIONS | aliases | set(YEAR.findall(words))) - negated), negated


@dataclass(frozen=True, slots=True)
class Card:
    id: str
    title: str
    description: str = ""
    details: str = ""

    @property
    def text(self) -> str:
        return "\n".join(part for part in (self.title, self.description, self.details) if part)


@dataclass(frozen=True, slots=True)
class Hit:
    score: float
    strong: bool
    reason: str


class SearchUnavailable(RuntimeError):
    pass


def cards_for(catalog: Catalog, descriptions: dict[str, str]) -> list[Card]:
    cards = []
    for item in sorted(catalog.materials.values(), key=lambda m: m.id):
        if not item.available:
            continue
        course = item.course_details
        details = "\n".join((*course.audiences, *course.outcomes)) if course else ""
        description = (course.description if course else descriptions.get(item.id)) or ""
        cards.append(Card(item.id, item.title, description, details))
    return cards


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def fingerprint(cards: list[Card]) -> str:
    fields = [(c.id, c.title, c.description, c.details) for c in cards]
    return sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()


def read_policy(path: Path, cards: list[Card], directory: Path) -> dict[str, Any]:
    policy: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if policy["catalog"] != fingerprint(cards) or policy["index"] != digest(directory / "manifest.json"):
        raise ValueError("policy snapshot")
    for mode in ("lexical", "semantic"):
        low, high = policy["thresholds"][mode]
        if not 0 <= low <= high <= 1:
            raise ValueError("thresholds")
    return policy


def configure(catalog: Catalog, settings: Settings, cards: list[Card]) -> None:
    requested = settings.catalog_relevance
    if settings.catalog_path is None:
        raise ValueError("Search requires a catalog path")
    directory = settings.catalog_search_dir or settings.catalog_path.parent / "search"
    coverage = {"requested": requested, "effective": "legacy"}
    catalog.coverage["relevance"] = coverage
    try:
        policy = read_policy(settings.catalog_search_policy, cards, directory) if settings.catalog_search_policy else {}
    except (OSError, ValueError, KeyError, TypeError):
        log.warning("Поисковая политика недоступна. Используется legacy")
        return
    thresholds = policy.get("thresholds")
    if requested == "hybrid" and policy.get("lexical_released") is True:
        try:
            catalog.search_fallback = SearchIndex(directory, cards, "lexical", thresholds=thresholds)
        except SearchUnavailable:
            log.warning("Резервный индекс FTS5 недоступен")
    try:
        catalog.search_index = SearchIndex(directory, cards, requested, settings.catalog_model_dir, thresholds)
    except SearchUnavailable as error:
        log.warning("Поиск %s недоступен (%s). Используется резервный режим", requested, error)
        catalog.search_index = catalog.search_fallback
        catalog.search_fallback = None
    if catalog.search_index:
        coverage["effective"] = catalog.search_index.mode


def build(directory: Path, cards: list[Card], model: Path | None, *, encoder_kind: str = "e5") -> None:
    index = directory / "lexical.sqlite3"
    with closing(sqlite3.connect(index)) as db, db:
        db.execute("CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED, title, description, details)")
        db.executemany(
            "INSERT INTO search VALUES (?, ?, ?, ?)",
            (
                (card.id, *(" ".join(_terms(text)) for text in (card.title, card.description, card.details)))
                for card in cards
            ),
        )
    manifest = {"schema": INDEX_SCHEMA, "catalog": fingerprint(cards), "lexical": digest(index)}
    if model:
        checksums = model_checksums(model, encoder_kind)
        encoder = make_encoder(model, encoder_kind)
        import numpy as np  # type: ignore[import-not-found]  # noqa: PLC0415

        batches = [encoder.encode([c.text for c in cards[i : i + 16]]) for i in range(0, len(cards), 16)]
        vectors = directory / "vectors.npy"
        np.save(vectors, np.concatenate(batches), allow_pickle=False)
        manifest.update(model=checksums, vectors=digest(vectors), encoder=encoder_kind)
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def model_checksums(directory: Path, kind: str) -> dict[str, str]:
    if kind == "e5":
        return {name: digest(directory / name) for name in MODEL_FILES}
    names = sorted(p.name for p in directory.iterdir() if p.suffix in {".json", ".safetensors", ".txt", ".model"})
    if not {"config.json", "model.safetensors", "tokenizer.json"} <= set(names):
        raise ValueError("incomplete model")
    return {name: digest(directory / name) for name in names}


def make_encoder(directory: Path, kind: str) -> Encoder | LocalModel:
    if kind == "e5":
        return Encoder(directory)
    if kind == "qwen-embedding":
        return LocalModel(directory, kind)
    raise ValueError("unsupported encoder")


class SearchIndex:
    def __init__(
        self,
        directory: Path,
        cards: list[Card],
        mode: str,
        model: Path | None = None,
        thresholds: dict[str, list[float]] | None = None,
    ) -> None:
        self.mode = mode
        self.thresholds = thresholds or DEFAULT_THRESHOLDS
        self.path = directory / "lexical.sqlite3"
        self.cards = {card.id: card for card in cards}
        self.fields = {
            card.id: tuple(frozenset(_terms(part)) for part in (card.title, card.description, card.details))
            for card in cards
        }
        self.constraints = {card.id: _constraints(card.text) for card in cards}
        self.df = Counter(term for fields in self.fields.values() for term in frozenset().union(*fields))
        self.slot = BoundedSemaphore(1)
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if (
                manifest["schema"] != INDEX_SCHEMA
                or manifest["catalog"] != fingerprint(cards)
                or manifest["lexical"] != digest(self.path)
            ):
                raise ValueError("index")
            if mode != "lexical":
                kind = manifest.get("encoder", "e5")
                vectors = directory / "vectors.npy"
                if (
                    model is None
                    or manifest["vectors"] != digest(vectors)
                    or manifest["model"] != model_checksums(model, kind)
                ):
                    raise ValueError("model")
                import numpy as np  # noqa: PLC0415

                self.encoder = make_encoder(model, kind)
                self.vectors = np.load(vectors, allow_pickle=False)
                dimension = {"e5": 384, "qwen-embedding": 1024}[kind]
                if (
                    self.vectors.shape != (len(cards), dimension)
                    or self.vectors.dtype != np.float32
                    or not np.isfinite(self.vectors).all()
                ):
                    raise ValueError("vectors")
        except Exception as error:
            raise SearchUnavailable(type(error).__name__) from None

    def _lexical(self, terms: dict[str, float], allowed: set[str]) -> list[tuple[str, float, str]]:
        if not terms:
            return []
        query = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            rows = db.execute(
                "SELECT id FROM search WHERE search MATCH ? ORDER BY bm25(search, 0, 3, 1, 0.5), id", (query,)
            ).fetchall()
        labels = ("в названии", "в кратком описании", "в сведениях о курсе")
        total = sum(terms.values())
        results = []
        for (key,) in rows:
            if key not in allowed:
                continue
            fields = self.fields[key]
            matched = frozenset().union(*fields)
            confidence = sum(weight for term, weight in terms.items() if term in matched) / total
            field = max(range(3), key=lambda i: sum(terms.get(t, 0) for t in fields[i]))
            results.append((key, confidence, f"Ключевые слова совпали {labels[field]}"))
        return results

    def _semantic(self, query: str, allowed: set[str]) -> list[tuple[str, float, str]]:
        if not self.slot.acquire(blocking=False):
            raise SearchUnavailable("busy")
        try:
            scores = self.vectors @ self.encoder.encode([query], query=True)[0]
            return sorted(
                (
                    (key, float(score), "Карточка близка по смыслу задачи")
                    for key, score in zip(self.cards, scores, strict=True)
                    if key in allowed
                ),
                key=lambda row: (-row[1], row[0]),
            )
        except Exception as error:
            raise SearchUnavailable(type(error).__name__) from None
        finally:
            self.slot.release()

    def constrained(self, query: str, allowed: set[str]) -> set[str]:
        required, negative = _constraints(query)
        return {
            key
            for key in allowed
            if key in self.cards and required <= self.constraints[key][0] and negative <= self.constraints[key][1]
        }

    def match(self, query: str, allowed: set[str], exact: frozenset[str]) -> dict[str, Hit]:
        allowed = self.constrained(query, allowed)
        if not allowed:
            return {}
        terms = {
            term: log1p((len(self.cards) - self.df[term] + 0.5) / (self.df[term] + 0.5))
            for term in sorted(set(_terms(query)))
        }
        if not terms:
            return {}
        channels = {}
        if self.mode != "semantic":
            try:
                channels["lexical"] = self._lexical(terms, allowed)
            except (OSError, sqlite3.Error) as error:
                raise SearchUnavailable(type(error).__name__) from None
        if self.mode != "lexical":
            channels["semantic"] = self._semantic(query, allowed)
        found: dict[str, Hit] = {}
        for mode, channel in channels.items():
            low, high = self.thresholds[mode]
            accepted = ((key, confidence, reason) for key, confidence, reason in channel if confidence >= low)
            for rank, (key, confidence, reason) in enumerate(accepted, 1):
                prior = found.get(key)
                explanation = reason
                strong = confidence >= high
                score = 1 / (60 + rank)
                if prior:
                    explanation = reason if strong and not prior.strong else prior.reason
                    strong = strong or prior.strong
                    score += prior.score
                found[key] = Hit(score, strong, explanation)
        for key in exact & allowed:
            found[key] = Hit(0, True, "Ключевые слова запроса совпали в названии")
        return found
