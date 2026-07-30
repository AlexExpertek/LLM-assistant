#!/usr/bin/env bash
set -Eeuo pipefail

DOCUMENT_URL="${1:-}"

if [[ -z "$DOCUMENT_URL" ]]; then
  echo "Использование:"
  echo "  $0 'https://example.org/document.pdf'"
  exit 1
fi

cd "$(dirname "$0")/.."

docker compose exec -T \
  -e DOCUMENT_URL="$DOCUMENT_URL" \
  app python - <<'PY'
import os
from uuid import uuid4
from app.workers.tasks_parsing import process_new_tender

url = os.environ["DOCUMENT_URL"]
external_id = f"MANUAL-{uuid4().hex[:8]}"

payload = {
    "source": "manual_document_test",
    "external_id": external_id,
    "title": "Ручной тест обработки документа",
    "customer_name": "Тестовый заказчик",
    "customer_inn": "",
    "law_type": "manual",
    "amount": None,
    "region": None,
    "submission_deadline": None,
    "source_url": url,
    "document_urls": [url],
}

task = process_new_tender.delay(payload)
print(f"TASK_ID={task.id}")
print(f"EXTERNAL_ID={external_id}")
print(f"DOCUMENT_URL={url}")
PY

echo
echo "Логи:"
echo "docker compose logs -f --tail=300 celery_worker"
