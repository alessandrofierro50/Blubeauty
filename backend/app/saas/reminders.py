"""Job giornaliero degli avvisi di scadenza e riepilogo settimanale per il super amministratore."""

import html
import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.mailer import send_email
from app.core.models import EmailLog, EmailTemplate, ReminderRule, Subscription, Tenant
from app.saas import logic
from app.saas.service import lifecycle_settings, tenant_state

log = logging.getLogger("blubeauty.reminders")


def _fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _send_logged(db: Session, *, tenant: Tenant | None, sub: Subscription | None, rule: str,
                 recipients: list[str], subject: str, html: str) -> bool:
    """Invia e registra. Il vincolo unico (abbonamento, regola) impedisce i doppi invii,
    anche se due job partissero insieme."""
    entry = EmailLog(
        tenant_id=tenant.id if tenant else None,
        subscription_id=sub.id if sub else None,
        rule=rule,
        recipients=", ".join(recipients),
        subject=subject,
    )
    try:
        with db.begin_nested():
            db.add(entry)
            db.flush()
    except IntegrityError:
        return False  # già inviato
    try:
        send_email(recipients, subject, html)
    except Exception as exc:  # registriamo l'errore e riproviamo al prossimo giro
        log.exception("Invio fallito per %s", rule)
        entry.success = False
        entry.error = str(exc)[:1000]
    db.flush()
    return entry.success


def _retry_failed(db: Session) -> None:
    """Le email fallite vengono cancellate dal registro così il job successivo le ritenta."""
    for failed in db.scalars(select(EmailLog).where(EmailLog.success.is_(False))):
        db.delete(failed)
    db.flush()


def contacts_text() -> str:
    s = get_settings()
    return " · ".join(x for x in (s.support_email, f"tel. {s.support_phone}" if s.support_phone else "") if x)


def _values(tenant: Tenant, state, sub: Subscription, on: date) -> dict:
    """Segnaposto dei modelli: quelli dello standard comune ({azienda}, {prodotto}, {piano}, {scadenza}, {giorni},
    {link_accesso}, {contatti}) e quelli storici di BluBeauty, che restano validi nei modelli già personalizzati."""
    settings = get_settings()
    url = settings.public_url.rstrip("/")
    end = _fmt(state.end_date) if state.end_date else ""
    days = state.days_left if state.days_left is not None else ""
    plan = state.plan.name if state.plan else ""
    return {
        "azienda": tenant.name, "prodotto": settings.brand_name, "piano": plan, "scadenza": end, "giorni": days,
        "link_accesso": f"{url}/login", "contatti": contacts_text(),
        "ragione_sociale": tenant.name, "pacchetto": plan, "data_scadenza": end, "giorni_rimanenti": days,
        "giorni_tolleranza": sub.grace_days, "giorni_sola_lettura": sub.readonly_days,
        "link_rinnovo": f"{url}/pagamento",  # «Rinnova ora»: pagina di pagamento (dopo il login)
    }


# Gli avvisi dopo la scadenza partono entro questa finestra: se il job resta fermo più a lungo non si recuperano.
LATE_WINDOW = timedelta(days=7)


def _after_expiry_rule(sub: Subscription, end: date, on: date, status: str) -> str | None:
    """Avviso dopo la fine di un periodo pagato: «fine_tolleranza» l'ultimo giorno di tolleranza (da domani sola lettura)
    e «sospensione» il primo giorno di sospensione. Se il job salta giorni parte solo il più vicino."""
    suspension_day = end + timedelta(days=sub.grace_days + sub.readonly_days + 1)
    last_grace_day = end + timedelta(days=sub.grace_days)
    if status == "sospeso" and suspension_day <= on <= suspension_day + LATE_WINDOW:
        return "sospensione"
    if status in ("tolleranza", "sola_lettura") and last_grace_day <= on <= last_grace_day + LATE_WINDOW:
        return "fine_tolleranza"
    return None


def run_reminders(db: Session, on: date) -> list[str]:
    """Esegue gli avvisi del giorno `on`. Restituisce l'elenco delle regole inviate (per log e test).

    Periodi pagati: giorni del pannello (30, 15, 7, 3, 1, 0), fine tolleranza e sospensione.
    Prova gratuita: 3, 1 giorno prima e il giorno della fine (logic.TRIAL_REMINDER_DAYS), poi «prova_scaduta»."""
    settings = get_settings()
    _retry_failed(db)
    rules = [r.days_before for r in db.scalars(select(ReminderRule).where(ReminderRule.active))]
    trial_rules = lifecycle_settings(db)["trial_reminder_days"]
    templates = {t.code: t for t in db.scalars(select(EmailTemplate))}
    sent: list[str] = []

    tenants = db.scalars(
        select(Tenant).options(
            selectinload(Tenant.subscriptions).selectinload(Subscription.plan),
            selectinload(Tenant.extra_modules),
        )
    ).all()

    for tenant in tenants:
        state = tenant_state(tenant, on)
        sub = state.subscription
        if sub is None or tenant.suspended or state.status == "programmato":
            continue
        recipients = [tenant.contact_email]
        if settings.admin_notify_email:
            recipients.append(settings.admin_notify_email)

        # La regola si lega al periodo che copre la data di fine effettiva,
        # così un rinnovo già inserito sposta in avanti gli avvisi.
        anchor = max(
            (s for s in tenant.subscriptions if s.end_date == state.end_date),
            key=lambda s: s.start_date,
            default=sub,
        )
        values = _values(tenant, state, anchor, on)

        rule = code = None
        if anchor.is_trial:
            if state.days_left is not None and state.days_left >= 0:
                d = logic.reminder_to_send(state.days_left, trial_rules)
                if d is not None:
                    rule, code = f"prova_{d}", "prova_oggi" if state.days_left == 0 else "prova_avviso"
            elif state.status == "prova_scaduta" and on - state.end_date <= LATE_WINDOW + timedelta(days=1):
                rule = code = "prova_scaduta"
        elif state.days_left is not None and state.days_left >= 0:
            d = logic.reminder_to_send(state.days_left, rules)
            if d is not None:
                rule, code = f"giorni_{d}", "scadenza_oggi" if state.days_left == 0 else "scadenza_avviso"
        elif state.end_date:
            rule = code = _after_expiry_rule(anchor, state.end_date, on, state.status)

        tpl = templates.get(code) if code else None
        if tpl is None and code:  # modello non ancora caricato (database creato prima dello standard): predefinito
            from app.saas.defaults import DEFAULT_TEMPLATES
            d = next((t for t in DEFAULT_TEMPLATES if t["code"] == code), None)
            tpl = EmailTemplate(**d) if d else None
        if tpl and _send_logged(
            db, tenant=tenant, sub=anchor, rule=rule, recipients=recipients,
            subject=logic.render_placeholders(tpl.subject, values),
            html=logic.render_placeholders(tpl.body, values),
        ):
            sent.append(f"{tenant.name}:{rule}")
    return sent


def weekly_summary(db: Session, on: date) -> bool:
    """Riepilogo per BluCode (lunedì): in scadenza a 30 giorni, scaduti, nuove prove, prove in scadenza,
    prove scadute non convertite, nuovi clienti, ricavo mensile stimato."""
    settings = get_settings()
    if not settings.admin_notify_email:
        return False
    tenants = db.scalars(
        select(Tenant).options(
            selectinload(Tenant.subscriptions).selectinload(Subscription.plan),
            selectinload(Tenant.extra_modules),
        )
    ).all()
    week_ago = on - timedelta(days=7)
    expiring, expired, new, new_trials, trials_expiring, trials_expired = [], [], [], [], [], []
    mrr = Decimal("0")
    for t in tenants:
        st = tenant_state(t, on)
        s = st.subscription
        plan = st.plan.name if st.plan else ""
        if st.status == "prova":
            if st.days_left is not None and st.days_left <= 7:
                trials_expiring.append(f"{t.name} — {plan}, fine prova {_fmt(st.end_date)} ({st.days_left} gg)")
        elif st.status == "in_scadenza":
            expiring.append(f"{t.name} — {plan}, {_fmt(st.end_date)} ({st.days_left} gg)")
        elif st.status == "prova_scaduta" and not t.suspended:
            if st.end_date and st.end_date >= on - timedelta(days=30):
                trials_expired.append(f"{t.name} — prova finita il {_fmt(st.end_date)}")
        elif st.status in ("tolleranza", "sola_lettura", "sospeso") and not t.suspended:
            expired.append(f"{t.name} — {logic.STATUS_LABELS[st.status]}, scaduto il {_fmt(st.end_date)}" if st.end_date else t.name)
        trial_new = [x for x in t.subscriptions if x.is_trial and x.start_date >= week_ago and x.start_date <= on]
        if trial_new:
            new_trials.append(f"{t.name} — {trial_new[0].plan.name} fino al {_fmt(trial_new[0].end_date)} · {t.contact_email}")
        elif t.created_at and t.created_at.date() >= week_ago:
            new.append(t.name)
        if st.access == "full" and s and not s.is_trial:
            mrr += logic.monthly_amount(s.amount, s.period, s.start_date, s.end_date)

    def ul(items):
        return "<ul>" + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ul>" if items else "<p>Nessuno</p>"

    html_body = (
        f"<h2>Riepilogo settimanale {settings.brand_name}</h2>"
        f"<p><b>Ricavo mensile ricorrente stimato:</b> € {mrr:,.2f}</p>"
        f"<h3>In scadenza nei prossimi 30 giorni</h3>{ul(expiring)}"
        f"<h3>Scaduti</h3>{ul(expired)}"
        f"<h3>Nuove prove (ultimi 7 giorni)</h3>{ul(new_trials)}"
        f"<h3>Prove in scadenza</h3>{ul(trials_expiring)}"
        f"<h3>Prove scadute non convertite (ultimi 30 giorni)</h3>{ul(trials_expired)}"
        f"<h3>Nuovi clienti (ultimi 7 giorni)</h3>{ul(new)}"
    )
    week = on.isocalendar()
    return _send_logged(
        db, tenant=None, sub=None, rule=f"riepilogo_{week.year}-{week.week:02d}",
        recipients=[settings.admin_notify_email],
        subject=f"{settings.brand_name}: riepilogo abbonamenti settimana {week.week}",
        html=html_body,
    )
