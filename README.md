# Установка дедупликации тендеров

Комплект рассчитан на текущий проект `~/LLM-assistant/tender-ai-platform`.

## Установка

Скопируйте каталог `dedup_files` и файл `install_tender_dedup.sh` в корень проекта:

```bash
cd ~/LLM-assistant/tender-ai-platform
chmod +x install_tender_dedup.sh
./install_tender_dedup.sh
```

Скрипт:

1. остановит `celery_beat`;
2. создаст backup файлов и PostgreSQL;
3. создаст отдельный реестр `tender_ingestion_registry`;
4. заменит TODO-блок в `tasks_parsing.py`;
5. применит Alembic-миграцию;
6. пересоберёт сервисы.

## Тест двух одинаковых тендеров

```bash
docker compose exec -T app python - <<'PY'
from app.workers.tasks_parsing import process_new_tender

tender = {
    "source": "manual_test",
    "external_id": "TEST-DEDUP-001",
    "title": "Тестовый тендер",
    "customer_name": "Тестовый заказчик",
    "customer_inn": "0000000000",
    "law_type": "manual",
    "amount": 1000000,
    "currency": "RUB",
    "region": "Москва",
    "submission_deadline": "2026-08-15T12:00:00+03:00",
    "source_url": "https://example.org/tenders/TEST-DEDUP-001",
    "document_urls": [],
}

print(process_new_tender.delay(tender).id)
print(process_new_tender.delay(tender).id)
PY
```

Проверка:

```bash
sleep 5
docker compose logs --since=5m celery_worker | grep -E "tender_deduplication_checked|TEST-DEDUP-001|skipped"
```

Ожидается:

```text
первый вызов: claimed=true, action=new
второй вызов: claimed=false, action=unchanged
```

Проверка БД:

```bash
docker compose exec -T postgres psql -U tender_user -d tender_db -x -c "
SELECT source, external_id, revision, processing_status,
       last_event, first_seen_at, last_seen_at
FROM tender_ingestion_registry
WHERE source='manual_test'
AND external_id='test-dedup-001';
"
```

Должна существовать одна строка.

## Проверка обновления

Повторите тест, изменив `amount` или `submission_deadline`. Тогда:

```text
revision = 2
last_event = updated
```

## Откат

```bash
docker compose stop celery_beat celery_worker
docker compose run --rm app alembic downgrade -1

LATEST="$(find backups -maxdepth 1 -type d -name 'dedup_*' | sort | tail -1)"
cp "$LATEST/tasks_parsing.py" app/workers/tasks_parsing.py
rm -f app/services/tender_dedup.py

docker compose up -d --build --force-recreate   app celery_worker celery_beat flower
```
