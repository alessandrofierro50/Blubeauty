import os

# Database di test separato (va impostato prima di importare l'app).
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://blubeauty_app:app@localhost:5432/blubeauty_test")
os.environ.setdefault("DATABASE_OWNER_URL", "postgresql+psycopg://blubeauty_owner:owner@localhost:5432/blubeauty_test")
os.environ["SMTP_HOST"] = ""
os.environ["RATE_LIMITS"] = "0"
os.environ["TERMS_VERSION"] = "1.0"
os.environ["TERMS_PDF_URL"] = ""  # niente download nei test: chi lo prova simula la risposta
os.environ["ADMIN_NOTIFY_EMAIL"] = "titolare@blubeauty.test"
os.environ["SUPERADMIN_EMAIL"] = "admin@blubeauty.test"
os.environ["SUPERADMIN_PASSWORD"] = "password-admin"
os.environ["TRIAL_PLAN"] = "PRO"  # i test ereditati da BluGest usano i suoi pacchetti (vedi LEGACY_PLANS)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.mailer import OUTBOX  # noqa: E402
from app.seed import seed_base  # noqa: E402

HERE = os.path.dirname(os.path.dirname(__file__))


# Pacchetti di BluGest usati SOLO dai test ereditati dal motore comune (abbonamenti, limiti, moduli, pagamenti…):
# così quei test restano identici a BluGest. I pacchetti veri di BluBeauty (AGENDA, SALONE) hanno test propri.
LEGACY_PLANS = [
    ("BASE", "Base", "29.00", "290.00", 3, 1, 1, 0, ["anagrafiche", "magazzino", "acquisti", "vendite", "scadenzario", "statistiche_base"]),
    ("PLUS", "Plus", "49.00", "490.00", 5, 1, 2, 2, ["anagrafiche", "magazzino", "acquisti", "vendite", "scadenzario", "statistiche_base",
                                                     "pos", "periferiche"]),
    ("PRO", "Pro", "79.00", "790.00", 10, 3, 5, 5, ["anagrafiche", "magazzino", "acquisti", "vendite", "scadenzario", "statistiche_base",
                                                    "pos", "periferiche", "statistiche_avanzate"]),
]


def add_legacy_plans(db):
    from decimal import Decimal
    from app.core.models import Plan
    for n, (code, name, pm, py, users, comps, whs, pos, mods) in enumerate(LEGACY_PLANS, start=10):
        db.add(Plan(code=code, name=f"BluBeauty {name}", price_month=Decimal(pm), price_year=Decimal(py), max_users=users,
                    max_companies=comps, max_warehouses=whs, max_pos=pos, sort_order=n, modules=mods))


@pytest.fixture(scope="session", autouse=True)
def database():
    owner = create_engine(get_settings().database_owner_url)
    with owner.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(os.path.join(HERE, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(HERE, "alembic"))
    command.upgrade(cfg, "head")
    yield
    owner.dispose()


@pytest.fixture(autouse=True)
def clean(database):
    owner = create_engine(get_settings().database_owner_url)
    with owner.begin() as c:
        c.execute(text("TRUNCATE tenants, email_log, audit_log, plans, reminder_rules, email_templates, saas_settings, "
                       "super_admins, payment_events, invoice_counters RESTART IDENTITY CASCADE"))
    with Session(owner) as db:
        seed_base(db)
        add_legacy_plans(db)
        db.commit()
    owner.dispose()
    OUTBOX.clear()
    yield


@pytest.fixture
def owner_db():
    engine = create_engine(get_settings().database_owner_url)
    with Session(engine) as db:
        yield db
    engine.dispose()


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


@pytest.fixture
def admin_headers(client):
    r = client.post("/api/admin/auth/login", json={"email": "admin@blubeauty.test", "password": "password-admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def make_tenant(client, admin_headers, name="Azienda Test", plan="BASE", email=None, **extra):
    email = email or f"{name.lower().replace(' ', '')}@test.it"
    body = {"name": name, "contact_email": email, "plan_code": plan, "admin_name": "Mario Rossi",
            "admin_email": email, **extra}
    r = client.post("/api/admin/tenants", json=body, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


def activate_and_login(client, tenant, password="password-123"):
    token = tenant["activation_link"].split("token=")[1]
    r = client.post("/api/auth/activate", json={"token": token, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
