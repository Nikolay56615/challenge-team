"""Паспорт модели ленты: числа офлайн-оценки на журнале записей.

Файл `data/model-card.json` записывает `evaluation/feed_eval.py --card`; в нём только агрегаты. Сервис отдаёт их
с подписями по адресу `GET /api/model-card`. Без файла адрес отвечает 404: числа не выдумываются.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from . import schemas
from .config import DATA_DIR
from .ranking.feed import SOURCE_LABELS

log = logging.getLogger("app")

CARD_PATH = DATA_DIR / "model-card.json"
# Первая группа — пользователи частей подтверждения: по ним веса не выбирались. Две другие покрывают всех
# пользователей и показаны отдельно: у одной скрыт последний по времени курс, у другой — случайная запись,
# и одно общее число скрыло бы разницу между ними
GROUPS = (
    ("confirmation", "Не участвовали в выборе весов"),
    ("strict", "Скрыт последний курс"),
    ("random", "Скрыта случайная запись"),
)
METHODS = (("product", "Лента"), ("coenroll", "Только совместные записи"), ("popularity", "Популярность"))
WEIGHTS = {
    "co_enrollment": SOURCE_LABELS["history"],
    "content": SOURCE_LABELS["content"],
    "continuation": SOURCE_LABELS["links"],
    "popularity": SOURCE_LABELS["popularity"],
    "access": SOURCE_LABELS["access"],
}
FEED = (
    ("overlap@50", "Общих карточек в лентах двух случайных пользователей", True),
    ("recall@10", "Скрытый курс вошёл в первые 10 карточек ленты", True),
    ("topics@10", "Разных тем в первых 10 карточках", False),
)


def load_model_card(path: Path = CARD_PATH) -> schemas.ModelCardResponse | None:
    try:
        card = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return schemas.ModelCardResponse(
            data=card["data"],
            groups=[
                schemas.ModelCardGroup(
                    code=code,
                    label=label,
                    users=card["groups"][code]["users"],
                    rows=[
                        schemas.ModelCardRow(
                            method=method,
                            label=name,
                            hit1=card["groups"][code]["methods"][method]["hit@1"],
                            hit5=card["groups"][code]["methods"][method]["hit@5"],
                            ndcg5=card["groups"][code]["methods"][method]["NDCG@5"],
                        )
                        for method, name in METHODS
                    ],
                )
                for code, label in GROUPS
            ],
            weights=[
                schemas.ModelCardValue(label=label, value=card["weights"][key], share=False)
                for key, label in WEIGHTS.items()
            ],
            feed=[
                schemas.ModelCardValue(label=label, value=card["feed"][key], share=share) for key, label, share in FEED
            ],
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.error("model card not loaded: %s", type(exc).__name__)
        return None
