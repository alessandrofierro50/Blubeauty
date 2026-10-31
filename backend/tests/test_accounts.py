"""Password provvisorie, recupero password (utenti e super amministratore) e prova gratuita dal sito."""

import re

from app.core.config import get_settings
from app.core.mailer import OUTBOX
from tests.conftest import make_tenant


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def bearer(r):
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_password_provvisoria_alla_creazione_e_rigenerata(client, admin_headers):
    t = make_tenant(client, admin_headers, "Rossi Srl", admin_password="Prova12345")
    assert t["temp_password"] == "Prova12345" and t["activation_link"] is None and t["email_sent"]
    mail = OUTBOX[-1]
    assert mail["to"] == ["rossisrl@test.it"] and "Prova12345" in mail["html"] and "rossisrl@test.it" in mail["html"]
    r = login(client, "rossisrl@test.it", "Prova12345")
    assert r.status_code == 200
    h = bearer(r)
    assert client.get("/api/auth/me", headers=h).json()["user"]["must_change_password"] is True
    assert client.post("/api/auth/password", headers=h, json={"current": "Prova12345", "new": "Prova12345"}).status_code == 422
    assert client.post("/api/auth/password", headers=h, json={"current": "Prova12345", "new": "MiaPassword9"}).status_code == 200
    assert client.get("/api/auth/me", headers=h).json()["user"]["must_change_password"] is False
    # il super amministratore genera una nuova password provvisoria (vista solo ora)
    detail = client.get(f"/api/admin/tenants/{t['id']}", headers=admin_headers).json()
    uid = detail["users"][0]["id"]
    r = client.post(f"/api/admin/tenants/{t['id']}/users/{uid}/password", headers=admin_headers, json={"send_email": True}).json()
    assert len(r["password"]) == 12 and r["email_sent"]
    assert login(client, "rossisrl@test.it", "MiaPassword9").status_code == 401
    assert login(client, "rossisrl@test.it", r["password"]).status_code == 200
    # password troppo semplice rifiutata
    assert client.post(f"/api/admin/tenants/{t['id']}/users/{uid}/password", headers=admin_headers,
                       json={"password": "12345678"}).status_code == 422


def test_creazione_senza_password_usa_il_link(client, admin_headers):
    t = make_tenant(client, admin_headers, "Link Srl")
    assert t["temp_password"] is None and "/attiva?token=" in t["activation_link"]
    g = client.get("/api/admin/password-provvisoria", headers=admin_headers).json()["password"]
    assert len(g) == 12 and re.search(r"\d", g) and re.search(r"[A-Z]", g)


def test_password_dimenticata_utente(client, admin_headers):
    make_tenant(client, admin_headers, "Bianchi Srl", admin_password="Prova12345")
    OUTBOX.clear()
    # email sconosciuta: stessa risposta, nessuna email
    r = client.post("/api/auth/password-dimenticata", json={"email": "nessuno@test.it"})
    assert r.status_code == 200 and not OUTBOX
    r = client.post("/api/auth/password-dimenticata", json={"email": "BIANCHISRL@test.it"})
    assert r.status_code == 200 and len(OUTBOX) == 1
    token = re.search(r"reimposta-password\?token=([\w-]+)", OUTBOX[0]["html"]).group(1)
    assert client.post("/api/auth/reimposta-password", json={"token": token, "password": "corta"}).status_code == 422
    r = client.post("/api/auth/reimposta-password", json={"token": token, "password": "NuovaPass77"})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=bearer(r)).json()["user"]["must_change_password"] is False
    assert login(client, "bianchisrl@test.it", "NuovaPass77").status_code == 200
    # il link vale una volta sola
    assert client.post("/api/auth/reimposta-password", json={"token": token, "password": "AltraPass88"}).status_code == 400


def test_password_super_amministratore(client, admin_headers):
    h = admin_headers
    assert client.post("/api/admin/auth/password", headers=h, json={"current": "sbagliata", "new": "NuovaAdmin2026x"}).status_code == 400
    assert client.post("/api/admin/auth/password", headers=h, json={"current": "password-admin", "new": "Corta123"}).status_code == 422
    assert client.post("/api/admin/auth/password", headers=h, json={"current": "password-admin", "new": "NuovaAdmin2026x"}).status_code == 200
    assert client.post("/api/admin/auth/login", json={"email": "admin@blubeauty.test", "password": "password-admin"}).status_code == 401
    assert client.post("/api/admin/auth/login", json={"email": "admin@blubeauty.test", "password": "NuovaAdmin2026x"}).status_code == 200
    # recupero via email
    OUTBOX.clear()
    assert client.post("/api/admin/auth/password-dimenticata", json={"email": "altro@test.it"}).status_code == 200 and not OUTBOX
    client.post("/api/admin/auth/password-dimenticata", json={"email": "admin@blubeauty.test"})
    token = re.search(r"admin/reimposta-password\?token=([\w-]+)", OUTBOX[0]["html"]).group(1)
    assert client.post("/api/admin/auth/reimposta-password", json={"token": token, "password": "RecuperataAdmin1"}).status_code == 200
    assert client.post("/api/admin/auth/login", json={"email": "admin@blubeauty.test", "password": "RecuperataAdmin1"}).status_code == 200
    assert client.post("/api/admin/auth/reimposta-password", json={"token": token, "password": "AncoraUnaAdmin2"}).status_code == 400


def test_prova_gratuita_dal_sito(client, admin_headers):
    info = client.get("/api/public/prova").json()
    assert info["enabled"] and info["days"] == 7 and info["product"] == "BluBeauty" and info["terms_version"] == "1.0"
    body = {"company_name": "Pasticceria Dolce", "vat_number": "IT 01234560033", "sector": "Alimentari", "name": "Anna Dolce",
            "email": "anna@dolce.it", "phone": "333 1112223", "privacy": True, "terms": True, "terms_version": "1.0",
            "elapsed_ms": 25000}
    OUTBOX.clear()
    r = client.post("/api/public/prova", json=body)
    assert r.status_code == 201, r.text
    assert "password" not in r.text.lower().replace("password provvisoria", "")  # la password viaggia solo via email
    creds = next(m for m in OUTBOX if m["to"] == ["anna@dolce.it"])
    pw = re.search(r"monospace;font-size:16px\">([A-Za-z0-9]+)<", creds["html"]).group(1)
    h = bearer(login(client, "anna@dolce.it", pw))
    me = client.get("/api/auth/me", headers=h).json()
    assert me["user"]["must_change_password"] and me["subscription"]["status"] == "prova" and me["subscription"]["plan_code"] == "PRO"
    tenants = client.get("/api/admin/tenants", headers=admin_headers).json()
    assert any(t["name"] == "Pasticceria Dolce" and t["vat_number"] == "01234560033" for t in tenants)
    # stessa email: si rimanda al recupero password; stessa partita IVA: all'assistenza
    assert client.post("/api/public/prova", json=body).json()["detail"]["code"] == "email_registrata"
    assert client.post("/api/public/prova", json={**body, "email": "altra@dolce.it"}).json()["detail"]["code"] == "azienda_registrata"
    # robot: risposta normale ma nessuna azienda creata
    n = len(client.get("/api/admin/tenants", headers=admin_headers).json())
    assert client.post("/api/public/prova", json={**body, "email": "bot@esempio.it", "vat_number": None, "website": "http://spam"}).status_code == 201
    assert client.post("/api/public/prova", json={**body, "email": "bot2@esempio.it", "vat_number": None, "elapsed_ms": 500}).status_code == 201
    assert len(client.get("/api/admin/tenants", headers=admin_headers).json()) == n
    # privacy obbligatoria, partita IVA controllata
    assert client.post("/api/public/prova", json={**body, "email": "x@esempio.it", "vat_number": None, "privacy": False}).status_code == 422
    assert client.post("/api/public/prova", json={**body, "email": "x@esempio.it", "vat_number": "12345678901"}).status_code == 422


class _Resp:
    def __init__(self, content: bytes, status: int = 200):
        self.content, self.status_code = content, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _trial_body(email, **extra):
    return {"company_name": f"Prova {email.split('@')[0]}", "name": "Anna Prova", "email": email, "privacy": True,
            "terms": True, "terms_version": "1.0", "elapsed_ms": 25000, **extra}


def test_prova_termini_obbligatori_e_versione(client, admin_headers):
    r = client.post("/api/public/prova", json=_trial_body("t1@esempio.it", terms=False))
    assert r.status_code == 422 and "termini di utilizzo" in r.json()["detail"]
    r = client.post("/api/public/prova", json=_trial_body("t1@esempio.it", terms_version="0.9"))
    assert r.status_code == 422 and "ricarica la pagina" in r.json()["detail"]
    body = _trial_body("t1@esempio.it")
    del body["terms"]
    assert client.post("/api/public/prova", json=body).status_code == 422  # campo mancante
    assert not any(t["name"] == "Prova t1" for t in client.get("/api/admin/tenants", headers=admin_headers).json())


def test_prova_accettazione_registrata_e_pdf_allegato(client, admin_headers, monkeypatch):
    from app.auth import accounts
    monkeypatch.setattr(get_settings(), "terms_pdf_url", "https://sito.test/termini-v1.0.pdf")
    calls = []
    monkeypatch.setattr(accounts.httpx, "get", lambda url, **kw: calls.append((url, kw)) or _Resp(b"%PDF-1.4 termini"))
    OUTBOX.clear()
    r = client.post("/api/public/prova", json=_trial_body("t2@esempio.it"))
    assert r.status_code == 201 and r.json()["email_sent"], r.text
    assert calls[0][0] == "https://sito.test/termini-v1.0.pdf" and calls[0][1]["timeout"] <= 10
    creds = next(m for m in OUTBOX if m["to"] == ["t2@esempio.it"])
    assert creds["attachments"] == [("termini-di-utilizzo-v1.0.pdf", len(b"%PDF-1.4 termini"), "application/pdf")]
    assert "termini di utilizzo" in creds["html"] and "v=1.0" in creds["html"] and "in allegato" in creds["html"]
    assert re.search(r"fino al \d\d/\d\d/\d{4}", creds["html"])  # data di fine della prova
    notify = next(m for m in OUTBOX if m["to"] == ["titolare@blubeauty.test"])
    assert "versione 1.0" in notify["html"]
    tid = next(t["id"] for t in client.get("/api/admin/tenants", headers=admin_headers).json() if t["name"] == "Prova t2")
    terms = client.get(f"/api/admin/tenants/{tid}", headers=admin_headers).json()["terms"]
    assert terms["version"] == "1.0" and terms["accepted_at"] and terms["ip"] == "testclient"


def test_prova_pdf_non_scaricato_email_senza_allegato(client, monkeypatch):
    from app.auth import accounts
    monkeypatch.setattr(get_settings(), "terms_pdf_url", "https://sito.test/termini-v1.0.pdf")

    def fail(url, **kw):
        raise accounts.httpx.ConnectTimeout("timeout")
    monkeypatch.setattr(accounts.httpx, "get", fail)
    OUTBOX.clear()
    r = client.post("/api/public/prova", json=_trial_body("t3@esempio.it"))
    assert r.status_code == 201 and r.json()["email_sent"]
    creds = next(m for m in OUTBOX if m["to"] == ["t3@esempio.it"])
    assert creds["attachments"] == [] and "termini di utilizzo" in creds["html"] and "in allegato" not in creds["html"]
    # risposta che non è un PDF (es. pagina di errore HTML): stessa cosa
    monkeypatch.setattr(accounts.httpx, "get", lambda url, **kw: _Resp(b"<html>404</html>"))
    OUTBOX.clear()
    assert client.post("/api/public/prova", json=_trial_body("t4@esempio.it")).status_code == 201
    assert next(m for m in OUTBOX if m["to"] == ["t4@esempio.it"])["attachments"] == []


def test_credenziali_azienda_normale_senza_termini(client, admin_headers, monkeypatch):
    from app.auth import accounts
    monkeypatch.setattr(accounts.httpx, "get", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("nessun download")))
    OUTBOX.clear()
    make_tenant(client, admin_headers, "Normale Srl", admin_password="Prova12345")
    mail = OUTBOX[-1]
    assert mail["attachments"] == [] and "termini di utilizzo" not in mail["html"] and "{termini}" not in mail["html"]


def test_password_provvisoria_obbliga_al_cambio_ovunque(client, admin_headers):
    t = make_tenant(client, admin_headers, "Cambio Srl", admin_password="Prova12345")
    h = bearer(login(client, "cambiosrl@test.it", "Prova12345"))
    # con la password provvisoria si può solo vedere chi si è e cambiarla
    r = client.get("/api/app/users", headers=h)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "cambio_password"
    assert client.get("/api/app/status", headers=h).status_code == 200
    assert client.post("/api/auth/password", headers=h, json={"current": "Prova12345", "new": "MiaPassword9"}).status_code == 200
    assert client.get("/api/app/users", headers=h).status_code == 200
    # l'amministratore dell'azienda crea un utente e gli dà una password provvisoria
    uid = client.post("/api/app/users", headers=h, json={"full_name": "Gino Vendite", "email": "gino@cambio.it"}).json()["id"]
    me_id = client.get("/api/auth/me", headers=h).json()["user"]["id"]
    assert client.post(f"/api/app/users/{me_id}/password", headers=h, json={}).status_code == 400
    OUTBOX.clear()
    r = client.post(f"/api/app/users/{uid}/password", headers=h, json={"send_email": True}).json()
    assert len(r["password"]) == 12 and r["email_sent"] and r["password"] in OUTBOX[-1]["html"]
    gino = next(u for u in client.get("/api/app/users", headers=h).json()["users"] if u["id"] == uid)
    assert gino["must_change_password"] and not gino["pending_activation"]
    hg = bearer(login(client, "gino@cambio.it", r["password"]))
    assert client.get("/api/auth/me", headers=hg).json()["user"]["must_change_password"] is True
    assert client.get("/api/anagrafiche/articoli", headers=hg).status_code == 403
    # reimpostata dall'amministratore dopo il cambio: di nuovo obbligatorio
    assert client.post("/api/auth/password", headers=hg, json={"current": r["password"], "new": "GinoPass2026"}).status_code == 200
    assert client.get("/api/auth/me", headers=hg).json()["user"]["must_change_password"] is False
    r = client.post(f"/api/app/users/{uid}/password", headers=h, json={"password": "Altra12345", "send_email": False}).json()
    assert not r["email_sent"]
    hg = bearer(login(client, "gino@cambio.it", "Altra12345"))
    assert client.get("/api/auth/me", headers=hg).json()["user"]["must_change_password"] is True
    # rigenerata dal super admin: obbligatorio anche così
    assert client.post("/api/auth/password", headers=hg, json={"current": "Altra12345", "new": "GinoPass2027"}).status_code == 200
    r = client.post(f"/api/admin/tenants/{t['id']}/users/{uid}/password", headers=admin_headers, json={"send_email": False}).json()
    hg = bearer(login(client, "gino@cambio.it", r["password"]))
    assert client.get("/api/auth/me", headers=hg).json()["user"]["must_change_password"] is True
    assert client.get("/api/app/users", headers=h).status_code == 200


def test_limite_tentativi(client, admin_headers, monkeypatch):
    from app.auth import passwords
    monkeypatch.setattr(get_settings(), "rate_limits", True)
    monkeypatch.setattr(passwords, "_memory", {})
    import redis
    try:
        redis.Redis.from_url(get_settings().redis_url).delete("rl:forgot:testclient", "rl:forgot:limite@test.it")
    except Exception:  # noqa: BLE001
        pass
    codes = [client.post("/api/auth/password-dimenticata", json={"email": "limite@test.it"}).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
