# Каталог источников

## Материалы кейса

| Источник | Статус и место | Что брать |
| --- | --- | --- |
| Предоставленное условие | Обезличенная локальная версия в [materials/case.md](materials/case.md) | Постановку обоих треков, ограничения, сценарии, формат сдачи и веса. Исходные фирменные изображения, аккаунты и ссылки исключены |
| Локальная выгрузка и описание | `catalog.sqlite3`, `catalog-signals.sqlite3` и [data-description.md](docs/data-description.md). Производные копии в закрытом для Git и сборки каталоге. Покрытие признаков проверено 9 ноября 2026 года агрегатами через [scripts/inspect_catalog.py](scripts/inspect_catalog.py); итоги в [PLAN.md](PLAN.md), раздел 2 | Каталог, темы, теги, отрасли, признаки доступа, редакционные связи, 36 признаков из названий и описаний, относительный порядок событий по курсам. Названий, ссылок и дат нет |
| Демонстрационные примеры | Синтетические образцы в [данных](guides/data.md), [треке 1](guides/recommender.md) и [треке 2](guides/telegram.md) | Проверку поведения на контролируемых входах. Схему выгрузки и эффект в продукте по ним не устанавливают |
| Редактура русского текста | [Локальное руководство](guides/russian-style.md) и [навык Claude Code](.claude/skills/translator/SKILL.md) | Ручную вычитку шаблонных оборотов, примеры для README, слайдов и речи, сверку фактов после правки |
| Проверенные результаты проекта | Текущая отметка в [CURRENT.md](CURRENT.md). Детальные протоколы появляются после прогонов | Фактические наблюдения и ограничения конкретной версии |

Запрос на дополнительные данные формулируй предметно. Для трека 1 сначала проверь локальный каталог. Если нужный признак или допустимая ссылка отсутствует, укажи, какой сценарий это затрагивает. Для трека 2 отдельно потребуются доступные для ответа тексты и карточки. Перед импортом уточни разрешённые операции. Подробный порядок — в [руководстве по данным](guides/data.md).

## Публичная техническая документация

Ссылки ниже предназначены для точечных справок. Для запуска без интернета используй локальные руководства и уже полученные входные данные. Проверяй документацию той версии, которую фактически выбрал проект.

| Вопрос | Где смотреть | Что использовать |
| --- | --- | --- |
| Как Claude Code находит навык и когда загружает его | [Claude Code Skills](https://code.claude.com/docs/en/skills) | Путь проектного навыка, поля YAML и режим ручного запуска |
| Как Claude Code загружает инструкции | [Claude Code Memory](https://code.claude.com/docs/en/memory) | Приоритет инструкций, проверку через `/memory`, влияние импортов на контекст |
| Что блокируют правила доступа | [Claude Code Permissions](https://code.claude.com/docs/en/permissions#read-and-edit) | Синтаксис `Read` и `Edit`, границы правил для обходов и процессов |
| Как читать предоставленный CSV | [Python csv](https://docs.python.org/3/library/csv.html) | Разделитель, кавычки, явную кодировку и проверку заголовков. Применять, если формат CSV и выбран Python |
| Как разложить рекомендации на этапы | [Google for Developers — Recommendation systems](https://developers.google.com/machine-learning/recommendation/overview/types) | Отбор кандидатов, оценку и корректировку итогового списка |
| Как посчитать метрику ранжирования | [scikit-learn — ndcg_score](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.ndcg_score.html) | Требования к оценкам релевантности, параметр k, работу с равными оценками |
| Как собрать форму и сообщать о её состоянии | [Формы MDN](https://developer.mozilla.org/en-US/docs/Learn_web_development/Extensions/Forms/Your_first_form), [подписи W3C WAI](https://www.w3.org/WAI/tutorials/forms/labels/) и [статусные сообщения W3C WAI](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html) | Структуру формы, явные подписи, доступное уведомление о загрузке и пустой выдаче |
| Как проверить веб-сценарий в браузере | [Локаторы Playwright](https://playwright.dev/docs/locators) | Если выбран Playwright, искать поля и кнопки по видимой подписи или роли |
| Как проверить типовые риски веб-выдачи и API | [OWASP API4](https://api-security.owasp.org/editions/2023/en/0xa4-unrestricted-resource-consumption/) и [OWASP XSS Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html) | Ограничения потребления ресурсов, безопасное отображение текста и обработку URL |
| Как задавать нагрузку и читать метрики | [Типы нагрузочных тестов k6](https://grafana.com/docs/k6/latest/testing-guides/test-types/), [метрики k6](https://grafana.com/docs/k6/latest/using-k6/metrics/reference/) и [Docker stats](https://docs.docker.com/reference/cli/docker/container/stats/) | Выбор профиля запросов, длительность и ошибки HTTP, ресурсы контейнера. Применять к локальному стенду после реализации |
| Как работает текстовый поиск в SQLite | [SQLite FTS5](https://www.sqlite.org/fts5.html) | Токенизацию, запросы и ранжирование. Проверить наличие FTS5 и качество на русских формулировках |
| Как устроено извлечение контекста для ответа | [Retrieval-Augmented Generation, оригинальная статья](https://arxiv.org/abs/2005.11401) | Связь извлечения и генерации. Контракт ссылок и условия отказа определить на примерах кейса |
| Как создать тестового бота и получить токен | [Telegram BotFather](https://core.telegram.org/bots/features#botfather) | Шаги создания и управление токеном. Применять при разрешённой живой проверке |
| Как доставляются события бота | [Telegram Bot API](https://core.telegram.org/bots/api#getting-updates) | Выбор между `getUpdates` и webhook, идентификаторы событий и форматы ответа |
| Как обрабатывать локальное время | [Python zoneinfo](https://docs.python.org/3/library/zoneinfo.html) | Часовые пояса IANA и переходы времени, если выбран Python |
| Как проверить настройку запуска и окружения | [Docker Compose up](https://docs.docker.com/reference/cli/docker/compose/up) и [переменные Compose](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/) | Сборку при запуске, подстановку переменных, отличие параметров Compose от окружения контейнера |
| Как спланировать сравнение в продукте | [Microsoft Research — Online Experimentation at Microsoft](https://www.microsoft.com/en-us/research/publication/online-experimentation-at-microsoft/) | Контроль и тестовую группу, интерпретацию результатов и границы эксперимента |

## Как добавлять источник

Запиши назначение, статус и результат проверки. Для локального материала укажи путь от проекта и преобразования. Для публичной документации укажи точный раздел и что он подтверждает. Если источник доступен только по отдельному разрешению, опиши способ получения нейтрально. Частные ссылки, ключи, исходные фирменные названия и карты обратной подстановки хранятся за пределами рабочей базы.
