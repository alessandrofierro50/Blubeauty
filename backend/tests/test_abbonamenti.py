"""Standard comune degli abbonamenti (progetto_blucode_informatica/comune/abbonamenti.md)."""

import csv
import io
from datetime import date, timedelta

from openpyxl import load_workbook
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.db import new_session
from app.core.mailer import OUTBOX, sender
from app.core.models import ReminderRule
from app.saas import logic
from app.saas.logic import SubscriptionLike as S
from app.saas.reminders import run_reminders, weekly_summary
from app.saas.service import today
from tests.conftest import activate_and_login, make_tenant


def _set_period(owner_db, tenant_id, start, end, **cols):
    sets = ", ".join(f"{k} = :{k}" for k in cols)
    owner_db.execute(text(f"UPDATE subscriptions SET start_date = :s, end_date = :e{', ' + sets if sets else ''} "
                          "WHERE tenant_id = :t"), {"s": start, "e": end, "t": tenant_id, **cols})
    owner_db.commit()


def _run(fn, on):
    db = new_session()
    try:
        out = fn(db, on)
        db.commit()
        return out
    finally:
        db.close()


# ---------------------------------------------------------------- regole


def test_prova_scaduta_subito_sospesa():
    trial = S(date(2026, 10, 1), date(2026, 10, 7), is_trial=True)
    assert logic.subscription_status(trial, date(2026, 10, 7)) == "prova"
    assert logic.subscription_status(trial, date(2026, 10, 8)) == "prova_scaduta"  # niente tolleranza
    assert logic.access_level("prova_scaduta") == "none"
    assert logic.blocked_code("prova_scaduta") == "prova_scaduta"
    assert logic.blocked_code("sospeso") == "abbonamento_sospeso"
    paid = S(date(2026, 1, 1), date(2026, 10, 7))
    assert logic.subscription_status(paid, date(2026, 10, 8)) == "tolleranza"


def test_importo_mensile():
    assert logic.monthly_amount(29, "mensile", date(2026, 1, 1), date(2026, 1, 31)) == 29
    assert logic.monthly_amount(120, "annuale", date(2026, 1, 1), date(2026, 12, 31)) == 10
    assert logic.monthly_amount(90, "personalizzata", date(2026, 1, 1), date(2026, 3, 1)) == 45  # 60 giorni


def test_giorni_di_avviso_predefiniti(client, admin_headers):
    assert client.get("/api/admin/reminder-rules", headers=admin_headers).json() == [30, 15, 7, 3, 1, 0]
    assert client.put("/api/admin/reminder-rules", headers=admin_headers, json={"days": [10, 3, 0]}).json() == [10, 3, 0]


def test_mittente_email():
    s = get_settings()
    assert s.smtp_from == "info@blucodeinformatica.it" and s.smtp_port == 465
    assert s.mail_from_name == "BluBeauty · BluCode Informatica"
    assert s.admin_notify_email == "titolare@blubeauty.test"  # nei test; predefinito blubeauty@blucodeinformatica.it
    assert sender().endswith("<info@blucodeinformatica.it>")
    from email.headerregistry import Address  # noqa: F401
    from email.message import EmailMessage
    m = EmailMessage()
    m["From"] = sender()
    assert m["From"].addresses[0].display_name == "BluBeauty · BluCode Informatica"


# ---------------------------------------------------------------- avvisi


def test_avvisi_pagati_3_giorni_fine_tolleranza_e_sospensione(client, admin_headers, owner_db):
    t = make_tenant(client, admin_headers, "Tre Giorni Srl", email="tre@test.it")
    end = today() + timedelta(days=3)
    _set_period(owner_db, t["id"], end - timedelta(days=364), end)
    assert _run(run_reminders, today()) == ["Tre Giorni Srl:giorni_3"]
    assert _run(run_reminders, today()) == []
    assert _run(run_reminders, end) == ["Tre Giorni Srl:giorni_0"]
    # ultimo giorno di tolleranza (15): «da domani sola lettura»
    assert _run(run_reminders, end + timedelta(days=14)) == []
    assert _run(run_reminders, end + timedelta(days=15)) == ["Tre Giorni Srl:fine_tolleranza"]
    mail = OUTBOX[-1]
    assert "Da domani" in mail["subject"] and mail["to"] == ["tre@test.it", "titolare@blubeauty.test"]
    # sospensione: dopo 15 di tolleranza e 30 di sola lettura
    assert _run(run_reminders, end + timedelta(days=45)) == []
    assert _run(run_reminders, end + timedelta(days=46)) == ["Tre Giorni Srl:sospensione"]
    assert "sospeso" in OUTBOX[-1]["subject"]
    assert _run(run_reminders, end + timedelta(days=47)) == []
    assert "info@blucodeinformatica.it" in OUTBOX[-1]["html"]  # {contatti}


def test_avvisi_della_prova(client, admin_headers, owner_db):
    t = make_tenant(client, admin_headers, "Prova Avvisi", email="pa@test.it", is_trial=True)
    sub = t["subscriptions"][0]
    assert (date.fromisoformat(sub["end_date"]) - date.fromisoformat(sub["start_date"])).days == 6  # 7 giorni
    end = today() + timedelta(days=6)
    _set_period(owner_db, t["id"], today(), end)
    # niente avvisi a 30/15/7 per la prova
    assert _run(run_reminders, today()) == []
    assert _run(run_reminders, end - timedelta(days=3)) == ["Prova Avvisi:prova_3"]
    assert "finisce tra 3 giorni" in OUTBOX[-1]["subject"]
    assert _run(run_reminders, end - timedelta(days=1)) == ["Prova Avvisi:prova_1"]
    assert _run(run_reminders, end) == ["Prova Avvisi:prova_0"]
    assert _run(run_reminders, end + timedelta(days=1)) == ["Prova Avvisi:prova_scaduta"]
    assert _run(run_reminders, end + timedelta(days=2)) == []


# ---------------------------------------------------------------- blocchi


def test_prova_scaduta_402_ma_login_password_e_abbonamento_permessi(client, admin_headers, owner_db):
    t = make_tenant(client, admin_headers, "Prova Finita", email="pf@test.it", is_trial=True)
    h = activate_and_login(client, t)
    _set_period(owner_db, t["id"], today() - timedelta(days=8), today() - timedelta(days=2))
    r = client.get("/api/app/companies", headers=h)
    assert r.status_code == 402 and r.json()["detail"]["code"] == "prova_scaduta"
    # login, chi sono, stato, cambio password e pagina Abbonamento restano permessi
    assert client.post("/api/auth/login", json={"email": "pf@test.it", "password": "password-123"}).status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 200
    st = client.get("/api/app/status", headers=h).json()
    assert st["status"] == "prova_scaduta" and st["access"] == "none" and st["banner"]["level"] == "error"
    page = client.get("/api/app/abbonamento", headers=h)
    assert page.status_code == 200 and page.json()["is_trial"] is True
    r = client.post("/api/auth/password", headers=h, json={"current": "password-123", "new": "nuova-pass-456"})
    assert r.status_code == 200, r.text


def test_sospeso_e_sola_lettura_codici(client, admin_headers, owner_db):
    t = make_tenant(client, admin_headers, "Pagata Scaduta", email="ps@test.it")
    h = activate_and_login(client, t)
    end = today() - timedelta(days=50)  # oltre 15 + 30
    _set_period(owner_db, t["id"], end - timedelta(days=364), end)
    r = client.get("/api/app/companies", headers=h)
    assert r.status_code == 402 and r.json()["detail"]["code"] == "abbonamento_sospeso"
    assert client.get("/api/app/abbonamento", headers=h).status_code == 200
    assert client.post("/api/auth/password", headers=h, json={"current": "password-123", "new": "nuova-pass-456"}).status_code == 200
    _set_period(owner_db, t["id"], today() - timedelta(days=384), today() - timedelta(days=20))
    r = client.post("/api/app/users", headers=h, json={"full_name": "X", "email": "x@test.it"})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "sola_lettura"
    # sospensione a mano
    client.post(f"/api/admin/tenants/{t['id']}/suspend", headers=admin_headers)
    assert client.get("/api/app/companies", headers=h).json()["detail"]["code"] == "abbonamento_sospeso"
    assert client.get("/api/app/abbonamento", headers=h).json()["status"] == "sospeso"


# ---------------------------------------------------------------- pagina Abbonamento


def test_pagina_abbonamento(client, admin_headers):
    t = make_tenant(client, admin_headers, "Pagina Srl", plan="PLUS", email="pagina@test.it")
    h = activate_and_login(client, t)
    p = client.get("/api/app/abbonamento", headers=h).json()
    assert p["plan_code"] == "PLUS" and p["status"] == "attivo" and p["days_left"] > 300
    assert p["usage"]["max_users"] == 1 and p["usage"]["max_warehouses"] == 1 and p["limits"]["max_users"] == 5
    assert len(p["history"]) == 1 and p["history"][0]["period"] == "annuale"
    assert p["contacts"]["email"] == "info@blucodeinformatica.it" and p["contacts"]["phone"]
    # un utente non amministratore vede piano, stato e contatti, non importi e storico
    client.post("/api/app/users", headers=h, json={"full_name": "Vendite", "email": "v@test.it", "role": "vendite"})
    db = new_session()
    try:
        from app.core.db import set_tenant
        from app.core.models import User
        set_tenant(db, t["id"])
        u = db.scalar(select(User).where(User.email == "v@test.it"))
        token = u.activation_token
    finally:
        db.close()
    hv = {"Authorization": "Bearer " + client.post("/api/auth/activate", json={"token": token, "password": "password-777"}).json()["token"]}
    pv = client.get("/api/app/abbonamento", headers=hv).json()
    assert pv["plan_code"] == "PLUS" and "history" not in pv and pv["amount"] is None


# ---------------------------------------------------------------- pannello


def test_converti_prova_da_oggi_e_da_fine_prova(client, admin_headers, owner_db):
    t = make_tenant(client, admin_headers, "Converti Oggi", email="co@test.it", is_trial=True, plan="PRO")
    r = client.post(f"/api/admin/tenants/{t['id']}/convert-trial", headers=admin_headers,
                    json={"plan_code": "PLUS", "period": "mensile", "start": "oggi"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["plan_code"] == "PLUS" and d["status"] in ("attivo", "in_scadenza")
    paid = [s for s in d["subscriptions"] if not s["is_trial"]][0]
    assert paid["start_date"] == today().isoformat() and paid["period"] == "mensile" and paid["amount"] == "49.00"
    # la prova resta nello storico, chiusa (iniziata oggi: dura solo oggi, ma vale il periodo pagato)
    trial = [s for s in d["subscriptions"] if s["is_trial"]]
    assert len(trial) == 1 and trial[0]["end_date"] == today().isoformat()
    again = client.post(f"/api/admin/tenants/{t['id']}/convert-trial", headers=admin_headers, json={"plan_code": "PLUS"})
    assert again.status_code in (400, 409)

    t2 = make_tenant(client, admin_headers, "Converti Dopo", email="cd@test.it", is_trial=True)
    trial_end = date.fromisoformat(t2["subscriptions"][0]["end_date"])
    d2 = client.post(f"/api/admin/tenants/{t2['id']}/convert-trial", headers=admin_headers,
                     json={"plan_code": "BASE", "period": "annuale", "start": "fine_prova", "amount": "250"}).json()
    paid2 = [s for s in d2["subscriptions"] if not s["is_trial"]][0]
    assert paid2["start_date"] == (trial_end + timedelta(days=1)).isoformat() and paid2["amount"] == "250.00"
    assert d2["status"] == "prova" and d2["end_date"] == paid2["end_date"]  # prova in corso, poi abbonamento continuo
    # prova già scaduta e convertita da oggi: l'azienda riparte con i suoi dati
    t3 = make_tenant(client, admin_headers, "Converti Scaduta", email="cs@test.it", is_trial=True)
    _set_period(owner_db, t3["id"], today() - timedelta(days=20), today() - timedelta(days=14))
    d3 = client.post(f"/api/admin/tenants/{t3['id']}/convert-trial", headers=admin_headers, json={"plan_code": "BASE"}).json()
    assert d3["status"] == "attivo"
    no = make_tenant(client, admin_headers, "Mai In Prova", email="mp@test.it")
    assert client.post(f"/api/admin/tenants/{no['id']}/convert-trial", headers=admin_headers, json={"plan_code": "BASE"}).status_code == 400


def test_esporta_aziende_csv_ed_excel(client, admin_headers):
    make_tenant(client, admin_headers, "Export Uno", email="e1@test.it", vat_number="01234567890", phone="0832 1")
    make_tenant(client, admin_headers, "Export Prova", email="e2@test.it", is_trial=True)
    r = client.get("/api/admin/tenants/export?format=csv", headers=admin_headers)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][:6] == ["Azienda", "Partita IVA", "Referente", "Email", "Telefono", "Pacchetto"]
    uno = next(x for x in rows if x[0] == "Export Uno")
    assert uno[1] == "01234567890" and uno[3] == "e1@test.it" and uno[9] == "290,00" and uno[10] == "annuale" and uno[11] == "no"
    assert next(x for x in rows if x[0] == "Export Prova")[11] == "sì"
    x = client.get("/api/admin/tenants/export", headers=admin_headers)
    ws = load_workbook(io.BytesIO(x.content)).active
    assert ws["A1"].value == "Azienda" and ws.max_row == 3
    assert client.get("/api/admin/tenants/export").status_code == 401


def test_riepilogo_settimanale_con_prove(client, admin_headers, owner_db):
    make_tenant(client, admin_headers, "Nuova Prova Srl", email="np@test.it", is_trial=True)
    old = make_tenant(client, admin_headers, "Prova Vecchia", email="pv@test.it", is_trial=True)
    _set_period(owner_db, old["id"], today() - timedelta(days=20), today() - timedelta(days=14))
    assert _run(weekly_summary, today()) is True
    html = OUTBOX[-1]["html"]
    assert "Nuove prove" in html and "Nuova Prova Srl" in html
    assert "Prove in scadenza" in html and "Prove scadute non convertite" in html and "Prova Vecchia" in html
    assert OUTBOX[-1]["to"] == ["titolare@blubeauty.test"]


def test_regola_3_giorni_aggiunta_dalla_migrazione(owner_db):
    # il seed dei test parte dai valori predefiniti: la regola dei 3 giorni c'è
    assert owner_db.get(ReminderRule, 3) is not None


def test_ciclo_di_vita_modificabile_dal_pannello(client, admin_headers, owner_db):
    assert client.get("/api/admin/lifecycle", headers=admin_headers).json() == {
        "grace_days": 15, "readonly_days": 30, "trial_reminder_days": [3, 1, 0]}
    r = client.put("/api/admin/lifecycle", headers=admin_headers,
                   json={"grace_days": 10, "readonly_days": 20, "trial_reminder_days": [2, 0, 2]})
    assert r.json() == {"grace_days": 10, "readonly_days": 20, "trial_reminder_days": [2, 0]}
    # i nuovi periodi prendono i valori predefiniti
    t = make_tenant(client, admin_headers, "Valori Nuovi", email="vn@test.it")
    sub = t["subscriptions"][0]
    assert sub["grace_days"] == 10 and sub["readonly_days"] == 20
    end = today() - timedelta(days=11)
    _set_period(owner_db, t["id"], end - timedelta(days=364), end)
    h = activate_and_login(client, t)
    assert client.get("/api/app/status", headers=h).json()["status"] == "sola_lettura"  # oltre 10 giorni
    # avvisi della prova con i giorni del pannello
    p = make_tenant(client, admin_headers, "Prova Due Giorni", email="p2@test.it", is_trial=True)
    pend = today() + timedelta(days=2)
    _set_period(owner_db, p["id"], today() - timedelta(days=4), pend)
    assert "Prova Due Giorni:prova_2" in _run(run_reminders, today())
    # conversione della prova: tolleranza predefinita
    d = client.post(f"/api/admin/tenants/{p['id']}/convert-trial", headers=admin_headers, json={"plan_code": "BASE"}).json()
    paid = [s for s in d["subscriptions"] if not s["is_trial"]][0]
    assert paid["grace_days"] == 10 and paid["readonly_days"] == 20


def test_migrazione_0022_su_database_esistente(owner_db):
    """La 0022 aggiunge la regola dei 3 giorni solo dove le regole esistono già, e toglie il vecchio testo di fine
    tolleranza se non personalizzato (il seed poi lo ricrea col testo nuovo)."""
    from alembic import command
    from alembic.config import Config
    import os
    from app.seed import seed_base

    here = os.path.dirname(os.path.dirname(__file__))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "alembic"))
    owner_db.execute(text("DELETE FROM reminder_rules WHERE days_before = 3"))
    owner_db.execute(text("UPDATE email_templates SET subject = 'BluBeauty è ora in sola lettura' WHERE code = 'fine_tolleranza'"))
    owner_db.commit()
    owner_db.close()
    command.downgrade(cfg, "0021_termini")
    command.upgrade(cfg, "head")
    owner_db.expire_all()
    assert owner_db.get(ReminderRule, 3) is not None
    assert owner_db.execute(text("SELECT count(*) FROM email_templates WHERE code = 'fine_tolleranza'")).scalar() == 0
    cols = {r[0] for r in owner_db.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'super_admins'"))}
    assert {"token_version", "created_at", "credentials_changed_at"} <= cols
    seed_base(owner_db)
    owner_db.commit()
    assert "Da domani" in owner_db.execute(text("SELECT subject FROM email_templates WHERE code = 'fine_tolleranza'")).scalar()
