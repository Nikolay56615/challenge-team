# syntax=docker/dockerfile:1
# Сборка интерфейса: в рабочий образ попадает только dist/
FROM node:26-alpine AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Рабочий образ: Python, зависимости бэкенда, синтетические данные и собранный интерфейс
FROM python:3.12-slim AS runtime
# Постоянные метки OCI (кандидат W06). Ревизия, адрес репозитория и дата меняются с каждым коммитом,
# их метки — в конце стадии. Метки лицензии нет: лицензию комплекта выбирает автор.
ARG IMAGE_VERSION=0.1.0
LABEL org.opencontainers.image.title="track1-recommender" \
      org.opencontainers.image.description="Прототип персональных рекомендаций учебных материалов, трек 1" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.base.name="docker.io/library/python:3.12-slim"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
# Исправления безопасности Debian, вышедшие после сборки базового образа. trivy в CI останавливает сборку
# на уязвимостях HIGH и CRITICAL, у которых есть исправление.
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get upgrade --yes \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/app/backend
# Только пакеты из requirements.lock: точные версии, проверка sha256, без разрешения зависимостей
# и без сборки из исходников. pip check подтверждает, что в блокировке есть все зависимости.
COPY backend/requirements.lock ./
RUN pip install --no-cache-dir --require-hashes --no-deps --only-binary=:all: -r requirements.lock \
 && pip check
COPY backend/app ./app
# Синтаксис кода разбирается интерпретатором образа при сборке: несовместимость версий Python
# видна здесь, а не при запуске контейнера, когда ошибка стоит уже поднятого сервиса.
RUN python -c "import pathlib; [compile(p.read_bytes(), str(p), 'exec') for p in pathlib.Path('app').rglob('*.py')]"
COPY backend/data ./data
COPY --from=frontend /src/frontend/dist /srv/app/frontend/dist
# Числовые uid и gid: так их проверяют среды запуска без доступа к /etc/passwd образа (hadolint DL3066)
RUN groupadd --system --gid 10001 appuser \
 && useradd --system --uid 10001 --gid 10001 --create-home appuser
USER 10001:10001
ENV FRONTEND_DIST=/srv/app/frontend/dist
# В контейнере сервис всегда слушает 8000. APP_PORT в compose.yaml задаёт только порт на машине пользователя.
EXPOSE 8000
# Готовность: /api/ready отвечает 200, когда каталог загружен, и 503 без каталога; urlopen на 503
# выбрасывает исключение, и проверка завершается с кодом 1. Отказ виден не позже чем через 3 × (15 + 3) = 54 с.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=2).status == 200 else 1)"]
# Метки ревизии, адреса репозитория и даты передаёт CI через --build-arg. Дата — время последнего коммита
# из SOURCE_DATE_EPOCH, по нему же BuildKit ставит время создания образа. ARG объявлены после всех RUN:
# каждый RUN после ARG неявно зависит от его значения, и новая ревизия сбрасывала бы кеш слоёв apt и pip.
ARG IMAGE_REVISION=unknown
ARG IMAGE_SOURCE=""
ARG IMAGE_CREATED=""
LABEL org.opencontainers.image.revision="${IMAGE_REVISION}" \
      org.opencontainers.image.source="${IMAGE_SOURCE}" \
      org.opencontainers.image.created="${IMAGE_CREATED}"
# Exec-форма без оболочки: PID 1 — Python, SIGTERM от docker stop получает uvicorn. app.serve проверяет
# переменные окружения, приводит LOG_LEVEL к нижнему регистру, неверное значение останавливает запуск
# с сообщением, где названа переменная. Пределы и таймауты uvicorn описаны в backend/app/serve.py.
CMD ["python", "-m", "app.serve", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS semantic
COPY --chown=10001:10001 backend/requirements-search.txt /tmp/requirements-search.txt
RUN pip install --no-cache-dir --target /home/appuser/semantic-deps -r /tmp/requirements-search.txt
ENV PYTHONPATH=/home/appuser/semantic-deps

FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime AS gpu
WORKDIR /srv/app/backend
COPY --from=runtime /srv/app /srv/app
# Здесь интерпретатор базового образа — Python 3.11: синтаксис 3.12 (PEP 695 и подобное) должен
# ломать сборку GPU-образа, а не запуск контейнера.
RUN python -c "import pathlib; [compile(p.read_bytes(), str(p), 'exec') for p in pathlib.Path('app').rglob('*.py')]"
COPY backend/requirements.txt backend/requirements-search.txt backend/requirements-gpu.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt -r /tmp/requirements-search.txt -r /tmp/requirements-gpu.txt \
    && groupadd --system --gid 10001 appuser \
    && useradd --system --uid 10001 --gid 10001 --no-create-home appuser
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FRONTEND_DIST=/srv/app/frontend/dist \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OPENBLAS_NUM_THREADS=1
HEALTHCHECK --interval=15s --timeout=3s --start-period=45s --retries=4 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=2)"]
CMD ["python", "-m", "app.serve", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS default
CMD ["python", "-m", "app.serve", "--host", "0.0.0.0", "--port", "8000"]
