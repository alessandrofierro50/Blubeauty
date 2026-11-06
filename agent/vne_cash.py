"""Cassa automatica VNE (Automatic Cash) - protocollo di comunicazione VNE 3.06: client, flusso di pagamento e simulatore.

Modulo COMUNE ai gestionali BluCode (BluOrderScan, BluTakeaway, BluGest Macellerie, BluGest): solo libreria standard
di Python, nessuna dipendenza dal gestionale. Il ponte del locale lo usa per parlare con la macchina nella rete locale:
    POST https://IP_MACCHINA/selfcashapi/   corpo JSON   (certificato della macchina autofirmato)

Comandi usati (gli altri sono nel manuale VNE; la gestione completa della macchina si fa dal suo WebTool, IP/tool/):
    1  richiesta di pagamento scontrino      -> id della transazione
    2  polling esito pagamento (ogni 250 ms) -> payment_status 1 completato / 2 in corso, payment_details
    3  annullamento scontrino pendente      -> tipo_annullamento 1 accetta parziale / 2 restituisci
    5  lista scontrini pendenti              (per ritrovare un pagamento la cui risposta è andata persa)
    20 stato della macchina                  (contenuto di banconote e monete, allarmi)
    40/41 login/logout operatore
    10/11/12 prelievo, polling prelievo, fine prelievo

Regola di sicurezza: un pagamento non si ripete mai alla cieca. Se la risposta al tipo 1 non arriva (5 s), prima di
rimandarlo si guarda la lista dei pendenti (tipo 5): l'id è lo UNIX timestamp in secondi + 3 cifre, quindi un pendente
nato dopo la nostra richiesta è il nostro.
"""
import http.client
import json
import socket
import ssl
import threading
import time

PATH = "/selfcashapi/"
TIMEOUT = 5          # il manuale: senza risposta entro 5 secondi la richiesta va rimandata
POLL_EVERY = 0.25    # consigliato da VNE
MAX_WAIT = 600       # dopo 10 minuti senza pagamento si annulla restituendo il denaro

ERRORS = {  # Appendice I del protocollo
    100: "richiesta non valida (struttura del pacchetto)",
    101: "comando sconosciuto alla cassa",
    102: "errore generico della cassa: contattare VNE",
    103: "errore durante la richiesta di pagamento o prelievo: riprovare",
    104: "transazione sconosciuta alla cassa",
    105: "c'è già uno scontrino in attesa di pagamento sulla cassa: completalo o annullalo",
    106: "taglio richiesto non disponibile nella cassa",
    107: "logout impossibile: pagamento in corso",
    108: "utente della cassa inesistente",
    110: "la cassa sta già eseguendo un'altra operazione",
    113: "annullamento impossibile: pagamento con POS in corso",
    114: "annullamento rifiutato: operatore diverso da quello che ha chiesto il pagamento",
    120: "autenticazione rifiutata (authKey)",
}
OPERATIONS = {1: "pagamento", 2: "rimborso", 3: "prelievo", 4: "ricarica (refill)", 5: "svuotamento"}
FINAL = ("completed", "returned", "partial", "deleted")


class VneError(Exception):
    """La cassa ha risposto NACK (req_status 2): la richiesta NON è stata eseguita."""

    def __init__(self, code, resp=None):
        self.code, self.resp = code, resp or {}
        text = ERRORS.get(int(code) if str(code).isdigit() else -1, f"errore {code}")
        extra = ""
        if str(code) == "110" and self.resp.get("operation"):
            extra = f" ({OPERATIONS.get(self.resp['operation'], self.resp['operation'])} di {self.resp.get('user') or '?'})"
        super().__init__(f"Cassa automatica: {text}{extra} [codice {code}]")


class VneUnreachable(Exception):
    """Connessione non riuscita: la richiesta certamente NON è arrivata alla cassa."""


class VneNoAnswer(Exception):
    """Richiesta inviata ma nessuna risposta: la cassa potrebbe averla eseguita."""


def message(code) -> str:
    return str(VneError(code))


class VneClient:
    def __init__(self, host, port=None, scheme="https", path=PATH, verify=False, timeout=TIMEOUT, auth_key="", op_name=""):
        self.host, self.scheme = host, scheme
        self.port = int(port or (443 if scheme == "https" else 80))
        self.path, self.verify, self.timeout = path or PATH, verify, timeout
        self.auth_key, self.op_name = auth_key, op_name

    def _conn(self):
        if self.scheme == "https":
            ctx = ssl.create_default_context()
            if not self.verify:  # la macchina usa un certificato autofirmato nella rete del locale
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            return http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=ctx)
        return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)

    def call(self, payload: dict) -> dict:
        body = dict(payload)
        if self.op_name and "opName" not in body and body.get("tipo") in (1, 2, 3, 5, 10, 11, 12, 13, 20, 40, 41):
            body["opName"] = self.op_name
        if self.auth_key and body.get("tipo") == 1:
            body["authKey"] = self.auth_key
        data = json.dumps(body).encode()
        conn = self._conn()
        try:
            try:
                conn.connect()
            except (ConnectionRefusedError, socket.gaierror, OSError) as e:
                raise VneUnreachable(f"Cassa automatica non raggiungibile a {self.host}:{self.port} ({e})") from e
            try:
                conn.request("POST", self.path, body=data, headers={"Content-Type": "application/json", "Content-Length": str(len(data))})
                resp = conn.getresponse()
                text = resp.read().decode("utf-8", "replace")
            except (socket.timeout, TimeoutError, OSError, http.client.HTTPException) as e:
                raise VneNoAnswer(f"Nessuna risposta dalla cassa automatica ({e})") from e
        finally:
            conn.close()
        try:
            out = json.loads(text)
        except ValueError as e:
            raise VneNoAnswer(f"Risposta non valida dalla cassa automatica (HTTP {resp.status}): {text[:120]}") from e
        return out

    def ok(self, payload: dict) -> dict:
        """call() che trasforma il NACK in VneError."""
        out = self.call(payload)
        if out.get("req_status") == 2:
            raise VneError(out.get("mess"), out)
        return out

    # ---- comandi ----
    def pay(self, amount_cents: int, refundable=True) -> dict:
        return self.ok({"tipo": 1, "importo": int(amount_cents), "refundable": 1 if refundable else 0})

    def poll(self, tid: str) -> dict:
        return self.ok({"tipo": 2, "id": str(tid)})

    def cancel(self, tid: str, mode: int = 2) -> dict:
        """mode 1 = accetta il pagamento parziale, 2 = restituisci il denaro al cliente."""
        return self.ok({"tipo": 3, "id": str(tid), "tipo_annullamento": 1 if mode == 1 else 2})

    def pending(self) -> list:
        out = self.ok({"tipo": 5})
        lst = out.get("pending_list") or {}
        return [str(lst[k]) for k in sorted(lst, key=lambda k: int(k.split("_")[-1]) if k.split("_")[-1].isdigit() else 0)]

    def status(self) -> dict:
        return self.call({"tipo": 20})

    def login(self, op_name=None) -> dict:
        return self.ok({"tipo": 40, **({"opName": op_name} if op_name else {})})

    def logout(self, op_name=None) -> dict:
        return self.ok({"tipo": 41, **({"opName": op_name} if op_name else {})})

    def withdraw(self, amount_cents: int, taglio: str = None, comment: str = "") -> dict:
        return self.ok({"tipo": 10, "importo": int(amount_cents), **({"taglio": taglio} if taglio else {}),
                        **({"commento": comment[:80]} if comment else {})})

    def poll_withdraw(self, tid: str) -> dict:
        return self.ok({"tipo": 11, "id": str(tid)})

    def end_withdraw(self) -> dict:
        return self.ok({"tipo": 12})

    def withdraw_denoms(self, amount_cents: int, denoms: dict, comment: str = "") -> dict:
        """Tipo 13: prelievo per singoli tagli, es. {"banconota_1000": 2, "moneta_200": 4}."""
        return self.ok({"tipo": 13, "importo": int(amount_cents), "listDenom": {k: int(v) for k, v in denoms.items() if int(v) > 0},
                        **({"commento": comment[:80]} if comment else {})})

    # ---- carico (refill), svuotamento, porta, chiusura ----
    def refill_start(self, accept_all=False) -> dict:
        return self.ok({"tipo": 30, "acceptAll": 1 if accept_all else 0})

    def refill_end(self) -> dict:
        return self.ok({"tipo": 31})

    def refill_poll(self) -> dict:
        return self.ok({"tipo": 33})

    def empty(self, what: str, full: bool = True) -> dict:
        """what «monete» (hopper, tipo 50) o «banconote» (riciclatore, tipo 51); full=False = fino al fondo cassa."""
        return self.ok({"tipo": 50 if what == "monete" else 51, "full": 0 if full else 1})

    def empty_poll(self) -> dict:
        return self.ok({"tipo": 53})

    def reset_stacker(self, peripheral: int) -> dict:
        """Dopo aver svuotato a mano: 0 cassa monete, 1 stacker banconote, 2 entrambi."""
        return self.ok({"tipo": 52, "peripheral": int(peripheral)})

    def open_door(self, wait: str = "0", port: int = 1) -> dict:
        return self.ok({"tipo": 55, "wait_timeout": wait, "port": int(port)})

    def closing(self) -> dict:
        return self.ok({"tipo": 60})


def _id_time(tid) -> int:
    s = str(tid)
    return int(s[:-3]) if len(s) > 3 and s.isdigit() else 0


def start_payment(client: VneClient, amount_cents: int, refundable=True) -> str:
    """Tipo 1 senza doppioni: se la risposta va persa si cerca il pagamento tra i pendenti prima di rimandarlo."""
    started = int(time.time()) - 1
    for attempt in range(2):
        try:
            return str(client.pay(amount_cents, refundable)["id"])
        except VneNoAnswer:
            for _ in range(3):
                try:
                    mine = [t for t in client.pending() if _id_time(t) >= started]
                    if mine:
                        return mine[-1]
                    break
                except (VneNoAnswer, VneUnreachable):
                    time.sleep(1)
            else:
                raise
            if attempt:
                raise
    raise VneNoAnswer("Nessuna risposta dalla cassa automatica alla richiesta di pagamento")


def run_payment(client: VneClient, amount_cents: int, on_progress=None, should_cancel=None, poll_every=POLL_EVERY,
                max_wait=MAX_WAIT, refundable=True, no_answer_limit=60) -> dict:
    """Pagamento completo: richiesta, polling fino all'esito finale, annullamento su richiesta del gestionale.

    on_progress(dict) riceve {id, status, amount, inserted, rest, not_returned, warning}; should_cancel() -> 0 | 1 | 2.
    Ritorna {id, status (completed|returned|partial|deleted), amount, inserted, rest, not_returned, cancelled_by, card}.
    Errori: VneError / VneUnreachable prima che la cassa accetti (pagamento NON avvenuto); VneNoAnswer dopo (esito
    da verificare sul display della cassa)."""
    tid = start_payment(client, amount_cents, refundable)
    t0, last_ok, last, sent_cancel = time.monotonic(), time.monotonic(), None, 0
    while True:
        try:
            out = client.poll(tid)
            last_ok = time.monotonic()
        except VneError as e:
            if str(e.code) == "104":   # annullato prima che la macchina lo prendesse in carico
                return {"id": tid, "status": "deleted", "amount": amount_cents, "inserted": 0, "rest": 0, "not_returned": 0,
                        "cancelled_by": None, "card": False}
            raise
        except (VneNoAnswer, VneUnreachable) as e:
            if time.monotonic() - last_ok > no_answer_limit:
                raise VneNoAnswer(f"La cassa automatica non risponde da {no_answer_limit} s durante il pagamento {tid}: "
                                  f"controlla il display prima di incassare di nuovo ({e})") from e
            time.sleep(1)
            continue
        det = out.get("payment_details") or {}
        state = det.get("status") or ("completed" if out.get("payment_status") == 1 else "pending")
        info = {"id": tid, "status": state, "amount": det.get("amount", amount_cents), "inserted": det.get("inserted", 0),
                "rest": det.get("rest", 0), "not_returned": det.get("not_returned", 0), "cancelled_by": det.get("cancelled_by"),
                "card": det.get("inserted") == -2}
        if state == "notCompleted":
            info["warning"] = (f"Resto non erogato: mancano {(info['inserted'] - info['amount'] - info['rest']) / 100:.2f} €. "
                               "Ricarica la cassa (refill) oppure annulla accettando il pagamento parziale")
        elif info["not_returned"]:
            info["warning"] = "Restituzione non completata: ricarica la cassa oppure annulla di nuovo"
        if out.get("payment_status") == 1 and state in FINAL + ("pending",):
            info["status"] = state if state != "pending" else "completed"
            return info
        if on_progress and info != last:
            on_progress(info)
            last = info
        want = should_cancel() if should_cancel else 0
        if not want and max_wait and time.monotonic() - t0 > max_wait and not sent_cancel:
            want = 2
        if want and want != sent_cancel:
            try:
                res = client.cancel(tid, want)
                sent_cancel = want
                if res.get("payment_status") == 1:   # annullato prima che la macchina lo mettesse a schermo
                    return {**info, "status": "deleted", "inserted": 0, "rest": 0}
            except VneError as e:
                if on_progress:
                    on_progress({**info, "warning": str(e)})
                sent_cancel = want
            except (VneNoAnswer, VneUnreachable):
                pass  # riprova al giro successivo
        time.sleep(poll_every)


def run_refill(client: VneClient, on_progress=None, should_stop=None, accept_all=False, poll_every=1.0, max_wait=1800) -> dict:
    """Carico: la cassa accetta banconote e monete finché l'operatore non chiude (should_stop() vero) -> {amount}."""
    client.refill_start(accept_all)
    t0, last = time.monotonic(), None
    while True:
        try:
            amount = int(client.refill_poll().get("amountRefill") or 0)
        except (VneNoAnswer, VneUnreachable):
            amount = last if last is not None else 0
        if on_progress and amount != last:
            on_progress({"status": "carico", "amount": amount})
        last = amount
        if (should_stop and should_stop()) or time.monotonic() - t0 > max_wait:
            break
        time.sleep(poll_every)
    client.refill_end()
    final = int(client.refill_poll().get("amountRefill") or last or 0)
    return {"status": "completed", "amount": final}


def run_withdraw(client: VneClient, amount_cents: int, taglio: str = None, denoms: dict = None, comment: str = "", on_progress=None,
                 should_stop=None, poll_every=1.0, max_wait=300) -> dict:
    """Prelievo: la cassa eroga, l'operatore ritira; poi «fine prelievo» -> {amount, withdrawed}."""
    tid = str((client.withdraw_denoms(amount_cents, denoms, comment) if denoms else client.withdraw(amount_cents, taglio, comment))["id"])
    t0, out = time.monotonic(), {}
    while time.monotonic() - t0 < max_wait:
        try:
            out = client.poll_withdraw(tid)
        except (VneNoAnswer, VneUnreachable):
            time.sleep(poll_every)
            continue
        if out.get("withdraw_status") == 1:
            break
        if on_progress:
            on_progress({"status": "prelievo", "id": tid, "amount": amount_cents})
        if should_stop and should_stop():
            break
        time.sleep(poll_every)
    det = out.get("payment_details") or {}
    try:
        client.end_withdraw()
    except VneError:
        pass
    done = out.get("withdraw_status") == 1
    return {"status": "completed" if done else "interrupted", "id": tid, "amount": det.get("amount", amount_cents),
            "withdrawed": det.get("withdrawed", 0) if done else 0}


def run_empty(client: VneClient, what: str, full: bool = True, on_progress=None, poll_every=3.0, max_wait=900) -> dict:
    """Svuotamento di monete o banconote (totale o fino al fondo cassa): si aspetta la fine (polling ogni 3 s)."""
    before = summarize_status(client.status())
    client.empty(what, full)
    t0 = time.monotonic()
    while time.monotonic() - t0 < max_wait:
        time.sleep(poll_every)
        try:
            if client.empty_poll().get("empty_status") == 0:
                break
        except (VneNoAnswer, VneUnreachable):
            continue
        if on_progress:
            on_progress({"status": "svuotamento", "what": what})
    after = summarize_status(client.status())
    key = "hopper_total_cents" if what == "monete" else "recycler_total_cents"
    return {"status": "completed", "what": what, "full": full, "before": before.get(key), "after": after.get(key),
            "removed": max(0, (before.get(key) or 0) - (after.get(key) or 0))}


def summarize_status(resp: dict) -> dict:
    """Tipo 20 -> riepilogo leggibile: totale, banconote e monete per taglio, allarmi e problemi."""
    notes, coins, problems = [], [], []
    alerts = {0: "ok", 1: "basso", 2: "vuoto", 3: "non riciclato"}
    total = 0
    for name in ("recycler", "dispenser"):
        r = resp.get(name)
        if not isinstance(r, dict):
            continue
        if r.get("error"):
            problems.append(f"{'Riciclatore' if name == 'recycler' else 'Dispenser'} banconote in errore: {r.get('mess')}")
        for k in sorted(r):
            v = r[k]
            if k.startswith("banconota_") and isinstance(v, dict):
                q = int(v.get("quantita") or 0)
                notes.append({"value": v.get("valore"), "qty": q, "alert": alerts.get(v.get("alert"), v.get("alert")),
                              "where": name})
                total += (v.get("valore") or 0) * q
        stacker = r.get("stacker") or 0
        if stacker:
            notes.append({"value": None, "qty": None, "stacker_cents": stacker, "where": f"{name}_stacker"})
    h = resp.get("hopper")
    if isinstance(h, dict):
        if h.get("error"):
            problems.append(f"Hopper monete in errore: {h.get('mess')}")
        for d in (1, 2, 5, 10, 20, 50, 100, 200):
            if f"moneta_{d}" in h:
                q = int(h.get(f"moneta_{d}") or 0)
                coins.append({"value": d, "qty": q, "alert": alerts.get(h.get(f"moneta_{d}_alert"), h.get(f"moneta_{d}_alert"))})
                total += d * q
    low = [f"{x['value'] / 100:.2f} € {x['alert']}" for x in notes + coins if x.get("value") and x.get("alert") in ("basso", "vuoto")]
    return {"ok": not problems, "total_cents": total, "notes": notes, "coins": coins, "problems": problems, "low": low,
            "recycler_total_cents": (resp.get("recycler") or {}).get("totalInRecycle"),
            "hopper_total_cents": (h or {}).get("totalInRecycle")}


# ======================================================================= simulatore
class VneSim:
    """Finta Automatic Cash per le prove (nessun denaro). Il «cliente» inserisce il denaro con insert(), oppure da solo
    dopo auto_pay secondi (paga con il primo taglio che copre l'importo). scenario: 'ok' | 'no_change' (resto non
    erogabile) | 'busy' (NACK 110)."""
    DENOMS = (50000, 20000, 10000, 5000, 2000, 1000, 500, 200, 100, 50, 20, 10, 5, 2, 1)

    def __init__(self, auto_pay=None, scenario="ok"):
        self.lock = threading.Lock()
        self.payments, self.order, self.seq, self.log = {}, [], 0, []
        self.auto_pay, self.scenario = auto_pay, scenario
        self.notes = {500: 20, 1000: 20, 2000: 10}
        self.coins = {d: 50 for d in (1, 2, 5, 10, 20, 50, 100, 200)}
        self.user = None

    def _new_id(self):
        self.seq = (self.seq + 1) % 1000
        return f"{int(time.time())}{self.seq:03d}"

    def insert(self, cents, tid=None):
        with self.lock:
            r = getattr(self, "refill", None)
            if r and r["on"]:                      # durante il carico il denaro entra nella cassa
                r["amount"] += cents
                if cents >= 500 and cents in self.notes:
                    self.notes[cents] += 1
                elif cents in self.coins:
                    self.coins[cents] += 1
                return True
            p = self.payments.get(tid) if tid else next((self.payments[t] for t in self.order if self.payments[t]["status"] == "pending"), None)
            if not p or p["status"] != "pending":
                return False
            p["inserted"] += cents
            self._settle(p)
            return True

    def _settle(self, p):
        if p["inserted"] >= p["amount"]:
            change = p["inserted"] - p["amount"]
            if self.scenario == "no_change" and change:
                p["status"] = "notCompleted"
            else:
                p.update(rest=change, status="completed")

    def _auto(self):
        if self.auto_pay is None:
            return
        for t in self.order:
            p = self.payments[t]
            if p["status"] == "pending" and time.time() - p["created"] >= self.auto_pay and not p["inserted"]:
                note = next((d for d in reversed(self.DENOMS) if d >= p["amount"]), p["amount"])
                p["inserted"] = note
                self._settle(p)

    def handle(self, req: dict) -> dict:
        with self.lock:
            self.log.append(req)
            self._auto()
            t = req.get("tipo")
            if t == 1:
                if self.scenario == "busy":
                    return {"tipo": 1, "req_status": 2, "mess": 110, "operation": 1, "user": "cassiere"}
                if any(self.payments[x]["status"] in ("pending", "notCompleted") for x in self.order):
                    return {"tipo": 1, "req_status": 2, "mess": 105}
                amount = req.get("importo")
                if not isinstance(amount, int) or amount <= 0:
                    return {"tipo": 1, "req_status": 2, "mess": 100}
                tid = self._new_id()
                self.payments[tid] = {"amount": amount, "inserted": 0, "rest": 0, "status": "pending", "created": time.time(),
                                      "op": req.get("opName"), "not_returned": 0}
                self.order.append(tid)
                return {"tipo": 1, "importo": amount, "req_status": 1, "id": tid}
            if t == 2:
                p = self.payments.get(str(req.get("id")))
                if not p:
                    return {"tipo": 2, "req_status": 2, "mess": 104}
                det = {"amount": p["amount"], "inserted": p["inserted"], "rest": p["rest"], "status": p["status"],
                       "not_returned": p["not_returned"], **({"cancelled_by": p["cancelled_by"]} if p.get("cancelled_by") else {})}
                done = p["status"] in FINAL
                return {"tipo": 2, "req_status": 1, "id": str(req.get("id")), "payment_status": 1 if done else 2, "payment_details": det}
            if t == 3:
                p = self.payments.get(str(req.get("id")))
                if not p:
                    return {"tipo": 3, "req_status": 2, "mess": 104}
                if p["status"] in FINAL:
                    return {"tipo": 3, "req_status": 1, "payment_status": 3}
                who = req.get("opName") or self.user or "auth_login"
                if req.get("tipo_annullamento") == 1:
                    p.update(status="partial", cancelled_by=who)
                elif p["status"] == "notCompleted":
                    return {"tipo": 3, "req_status": 1, "payment_status": 4}
                else:
                    p.update(status="returned" if p["inserted"] else "deleted", rest=p["inserted"], cancelled_by=who)
                return {"tipo": 3, "req_status": 1, "payment_status": 2}
            if t == 5:
                pend = [x for x in self.order if self.payments[x]["status"] in ("pending", "notCompleted")]
                return {"tipo": 5, "list_length": len(pend), **({"pending_list": {f"id_{i}": int(x) for i, x in enumerate(pend)}} if pend else {})}
            if t == 20:
                rec = {"error": 0, "mess": "OK", "stacker": 0, "detailNotesStacker": {"500": 0, "1000": 0, "2000": 0, "5000": 0}}
                for i, (v, q) in enumerate(sorted(self.notes.items()), 1):
                    rec[f"banconota_{i}"] = {"valore": v, "quantita": q, "alert": 0 if q > 5 else (1 if q else 2), "min_level": 5, "max_level": 60}
                rec["totalInRecycle"] = sum(v * q for v, q in self.notes.items())
                hop = {"error": 0, "mess": "OK", "stacker": 0}
                for d, q in self.coins.items():
                    hop.update({f"moneta_{d}": q, f"moneta_{d}_alert": 0 if q >= 20 else 1, f"moneta_{d}_accept": 1,
                                f"moneta_{d}_recycle": 1, f"moneta_{d}_min_level": 20, f"moneta_{d}_max_level": 500})
                hop["totalInRecycle"] = sum(d * q for d, q in self.coins.items())
                return {"tipo": 20, "req_status": 1, "recycler": rec, "hopper": hop}
            if t in (40, 41):
                self.user = req.get("opName") or "auth_login" if t == 40 else None
                return {"tipo": t, "req_status": 1}
            if t == 30:
                self.refill = {"on": True, "amount": 0}
                return {"tipo": 30, "req_status": 1}
            if t == 31:
                if getattr(self, "refill", None):
                    self.refill["on"] = False
                return {"tipo": 31, "req_status": 1}
            if t == 33:
                r = getattr(self, "refill", None) or {"on": False, "amount": 0}
                return {"tipo": 33, "req_status": 1, "refillOn": 1 if r["on"] else 0, "amountRefill": r["amount"]}
            if t in (50, 51):
                full = req.get("full", 0) == 0
                if t == 50:
                    for d in self.coins:
                        self.coins[d] = 0 if full else min(self.coins[d], 20)
                else:
                    for v in self.notes:
                        self.notes[v] = 0 if full else min(self.notes[v], 5)
                self.emptying = 1
                return {"tipo": t, "req_status": 1}
            if t == 53:
                st = getattr(self, "emptying", 0)
                self.emptying = 0
                return {"tipo": 53, "req_status": 1, "empty_status": st}
            if t in (52, 55):
                self.door = t == 55 or getattr(self, "door", False)
                return {"tipo": t, "req_status": 1}
            if t == 60:
                total = sum(v * q for v, q in self.notes.items()) + sum(d * q for d, q in self.coins.items())
                return {"tipo": 60, "req_status": 1, "date": int(time.time()), "total_content": total}
            if t == 13:
                denoms = req.get("listDenom") or {}
                if sum(int(k.split("_")[1]) * int(v) for k, v in denoms.items()) != req.get("importo"):
                    return {"tipo": 13, "req_status": 2, "mess": 106}
                tid = self._new_id()
                self.payments[tid] = {"withdraw": req.get("importo"), "status": "w"}
                return {"tipo": 13, "importo": req.get("importo"), "req_status": 1, "id": tid}
            if t == 10:
                tid = self._new_id()
                self.payments[tid] = {"withdraw": req.get("importo"), "status": "w"}
                return {"tipo": 10, "importo": req.get("importo"), "req_status": 1, "id": tid}
            if t == 11:
                p = self.payments.get(str(req.get("id")))
                if not p or "withdraw" not in p:
                    return {"tipo": 11, "req_status": 2, "mess": 104}
                return {"tipo": 11, "req_status": 1, "id": str(req.get("id")), "withdraw_status": 1,
                        "payment_details": {"amount": p["withdraw"], "withdrawed": p["withdraw"]}}
            if t == 12:
                return {"tipo": 12, "req_status": 1}
            return {"tipo": t, "req_status": 2, "mess": 101}


def serve(sim: VneSim, host="127.0.0.1", port=8443, certfile=None, keyfile=None):
    """Avvia il simulatore in un thread (HTTP, o HTTPS con certfile). Ritorna il server (shutdown() per fermarlo)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
                out = sim.handle(req) if self.path.rstrip("/") == PATH.rstrip("/") else {"req_status": 2, "mess": 100}
            except ValueError:
                out = {"req_status": 2, "mess": 100}
            data = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer((host, port), Handler)
    if certfile:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile, keyfile)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
