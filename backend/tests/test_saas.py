from datetime import timedelta

from sqlalchemy import select, text

from app.core.db import new_session, set_tenant
from app.core.mailer import OUTBOX
from app.core.models import Company, EmailLog, User
from app.saas.reminders import run_reminders, weekly_summary
from app.saas.service import today
from tests.conftest import activate_and_login, make_tenant


def test_login_admin_errato(client):
    r = client.post("/api/admin/auth/login", json={"email": "admin@blubeauty.test", "password": "no"})
    assert r.status_code == 401


def test_area_admin_protetta(client):
    assert client.get("/api/admin/tenants").status_code == 401


def test_creazione_azienda_e_attivazione(client, admin_headers):
    t = make_tenant(client, admin_headers, "Panificio Test", plan="BASE")
    assert t["status"] == "attivo" and t["plan_code"] == "BASE"
    assert len(t["subscriptions"]) == 1
    assert any("attiva il tuo account" in m["subject"] for m in OUTBOX)
    h = activate_and_login(client, t)
    me = client.get("/api/auth/me", headers=h).json()
    assert me["tenant"]["name"] == "Panificio Test"
    # il link di attivazione vale una volta sola
    token = t["activation_link"].split("token=")[1]
    assert client.post("/api/auth/activate", json={"token": token, "password": "altra-pass-1"}).status_code == 400
    # login con password
    r = client.post("/api/auth/login", json={"email": "panificiotest@test.it", "password": "password-123"})
    assert r.status_code == 200


def test_isolamento_tra_aziende(client, admin_headers):
    a = make_tenant(client, admin_headers, "Azienda A")
    b = make_tenant(client, admin_headers, "Azienda B")
    ha = activate_and_login(client, a)
    users_a = client.get("/api/app/users", headers=ha).json()["users"]
    assert [u["email"] for u in users_a] == ["aziendaa@test.it"]
    companies = client.get("/api/app/companies", headers=ha).json()
    assert [c["name"] for c in companies] == ["Azienda A"]

    # Anche a livello di database: senza tenant non si vede nulla, con il tenant A solo i dati di A.
    db = new_session()
    try:
        assert db.scalars(select(User)).all() == []
        set_tenant(db, a["id"])
        assert {c.name for c in db.scalars(select(Company))} == {"Azienda A"}
        # scrivere una riga di B mentre si è "dentro" A è impedito dalla policy
        try:
            db.execute(text("INSERT INTO companies (id, tenant_id, name, tax_regime) "
                            "VALUES (gen_random_uuid(), :b, 'intrusa', 'RF01')"), {"b": b["id"]})
            assert False, "inserimento consentito"
        except Exception as exc:
            assert "row-level security" in str(exc)
    finally:
        db.rollback()
        db.close()


def test_rinnovo_un_clic(client, admin_headers):
    t = make_tenant(client, admin_headers, "Rinnovo Spa", period="annuale")
    first_end = t["end_date"]
    r = client.post(f"/api/admin/tenants/{t['id']}/renew", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data["subscriptions"]) == 2
    assert data["end_date"] > first_end  # la scadenza effettiva si sposta in avanti


def test_cambio_pacchetto_attiva_moduli(client, admin_headers):
    t = make_tenant(client, admin_headers, "Upgrade Srl", plan="BASE")
    h = activate_and_login(client, t)
    r = client.get("/api/app/modules/pos/check", headers=h)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "modulo_non_incluso"
    on = today()
    r = client.post(f"/api/admin/tenants/{t['id']}/subscriptions", headers=admin_headers,
                    json={"plan_code": "PLUS", "start_date": str(on), "end_date": str(on + timedelta(days=364))})
    assert r.status_code == 201, r.text
    assert r.json()["plan_code"] == "PLUS"
    assert client.get("/api/app/modules/pos/check", headers=h).status_code == 200


def test_modulo_extra_singolo_cliente(client, admin_headers):
    t = make_tenant(client, admin_headers, "Extra Srl", plan="BASE")
    h = activate_and_login(client, t)
    client.patch(f"/api/admin/tenants/{t['id']}", json={"extra_modules": ["statistiche_avanzate"]}, headers=admin_headers)
    assert client.get("/api/app/modules/statistiche_avanzate/check", headers=h).status_code == 200


def _set_end(owner_db, tenant_id, end):
    owner_db.execute(text("UPDATE subscriptions SET end_date = :e, start_date = :s WHERE tenant_id = :t"),
                     {"e": end, "s": end - timedelta(days=364), "t": tenant_id})
    owner_db.commit()


def test_sola_lettura_e_sospensione(client, admin_headers, owner_db):
    t = make_tenant(client, admin_headers, "Scaduta Srl", plan="BASE")
    h = activate_and_login(client, t)
    _set_end(owner_db, t["id"], today() - timedelta(days=20))  # oltre i 15 giorni di tolleranza
    assert client.get("/api/app/status", headers=h).json()["status"] == "sola_lettura"
    r = client.post("/api/app/users", headers=h, json={"full_name": "Nuovo", "email": "n@test.it"})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "sola_lettura"
    client.post(f"/api/admin/tenants/{t['id']}/suspend", headers=admin_headers)
    # sospeso: lo stato resta leggibile (per la pagina «Abbonamento»), il resto risponde 402
    assert client.get("/api/app/status", headers=h).json()["status"] == "sospeso"
    assert client.get("/api/app/companies", headers=h).status_code == 402
    client.post(f"/api/admin/tenants/{t['id']}/reactivate", headers=admin_headers)
    assert client.get("/api/app/companies", headers=h).status_code == 200


def test_limite_utenti(client, admin_headers):
    t = make_tenant(client, admin_headers, "Piccola Srl", plan="BASE")  # BASE: max 3 utenti
    h = activate_and_login(client, t)
    for i in range(2):
        assert client.post("/api/app/users", headers=h, json={"full_name": f"U{i}", "email": f"u{i}@test.it"}).status_code == 201
    r = client.post("/api/app/users", headers=h, json={"full_name": "U9", "email": "u9@test.it"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "limite_utenti"


def test_avvisi_scadenza_senza_doppioni(client, admin_headers, owner_db):
    t = make_tenant(client, admin_headers, "Avvisi Srl", plan="BASE", email="avvisi@test.it")
    _set_end(owner_db, t["id"], today() + timedelta(days=7))
    OUTBOX.clear()
    db = new_session()
    try:
        assert run_reminders(db, today()) == ["Avvisi Srl:giorni_7"]
        assert run_reminders(db, today()) == []  # secondo giro: nessun doppione
        db.commit()
        mail = OUTBOX[0]
        assert "7 giorni" in mail["subject"]
        assert mail["to"] == ["avvisi@test.it", "titolare@blubeauty.test"]
        # il giorno dopo nessun nuovo avviso; a 1 giorno dalla scadenza sì
        assert run_reminders(db, today() + timedelta(days=1)) == []
        assert run_reminders(db, today() + timedelta(days=6)) == ["Avvisi Srl:giorni_1"]
        assert run_reminders(db, today() + timedelta(days=7)) == ["Avvisi Srl:giorni_0"]
        # fine tolleranza (15 giorni) -> passaggio in sola lettura
        assert run_reminders(db, today() + timedelta(days=7 + 16)) == ["Avvisi Srl:fine_tolleranza"]
        db.commit()
        assert db.scalar(select(EmailLog).where(EmailLog.rule == "giorni_0")) is not None
    finally:
        db.close()


def test_rinnovo_azzera_gli_avvisi(client, admin_headers, owner_db):
    t = make_tenant(client, admin_headers, "Rinnova Srl", plan="BASE")
    _set_end(owner_db, t["id"], today() + timedelta(days=7))
    db = new_session()
    try:
        assert run_reminders(db, today()) == ["Rinnova Srl:giorni_7"]
        db.commit()
    finally:
        db.close()
    client.post(f"/api/admin/tenants/{t['id']}/renew", headers=admin_headers)
    db = new_session()
    try:
        assert run_reminders(db, today() + timedelta(days=6)) == []  # rinnovato: niente avviso a 1 giorno
    finally:
        db.close()


def test_riepilogo_settimanale_una_volta(client, admin_headers):
    make_tenant(client, admin_headers, "Riepilogo Srl")
    db = new_session()
    try:
        assert weekly_summary(db, today()) is True
        assert weekly_summary(db, today()) is False
        db.commit()
    finally:
        db.close()


def test_impersonificazione_registrata(client, admin_headers):
    t = make_tenant(client, admin_headers, "Assistenza Srl")
    detail = client.get(f"/api/admin/tenants/{t['id']}", headers=admin_headers).json()
    uid = detail["users"][0]["id"]
    r = client.post(f"/api/admin/tenants/{t['id']}/impersonate/{uid}", headers=admin_headers)
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get("/api/auth/me", headers=h).json()["impersonated"] is True
    log = client.get(f"/api/admin/audit?tenant_id={t['id']}", headers=admin_headers).json()
    assert any(a["action"] == "impersonificazione" for a in log)


def test_dashboard(client, admin_headers):
    make_tenant(client, admin_headers, "Uno Srl", plan="BASE")
    make_tenant(client, admin_headers, "Due Srl", plan="PRO")
    d = client.get("/api/admin/dashboard", headers=admin_headers).json()
    assert d["tenants_total"] == 2
    assert d["by_plan"] == {"BASE": 1, "PRO": 1}
    assert float(d["mrr"]) > 0
