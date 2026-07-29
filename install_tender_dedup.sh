#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-$HOME/LLM-assistant/tender-ai-platform}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="$PROJECT_DIR/backups/dedup_$STAMP"

log(){ printf '\n[%s] %s\n' "$(date -Is)" "$*"; }
die(){ printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }

cd "$PROJECT_DIR" || die "Нет каталога $PROJECT_DIR"
[[ -f app/workers/tasks_parsing.py ]] || die "Нет tasks_parsing.py"
[[ -f alembic.ini ]] || die "Нет alembic.ini"
docker compose config >/dev/null || die "Ошибка docker compose"

log "Останавливаем celery_beat"
docker compose stop celery_beat >/dev/null 2>&1 || true

log "Backup"
mkdir -p "$BACKUP_DIR"
cp app/workers/tasks_parsing.py "$BACKUP_DIR/"
cp -a migrations "$BACKUP_DIR/" 2>/dev/null || true
docker compose exec -T postgres pg_dump   -U "${POSTGRES_USER:-tender_user}"   -d "${POSTGRES_DB:-tender_db}" -Fc > "$BACKUP_DIR/postgres.dump"
test -s "$BACKUP_DIR/postgres.dump" || die "Пустой pg_dump"

log "Копируем файлы реализации"
mkdir -p app/services
touch app/services/__init__.py
cp ./dedup_files/tender_dedup.py app/services/tender_dedup.py

HEAD="$(docker compose run --rm app alembic heads | awk 'NR==1{print $1}')"
[[ -n "$HEAD" ]] || die "Не удалось определить Alembic head"
REV="$(date +%y%m%d%H%M%S)"
MIG="migrations/versions/${REV}_add_tender_ingestion_dedup_registry.py"

python3 - "$HEAD" "$REV" "$MIG" <<'PY'
from pathlib import Path
import sys

head, revision, output = sys.argv[1:]
template = Path("dedup_files/migration_template.py.txt").read_text(encoding="utf-8")
content = template.format(
    revision=revision,
    down_revision=head,
    down_revision_repr=repr(head),
)
Path(output).write_text(content, encoding="utf-8")
print(output)
PY

python3 dedup_files/patch_tasks_parsing.py

log "Проверка синтаксиса"
docker compose run --rm app python -m compileall -q   app/services/tender_dedup.py app/workers/tasks_parsing.py "$MIG"

log "Миграция"
docker compose run --rm app alembic upgrade head

log "Проверка таблицы"
docker compose exec -T postgres psql   -U "${POSTGRES_USER:-tender_user}"   -d "${POSTGRES_DB:-tender_db}"   -c '\d+ tender_ingestion_registry'

log "Пересборка"
docker compose up -d --build --force-recreate   app celery_worker celery_beat flower

docker compose ps
echo "Backup: $BACKUP_DIR"
