"""Расширенный отбор, затем локальная оценка кандидатов."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import closing
from dataclasses import replace
from math import isfinite
from pathlib import Path
from threading import BoundedSemaphore, Lock
from time import monotonic
from typing import Any, Protocol

from ..config import Settings
from .global_search import (
    ALIAS_PATTERN,
    ALIASES,
    NORMALIZED_ALIASES,
    YEAR,
    Card,
    Hit,
    SearchIndex,
    SearchUnavailable,
    _constraints,
    _terms,
    configure,
    digest,
    fingerprint,
    model_checksums,
)
from .lexicon import title_matches_gaps
from .models import Catalog
from .neural_rank import LocalModel
from .text_search import _words

log = logging.getLogger(__name__)
PLATFORMS = frozenset(group[0] for group in (*ALIASES[:4], *ALIASES[-2:]))
COUNTRIES = frozenset(group[0] for group in ALIASES[7:-2])
TAX_REGIMES = frozenset({"усн", "осно", "нпд", "псн", "аусн", "есхн"})
NEGATIVE_TAX = re.compile(r"\bбез (?:уплаты |учета |перехода на )?(усн|осно|нпд|псн|аусн|есхн)\b")
REFORMULATIONS = (
    (("недавн", "част", "сумм"), "RFM анализ сегментация клиентов"),
    (("передач", "оборудован", "подписа"), "акт приема передачи оборудования"),
    (("долг", "налогов"), "налоговая задолженность"),
)
MIN_FRAGMENT_OVERLAP = 2
PASSAGE_CANDIDATES = 20
Constraints = tuple[frozenset[str], frozenset[str]]
Fragments = dict[str, tuple[str, str]]


class PassageTokenizer(Protocol):
    def encode(self, text: str, *, add_special_tokens: bool) -> Any: ...


class Reranker(Protocol):
    def score(self, query: str, cards: list[str], *, deadline: float | None = None) -> list[float]: ...


def expansions(terms: dict[str, float]) -> tuple[str, ...]:
    return tuple(
        expansion
        for anchors, expansion in REFORMULATIONS
        if all(any(term.startswith(anchor) for term in terms) for anchor in anchors)
    )


def requirement_state(query: str, text: str) -> str:
    return _requirement_state(requirements(query), requirements(text))


def requirements(text: str) -> tuple[frozenset[str], frozenset[str]]:
    normalized = " ".join(_words(text))
    normalized = ALIAS_PATTERN.sub(lambda match: NORMALIZED_ALIASES[match[0]], normalized)
    required, negative = _constraints(normalized)
    negative |= frozenset(NEGATIVE_TAX.findall(normalized))
    return (required | TAX_REGIMES.intersection(normalized.split())) - negative, negative


def _requirement_state(query: Constraints, card: Constraints) -> str:
    required, negative = query
    present, negated = card
    if negative & (present - negated) or required & negated:
        return "conflict"
    if required <= present and negative <= negated:
        return "confirmed"
    for group in (PLATFORMS, COUNTRIES, TAX_REGIMES, {term for term in required | present if YEAR.fullmatch(term)}):
        if required & group and present & group and not (required & present & group):
            return "conflict"
    return "unknown"


def write_passages(
    path: Path,
    sections: Mapping[str, Iterable[tuple[str, str]]],
    tokenizer: PassageTokenizer,
) -> int:
    count = 0
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE VIRTUAL TABLE passages USING fts5(id UNINDEXED, heading UNINDEXED, body UNINDEXED, terms)")
        for key, blocks in sections.items():
            seen = set()
            for heading, text in blocks:
                encoding = tokenizer.encode(text, add_special_tokens=False)
                offsets = encoding.offsets
                for start in range(0, len(offsets), 136):
                    end = min(start + 160, len(offsets))
                    fragment = text[offsets[start][0] : offsets[end - 1][1]].strip()
                    normalized = " ".join(_terms(fragment))
                    if normalized and normalized not in seen:
                        seen.add(normalized)
                        db.execute(
                            "INSERT INTO passages VALUES (?, ?, ?, ?)",
                            (key, heading, fragment, " ".join(_terms(heading)) + " " + normalized),
                        )
                        count += 1
                    if end == len(offsets):
                        break
    return count


class RerankedIndex:
    mode = "reranked"

    def __init__(  # noqa: PLR0913 — independent index and model configuration
        self,
        index: SearchIndex,
        *,
        passages: Path | None = None,
        model: Reranker | None = None,
        budget: int = 50,
        thresholds: tuple[float, float] = (0.35, 0.85),
        protect_exact: bool = True,
        timeout: float = 0.8,
        reformulate: bool = False,
    ) -> None:
        self.index = index
        self.requirements = {key: requirements(card.text) for key, card in index.cards.items()} if index else {}
        self.passages = passages
        self.model = model
        self.budget = budget
        self.low, self.high = thresholds
        self.protect_exact = protect_exact
        self.timeout = timeout
        self.lock_timeout = timeout / 2
        self.reformulate = reformulate
        self.lock = Lock()
        self.slots = BoundedSemaphore(2)
        self.stats_lock = Lock()
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.stats = {"gpu_requests": 0, "fallbacks": 0}

    def fragments(self, terms: Mapping[str, float], allowed: set[str], gaps: tuple[str, ...] = ()) -> Fragments:
        if not self.passages or not terms:
            return {}
        query = " OR ".join(f'"{term}"' for term in terms)
        with closing(sqlite3.connect(self.passages.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            rows = db.execute(
                "SELECT id, heading, body FROM passages WHERE passages MATCH ? ORDER BY bm25(passages), rowid",
                (query,),
            )
            found: Fragments = {}
            for key, heading, body in rows:
                if key in allowed and (not gaps or title_matches_gaps(body, gaps)):
                    found.setdefault(key, (heading, body))
                    if len(found) == PASSAGE_CANDIDATES:
                        break
        return found

    def retrieve(
        self,
        query: str,
        allowed: set[str],
        exact: frozenset[str],
        gaps: tuple[str, ...] = (),
    ) -> tuple[dict[str, float], Fragments, dict[str, str]]:
        terms = dict.fromkeys(_terms(query), 1.0)
        if not terms and not exact:
            return {}, {}, {}
        constraints = requirements(query)
        states = {
            key: _requirement_state(constraints, self.requirements[key]) for key in allowed & self.index.cards.keys()
        }
        scope = {key for key, state in states.items() if state != "conflict"}
        # Expansion adds terms to retrieval only. Requirements and pair scoring use the original query.
        if self.reformulate:
            for expansion in expansions(terms):
                terms.update(dict.fromkeys(_terms(expansion), 1.0))
        fragments = self.fragments(terms, scope, gaps)
        lex = self.index._lexical(terms, scope)[:50]
        dense = self.index._semantic(query, scope)[:50] if scope else []
        scores: defaultdict[str, float] = defaultdict(float)
        for channel in ([key for key, _, _ in lex], [key for key, _, _ in dense], list(fragments)):
            for rank, key in enumerate(channel, 1):
                scores[key] += 1 / (60 + rank)
        for key in sorted(exact & scope):
            scores.setdefault(key, 0)
        ordered = sorted(scores, key=lambda key: (key not in exact, -scores[key], key))
        required, _ = constraints
        geographic = required & (COUNTRIES - {"россия"})
        for key in ordered:
            if key in fragments and states[key] == "unknown":
                states[key] = _requirement_state(
                    constraints, requirements(self.index.cards[key].text + " " + " ".join(fragments[key]))
                )
        if gaps:
            ordered = [
                key for key in ordered if title_matches_gaps(self.index.cards[key].title, gaps) or key in fragments
            ]
        if geographic and not any(states[key] == "confirmed" for key in ordered):
            return {}, {}, {}
        ordered = [key for key in ordered if states[key] != "conflict"]
        selected = ordered[: max(self.budget, len(exact.intersection(ordered)))]
        return {key: scores[key] for key in selected}, fragments, states

    def score(
        self,
        query: str,
        candidates: dict[str, float],
        fragments: Fragments,
        *,
        deadline: float | None = None,
    ) -> dict[str, float]:
        if self.model is None:
            raise SearchUnavailable("reranker unavailable")
        cards = self.index.cards
        texts = [
            "\n".join(
                part
                for part in (cards[key].title, cards[key].description, *fragments.get(key, ()), cards[key].details)
                if part
            )
            for key in candidates
        ]
        return dict(zip(candidates, self.model.score(query, texts, deadline=deadline), strict=True))

    def match(self, query: str, allowed: set[str], exact: frozenset[str], gaps: tuple[str, ...] = ()) -> dict[str, Hit]:
        started = monotonic()
        if not self.slots.acquire(blocking=False):
            self._count("fallbacks")
            raise SearchUnavailable("reranker busy")
        if not self.lock.acquire(timeout=self.lock_timeout):
            self.slots.release()
            self._count("fallbacks")
            raise SearchUnavailable("reranker busy")
        try:
            pending = self.worker.submit(self._match, query, allowed, exact, gaps, started + self.timeout)
        except RuntimeError as error:
            self._release()
            self._count("fallbacks")
            raise SearchUnavailable("reranker stopped") from error
        pending.add_done_callback(lambda _: self._release())
        try:
            hits = pending.result(timeout=max(0, started + self.timeout - monotonic()))
        except (TimeoutError, SearchUnavailable):
            self._count("fallbacks")
            raise SearchUnavailable("reranker inference") from None
        self._count("gpu_requests")
        return hits

    def _release(self) -> None:
        self.lock.release()
        self.slots.release()

    def _count(self, name: str) -> None:
        with self.stats_lock:
            self.stats[name] += 1

    def _match(
        self, query: str, allowed: set[str], exact: frozenset[str], gaps: tuple[str, ...], deadline: float
    ) -> dict[str, Hit]:
        try:
            candidates, fragments, states = self.retrieve(query, allowed, exact, gaps)
            if not candidates:
                return {}
            scores = self.score(query, candidates, fragments, deadline=deadline)
            if monotonic() > deadline or not all(isfinite(value) for value in scores.values()):
                raise SearchUnavailable("reranker deadline or invalid scores")
        except Exception as error:
            raise SearchUnavailable(type(error).__name__) from None
        return self.hits(query, exact, scores, fragments, states)

    def hits(
        self,
        query: str,
        exact: frozenset[str],
        scores: dict[str, float],
        fragments: Fragments,
        states: dict[str, str],
    ) -> dict[str, Hit]:
        hits = {}
        query_terms = set(_terms(query))
        for key, score in scores.items():
            if score < self.low:
                continue
            reason = "Карточка соответствует задаче по смыслу"
            if key in exact:
                reason = "Ключевые слова запроса совпали в названии"
            elif key in fragments and len(query_terms.intersection(_terms(fragments[key][1]))) >= MIN_FRAGMENT_OVERLAP:
                heading = fragments[key][0]
                reason = (
                    f"Найдено совпадение в разделе «{heading[:100]}»"
                    if heading
                    else "Найдено совпадение в тексте статьи"
                )
            strong = score >= self.high and states[key] == "confirmed"
            hits[key] = Hit(score, strong, reason)
        return hits


def corpus_cards(cards: list[Card], directory: Path, catalog: Catalog) -> list[Card]:
    extras = json.loads((directory / "descriptions.json").read_text(encoding="utf-8"))
    return [
        replace(card, description=extras[card.id])
        if card.id in extras
        and catalog.materials[card.id].format in {"document", "webinar", "podcast"}
        and catalog.materials[card.id].access == "open"
        else card
        for card in cards
    ]


def configure_reranked(catalog: Catalog, settings: Settings, cards: list[Card]) -> None:
    if settings.catalog_path is None:
        raise ValueError("Search requires a catalog path")

    configure(catalog, replace(settings, catalog_relevance="hybrid"), cards)
    coverage = catalog.coverage["relevance"]
    if not isinstance(catalog.search_index, SearchIndex) or catalog.search_index.mode != "hybrid":
        catalog.search_index = None
        coverage["effective"] = "legacy"
    catalog.search_fallback = catalog.search_index
    coverage.update(requested="reranked", gpu_available=False)
    try:
        import torch  # type: ignore[import-not-found]  # noqa: PLC0415

        coverage["gpu_available"] = torch.cuda.is_available()
        directory = settings.catalog_rerank_dir or settings.catalog_path.parent / "reranked"
        path = settings.catalog_rerank_policy or directory / "rerank.json"
        policy = json.loads(path.read_text(encoding="utf-8"))
        kind = policy["model"]
        model_dir = settings.catalog_rerank_model_dir
        if (
            not coverage["gpu_available"]
            or model_dir is None
            or kind not in {"qwen", "bge"}
            or policy["catalog"] != fingerprint(cards)
            or policy["index"] != digest(directory / "manifest.json")
            or policy["weights"] != model_checksums(model_dir, kind)
        ):
            raise ValueError("reranking configuration")
        budget = policy["budget"]
        low, high = policy["thresholds"]
        if budget not in (30, 50, 80) or not 0 <= low <= high <= 1 or type(policy["protect_exact"]) is not bool:
            raise ValueError("reranking policy")
        if policy["descriptions"] != digest(directory / "descriptions.json"):
            raise ValueError("descriptions")
        updated = corpus_cards(cards, directory, catalog)
        fragments = None
        if policy.get("passages"):
            fragments = directory / "passages.sqlite3"
            if policy["passages"] != digest(fragments):
                raise ValueError("passages")
        # Passage files are bound to the source SQLite, including availability flags.
        if policy["snapshot"] != digest(settings.catalog_path):
            raise ValueError("catalog snapshot")
        encoder = settings.catalog_rerank_encoder_dir or settings.catalog_model_dir
        index = SearchIndex(directory, updated, "hybrid", encoder)
        catalog.search_index = RerankedIndex(
            index,
            passages=fragments,
            model=LocalModel(model_dir, kind),
            budget=budget,
            thresholds=(low, high),
            protect_exact=policy["protect_exact"],
            reformulate=policy.get("reformulate", False),
        )
        coverage.update(effective="reranked", index_version=digest(path)[:12])
        coverage["requests"] = catalog.search_index.stats
    except Exception as error:
        catalog.search_fallback = None
        log.warning("Переранжирование недоступно (%s). Используется %s", type(error).__name__, coverage["effective"])
