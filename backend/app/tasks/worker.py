"""Job pianificati (Celery). Avvio:
    celery -A app.tasks.worker worker -l info
    celery -A app.tasks.worker beat -l info
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings
from app.core.db import new_session
from app.saas.reminders import run_reminders, weekly_summary
from app.saas.service import today

settings = get_settings()

celery_app = Celery("blubeauty", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.timezone = settings.timezone
celery_app.conf.beat_schedule = {
    # Avvisi di scadenza: ogni mattina alle 8:07 (minuto non tondo per non coincidere con i picchi).
    "avvisi-scadenza": {"task": "app.tasks.worker.daily_reminders", "schedule": crontab(hour=8, minute=7)},
    # Riepilogo per il super amministratore: lunedì alle 8:17.
    # Fatture dei canoni ricorrenti: ogni mattina alle 6:13.
    "canoni-ricorrenti": {"task": "app.tasks.worker.recurring_invoices", "schedule": crontab(hour=6, minute=13)},
    # Solleciti di pagamento automatici (solo per le aziende che li hanno attivati): ogni giorno alle 9:23.
    "solleciti": {"task": "app.tasks.worker.payment_reminders", "schedule": crontab(hour=9, minute=23)},
    # Fatturazione elettronica: stati SDI e fatture ricevute (riserva delle callback di Aruba), ogni 20 minuti.
    "sdi-aggiornamento": {"task": "app.tasks.worker.einvoice_poll", "schedule": crontab(minute="4,24,44")},
    # Report programmati del report builder (pacchetto Pro): ogni mattina alle 7:41.
    "report-programmati": {"task": "app.tasks.worker.scheduled_reports", "schedule": crontab(hour=7, minute=41)},
    # BluBeauty: promemoria degli appuntamenti ogni ora (al minuto 11), marketing automatico ogni mattina alle 9:37.
    "promemoria-appuntamenti": {"task": "app.tasks.worker.appointment_reminders", "schedule": crontab(minute=11)},
    "marketing-automatico": {"task": "app.tasks.worker.daily_marketing", "schedule": crontab(hour=9, minute=37)},
    "riepilogo-settimanale": {
        "task": "app.tasks.worker.weekly_admin_summary",
        "schedule": crontab(hour=8, minute=17, day_of_week=1),
    },
}


def _run(fn):
    db = new_session()
    try:
        result = fn(db, today())
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task
def daily_reminders():
    return _run(run_reminders)


@celery_app.task
def weekly_admin_summary():
    return _run(weekly_summary)


@celery_app.task
def recurring_invoices():
    """Una transazione per azienda: un errore su un cliente non blocca gli altri."""
    from app.documenti.recurring import run_recurring_invoices
    return run_recurring_invoices(new_session, today())


@celery_app.task
def payment_reminders():
    from app.scadenzario.reminders import run_all_tenants
    return run_all_tenants(new_session, today())


@celery_app.task
def einvoice_poll():
    from app.fatturapa.jobs import poll_all_tenants
    return poll_all_tenants(new_session, today())


@celery_app.task
def scheduled_reports():
    from app.bi.reports import run_scheduled
    return run_scheduled(new_session, today())


@celery_app.task
def appointment_reminders():
    from app.marketing.jobs import run_reminders
    return run_reminders(new_session, today())


@celery_app.task
def daily_marketing():
    from app.marketing.jobs import run_daily_marketing
    return run_daily_marketing(new_session, today())
