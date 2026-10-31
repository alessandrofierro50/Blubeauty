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
