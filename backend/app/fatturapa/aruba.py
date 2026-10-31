"""Client REST per la Fatturazione Elettronica Aruba (API v2).

Il token dura 30 minuti e Aruba accetta una sola autenticazione al minuto per IP: il token si conserva in Redis
(condiviso tra api e worker) e si rinnova con il refresh token prima di rifare il signin."""

import base64
import json
import logging
import threading
import time
from datetime import date, datetime

import httpx

from app.core.config import get_settings

log = logging.getLogger(__name__)

ENVIRONMENTS = {
    "demo": ("https://demoauth.fatturazioneelettronica.aruba.it", "https://demows.fatturazioneelettronica.aruba.it"),
    "produzione": ("https://auth.fatturazioneelettronica.aruba.it", "https://ws.fatturazioneelettronica.aruba.it"),
}
SYNC_ERRORS = {
    "0001": "Errore imprevisto di Aruba", "0002": "File fattura non valido o assente", "0012": "Autenticazione ad Aruba fallita",
    "0013": "Errore di salvataggio presso Aruba", "0033": "File troppo grande (massimo 5 MB)",
    "0034": "Questo file è già stato inviato di recente", "0092": "Il file non rispetta lo schema FatturaPA",
    "0093": "Deleghe Aruba non valide per questa partita IVA", "0094": "Dati del trasmittente diversi da quelli di Aruba",
    "0095": "Servizio Aruba momentaneamente non disponibile, riprova più tardi", "0096": "Errore nei controlli SDI",
    "0097": "Spazio di conservazione Aruba esaurito", "0098": "Codifica del file non valida",
}


class ArubaError(Exception):
    def __init__(self, message: str, code: str | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


class _MemoryStore:
    def __init__(self):
        self.data: dict = {}
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            return self.data.get(key)

    def set(self, key, value, ttl):
        with self.lock:
            self.data[key] = value

    def delete(self, key):
        with self.lock:
            self.data.pop(key, None)


class _RedisStore:
    def __init__(self, url: str):
        import redis
        self.r = redis.Redis.from_url(url, socket_timeout=2)
        self.r.ping()

    def get(self, key):
        v = self.r.get(key)
        return json.loads(v) if v else None

    def set(self, key, value, ttl):
        self.r.set(key, json.dumps(value), ex=int(ttl))

    def delete(self, key):
        self.r.delete(key)


_store = None


def token_store():
    global _store
    if _store is None:
        try:
            _store = _RedisStore(get_settings().redis_url)
        except Exception:  # noqa: BLE001 - senza Redis (sviluppo, test) basta la memoria del processo
            _store = _MemoryStore()
    return _store


class ArubaClient:
    def __init__(self, username: str, password: str, env: str = "demo", transport: httpx.BaseTransport | None = None):
        if env not in ENVIRONMENTS:
            raise ArubaError(f"Ambiente Aruba sconosciuto: {env}")
        if not username or not password:
            raise ArubaError("Credenziali Aruba non configurate")
        self.username, self.password, self.env = username, password, env
        self.auth_url, self.ws_url = ENVIRONMENTS[env]
        self.http = httpx.Client(timeout=60, transport=transport)
        self.key = f"aruba:{env}:{username}"

    # ------------------------------------------------------------------ autenticazione
    def _auth(self, data: dict) -> dict:
        r = self.http.post(f"{self.auth_url}/auth/signin", data=data,
                           headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        if r.status_code == 429:
            raise ArubaError("Aruba limita gli accessi a uno al minuto: riprova tra poco", status=429)
        if r.status_code >= 400:
            try:
                desc = r.json().get("error_description") or r.text
            except ValueError:
                desc = r.text
            if data.get("grant_type") == "password":
                raise ArubaError(f"Accesso ad Aruba non riuscito: {desc}", code="auth", status=r.status_code)
            raise ArubaError("refresh", code="refresh", status=r.status_code)
        tok = r.json()
        now = time.time()
        return {"access": tok["access_token"], "refresh": tok.get("refresh_token"), "expires": now + int(tok.get("expires_in", 1800)),
                "refresh_until": now + 3600}

    def token(self, force: bool = False) -> str:
        store = token_store()
        t = None if force else store.get(self.key)
        now = time.time()
        if t and t["expires"] - 60 > now:
            return t["access"]
        if t and t.get("refresh") and t["refresh_until"] - 60 > now:
            try:
                t = self._auth({"grant_type": "refresh_token", "refresh_token": t["refresh"]})
                store.set(self.key, t, 3600)
                return t["access"]
            except ArubaError as exc:
                if exc.code != "refresh":
                    raise
        t = self._auth({"grant_type": "password", "username": self.username, "password": self.password})
        store.set(self.key, t, 3600)
        return t["access"]

    def _call(self, method: str, url: str, **kw) -> httpx.Response:
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self.token(force=attempt == 2)}", "Accept": "application/json"}
            r = self.http.request(method, url, headers=headers, **kw)
            if r.status_code == 401 and attempt == 1:
                token_store().delete(self.key)
                continue
            break
        if r.status_code == 429:
            raise ArubaError("Troppe richieste ad Aruba: riprova tra qualche minuto", status=429)
        if r.status_code == 404:
            raise ArubaError("Non trovato su Aruba", status=404)
        if r.status_code >= 400:
            raise ArubaError(f"Errore Aruba ({r.status_code}): {r.text[:300]}", status=r.status_code)
        return r

    def _json(self, method: str, path: str, **kw):
        return self._call(method, f"{self.ws_url}{path}", **kw).json()

    # ------------------------------------------------------------------ utenza
    def user_info(self) -> dict:
        return self._call("GET", f"{self.auth_url}/auth/userInfo").json()

    # ------------------------------------------------------------------ invio
    def upload(self, xml: bytes, dry_run: bool = False, domain: str | None = None, credential: str | None = None) -> dict:
        body = {"dataFile": base64.b64encode(xml).decode(), "dryRun": dry_run, "skipExtraSchema": False}
        if domain and credential:
            body.update({"domain": domain, "credential": credential})
        r = self._json("POST", "/services/invoice/upload", json=body)
        code = (r.get("errorCode") or "").strip()
        if code not in ("", "0000"):
            msg = SYNC_ERRORS.get(code, "Fattura rifiutata da Aruba")
            raise ArubaError(f"{msg}: {r.get('errorDescription') or ''}".strip(": "), code=code)
        return r

    def sent_detail(self, filename: str) -> dict:
        return self._json("GET", "/api/v2/invoices-out/detail", params={"filename": filename, "includeFile": "false"})

    def sent_notifications(self, filename: str) -> list[dict]:
        return self._json("GET", "/api/v2/invoices-out/notifications", params={"filename": filename}).get("notifications") or []

    # ------------------------------------------------------------------ fatture ricevute
    def received(self, start: datetime, end: datetime, page: int = 1, receiver_vat: str | None = None) -> dict:
        params = {"creationStartDate": start.isoformat(timespec="seconds"), "creationEndDate": end.isoformat(timespec="seconds"),
                  "page": page, "size": 100}
        if receiver_vat:
            params.update({"receiverCountry": "IT", "receiverVatcode": receiver_vat})
        return self._json("GET", "/api/v2/invoices-in", params=params)

    def received_detail(self, filename: str) -> dict:
        return self._json("GET", "/api/v2/invoices-in/detail", params={"filename": filename, "includeFile": "true"})

    # ------------------------------------------------------------------ simulatore SDI (solo ambiente demo)
    def simulate_received(self, vat: str) -> dict:
        if self.env != "demo":
            raise ArubaError("Il simulatore SDI esiste solo nell'ambiente demo")
        return self._json("POST", "/services/sdisimulator/invoiceIn", json={"countryReceiver": "IT", "vatcodeReceiver": vat})

    def simulate_notification(self, filename: str, notification_type: str) -> dict:
        if self.env != "demo":
            raise ArubaError("Il simulatore SDI esiste solo nell'ambiente demo")
        return self._json("POST", "/services/sdisimulator/notificationOut",
                          json={"invoiceFileName": filename, "notificationType": notification_type})


def parse_date(v) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None
