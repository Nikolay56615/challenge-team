# Данные для сверки

Для первого прогона используйте [тестовый каталог](../backend/data/catalog.synthetic.json), [профили](../backend/data/profiles.synthetic.json) и [разметку релевантности](../backend/tests/relevance.json). Они входят в репозиторий и запускаются командой из README.

Исходные файлы участников находятся в [выданной папке с выгрузкой](https://drive.google.com/drive/folders/10jr0janwjzDHvt0wiiZMini7V8pGj76K?usp=drive_link). Сверяйте по ним схему и смысл полей. Для запуска используйте подготовленные `catalog.sqlite3` и `catalog-signals.sqlite3`. Получите их у владельца рабочей копии по разрешённому каналу и положите в `data/local/`. Таблицы описаны в [описании локальной копии](data-description.md). Храните исходные файлы и SQLite-копии вне Git и Docker-образа.

```powershell
$env:LOCAL_DATA_DIR = (Resolve-Path -LiteralPath 'data/local').Path
docker compose -f compose.yaml -f compose.data.yaml up --build
```

Сверьте источник `sqlite` и покрытие признаков в `/api/health`. [Скрипт проверки](../scripts/inspect_catalog.py) читает данные локально. В оценке отделяйте синтетические сценарии от агрегатов на выгрузке. Для интерпретации `IsPaid` как покупки нужно подтверждение оплаты.
