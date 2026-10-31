#!/bin/sh
set -e
case "$1" in
  api)
    alembic upgrade head
    python -m app.seed ${SEED_DEMO:+--demo}
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --workers ${API_WORKERS:-2}
    ;;
  worker) exec celery -A app.tasks.worker worker -l info --concurrency ${CELERY_CONCURRENCY:-2} ;;
  beat)   exec celery -A app.tasks.worker beat -l info --schedule /tmp/celerybeat-schedule ;;
  *)      exec "$@" ;;
esac
