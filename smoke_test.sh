#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")/.."

echo "[1/8] Проверка Docker Compose"
docker compose config >/dev/null

echo "[2/8] Сервисы"
docker compose ps

echo "[3/8] PostgreSQL"
docker compose exec -T postgres sh -lc \
  'pg_isready -U "${POSTGRES_USER:-tender_user}" -d "${POSTGRES_DB:-tender_db}"'

echo "[4/8] Redis"
docker compose exec -T redis redis-cli ping

echo "[5/8] FastAPI"
curl -fsS http://127.0.0.1:8000/health

echo
echo "[6/8] Celery ping"
docker compose exec -T celery_worker \
  celery -A app.workers.celery_app.celery_app inspect ping

echo "[7/8] Зарегистрированные задачи"
docker compose exec -T celery_worker \
  celery -A app.workers.celery_app.celery_app inspect registered

echo "[8/8] Последние ошибки"
docker compose logs --since=30m \
  | grep -iE 'error|exception|traceback|failed|critical' || true

echo "Smoke test завершён."
