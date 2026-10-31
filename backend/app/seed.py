"""Dati iniziali. Uso:  python -m app.seed          (pacchetti, modelli email, super admin)
                         python -m app.seed --demo   (aggiunge le tre aziende di esempio)

Idempotente: si può rilanciare senza duplicare nulla."""

import sys
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.anagrafiche.bootstrap import bootstrap_tenant
from app.anagrafiche.demo import load_demo
from app.magazzino.demo import load_stock_demo
from app.core.config import get_settings
from app.core.models import (
    Company,
    EmailTemplate,
    Plan,
    ReminderRule,
    Subscription,
    SuperAdmin,
    Tenant,
    TenantModule,
    User,
    Warehouse,
)
from app.core.security import hash_password
from app.saas.defaults import DEFAULT_PLANS, DEFAULT_REMINDER_DAYS, DEFAULT_TEMPLATES
from app.saas.service import today

DEMO_PASSWORD = "Demo2026!"

DEMO_TENANTS = [
    {
        "name": "Moda Bella Boutique",
        "demo": "abbigliamento",
        "sector": "Abbigliamento",
        "vat_number": "01234560011",
        "city": "Bari", "province": "BA", "address": "Via Sparano 45", "zip_code": "70121",
        "contact_email": "abbigliamento@demo.blubeauty.it",
        "admin_name": "Giulia Moretti",
        "plan": "PLUS", "period": "annuale",
        # scade tra 25 giorni: mostra il banner "in scadenza"
        "end_in_days": 25,
        "warehouses": [("MAG01", "Negozio"), ("MAG02", "Deposito")],
    },
    {
        "name": "Panificio Il Forno Antico",
        "demo": "panetteria",
        "sector": "Panetteria",
        "vat_number": "01234560022",
        "city": "Altamura", "province": "BA", "address": "Corso Federico II 12", "zip_code": "70022",
        "contact_email": "panetteria@demo.blubeauty.it",
        "admin_name": "Michele Lorusso",
        "plan": "BASE", "period": "mensile",
        "end_in_days": 7,
        "warehouses": [("MAG01", "Laboratorio e punto vendita")],
    },
    {
        "name": "Ferramenta Rossi",
        "demo": "ferramenta",
        "sector": "Ferramenta",
        "vat_number": "01234560033",
        "city": "Lecce", "province": "LE", "address": "Viale Leopardi 88", "zip_code": "73100",
        "contact_email": "ferramenta@demo.blubeauty.it",
        "admin_name": "Antonio Rossi",
        "plan": "PRO", "period": "annuale",
        "end_in_days": 240,
        "warehouses": [("MAG01", "Negozio"), ("MAG02", "Magazzino esterno")],
        "extra_modules": ["fatturapa", "tentata_vendita"],  # moduli extra a pagamento, attivi per mostrarli nella demo
    },
]


def seed_base(db: Session) -> None:
    for p in DEFAULT_PLANS:
        if not db.scalar(select(Plan).where(Plan.code == p["code"])):
            db.add(Plan(**p))
    if not db.scalar(select(ReminderRule)):
        for d in DEFAULT_REMINDER_DAYS:
            db.add(ReminderRule(days_before=d, active=True))
    for t in DEFAULT_TEMPLATES:
        if not db.get(EmailTemplate, t["code"]):
            db.add(EmailTemplate(**t))
    s = get_settings()
    # Solo al primo avvio: le credenziali poi si cambiano dal pannello o dalla Console (standard comune §8), e un
    # SUPERADMIN_EMAIL rimasto nel .env non deve ricreare il vecchio accesso.
    if not db.scalar(select(SuperAdmin).limit(1)):
        db.add(SuperAdmin(email=s.superadmin_email.lower(), password_hash=hash_password(s.superadmin_password)))
    db.flush()
    # Tabelle di supporto per le aziende create prima della Fase 2 (idempotente).
    for t in db.scalars(select(Tenant)):
        bootstrap_tenant(db, t.id, t.sector)


def seed_demo(db: Session) -> None:
    on = today()
    for d in DEMO_TENANTS:
        existing = db.scalar(select(Tenant).where(Tenant.name == d["name"]))
        if existing:  # aggiunge i dati delle fasi successive alle aziende demo già create
            have = set(db.scalars(select(TenantModule.module).where(TenantModule.tenant_id == existing.id)))
            for m in d.get("extra_modules", []):
                if m not in have:
                    db.add(TenantModule(tenant_id=existing.id, module=m))
            bootstrap_tenant(db, existing.id, existing.sector)
            load_demo(db, existing.id, d["demo"])
            load_stock_demo(db, existing.id)
            continue
        plan = db.scalar(select(Plan).where(Plan.code == d["plan"]))
        end = on + timedelta(days=d["end_in_days"])
        if d["period"] == "mensile":
            start = end - relativedelta(months=1) + timedelta(days=1)
        else:
            start = end - relativedelta(years=1) + timedelta(days=1)
        tenant = Tenant(name=d["name"], sector=d["sector"], vat_number=d["vat_number"],
                        contact_name=d["admin_name"], contact_email=d["contact_email"], billing_data={},
                        notes="Azienda di esempio")
        db.add(tenant)
        db.flush()
        db.add(Subscription(tenant_id=tenant.id, plan_id=plan.id, start_date=start, end_date=end,
                            period=d["period"],
                            amount=plan.price_month if d["period"] == "mensile" else plan.price_year))
        company = Company(tenant_id=tenant.id, name=d["name"], vat_number=d["vat_number"], address=d["address"],
                          zip_code=d["zip_code"], city=d["city"], province=d["province"], email=d["contact_email"])
        db.add(company)
        db.flush()
        for code, name in d["warehouses"]:
            db.add(Warehouse(tenant_id=tenant.id, company_id=company.id, code=code, name=name))
        for m in d.get("extra_modules", []):
            db.add(TenantModule(tenant_id=tenant.id, module=m))
        db.add(User(tenant_id=tenant.id, email=d["contact_email"], full_name=d["admin_name"],
                    role="amministratore", password_hash=hash_password(DEMO_PASSWORD)))
        bootstrap_tenant(db, tenant.id, tenant.sector)
        load_demo(db, tenant.id, d["demo"])
        load_stock_demo(db, tenant.id)
    db.flush()


def main() -> None:
    # Il seed usa il ruolo proprietario (scrive anche nelle tabelle protette dalla RLS).
    engine = create_engine(get_settings().database_owner_url)
    with Session(engine) as db:
        seed_base(db)
        if "--demo" in sys.argv:
            seed_demo(db)
        db.commit()
    if "--demo" in sys.argv:
        seed_demo_documents()
    print("Seed completato.")


def seed_demo_documents() -> None:
    """Documenti demo creati col ruolo dell'applicazione, come farebbe un utente: la RLS limita ogni lettura
    all'azienda corrente (col ruolo proprietario le ricerche senza filtro vedrebbero anche le altre aziende)."""
    from app.core.db import set_tenant
    from app.documenti.demo import load_accounts_demo, load_due_demo, load_purchases_demo, load_sales_demo

    engine = create_engine(get_settings().database_url)
    names = [d["name"] for d in DEMO_TENANTS]
    from app.pos.demo import load_pos_demo

    info = {d["name"]: d for d in DEMO_TENANTS}
    with Session(engine) as db:
        tenants = [(t.id, info[t.name]) for t in db.scalars(select(Tenant).where(Tenant.name.in_(names)))]
    for tid, d in tenants:
        with Session(engine) as db:
            set_tenant(db, tid)
            load_accounts_demo(db, tid)
            load_purchases_demo(db, tid)
            load_sales_demo(db, tid)
            load_due_demo(db, tid)
            if d["plan"] in ("PLUS", "PRO"):
                load_pos_demo(db, tid, d["demo"])
            if d["plan"] == "PRO":
                from app.bi.demo import load_bi_demo
                load_bi_demo(db, tid)
            if "tentata_vendita" in d.get("extra_modules", []):
                from app.tentata.demo import load_tentata_demo
                load_tentata_demo(db, tid, DEMO_PASSWORD)
            db.commit()


if __name__ == "__main__":
    main()
