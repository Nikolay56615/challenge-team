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
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv/app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/app ./app
COPY backend/data ./data
COPY --from=frontend /src/frontend/dist /srv/app/frontend/dist
RUN useradd --system --uid 10001 --no-create-home appuser
USER appuser
ENV FRONTEND_DIST=/srv/app/frontend/dist
# В контейнере сервис всегда слушает 8000. APP_PORT в compose.yaml задаёт только порт на машине пользователя.
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"
# LOG_LEVEL задаёт и уровень uvicorn, регистр не важен. Неизвестное значение uvicorn получает как info,
# а приложение при запуске отклоняет его с сообщением, где названа переменная.
CMD ["sh", "-c", "level=$(printf '%s' \"${LOG_LEVEL:-info}\" | tr '[:upper:]' '[:lower:]'); case \"$level\" in debug|info|warning|error|critical) ;; *) level=info ;; esac; exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level \"$level\""]

FROM runtime AS semantic
USER root
COPY backend/requirements-search.txt /tmp/requirements-search.txt
RUN pip install -r /tmp/requirements-search.txt && rm /tmp/requirements-search.txt
USER appuser

FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime AS gpu
WORKDIR /srv/app/backend
COPY --from=runtime /srv/app /srv/app
COPY backend/requirements-search.txt backend/requirements-gpu.txt /tmp/
RUN pip install --no-cache-dir -r requirements.txt -r /tmp/requirements-search.txt -r /tmp/requirements-gpu.txt \
    && useradd --system --uid 10001 --no-create-home appuser
USER appuser
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FRONTEND_DIST=/srv/app/frontend/dist \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OPENBLAS_NUM_THREADS=1
HEALTHCHECK --interval=15s --timeout=3s --start-period=45s --retries=4 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS default
