"""API per la BluCode Console: §7 riepilogo e §8 credenziali del super amministratore (comune/abbonamenti.md)."""

from datetime import date, timedelta

import pyotp
import pytest
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.db import new_session
from app.core.mailer import OUTBOX
from app.core.models import AuditLog, SuperAdmin
from app.core.security import hash_password, verify_password
from app.saas.console import build_summary
from app.saas.service import today
from tests.conftest import activate_and_login, make_tenant

API = "chiave-console-lunga-e-casuale-1234567890"
ADMIN = "seconda-chiave-diversa-0987654321"
NEW_PW = "NuovaPassword2026"


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(get_settings(), "console_api_key", API)
    monkeypatch.setattr(get_settings(), "console_admin_key", ADMIN)


def _h(api=API, admin=ADMIN):
    h = {"Authorization": f"Bearer {api}"}
    if admin is not None:
        h["X-Console-Admin-Key"] = admin
    return h


def _period(owner_db, tenant_id, start, end, **cols):
    sets = "".join(f", {k} = :{k}" for k in cols)
    owner_db.execute(text(f"UPDATE subscriptions SET start_date = :s, end_date = :e{sets} WHERE tenant_id = :t"),
                     {"s": start, "e": end, "t": tenant_id, **cols})
    owner_db.commit()


def _summary(on=None):
    db = new_session()
    try:
        return build_summary(db, on)
    finally:
        db.close()


# ---------------------------------------------------------------- §7 riepilogo


def test_riepilogo_404_senza_chiave_e_401_con_chiave_errata(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "console_api_key", "")
    assert client.get("/api/console/riepilogo", headers=_h()).status_code == 404
    monkeypatch.setattr(get_settings(), "console_api_key", API)
    assert client.get("/api/console/riepilogo").status_code == 401
    assert client.get("/api/console/riepilogo", headers=_h(api="sbagliata")).status_code == 401
    r = client.get("/api/console/riepilogo", headers=_h(admin=None))
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers


def test_riepilogo_formato_e_calcoli(client, admin_headers, owner_db, keys):
    on = today()
    # attiva annuale PRO 790 (in scadenza tra 7 giorni)
    a = make_tenant(client, admin_headers, "Ferramenta Rossi", plan="PRO", email="fr@test.it", phone="0832 111")
    _period(owner_db, a["id"], on - timedelta(days=358), on + timedelta(days=7), amount=790, period="annuale")
    # attiva mensile BASE 29, iniziata oggi (incassato del mese)
    b = make_tenant(client, admin_headers, "Panificio", plan="BASE", email="pa@test.it", period="mensile")
    # personalizzata 90 € su 60 giorni = 45/mese
    c = make_tenant(client, admin_headers, "Custom", plan="BASE", email="cu@test.it")
    _period(owner_db, c["id"], on - timedelta(days=10), on + timedelta(days=49), amount=90, period="personalizzata")
    # tolleranza (scaduta 4 giorni fa, 120 €/anno = 10/mese)
    d = make_tenant(client, admin_headers, "In Tolleranza", plan="BASE", email="to@test.it")
    _period(owner_db, d["id"], on - timedelta(days=369), on - timedelta(days=4), amount=120)
    # sola lettura e sospesa
    e = make_tenant(client, admin_headers, "Sola Lettura", plan="BASE", email="sl@test.it")
    _period(owner_db, e["id"], on - timedelta(days=385), on - timedelta(days=20))
    f = make_tenant(client, admin_headers, "Sospesa", plan="BASE", email="so@test.it")
    _period(owner_db, f["id"], on - timedelta(days=425), on - timedelta(days=60))
    # prova in corso e prova scaduta non convertita
    make_tenant(client, admin_headers, "In Prova", plan="PRO", email="ip@test.it", is_trial=True)
    g = make_tenant(client, admin_headers, "Prova Finita", plan="PRO", email="pf@test.it", is_trial=True)
    _period(owner_db, g["id"], on - timedelta(days=12), on - timedelta(days=6))

    r = client.get("/api/console/riepilogo", headers=_h(admin=None))
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j) == {"prodotto", "generato_il", "aziende", "ricavi", "movimenti_30_giorni", "per_piano",
                      "in_scadenza", "scadute", "andamento_12_mesi"}
    assert j["prodotto"] == "BluBeauty" and j["generato_il"][-6:] in ("+01:00", "+02:00")
    assert j["aziende"] == {"totale": 8, "attive": 3, "prova": 1, "tolleranza": 1, "sola_lettura": 1, "sospese": 2}
    # 790/12 + 29 + 45 + 10 (tolleranza conta) = 149.83
    assert j["ricavi"]["mensile_ricorrente"] == 149.83
    assert j["ricavi"]["annuale_ricorrente"] == round(149.8333333 * 12, 2)
    assert j["ricavi"]["incassato_mese_corrente"] >= 29.0  # il periodo del Panificio inizia oggi
    assert isinstance(j["ricavi"]["incassato_anno_corrente"], float)
    piani = {p["piano"]: p for p in j["per_piano"]}
    assert piani["Pro"]["aziende"] == 1 and piani["Pro"]["mensile_ricorrente"] == 65.83
    assert piani["Base"]["aziende"] == 3
    # in scadenza entro 30 giorni, ordinati per data (la prova in corso finisce tra 6 giorni)
    names = [x["azienda"] for x in j["in_scadenza"]]
    assert names[:2] == ["In Prova", "Ferramenta Rossi"]
    fr = j["in_scadenza"][1]
    assert fr == {"azienda": "Ferramenta Rossi", "piano": "Pro", "scadenza": (on + timedelta(days=7)).isoformat(),
                  "giorni": 7, "stato": "attivo", "importo": 790.0, "periodicita": "annuale", "prova": False,
                  "email": "fr@test.it", "telefono": "0832 111"}
    assert j["in_scadenza"][0]["stato"] == "prova" and j["in_scadenza"][0]["prova"] is True
    # scadute: ordinate per data di scadenza
    sc = j["scadute"]
    assert [x["azienda"] for x in sc] == ["Sospesa", "Sola Lettura", "Prova Finita", "In Tolleranza"]
    assert {x["stato"] for x in sc} <= {"tolleranza", "sola_lettura", "sospeso"}
    assert next(x for x in sc if x["azienda"] == "In Tolleranza")["giorni_da"] == 4
    mov = j["movimenti_30_giorni"]
    assert mov["nuove_prove"] == 2 and mov["prove_scadute_non_convertite"] == 1
    assert len(j["andamento_12_mesi"]) == 12
    last = j["andamento_12_mesi"][-1]
    assert last["mese"] == on.strftime("%Y-%m") and last["mensile_ricorrente"] == 149.83 and last["aziende_paganti"] == 4
    assert last["incassato"] == j["ricavi"]["incassato_mese_corrente"]
    assert b and c


def test_riepilogo_movimenti_rinnovi_e_conversioni(client, admin_headers, owner_db, keys):
    on = today()
    t = make_tenant(client, admin_headers, "Rinnova", plan="BASE", email="rn@test.it")
    _period(owner_db, t["id"], on - timedelta(days=364 + 5), on - timedelta(days=5))
    client.post(f"/api/admin/tenants/{t['id']}/renew", headers=admin_headers)
    p = make_tenant(client, admin_headers, "Converte", plan="BASE", email="cv@test.it", is_trial=True)
    _period(owner_db, p["id"], on - timedelta(days=3), on + timedelta(days=3))
    client.post(f"/api/admin/tenants/{p['id']}/convert-trial", headers=admin_headers, json={"plan_code": "BASE"})
    s = make_tenant(client, admin_headers, "Sospesa A Mano", plan="BASE", email="sm@test.it")
    client.post(f"/api/admin/tenants/{s['id']}/suspend", headers=admin_headers)
    mov = _summary()["movimenti_30_giorni"]
    assert mov["rinnovi"] == 1 and mov["prove_convertite"] == 1 and mov["nuove_prove"] == 1
    assert mov["nuovi_abbonamenti"] == 1  # «Sospesa A Mano», creata oggi
    assert mov["disdette_o_sospensioni"] == 1


def test_riepilogo_andamento_12_mesi_dai_periodi(client, admin_headers, owner_db, keys):
    on = today()
    t = make_tenant(client, admin_headers, "Storica", plan="BASE", email="st@test.it", period="mensile")
    # mensile 29 € iniziato 3 mesi fa e mai rinnovato: pagante solo nelle fotografie di fine mese coperte
    start = (on.replace(day=1) - timedelta(days=1)).replace(day=1)  # primo del mese scorso
    _period(owner_db, t["id"], start, start + timedelta(days=40), amount=29, period="mensile")
    trend = {m["mese"]: m for m in _summary()["andamento_12_mesi"]}
    prev = start.strftime("%Y-%m")
    assert trend[prev]["aziende_paganti"] == 1 and trend[prev]["mensile_ricorrente"] == 29.0
    two_ago = (start - timedelta(days=1)).strftime("%Y-%m")
    assert trend[two_ago]["aziende_paganti"] == 0
    # incassato del mese: importi dei periodi non di prova iniziati in quel mese
    assert trend[prev]["incassato"] == 29.0 and trend[two_ago]["incassato"] == 0.0
    make_tenant(client, admin_headers, "Prova Non Incassa", plan="PRO", email="pni@test.it", is_trial=True)
    s = _summary()
    cur = s["andamento_12_mesi"][-1]
    assert cur["mese"] == today().strftime("%Y-%m") and cur["incassato"] == 0.0
    assert set(cur) == {"mese", "mensile_ricorrente", "incassato", "aziende_paganti", "nuove_prove"}


# ---------------------------------------------------------------- §8 credenziali


def test_credenziali_404_se_chiave_admin_vuota(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "console_api_key", API)
    monkeypatch.setattr(get_settings(), "console_admin_key", "")
    r = client.post("/api/console/super-admin/credenziali", headers=_h(), json={"password": NEW_PW})
    assert r.status_code == 404


def test_credenziali_servono_entrambe_le_chiavi(client, keys):
    url = "/api/console/super-admin/credenziali"
    assert client.post(url, headers=_h(admin=None), json={"password": NEW_PW}).status_code == 401
    assert client.post(url, headers=_h(admin="sbagliata"), json={"password": NEW_PW}).status_code == 401
    assert client.post(url, headers=_h(api="sbagliata"), json={"password": NEW_PW}).status_code == 401
    assert client.post(url, headers={"X-Console-Admin-Key": ADMIN}, json={"password": NEW_PW}).status_code == 401


@pytest.mark.parametrize("pw", ["Corta1", "tuttominuscole123", "TUTTOMAIUSCOLE123", "SenzaCifreMaiLunga"])
def test_credenziali_password_debole_422(client, keys, pw):
    r = client.post("/api/console/super-admin/credenziali", headers=_h(), json={"password": pw})
    assert r.status_code == 422


def test_credenziali_cambio_invalida_sessioni(client, admin_headers, owner_db, keys):
    t = make_tenant(client, admin_headers, "Assistita", email="as@test.it")
    # sessione di impersonificazione aperta prima del cambio
    db = new_session()
    try:
        from app.core.db import set_tenant
        from app.core.models import User
        set_tenant(db, t["id"])
        uid = db.scalar(select(User.id).where(User.email == "as@test.it"))
    finally:
        db.close()
    activate_and_login(client, t)
    imp = client.post(f"/api/admin/tenants/{t['id']}/impersonate/{uid}", headers=admin_headers).json()["token"]
    imp_h = {"Authorization": f"Bearer {imp}"}
    assert client.get("/api/app/companies", headers=imp_h).status_code == 200
    # verifica in due passaggi attiva: deve restare com'è
    owner_db.execute(text("UPDATE super_admins SET totp_secret = :s, totp_enabled = true"), {"s": pyotp.random_base32()})
    owner_db.commit()
    OUTBOX.clear()

    r = client.post("/api/console/super-admin/credenziali", headers=_h(),
                    json={"email": "Titolare@BluCodeInformatica.it", "password": NEW_PW})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True and j["email"] == "titolare@blucodeinformatica.it" and "password" not in j
    assert date.fromisoformat(j["cambiato_il"][:10]) == today()

    # sessioni e token precedenti non valgono più (anche l'impersonificazione)
    assert client.get("/api/admin/auth/me", headers=admin_headers).status_code == 401
    assert client.get("/api/app/companies", headers=imp_h).status_code == 401
    # vecchie credenziali rifiutate, nuove accettate (con TOTP, ancora attivo)
    assert client.post("/api/admin/auth/login", json={"email": "admin@blubeauty.test", "password": "password-admin"}).status_code == 401
    r = client.post("/api/admin/auth/login", json={"email": "titolare@blucodeinformatica.it", "password": NEW_PW})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "totp_richiesto"
    owner_db.expire_all()
    admin = owner_db.scalar(select(SuperAdmin))
    assert admin.totp_enabled is True and verify_password(NEW_PW, admin.password_hash)
    assert NEW_PW not in admin.password_hash and admin.token_version == 1
    code = pyotp.TOTP(admin.totp_secret).now()
    r = client.post("/api/admin/auth/login", json={"email": "titolare@blucodeinformatica.it", "password": NEW_PW, "totp": code})
    assert r.status_code == 200
    assert client.get("/api/admin/auth/me", headers={"Authorization": f"Bearer {r.json()['token']}"}).status_code == 200
    # registro: chi «console», IP, data
    entry = owner_db.scalar(select(AuditLog).where(AuditLog.action == "credenziali da console"))
    assert entry.after["chi"] == "console" and entry.after["ip"] and entry.after["data"]
    # avviso a ADMIN_NOTIFY_EMAIL, senza la password
    mail = [m for m in OUTBOX if "credenziali" in m["subject"]]
    assert len(mail) == 1 and mail[0]["to"] == ["titolare@blubeauty.test"] and NEW_PW not in mail[0]["html"]


def test_credenziali_solo_password_e_nessun_cambio_forzato(client, keys, owner_db):
    r = client.post("/api/console/super-admin/credenziali", headers=_h(), json={"password": NEW_PW})
    assert r.status_code == 200 and r.json()["email"] == "admin@blubeauty.test"
    r = client.post("/api/admin/auth/login", json={"email": "admin@blubeauty.test", "password": NEW_PW})
    assert r.status_code == 200
    # il super amministratore non ha cambio forzato: accede subito al pannello
    assert client.get("/api/admin/tenants", headers={"Authorization": f"Bearer {r.json()['token']}"}).status_code == 200


def test_credenziali_email_gia_usata_409(client, admin_headers, owner_db, keys):
    make_tenant(client, admin_headers, "Cliente", email="cliente@test.it")
    owner_db.add(SuperAdmin(email="secondo@blucodeinformatica.it", password_hash=hash_password("x")))
    owner_db.commit()
    url = "/api/console/super-admin/credenziali"
    assert client.post(url, headers=_h(), json={"email": "secondo@blucodeinformatica.it", "password": NEW_PW}).status_code == 409
    assert client.post(url, headers=_h(), json={"email": "cliente@test.it", "password": NEW_PW}).status_code == 409
    assert client.post(url, headers=_h(), json={"email": "non-una-email", "password": NEW_PW}).status_code == 422


def test_credenziali_super_admin_principale(client, owner_db, keys, monkeypatch):
    owner_db.execute(text("UPDATE super_admins SET created_at = now() - interval '1 day'"))
    owner_db.add(SuperAdmin(email="secondo@blubeauty.test", password_hash=hash_password("x")))
    owner_db.commit()
    # senza CONSOLE_SUPERADMIN_EMAIL: il primo creato
    assert client.post("/api/console/super-admin/credenziali", headers=_h(),
                       json={"password": NEW_PW}).json()["email"] == "admin@blubeauty.test"
    monkeypatch.setattr(get_settings(), "console_superadmin_email", "Secondo@blubeauty.test")
    assert client.post("/api/console/super-admin/credenziali", headers=_h(),
                       json={"password": NEW_PW}).json()["email"] == "secondo@blubeauty.test"


def test_credenziali_limite_5_all_ora(client, keys, monkeypatch):
    from app.auth import passwords
    monkeypatch.setattr(get_settings(), "rate_limits", True)
    monkeypatch.setattr(passwords, "_memory", {})
    try:
        import redis
        redis.Redis.from_url(get_settings().redis_url).delete("rl:console:credenziali")
    except Exception:  # noqa: BLE001
        pass
    codes = [client.post("/api/console/super-admin/credenziali", headers=_h(api="x"), json={"password": NEW_PW}).status_code
             for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    try:
        redis.Redis.from_url(get_settings().redis_url).delete("rl:console:credenziali")
    except Exception:  # noqa: BLE001
        pass
