# Данные для сверки

Для первого прогона используйте [тестовый каталог](../backend/data/catalog.synthetic.json), [профили](../backend/data/profiles.synthetic.json) и [разметку релевантности](../backend/tests/relevance.json). Они входят в репозиторий и запускаются командой из README.

## Импорт PostgreSQL-бэкапа

Для импорта нужны Python 3.12 с зависимостями из `backend/requirements.txt` и запущенный Docker. Из корня репозитория укажите путь к выданному бэкапу и новый каталог назначения.

```powershell
python -X utf8 scripts/import_alfa_backup.py --backup "C:/путь/alfa_course_hackathon.backup" --output-dir data/local/alfa-course
```

Импорт использует временный контейнер `postgres:17.6-bookworm` без сети и монтирует бэкап только для чтения. После проверки он публикует `catalog.sqlite3` и `catalog-signals.sqlite3` и выводит число материалов по форматам, число доступных материалов и число совпадений с признаками. Для повторного импорта укажите новый каталог.

В локальном интерфейсе видны исходные названия доступных материалов. База признаков формируется по названиям. Для статей, курсов, документов и вебинаров импорт собирает ссылки на страницы `kurs.alfabank.ru` из коротких адресов. Для подкастов и карточек без допустимого адреса доступно копирование названия. Число уроков и бейдж «Сертификат» отражают поля `LessonQuantity` и `IsCertified` на момент выгрузки. В уже подготовленном каталоге эти поля и ссылки появятся после повторного импорта в новую папку и запуска с новым `LOCAL_DATA_DIR`.

Карточки курсов получают короткое описание, сведения об аудитории и результаты обучения из полей каталога. В SQLite сохраняются только подготовленные тексты доступных курсов. Импорт сообщает число курсов с описанием и с раскрываемыми сведениями. Для прежней базы повторите импорт в новый каталог.

Импорт добавляет в `catalog.sqlite3` краткие описания доступных открытых статей с разрешённой индексацией. Описание берётся из `Articles.Description`, а при пустом значении — из `DescriptionTag`. Тексты очищаются от HTML и используются для поиска. Текстовые блоки статей используются только в отдельной офлайн-проверке. [Протокол оценки](../evaluation/search-relevance.md#подбор-по-действию-и-объекту)

В таблице записей на курсы остаются только псевдонимные ключи курсов для подсчёта популярности. Даты и идентификаторы пользователей используются в памяти отдельной офлайн-команды. Результат содержит только агрегаты. [Протокол оценки](../evaluation/track1-offline-courses.md#повторная-проверка-по-датам)

## Запуск с подготовленными базами

Храните бэкап и SQLite-файлы локально вне Git и Docker-образа. Следующая команда монтирует обе базы только для чтения. Для уже подготовленной пары файлов укажите папку, в которой они лежат.

```powershell
$env:LOCAL_DATA_DIR = (Resolve-Path -LiteralPath 'data/local/alfa-course').Path
$env:DEMO_MODE = 'false'
docker compose -f compose.yaml -f compose.data.yaml up --build
```

Для локальной проверки ранжирования по задаче повторите импорт в новый каталог, укажите его в `LOCAL_DATA_DIR` и задайте `$env:CATALOG_RELEVANCE = 'task'` перед запуском с `compose.data.yaml`. Значение по умолчанию — `legacy`. Старые SQLite-базы открываются без миграции, при их использовании в режиме `task` индекс строится из имеющихся полей.

### Глобальный поиск

Для поиска по словам соберите отдельный индекс. Для гибридного поиска скачайте файлы `onnx/model.onnx` и `onnx/tokenizer.json` модели `intfloat/multilingual-e5-small` ревизии `ccc66d3` в локальную папку и установите зависимости из `backend/requirements-search.txt`. Модель в контейнере читает их с диска. [Файлы модели](https://huggingface.co/intfloat/multilingual-e5-small/tree/ccc66d3/onnx)

```powershell
$catalog = 'data/local/alfa-course-task'
$model = 'data/local/e5-small'
# С флагом --model-dir команда готовит оба канала. Для FTS5 достаточно опустить этот флаг.
python -X utf8 scripts/build_search_index.py "$catalog/catalog.sqlite3" --model-dir $model
$env:LOCAL_DATA_DIR = (Resolve-Path $catalog).Path
$env:LOCAL_MODEL_DIR = (Resolve-Path $model).Path
$env:CATALOG_BUILD_TARGET = 'semantic'
$env:CATALOG_RELEVANCE = 'hybrid'
docker compose -f compose.yaml -f compose.data.yaml up --build
```

Для режима `lexical` используйте сборочную цель `runtime`. По умолчанию индекс читается из папки `search` рядом с каталогом. Другой индекс можно указать через `CATALOG_SEARCH_DIR`. В `CATALOG_SEARCH_POLICY` передаётся путь внутри контейнера к файлу калибровки. Старый индекс сохраняйте в отдельной папке, а следующий собирайте через `--output-dir`. Поле `catalog.coverage.relevance` в `/api/health` показывает запрошенный и фактический режимы после загрузки. При отказе модели сервис использует FTS5 с подтверждённой политикой выпуска или возвращается к `legacy`. [Оценка и решение о выпуске](../evaluation/search-relevance.md#глобальный-и-гибридный-поиск)

### Локальное переранжирование на GPU

Режим `reranked` запускается явно. Для Windows нужен Docker Desktop с WSL 2 и доступной NVIDIA GPU. Подготовьте обычный CPU-индекс E5 в `search` для резерва. Разместите публичные веса `Qwen3-Reranker-0.6B` или `bge-reranker-v2-m3` и файлы токенизатора отдельной папкой в `data/local`. Для эксперимента с новым поисковым энкодером подготовьте также `Qwen3-Embedding-0.6B`. Сохраняйте ревизии моделей вместе с весами. [Модель Qwen](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) · [Модель BGE](https://huggingface.co/BAAI/bge-reranker-v2-m3) · [GPU в Docker Desktop](https://docs.docker.com/desktop/features/gpu)

```powershell
$catalog = 'data/local/alfa-course-task'
python -X utf8 scripts/build_rerank_index.py "$catalog/catalog.sqlite3" --extract-only --backup "C:/путь/alfa_course_hackathon.backup" --output data/local/rerank-corpus.json

docker build --target gpu -t track1-recommender-gpu:local .
$repo = "type=bind,source=$($PWD.Path),target=/src,readonly"
$data = "type=bind,source=$((Resolve-Path 'data/local').Path),target=/local"
docker run --rm --network none --gpus all --mount $repo --mount $data --entrypoint python track1-recommender-gpu:local /src/scripts/build_rerank_index.py /local/alfa-course-task/catalog.sqlite3 --output /local/alfa-course-task/reranked --corpus /local/rerank-corpus.json --encoder-dir /local/e5-small --model bge --model-dir /local/bge-reranker --extra-descriptions --passages

$env:LOCAL_DATA_DIR = (Resolve-Path $catalog).Path
$env:LOCAL_MODEL_DIR = (Resolve-Path 'data/local/e5-small').Path
$env:LOCAL_RERANK_MODEL_DIR = (Resolve-Path 'data/local/bge-reranker').Path
$env:CATALOG_RELEVANCE = 'reranked'
docker compose -f compose.yaml -f compose.data.yaml -f compose.gpu.yaml up -d --wait
```

Для индекса Qwen укажите `--encoder qwen-embedding --encoder-dir /local/qwen-embedding`. При запуске задайте `LOCAL_RERANK_ENCODER_DIR` и `CATALOG_RERANK_ENCODER_DIR=/encoder`. Для модели переранжирования Qwen передайте `--model qwen` и папку её весов. Калиброванную политику можно передать через `CATALOG_RERANK_POLICY`. Индекс по умолчанию читается из `reranked`, альтернативный путь задаёт `CATALOG_RERANK_DIR`. Проверяйте `catalog.coverage.relevance` в `/api/health`. В этом поле видны фактический режим, доступность GPU и агрегаты запросов с переранжированием и резервом. [Протокол проверки](../evaluation/search-relevance.md#переранжирование-и-открытые-фрагменты)

В собственной среде Python с CUDA-версией PyTorch и зависимостями из `backend/requirements*.txt` можно запустить тот же режим напрямую. Собранный интерфейс укажите через `FRONTEND_DIST`.

```powershell
$env:CATALOG_SOURCE = 'sqlite'
$env:CATALOG_PATH = (Resolve-Path 'data/local/alfa-course-task/catalog.sqlite3').Path
$env:CATALOG_SIGNALS_PATH = (Resolve-Path 'data/local/alfa-course-task/catalog-signals.sqlite3').Path
$env:CATALOG_MODEL_DIR = (Resolve-Path 'data/local/e5-small').Path
$env:CATALOG_RERANK_MODEL_DIR = (Resolve-Path 'data/local/bge-reranker').Path
$env:CATALOG_RELEVANCE = 'reranked'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8080
```

Сверьте источник `sqlite` и покрытие признаков в `/api/health`. Для выданного бэкапа ожидается 1 166 материалов до фильтрации доступности, 1 078 сформированных ссылок (`coverage.links_total`), 26 курсов с числом уроков и 4 с сертификатом (`coverage.fields_count`). Ссылка ведёт на публичную страницу, где платформа определяет доступ. Проверьте запросы «Как выбрать налоговый режим» и «Нужна лицензия на продажу алкоголя». [Скрипт проверки](../scripts/inspect_catalog.py) читает данные локально. Для интерпретации `IsPaid` как покупки нужно подтверждение оплаты.

В разделе «Каталог» доступны 13 тем. Откройте «Маркетплейсы» из списка слева или подтвердите выбор кнопкой «Показать материалы темы» на узком экране. Для свежего сеанса ожидается счётчик «Показано 5 из 50 материалов».
