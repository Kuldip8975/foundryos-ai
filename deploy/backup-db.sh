#!/usr/bin/env bash
# Daily PostgreSQL backup for the production stack; keeps the last 7 days.
#   bash deploy/backup-db.sh            (run from the repository root or anywhere)
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a
mkdir -p backups
file="backups/foundryos-$(date +%Y%m%d-%H%M).dump"
docker compose -f "${COMPOSE_FILE:-docker-compose.prod.yml}" exec -T db \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -F c > "$file"
chmod 600 "$file"
find backups -name 'foundryos-*.dump' -mtime +7 -delete
echo "Backup written: $file"
