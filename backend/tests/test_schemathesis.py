"""Контракт API по схеме OpenAPI: Schemathesis против приложения в процессе, без сервера.

Schemathesis читает `/openapi.json` приложения и для каждой операции строит запросы тремя способами: примеры
из схемы, покрытие границ (длины, диапазоны, перечисления, отсутствующие поля, неподдерживаемые методы)
и случайные данные Hypothesis — верные и заведомо неверные. Каждый ответ проверяют все проверки Schemathesis
по умолчанию, среди них:
- нет ответа 5xx (`not_a_server_error`);
- код ответа описан в схеме операции (`status_code_conformance`), тип содержимого и тело — тоже
  (`content_type_conformance`, `response_schema_conformance`);
- неверные по схеме данные отклоняются (`negative_data_rejection`), верные принимаются (`positive_data_acceptance`);
- неподдерживаемый метод получает 405 с заголовком Allow (`unsupported_method`, `allow_header_conformance`).

Предел задачи. Схема описывает жёсткий предел TASK_HARD_LIMIT, 2000 символов, а рабочий предел MAX_TASK_LENGTH
по умолчанию 300 и проверяется в обработчике; клиент узнаёт его из `/api/meta`. При рабочем пределе 300 задача
из 301–2000 символов верна по схеме, но получает 422, и `positive_data_acceptance` это отмечает. Поэтому контракт
проверяется при MAX_TASK_LENGTH = TASK_HARD_LIMIT, а ответ 422 на задачу длиннее рабочего предела проверяют
`test_api.py::test_validation_errors_have_clear_messages` и `test_api.py::test_length_message_uses_genitive`.

Найдено и исправлено при введении проверки (12 ноября 2026 года):
- Schemathesis: `"seq": false` проходил, как и `"limit": "5"` и `"limit": true`: pydantic приводил их к целому.
  Теперь 422, а `8.0` по-прежнему целое, как в JSON Schema (`schemas.json_integer`);
- при разборе схемы: 422 был описан моделью FastAPI HTTPValidationError с полем `detail`, а сервис отвечает
  конвертом `error`; 404, 413 и 503 в схеме не было. Проверку Schemathesis это не роняло: у HTTPValidationError
  нет обязательных полей. Теперь все коды ошибок описаны моделью ErrorResponse (`api/routes.py::_errors`).

Прогон воспроизводим на той же версии Python: `derandomize` и без базы примеров. CI на 3.12 повторяет локальный
прогон на 3.12; на другой версии случайные строки иные, они зависят от её таблицы Unicode. На машине разработки
обе операции подбора занимают около 13 с, остальные пять — меньше секунды.
"""

from __future__ import annotations

import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis import GenerationMode
from schemathesis.core.result import Ok

from app.config import Settings
from app.main import create_app
from app.schemas import TASK_HARD_LIMIT

from .conftest import NO_FRONTEND

# Случайных примеров на операцию сверх примеров покрытия границ
MAX_EXAMPLES = 50
OPERATIONS = {
    "GET /api/health", "GET /api/live", "GET /api/ready", "GET /api/meta", "GET /api/profiles",
    "POST /api/recommend", "POST /api/compare", "POST /api/feed", "GET /api/users", "GET /api/model-card",
}

APP = create_app(Settings(frontend_dist=NO_FRONTEND, max_task_length=TASK_HARD_LIMIT))
schema = schemathesis.openapi.from_asgi("/openapi.json", APP)
schema.config.generation.update(modes=[GenerationMode.POSITIVE, GenerationMode.NEGATIVE])


@schema.parametrize()
@settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much, HealthCheck.data_too_large],
)
def test_api_conforms_to_its_openapi_schema(case):
    case.call_and_validate()


def test_schemathesis_covers_every_operation():
    """Новая операция попадёт под проверку сама; список здесь — чтобы её появление было замечено."""
    results = list(schema.get_all_operations())
    assert [result for result in results if not isinstance(result, Ok)] == []
    labels = {result.ok().label for result in results if isinstance(result, Ok)}
    assert labels == OPERATIONS
