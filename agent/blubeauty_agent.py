#!/usr/bin/env python3
"""BluBeauty Agent: collega il gestionale in cloud alle periferiche del negozio.

Gira sul computer del negozio (Windows, Linux o macOS, Python 3.9+, solo libreria standard; per la bilancia seriale
serve anche `pyserial`). Fa due cose:

1. riceve dal gestionale i lavori da eseguire (scontrini sul registratore telematico, chiusure, ricevute ed etichette,
   letture della bilancia) con una connessione in uscita verso il server: niente porte da aprire sul router;
2. espone un piccolo servizio su http://127.0.0.1:8765 che la cassa usa quando internet non c'è, così il documento
   commerciale si stampa lo stesso (il gestionale lo registra appena torna la rete).

Uso:
    python blubeauty_agent.py abbina https://gestionale.esempio.it CODICE    (una volta: il codice si genera nel gestionale)
    python blubeauty_agent.py avvia                                           (resta in esecuzione)
    python blubeauty_agent.py prova                                           (elenca i dispositivi e ne controlla lo stato)

Formato dei lavori (uguale per server e cassa offline), con importi IVA inclusa come testo "12.34":
    rt.receipt  {lines:[{description, quantity, unit_price, amount, full_amount, vat_rate, department}],
                 adjustments:[{description, amount, vat_rate, department}], payments:[{method, amount}], lottery}
    rt.refund   {lines, payments, reference:{z, number, date, serial} | null, void: bool}
    rt.z / rt.x / status   {}
    print.text  {lines:[{type: text|line|feed|barcode|qr|cut, text, align, bold, size, data}], open_drawer}
    rt.nonfiscal  stesso formato di print.text, stampato come documento NON fiscale sul registratore telematico
    print.zpl   {zpl, copies}
    scale.read  {}  →  {weight, unit, stable}
"""

from __future__ import annotations

import json
import os
import platform
import random
import re
import socket
import ssl
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.sax.saxutils import quoteattr

VERSION = "1.0.0"
LOCAL_PORT = 8765
CENT = Decimal("0.01")


def config_path() -> Path:
    env = os.environ.get("BLUBEAUTY_AGENT_CONFIG")
    if env:
        return Path(env)
    base = Path(os.environ.get("PROGRAMDATA", "")) / "BluBeautyAgent" if platform.system() == "Windows" and os.environ.get("PROGRAMDATA") \
        else Path.home() / ".blubeauty-agent"
    return base / "config.json"


def load_config() -> dict:
    p = config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8")
    tmp.replace(p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        lp = config_path().parent / "agent.log"
        lp.parent.mkdir(parents=True, exist_ok=True)
        if lp.exists() and lp.stat().st_size > 5_000_000:
            lp.replace(lp.with_suffix(".log.1"))
        with lp.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


class DeviceError(Exception):
    """Errore del dispositivo, con messaggio da mostrare in cassa."""


def D(v) -> Decimal:
    return Decimal(str(v if v not in (None, "") else 0))


def money(v) -> Decimal:
    return D(v).quantize(CENT, ROUND_HALF_UP)


# =====================================================================================================================
# Registratori telematici


def rt_clean(text: str, n: int = 999) -> str:
    """Testo stampabile dal registratore: niente accenti né simboli fuori dal set di base (€ → EUR), come BluOrderScan."""
    import unicodedata
    t = (text or "").replace("€", "EUR")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"[^\x20-\x7E]", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:n].strip()


def text_rows(p: dict, width: int, rt: bool = False) -> list[str]:
    """Formato neutro di print.text → righe di testo semplice per i documenti non fiscali del registratore.

    Con `rt=True` (come BluOrderScan e il gestionale macellerie): solo caratteri di base, niente righe d'intestazione
    (`rt_skip`, il registratore stampa già la sua), testi alternativi `rt_text`, righe vuote tolte, testi lunghi a capo.
    """
    import textwrap
    rows = []
    for ln in p.get("lines", []):
        t = ln.get("type", "text")
        if t == "cut" or (rt and ln.get("rt_skip")):
            continue
        if t == "feed":
            if not rt:
                rows += [""] * int(ln.get("lines", 1))
        elif t == "line":
            rows.append("-" * width)
        elif t in ("barcode", "qr"):
            label = str(ln.get("label") or ln.get("data", ""))
            if not (rt and t == "qr"):  # un QR non si stampa in testo: sul registratore si salta
                rows.append(rt_clean(label, width) if rt else label[:width])
        else:
            text = str((ln.get("rt_text") if rt else None) or ln.get("text", ""))
            right = str(ln["right"]) if ln.get("right") else ""
            if rt:
                text, right = rt_clean(text), rt_clean(right, 12)
            if right:
                room = width - len(right) - 1
                rows.append(text[:room].ljust(width - len(right)) + right)
                continue
            parts = textwrap.wrap(text, width, break_long_words=True) if rt else [text[:width]]
            align = "left" if len(parts) > 1 else ln.get("align", "left")  # un testo andato a capo resta a sinistra
            for part in parts or [""]:
                rows.append(part.center(width).rstrip() if align == "center" else part.rjust(width) if align == "right" else part)
    return [r for r in rows if r.strip()] if rt else rows


def department_for(line: dict, options: dict) -> int:
    if line.get("department"):
        return int(line["department"])
    deps = options.get("departments") or {}
    rate = D(line.get("vat_rate"))
    for k, v in deps.items():
        if D(k) == rate:
            return int(v)
    return int(deps.get("default", 1))


class EpsonRT:
    """Epson FP-81 II RT / FP-90III: protocollo XML (ePOS-Print fiscale) via HTTP su /cgi-bin/fpmate.cgi."""

    PAYMENTS = {"contanti": (0, 0), "carta": (2, 1), "bancomat": (2, 1), "satispay": (2, 1), "buono_pasto": (3, 1),
                "buono": (6, 1), "altro": (2, 1)}
    DESC = 38

    def __init__(self, address: str, options: dict, http=None):
        self.address = address if address.startswith("http") else f"http://{address}"
        self.options = options or {}
        self.http = http or http_post

    @staticmethod
    def amount(v) -> str:
        return f"{money(v):.2f}".replace(".", ",")

    @staticmethod
    def qty(v) -> str:
        q = D(v).normalize()
        s = f"{q:f}"
        return s.replace(".", ",")

    def desc(self, s) -> str:
        return (s or "").replace("\n", " ")[: self.DESC]

    def _pay(self, method: str):
        custom = (self.options.get("payments") or {}).get(method)
        if custom:
            a, b = str(custom).split("-") if isinstance(custom, str) else custom
            return int(a), int(b)
        return self.PAYMENTS.get(method, (2, 1))

    def receipt_xml(self, p: dict) -> str:
        out = ["<printerFiscalReceipt>", '<beginFiscalReceipt operator="1" />']
        for ln in p.get("lines", []):
            dep = department_for(ln, self.options)
            full = money(ln.get("full_amount") or ln["amount"])
            qty = D(ln["quantity"])
            unit = money(ln.get("unit_price")) if qty != 1 else full
            out.append(f'<printRecItem operator="1" description={quoteattr(self.desc(ln["description"]))} quantity="{self.qty(qty)}" '
                       f'unitPrice="{self.amount(unit)}" department="{dep}" justification="1" />')
            disc = full - money(ln["amount"])
            if disc > 0:
                out.append(f'<printRecItemAdjustment operator="1" adjustmentType="3" description="SCONTO" amount="{self.amount(disc)}" '
                           f'department="{dep}" justification="1" />')
        for a in p.get("adjustments", []):
            if money(a["amount"]) > 0:
                out.append(f'<printRecItemAdjustment operator="1" adjustmentType="3" description={quoteattr(self.desc(a["description"]))} '
                           f'amount="{self.amount(a["amount"])}" department="{department_for(a, self.options)}" justification="1" />')
        if p.get("lottery"):
            out.append(f'<printRecLotteryID operator="1" code={quoteattr(p["lottery"])} />')
        out += self._totals(p)
        out.append('<endFiscalReceipt operator="1" />')
        out.append("</printerFiscalReceipt>")
        return envelope("".join(out))

    def _totals(self, p) -> list[str]:
        out = []
        for pay in p.get("payments", []) or [{"method": "contanti", "amount": "0"}]:
            t, i = self._pay(pay["method"])
            label = {"contanti": "CONTANTI", "carta": "CARTA", "bancomat": "BANCOMAT", "buono_pasto": "BUONI PASTO", "buono": "BUONO",
                     "satispay": "SATISPAY"}.get(pay["method"], "PAGAMENTO")
            out.append(f'<printRecTotal operator="1" description="{label}" payment="{self.amount(abs(D(pay["amount"])))}" '
                       f'paymentType="{t}" index="{i}" justification="1" />')
        return out

    def refund_xml(self, p: dict) -> str:
        ref = p.get("reference") or {}
        when = datetime.strptime(ref["date"][:10], "%Y-%m-%d") if ref.get("date") else datetime.now()
        z, n = int(ref.get("z") or 0), int(ref.get("number") or 0)
        serial = ref.get("serial") or "ND"
        kind = "VOID" if p.get("void") else "REFUND"
        out = ["<printerFiscalReceipt>",
               f'<printRecMessage operator="1" messageType="4" message="{kind} {z:04d} {n:04d} {when:%d%m%Y} {serial}" />',
               '<beginFiscalReceipt operator="1" />']
        tag = "printRecVoid" if p.get("void") else "printRecRefund"
        for ln in p.get("lines", []):
            amount = money(ln["amount"])
            if amount <= 0:
                continue
            qty = D(ln["quantity"])
            out.append(f'<{tag} operator="1" description={quoteattr(self.desc(ln["description"]))} quantity="{self.qty(qty)}" '
                       f'unitPrice="{self.amount(amount / qty if qty else amount)}" amount="{self.amount(amount)}" '
                       f'department="{department_for(ln, self.options)}" justification="1" />')
        out += self._totals(p)
        out.append('<endFiscalReceipt operator="1" />')
        out.append("</printerFiscalReceipt>")
        return envelope("".join(out))

    def send(self, body: str, timeout: int = 30) -> ET.Element:
        url = f"{self.address.rstrip('/')}/cgi-bin/fpmate.cgi?devid=local_printer&timeout={timeout * 1000}"
        raw = self.http(url, body.encode("utf-8"), {"Content-Type": "text/xml; charset=utf-8"}, timeout + 5)
        resp = find(parse_xml(raw), "response")
        if resp is None:
            raise DeviceError("Risposta del registratore non valida")
        if resp.get("success", "").lower() != "true":
            code = resp.get("code") or resp.get("status") or "?"
            raise DeviceError(f"Il registratore ha rifiutato il documento ({code}{': ' + EPSON_ERRORS.get(code, '') if code in EPSON_ERRORS else ''})")
        return resp

    def _info(self, resp: ET.Element) -> dict:
        info = {child_tag(e): (e.text or "").strip() for e in resp.iter() if child_tag(e) not in ("response", "addInfo")}
        number = info.get("fiscalReceiptNumber")
        z = info.get("zRepNumber")
        d = info.get("fiscalReceiptDate")  # gg/mm/aaaa
        try:
            iso = datetime.strptime(d, "%d/%m/%Y").date().isoformat() if d else date.today().isoformat()
        except ValueError:
            iso = date.today().isoformat()
        return {"number": str(int(number)).zfill(4) if number and number.isdigit() else number, "z": str(int(z)).zfill(4) if z and z.isdigit() else z,
                "date": iso, "time": info.get("fiscalReceiptTime"), "serial": info.get("serialNumber") or self.options.get("serial"),
                "amount": info.get("fiscalReceiptAmount")}

    def run(self, kind: str, p: dict) -> dict:
        if kind == "rt.receipt":
            return self._info(self.send(self.receipt_xml(p)))
        if kind == "rt.refund":
            return self._info(self.send(self.refund_xml(p)))
        if kind == "rt.nonfiscal":
            # Epson (printerNonFiscal di fpmate): non ancora collaudato su un apparecchio vero, a differenza del Custom
            rows = text_rows(p, int(self.options.get("width") or 42), rt=True)
            body = "".join(f'<printNormal operator="1" font="1" data={quoteattr(r)} />' for r in rows)
            self.send(envelope(f'<printerNonFiscal><beginNonFiscal operator="1" />{body}<endNonFiscal operator="1" /></printerNonFiscal>'))
            return {"printed": True, "rows": len(rows)}
        if kind in ("rt.z", "rt.x"):
            tag = "printZReport" if kind == "rt.z" else "printXReport"
            resp = self.send(envelope(f'<printerFiscalReport><{tag} operator="1" /></printerFiscalReport>'), timeout=120)
            info = self._info(resp)
            return {"z": info.get("z"), "date": info.get("date")}
        if kind == "status":
            resp = self.send(envelope('<printerCommand><queryPrinterStatus operator="1" /></printerCommand>'))
            return {"ok": True, "status": resp.get("status")}
        raise DeviceError(f"Operazione non prevista per il registratore: {kind}")


EPSON_ERRORS = {"EPTR_REC_EMPTY": "carta finita", "EPTR_COVER_OPEN": "coperchio aperto", "FP_NO_ANSWER": "il registratore non risponde",
                "PRINTER ERROR": "errore della stampante", "LAN_TIME_OUT": "tempo scaduto"}


class RtNotSent(DeviceError):
    """Il registratore non ha eseguito nulla (rifiuto, non raggiungibile, password): si può riprovare senza doppioni."""


class RtNoAnswer(DeviceError):
    """La richiesta è partita ma la risposta non è arrivata: esito da verificare sul registratore, mai ristampare alla cieca."""


def rt_describe(code) -> str:
    try:
        import rt_errors  # tabella dei codici del manuale Custom (file accanto all'agent)
        return rt_errors.describe(code)
    except Exception:  # noqa: BLE001
        return f"errore {code}"


def rt_parse(text: str) -> dict:
    """Risposta XML del registratore Custom: esito, codice d'errore, numeri del documento, lastIdCmd, stato della carta."""
    out: dict = {"ok": False, "status": None}
    try:
        root = ET.fromstring((text or "").strip().encode("utf-8"))
    except ET.ParseError as e:
        out["message"] = f"Risposta non leggibile: {e}"
        return out
    attrs = {k.lower(): v for k, v in root.attrib.items()}
    out["ok"] = str(attrs.get("success", "")).strip().lower() == "true"
    try:
        out["status"] = int(str(attrs.get("status", "0")).strip() or 0)
    except ValueError:
        pass
    names = {"fiscaldoc": "fiscal_number", "nclose": "z_number", "datetime": "date_time", "fpstatus": "fp_status",
             "responsebuf": "response_buf", "cpurel": "model", "mfstatus": "mf_status", "printerstatus": "printer_status"}
    for el in root.iter():
        t, v = child_tag(el).lower(), (el.text or "").strip()
        if t == "lastidcmd":
            out["last_idcmd"] = (el.attrib.get("IdCmd") or el.attrib.get("idcmd") or v or "").strip() or None
        elif t in names and v:
            out[names[t]] = v
    ps = out.get("printer_status") or ""
    if re.fullmatch(r"[01]{5}", ps):
        out["problems"] = [m for i, m in ((0, "coperchio aperto"), (1, "carta finita"), (2, "carta in esaurimento"),
                                          (3, "giornale elettronico pieno")) if ps[i] == "1"]
    if not out["ok"] and not out.get("message"):
        out["message"] = f"Registratore: {rt_describe(out['status'])}" if out["status"] else "Il registratore ha rifiutato il comando"
    return out


def _digest(user: str, password: str, challenge: str, method: str, uri: str) -> str:
    import hashlib
    f = dict(re.findall(r'(\w+)="?([^",]*)"?', challenge))
    algo = f.get("algorithm", "MD5").upper()
    h = (lambda x: hashlib.sha256(x.encode()).hexdigest()) if algo.startswith("SHA-256") else (lambda x: hashlib.md5(x.encode()).hexdigest())
    ha1, ha2 = h(f"{user}:{f.get('realm', '')}:{password}"), h(f"{method}:{uri}")
    cnonce, nc = os.urandom(8).hex(), "00000001"
    if "auth" in f.get("qop", "").split(","):
        resp, extra = h(f"{ha1}:{f.get('nonce', '')}:{nc}:{cnonce}:auth:{ha2}"), f', qop=auth, nc={nc}, cnonce="{cnonce}"'
    else:
        resp, extra = h(f"{ha1}:{f.get('nonce', '')}:{ha2}"), ""
    opaque = f', opaque="{f["opaque"]}"' if "opaque" in f else ""
    return (f'Digest username="{user}", realm="{f.get("realm", "")}", nonce="{f.get("nonce", "")}", uri="{uri}", '
            f'algorithm={f.get("algorithm", "MD5")}, response="{resp}"{opaque}{extra}')


def custom_http(host: str, port: int, body: str, auth: tuple | None, timeout: int) -> str:
    """POST /xml/printer.htm come il ponte di BluOrderScan (collaudato sul KUBE II-F): text/plain, autenticazione Basic o
    Digest, connessione ritentata 3 volte (subito dopo una stampa il registratore rifiuta connessioni per qualche secondo)."""
    import base64
    import http.client
    header = "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode() if auth else None
    for attempt in range(2):
        for n in range(CustomRT.CONNECT_TRIES):
            conn = http.client.HTTPConnection(host, port, timeout=8)
            try:
                conn.connect()
                break
            except OSError as e:
                conn.close()
                if n == CustomRT.CONNECT_TRIES - 1:
                    raise RtNotSent(f"Registratore {host}:{port} non raggiungibile ({e.__class__.__name__}: {e})") from None
                time.sleep(CustomRT.CONNECT_PAUSE)
        try:
            conn.sock.settimeout(timeout)
            data = body.encode("utf-8")
            headers = {"Content-Type": "text/plain; charset=utf-8", "Content-Length": str(len(data))}
            if header:
                headers["Authorization"] = header
            conn.request("POST", CustomRT.PATH, body=data, headers=headers)
            r = conn.getresponse()
            text = r.read().decode("utf-8", "replace")
            if r.status == 401:  # rifiutata senza eseguirla: si può riprovare senza doppioni
                challenge = r.getheader("WWW-Authenticate") or ""
                if auth and attempt == 0 and challenge.lower().startswith("digest"):
                    header = _digest(auth[0], auth[1], challenge, "POST", CustomRT.PATH)
                    continue
                raise RtNotSent("Il registratore chiede utente e password (HTTP 401): " +
                                ("utente o password non corretti" if auth else "scrivili nelle impostazioni del dispositivo"))
            if r.status != 200:
                raise RtNoAnswer(f"Risposta HTTP {r.status} dal registratore")
            return text
        except (OSError, http.client.HTTPException) as e:
            raise RtNoAnswer(f"Risposta non ricevuta ({e.__class__.__name__}: {e})") from None
        finally:
            conn.close()
    raise RtNotSent("Il registratore chiede utente e password (HTTP 401): utente o password non corretti")


class CustomRT:
    """Custom (KUBE II-F, Q3X…): protocollo XML via HTTP su /xml/printer.htm, importi in centesimi.

    Tutto come il ponte di BluOrderScan e il gestionale macellerie, dove il primo scontrino reale è uscito dopo diverse
    prove sul KUBE II-F (repository Ordini-scan: backend/rt_custom.py e backend/ponte/sof_bridge.py):
    - scontrino = UN solo XML; printRecItem con unitPrice = importo della RIGA (quantità × prezzo, già scontato), IdVat =
      indice IVA del registratore; la quantità va in un printRecMessage «2 x 15,00 EUR»; printRecSubtotal; printRecTotal
      con il contante RICEVUTO (il resto lo calcola il registratore); endFiscalReceiptCut con IdCmd univoco;
    - descrizioni senza accenti, max 22 caratteri; gli sconti finiscono nelle righe (nessun comando di sconto separato);
    - comando rifiutato → resetPrinter (altrimenti il documento rimasto aperto blocca tutto);
    - risposta persa → si chiede lastIdCmd al registratore (2, 4, 8 secondi): mai una ristampa alla cieca;
    - chiusura Z come l'esempio del manuale (senza IdCmd), attesa di 300 s, poi 20 s di pausa e resetPrinter (il KUBE
      apre da solo il promemoria «VISITA TECNICA» che blocca i documenti successivi).
    """

    PATH = "/xml/printer.htm"
    DESC, MSG = 22, 42
    PAYMENTS = {"contanti": 1, "carta": 2, "bancomat": 2, "satispay": 2, "buono_pasto": 3, "buono": 2, "altro": 2}
    TIMEOUT, REPORT_TIMEOUT = 120, 300       # risponde a stampa finita; la Z trasmette anche all'Agenzia delle Entrate
    CONNECT_TRIES, CONNECT_PAUSE = 3, 4
    VERIFY_WAITS = (2, 4, 8)
    VAT_SLOTS = 10
    _vat_cache: dict[str, list[dict]] = {}

    def __init__(self, address: str, options: dict, http=None):
        a = address if address.startswith("http") else f"http://{address}"
        hostport = a.split("://", 1)[1].split("/", 1)[0]
        self.host, _, port = hostport.partition(":")
        self.port = int(port or 80)
        self.address = f"http://{hostport}"
        self.options = options or {}
        self.http = http  # solo per le prove: http(url, dati, intestazioni, timeout) -> bytes
        self.after_z_pause = float(self.options.get("after_z_pause", 20))

    # ------------------------------------------------------------------------------------------------ trasporto
    def request(self, body: str, timeout: int | None = None) -> dict:
        timeout = timeout or self.TIMEOUT
        user = self.options.get("username") or self.options.get("rt_user")
        auth = (user, self.options.get("password") or self.options.get("rt_password") or "") if user else None
        if self.http is None:
            return rt_parse(custom_http(self.host, self.port, body, auth, timeout))
        headers = {"Content-Type": "text/plain; charset=utf-8"}
        if auth:
            import base64
            headers["Authorization"] = "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        raw = self.http(f"{self.address}{self.PATH}", body.encode("utf-8"), headers, timeout)
        return rt_parse(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)

    def send(self, body: str, timeout: int | None = None) -> dict:
        """Comando di servizio: errore se rifiutato."""
        st = self.request(body, timeout)
        if not st["ok"]:
            raise RtNotSent(st["message"])
        return st

    def reset(self, why: str) -> None:
        """Annulla la transazione rimasta aperta (resetPrinter, come «annulla» dalla tastiera): un documento aperto non è emesso."""
        try:
            log(f"Custom RT: annullo della transazione eventualmente aperta ({why})")
            self.request(self.command("resetPrinter"), timeout=15)
        except DeviceError as e:
            log(f"Custom RT: annullo della transazione aperta non riuscito: {e}")

    def verify(self, my_id: str, why: str) -> dict:
        for wait in self.VERIFY_WAITS:
            time.sleep(wait)
            try:
                st = self.request(self.command("queryPrinterStatus"), timeout=10)
            except DeviceError:
                continue
            if st.get("last_idcmd") == my_id:
                log("Custom RT: risposta persa ma documento eseguito (lastIdCmd): registro l'esito senza ristampare")
                return {**st, "already_done": True}
            if st.get("fp_status") in ("000", None, ""):
                raise RtNotSent(f"{why}. Verificato sul registratore: documento NON emesso, si può riprovare")
        raise RtNoAnswer(f"{why}. Controlla sul registratore se il documento è uscito prima di riprovare")

    # ------------------------------------------------------------------------------------------------ XML
    @staticmethod
    def cents(v) -> int:
        return int((money(v) * 100).to_integral_value(ROUND_HALF_UP))

    @staticmethod
    def eur(cents: int) -> str:
        return f"{cents / 100:.2f}".replace(".", ",")

    @staticmethod
    def tag(name: str, **attrs) -> str:
        a = "".join(f" {k}={quoteattr(str(v))}" for k, v in attrs.items() if v is not None)
        return f"<{name}{a}></{name}>"

    @staticmethod
    def doc(root: str, body: list[str]) -> str:
        return '<?xml version="1.0" encoding="utf-8"?>\n' + f"<{root}>\n" + "".join(f" {x}\n" for x in body) + f"</{root}>\n"

    def command(self, name: str, **attrs) -> str:
        return self.doc("printerCommand", [self.tag(name, **attrs)])

    @staticmethod
    def idcmd(ref: str, suffix: str = "E") -> str:
        """Identificativo del comando (max 36 caratteri alfanumerici), sempre uguale per lo stesso documento."""
        return re.sub(r"[^A-Za-z0-9]", "", ref or uuid.uuid4().hex)[:34] + suffix

    def vat_table(self, refresh: bool = False) -> list[dict]:
        """Aliquote programmate nel registratore (getVatRate 1…10): indice a 2 cifre + aliquota a 4 cifre (centesimi)."""
        key = f"{self.host}:{self.port}"
        if refresh or key not in self._vat_cache:
            table = []
            for n in range(1, self.VAT_SLOTS + 1):
                st = self.request(self.command("getVatRate", numVat=n), timeout=15)
                b = (st.get("response_buf") or "").rstrip("\r\n")
                if st["ok"] and len(b) >= 6 and b[:6].isdigit() and int(b[2:6]):
                    table.append({"index": int(b[:2]), "rate": str(Decimal(int(b[2:6])) / 100), "description": b[8:33].strip()})
            self._vat_cache[key] = table
        return self._vat_cache[key]

    def id_vat(self, line) -> int:
        """Indice IVA: impostato a mano (opzione vat_ids, es. {"22": 1}) o letto dal registratore."""
        rate = D(line.get("vat_rate"))
        for k, v in (self.options.get("vat_ids") or self.options.get("vat_index") or {}).items():
            if v and D(k) == rate:
                return int(v)
        for refresh in (False, True):  # aliquota non trovata: si rilegge la tabella (il tecnico può averla cambiata)
            for v in self.vat_table(refresh):
                if D(v["rate"]) == rate:
                    return int(v["index"])
        raise RtNotSent(f"Aliquota IVA {rate.normalize()}% non programmata nel registratore: scrivi l'indice IVA nelle "
                        "impostazioni del dispositivo oppure fai programmare l'aliquota dal tecnico")

    def pay_code(self, method: str) -> int:
        pays = {**self.PAYMENTS, **(self.options.get("pay_types") or {}), **(self.options.get("payments") or {})}
        try:
            c = int(pays.get(method, pays.get("carta", 2)))
        except (TypeError, ValueError):
            c = 0
        if not 1 <= c <= 30:
            raise RtNotSent(f"Nel registratore manca il codice del pagamento «{method}»: impostalo nelle impostazioni del dispositivo")
        return c

    def sale_rows(self, p: dict) -> list[dict]:
        """Righe con lo sconto già dentro: le righe di sconto del documento (promozioni, premi fedeltà) si tolgono dalle
        righe della stessa aliquota, come in BluOrderScan (nessun printRecItemAdjustment, mai collaudato)."""
        rows = [{**ln, "cents": self.cents(ln["amount"]), "full_cents": self.cents(ln.get("full_amount") or ln["amount"])}
                for ln in p.get("lines", []) if money(ln["amount"]) > 0]
        for a in p.get("adjustments", []):
            left = self.cents(a["amount"])
            for r in rows:
                if left <= 0:
                    break
                if D(r["vat_rate"]) == D(a["vat_rate"]):
                    cut = min(left, r["cents"])
                    r["cents"] -= cut
                    left -= cut
            if left > 0:
                raise RtNotSent(f"Lo sconto «{a.get('description', '')}» supera le righe con IVA {D(a['vat_rate']).normalize()}%")
        rows = [r for r in rows if r["cents"] > 0]  # una riga tutta in omaggio non si stampa (importo zero)
        if not rows:
            raise RtNotSent("Lo scontrino deve avere almeno una riga con un importo")
        return rows

    def items(self, rows: list[dict], messages: bool = True) -> list[str]:
        out = []
        for r in rows:
            out.append(self.tag("printRecItem", description=rt_clean(r["description"], self.DESC) or "ARTICOLO", unitPrice=r["cents"],
                                department=department_for(r, self.options), IdVat=self.id_vat(r)))
            if not messages:
                continue
            qty = D(r.get("quantity") or 1)
            if qty != 1:
                q = f"{qty.normalize():f}".replace(".", ",")
                out.append(self.tag("printRecMessage", messageType=1, font=1,
                                    message=rt_clean(f"{q} x {self.eur(self.cents(r.get('unit_price') or 0))} EUR", self.MSG)))
            if r["full_cents"] > r["cents"]:
                out.append(self.tag("printRecMessage", messageType=1, font=1,
                                    message=rt_clean(f"Sconto {self.eur(r['full_cents'] - r['cents'])} EUR", self.MSG)))
        return out

    def totals(self, p: dict) -> list[str]:
        """Pagamenti, il contante per ultimo con l'importo ricevuto: il resto lo stampa il registratore."""
        pays = sorted(p.get("payments", []), key=lambda x: x["method"] == "contanti")
        out = [self.tag("printRecTotal", description="CONTANTI" if x["method"] == "contanti" else rt_clean(x["method"].replace("_", " ").upper(), self.DESC),
                        payment=self.cents(abs(D(x["amount"]))), paymentType=self.pay_code(x["method"])) for x in pays if money(x["amount"]) != 0]
        return out or [self.tag("printRecTotal", description="CONTANTI", payment=0, paymentType=self.pay_code("contanti"))]

    def end(self, my_id: str) -> str:
        return self.tag("endFiscalReceiptCut" if self.options.get("cut", True) else "endFiscalReceipt", IdCmd=my_id)

    def receipt_xml(self, p: dict, my_id: str | None = None) -> str:
        body = [self.tag("beginFiscalReceipt")] + self.items(self.sale_rows(p))
        if p.get("lottery"):
            body.append(self.tag("setLotteryCode", code=p["lottery"]))
        body.append(self.tag("printRecSubtotal"))
        body += self.totals(p)
        if p.get("document"):
            body.append(self.tag("printRecMessage", messageType=3, font=1, message=rt_clean(f"Rif. {p['document']}", self.MSG)))
        body.append(self.end(my_id or self.idcmd(p.get("document"))))
        return self.doc("printerFiscalReceipt", body)

    def refund_xml(self, p: dict, my_id: str | None = None) -> str:
        """Annullo (collaudato in BluOrderScan: stesse righe dello scontrino e totale «ANNULLO») o reso (da collaudare)."""
        ref, void = p.get("reference"), bool(p.get("void"))
        rows = [{**ln, "cents": self.cents(ln["amount"]), "full_cents": self.cents(ln["amount"])}
                for ln in p.get("lines", []) if money(ln["amount"]) > 0]
        my_id = my_id or self.idcmd(p.get("document"), "R")
        if ref:
            d = datetime.strptime(ref["date"][:10], "%Y-%m-%d")
            attrs = {"docRefZ": int(ref.get("z") or 0), "docRefNumber": int(ref.get("number") or 0), "docDate": f"{d:%d%m%y}"}
            if not void:
                attrs.update(printPreview=0, fiscalSerial=ref.get("serial") or self.options.get("serial") or "", checkOnly=0)
            body = [self.tag("beginRtDocAnnulment" if void else "beginRtDocRefund", **attrs)]
        else:  # documento d'origine non emesso da questo registratore
            body = [self.tag("beginRtDocAnnulmentSpecial" if void else "beginRtDocRefundSpecial", service="ND", docDate=f"{date.today():%d%m%y}")]
        if void:
            body += self.items(rows, messages=False)
            total = sum(r["cents"] for r in rows)
            body.append(self.tag("printRecTotal", description="ANNULLO", payment=total, paymentType=self.pay_code("contanti")))
        else:
            body += [x.replace("<printRecItem ", "<printRecRefund ").replace("</printRecItem>", "</printRecRefund>")
                     for x in self.items(rows, messages=False)]
            body += self.totals(p)
        body.append(self.end(my_id))
        return self.doc("printerFiscalReceipt", body)

    @staticmethod
    def direct_io(command: str, data: str) -> str:
        return CustomRT.doc("printerCommand", [CustomRT.tag("directIO", command=command, data=data)])

    # ------------------------------------------------------------------------------------------------ operazioni
    def fiscal(self, xml: str, my_id: str, what: str = "scontrino") -> dict:
        """Documento fiscale: un solo XML. Rifiutato → resetPrinter; risposta persa → verifica con lastIdCmd."""
        try:
            st = self.request(xml)
        except RtNoAnswer as e:
            st = self.verify(my_id, str(e))
        else:
            if not st["ok"]:
                self.reset("dopo il rifiuto")  # documento rifiutato a metà: altrimenti blocca tutto il resto
                raise RtNotSent(f"{st['message']}: {what} non emesso")
        return self.info(st)

    def info(self, st: dict) -> dict:
        n, z = st.get("fiscal_number"), st.get("z_number")
        out = {"number": n.zfill(4) if n and n.isdigit() else n, "z": z.zfill(4) if z and z.isdigit() else z,
               "date": date.today().isoformat(), "serial": self.options.get("serial")}
        if st.get("problems"):
            out["problems"] = st["problems"]
        if st.get("already_done"):
            out["verified"] = True
        return out

    def report(self, kind: str) -> dict:
        xml = self.doc("printerFiscalReport", [self.tag("printXReport") if kind == "X" else self.tag("printZReport", description="")])
        try:
            st = self.request(xml, self.REPORT_TIMEOUT)
        except RtNoAnswer as e:
            raise RtNoAnswer(f"{e}. Controlla sul registratore se la chiusura è uscita") from None
        if not st["ok"]:
            self.reset("dopo il rifiuto")
            raise RtNotSent(f"{st['message']}: chiusura non eseguita")
        if kind == "Z":
            time.sleep(self.after_z_pause)
            self.reset("dopo la chiusura")
        return {"z": st.get("z_number"), "date": date.today().isoformat(), "problems": st.get("problems", [])}

    def nonfiscal(self, p: dict) -> dict:
        """Scontrino NON fiscale sul registratore con i comandi Custom 4001 / 4003 / 4004 via directIO, uno per richiesta,
        come BluOrderScan e il gestionale macellerie (collaudati sul KUBE II). Righe da 32 caratteri (rotolo 57 mm),
        modificabili con l'opzione `width`. Se un comando viene rifiutato si annulla il documento aperto (resetPrinter)."""
        width = int(self.options.get("width") or 32)
        rows = text_rows(p, width, rt=True)
        try:
            self.send(self.direct_io("4001", "10"), 30)  # DOC 1 = scontrino non fiscale, COPIA 0
            for r in rows:
                self.send(self.direct_io("4003", f"1{len(r):02d}{r}"), 30)
            self.send(self.direct_io("4004", ""), 30)
        except DeviceError as e:
            self.reset("dopo la stampa non fiscale")
            raise RtNotSent(f"Stampa non fiscale rifiutata: {e}") from e
        return {"printed": True, "rows": len(rows)}

    def status(self) -> dict:
        try:
            st = self.request(self.command("queryPrinterStatus"), timeout=15)
        except RtNoAnswer as e:
            raise RtNotSent(f"Il registratore {self.host}:{self.port} non risponde al protocollo XML ({e}). Controlla che la "
                            "porta sia quella del server web del registratore (di solito 80)") from None
        if not st["ok"]:
            raise RtNotSent(st["message"])
        out = {"ok": True, "model": st.get("model"), "problems": st.get("problems", []), "z": st.get("z_number"),
               "number": st.get("fiscal_number")}
        try:
            out["vat_table"] = self.vat_table(refresh=True)
        except DeviceError as e:
            out["vat_error"] = str(e)
        return out

    def run(self, kind: str, p: dict) -> dict:
        if kind == "rt.receipt":
            my_id = self.idcmd(p.get("document"))
            return self.fiscal(self.receipt_xml(p, my_id), my_id)
        if kind == "rt.refund":
            my_id = self.idcmd(p.get("document"), "R")
            return self.fiscal(self.refund_xml(p, my_id), my_id, "annullo" if p.get("void") else "reso")
        if kind == "rt.z":
            return self.report("Z")
        if kind == "rt.x":
            self.report("X")
            return {}
        if kind == "rt.nonfiscal":
            return self.nonfiscal(p)
        if kind == "rt.vat":
            return {"vat_table": self.vat_table(refresh=True)}
        if kind == "status":
            return self.status()
        raise DeviceError(f"Operazione non prevista per il registratore: {kind}")


class SimulatedRT:
    """Registratore finto per provare tutto senza hardware: scrive i documenti nel registro dell'agent."""

    def __init__(self, address: str, options: dict, state_file: Path | None = None):
        self.options = options or {}
        self.state_file = state_file or (config_path().parent / "simulatore_rt.json")

    def _state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text("utf-8"))
        except (OSError, ValueError):
            return {"z": 1, "number": 0, "day": date.today().isoformat()}

    def _save(self, st):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(st), "utf-8")

    def run(self, kind: str, p: dict) -> dict:
        if self.options.get("fail"):
            raise DeviceError(str(self.options["fail"]))
        st = self._state()
        if kind in ("rt.receipt", "rt.refund"):
            total = sum((money(x["amount"]) for x in p.get("lines", [])), Decimal(0)) - sum((money(a["amount"]) for a in p.get("adjustments", [])), Decimal(0))
            st["number"] += 1
            self._save(st)
            what = "ANNULLO" if p.get("void") else "RESO" if kind == "rt.refund" else "DOCUMENTO COMMERCIALE"
            log(f"[simulatore RT] {what} {st['z']:04d}-{st['number']:04d} totale {total:.2f}")
            return {"number": f"{st['number']:04d}", "z": f"{st['z']:04d}", "date": date.today().isoformat(),
                    "serial": self.options.get("serial") or "99SIM000001", "amount": f"{total:.2f}", "simulated": True}
        if kind == "rt.z":
            z = st["z"]
            st.update(z=z + 1, number=0)
            self._save(st)
            log(f"[simulatore RT] chiusura giornaliera Z {z:04d}")
            return {"z": f"{z:04d}", "date": date.today().isoformat(), "simulated": True}
        if kind in ("rt.x", "status"):
            return {"ok": True, "simulated": True}
        if kind == "rt.nonfiscal":
            rows = text_rows(p, int(self.options.get("width") or 32), rt=True)
            log("[simulatore RT] documento NON fiscale\n" + "\n".join(rows))
            return {"printed": True, "rows": len(rows), "simulated": True}
        raise DeviceError(f"Operazione non prevista: {kind}")


# =====================================================================================================================
# Stampanti di ricevute (ESC/POS) ed etichette (ZPL)

ESC, GS = b"\x1b", b"\x1d"


# Tabelle dei caratteri: (numero per ESC t n, codifica Python). Esperienza di BluOrderScan e del gestionale macellerie:
# le Epson originali hanno la PC858 (con € e le lettere accentate); molte compatibili al numero 19 hanno un'altra tabella
# (es. greca: «più» stampato «piΩ») e vanno impostate su PC850 o PC437 (accenti sì, € no → «EUR»). «ascii» non usa
# nessuna tabella: «più» → «piu'». La pagina di prova stampa «àèéìòù ÀÈÉ €» per scegliere quella giusta.
CHARSETS = {"pc858": (19, "cp858"), "pc850": (2, "cp850"), "pc437": (0, "cp437"), "ascii": (0, None)}
REPLACE = {"–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...", "·": "-", "×": "x", "\u00a0": " ", "\u202f": " "}


class Charset:
    def __init__(self, name: str = "pc858"):
        self.name = name if name in CHARSETS else "pc858"
        self.number, self.codec = CHARSETS[self.name]
        self.euro = self.name == "pc858"  # il simbolo € c'è solo nella PC858

    def select(self) -> bytes:
        return ESC + b"t" + bytes([self.number])

    def norm(self, text: str) -> str:
        """Testo come verrà stampato (un carattere = un byte): serve anche per allineare le colonne."""
        import unicodedata
        t = "".join(REPLACE.get(ch, ch) for ch in (text or ""))
        if not self.euro:
            t = t.replace("€", "EUR")
        if self.codec is None:  # senza accenti: «più» → «piu'», «perché» → «perche'»
            t = re.sub(r"([aeiouAEIOU])[\u0300\u0301]", r"\1'", unicodedata.normalize("NFD", t))
            t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
        return t

    def enc(self, text: str) -> bytes:
        import unicodedata
        out = bytearray()
        for ch in self.norm(text):
            try:
                out += ch.encode(self.codec or "ascii")
            except UnicodeEncodeError:  # carattere fuori tabella: lettera senza accento o «?»
                out += unicodedata.normalize("NFKD", ch).encode("ascii", "ignore")[:1] or b"?"
        return bytes(out)


def escpos(p: dict, width: int = 48, charset: str = "pc858") -> bytes:
    """Testo neutro → comandi ESC/POS con la tabella dei caratteri scelta per la stampante (vedi CHARSETS)."""
    import textwrap
    cs = Charset(charset)
    out = bytearray(ESC + b"@" + cs.select())
    align = {"left": 0, "center": 1, "right": 2}
    for ln in p.get("lines", []):
        t = ln.get("type", "text")
        if t == "cut":
            out += b"\n\n\n" + GS + b"V\x42\x00"
            continue
        if t == "feed":
            out += b"\n" * int(ln.get("lines", 1))
            continue
        if t == "line":
            out += ESC + b"a\x00" + ("-" * width).encode("ascii") + b"\n"
            continue
        out += ESC + b"a" + bytes([align.get(ln.get("align", "left"), 0)])
        if t == "barcode":
            data = str(ln.get("data", "")).encode("ascii", "ignore")
            out += GS + b"h\x50" + GS + b"w\x02" + GS + b"H\x02" + GS + b"k\x49" + bytes([len(data) + 2]) + b"{B" + data + b"\n"
            continue
        if t == "qr":
            data = str(ln.get("data", "")).encode("utf-8")
            size = len(data) + 3
            out += GS + b"(k\x04\x001A2\x00" + GS + b"(k\x03\x001C\x06" + GS + b"(k\x03\x001E1"
            out += GS + b"(k" + bytes([size % 256, size // 256]) + b"1P0" + data + GS + b"(k\x03\x001Q0\n"
            continue
        size = int(ln.get("size", 1))
        cols = width // (2 if size >= 2 else 1)
        out += GS + b"!" + bytes([0x11 if size >= 2 else 0x00]) + ESC + b"E" + bytes([1 if ln.get("bold") else 0])
        text = cs.norm(str(ln.get("text", "")))
        if ln.get("right"):  # due colonne: testo a sinistra (a capo se lungo), importo allineato a destra
            right = cs.norm(str(ln["right"]))[: cols - 2]
            parts = textwrap.wrap(text, max(cols - len(right) - 1, 8)) or [""]
            for part in parts[:-1]:
                out += cs.enc(part) + b"\n"
            last = parts[-1]
            out += cs.enc(last + " " * max(1, cols - len(last) - len(right)) + right) + b"\n"
        else:
            for part in textwrap.wrap(text, cols, break_long_words=True) or [""]:
                out += cs.enc(part) + b"\n"
        out += GS + b"!\x00" + ESC + b"E\x00"
    if p.get("open_drawer"):
        out += ESC + b"p\x00\x19\xfa"
    if not any(ln.get("type") == "cut" for ln in p.get("lines", [])):
        out += b"\n\n\n" + GS + b"V\x42\x00"
    return bytes(out)


def raw_tcp(address: str, data: bytes, default_port: int = 9100, timeout: int = 10) -> None:
    host, _, port = address.partition(":")
    try:
        with socket.create_connection((host, int(port or default_port)), timeout=timeout) as s:
            s.sendall(data)
    except OSError as e:
        raise DeviceError(f"Stampante non raggiungibile su {address}: {e}") from None


def raw_windows(printer_name: str, data: bytes, title: str = "BluBeauty") -> None:
    try:
        import win32print  # type: ignore
    except ImportError:
        raise DeviceError("Per le stampanti installate su Windows serve il pacchetto pywin32 (pip install pywin32)") from None
    h = win32print.OpenPrinter(printer_name)
    try:
        win32print.StartDocPrinter(h, 1, (title, None, "RAW"))
        win32print.StartPagePrinter(h)
        win32print.WritePrinter(h, data)
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
    finally:
        win32print.ClosePrinter(h)


class Printer:
    def __init__(self, driver: str, address: str, options: dict):
        self.driver, self.address, self.options = driver, address, options or {}

    def _send(self, data: bytes):
        if self.driver.endswith("_tcp"):
            raw_tcp(self.address, data)
        elif self.driver.endswith("_windows"):
            raw_windows(self.address, data)
        elif self.driver.endswith("_file") or self.driver.startswith("simulatore"):
            target = Path(self.address or (config_path().parent / "stampe"))
            target.mkdir(parents=True, exist_ok=True)
            f = target / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.{'zpl' if 'zpl' in self.driver or 'etichette' in self.driver else 'bin'}"
            f.write_bytes(data)
            log(f"[{self.driver}] stampa salvata in {f}")
        else:
            raise DeviceError(f"Collegamento non previsto: {self.driver}")

    def run(self, kind: str, p: dict) -> dict:
        if kind == "print.text":
            self._send(escpos(p, int(self.options.get("columns", 48)), self.options.get("charset") or "pc858"))
            return {"printed": True}
        if kind == "print.zpl":
            data = (p.get("zpl") or "").encode("utf-8")
            for _ in range(max(1, int(p.get("copies", 1)))):
                self._send(data)
            return {"printed": True, "bytes": len(data)}
        if kind == "status":
            if self.driver.endswith("_tcp"):
                raw_tcp(self.address, b"")
            return {"ok": True}
        raise DeviceError(f"Operazione non prevista per la stampante: {kind}")


# =====================================================================================================================
# Bilance


class SerialScale:
    """Bilancia su porta seriale/USB: invia la richiesta (se prevista) e legge il peso dalla risposta."""

    def __init__(self, address: str, options: dict):
        self.address, self.options = address, options or {}

    def run(self, kind: str, p: dict) -> dict:
        if kind not in ("scale.read", "status"):
            raise DeviceError(f"Operazione non prevista per la bilancia: {kind}")
        try:
            import serial  # type: ignore
        except ImportError:
            raise DeviceError("Per la bilancia serve il pacchetto pyserial (pip install pyserial)") from None
        o = self.options
        try:
            with serial.Serial(self.address, int(o.get("baud", 9600)), bytesize=int(o.get("bits", 8)), parity=o.get("parity", "N"),
                               stopbits=int(o.get("stopbits", 1)), timeout=float(o.get("timeout", 2))) as s:
                req = o.get("request", "W\r")
                if req:
                    s.write(req.encode("latin-1").decode("unicode_escape").encode("latin-1"))
                raw = s.read(int(o.get("read_bytes", 64))).decode("latin-1", "replace")
        except Exception as e:  # noqa: BLE001 — errori della porta seriale
            raise DeviceError(f"Bilancia non raggiungibile su {self.address}: {e}") from None
        return parse_weight(raw, o)


def parse_weight(raw: str, o: dict | None = None) -> dict:
    o = o or {}
    m = re.findall(o.get("regex", r"([-+]?\d+[.,]\d+)"), raw)
    if not m:
        raise DeviceError("Peso non leggibile: la bilancia non ha risposto con un numero")
    w = Decimal(m[-1].replace(",", "."))
    if o.get("grams"):
        w = w / 1000
    unstable = any(x in raw.upper() for x in ("US,", "?", "M ")) or (o.get("unstable_marker") and o["unstable_marker"] in raw)
    return {"weight": f"{w:.3f}", "unit": "kg", "stable": not unstable}


class SimulatedScale:
    def __init__(self, address: str, options: dict):
        self.options = options or {}

    def run(self, kind: str, p: dict) -> dict:
        w = self.options.get("weight") or f"{random.uniform(0.1, 2.5):.3f}"
        return {"weight": f"{D(w):.3f}", "unit": "kg", "stable": True, "simulated": True}


# =====================================================================================================================


def make_driver(dev: dict):
    drv, addr, opt = dev.get("driver", ""), dev.get("address") or "", dev.get("options") or {}
    if drv == "epson_rt":
        return EpsonRT(addr, opt)
    if drv == "custom_rt":
        return CustomRT(addr, opt)
    if drv == "simulatore_rt":
        return SimulatedRT(addr, opt)
    if drv in ("escpos_tcp", "escpos_windows", "escpos_file", "zpl_tcp", "zpl_windows", "zpl_file", "simulatore_stampante", "simulatore_etichette"):
        return Printer(drv, addr, opt)
    if drv == "bilancia_seriale":
        return SerialScale(addr, opt)
    if drv == "simulatore_bilancia":
        return SimulatedScale(addr, opt)
    raise DeviceError(f"Driver sconosciuto: {drv}")


_device_locks: dict[str, threading.Lock] = {}


def execute(dev: dict, kind: str, payload: dict) -> dict:
    """Esegue un lavoro su un dispositivo (un lavoro per volta per dispositivo: il registratore non accetta sovrapposizioni)."""
    lock = _device_locks.setdefault(str(dev.get("id")), threading.Lock())
    with lock:
        return make_driver(dev).run(kind, payload or {})


# ----------------------------------------------------------------------------------------------------------- utilità


def child_tag(e: ET.Element) -> str:
    return e.tag.split("}", 1)[-1]


def find(root: ET.Element | None, name: str) -> ET.Element | None:
    if root is None:
        return None
    if child_tag(root) == name:
        return root
    for e in root.iter():
        if child_tag(e) == name:
            return e
    return None


def parse_xml(raw: bytes) -> ET.Element | None:
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        return None


def envelope(body: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
            f"<s:Body>{body}</s:Body></s:Envelope>")


def _ssl_context():
    ctx = ssl.create_default_context()
    extra = os.environ.get("BLUBEAUTY_AGENT_CA")
    if extra:
        ctx.load_verify_locations(extra)
    return ctx


def http_post(url: str, data: bytes, headers: dict, timeout: int) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context() if url.startswith("https") else None) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise DeviceError(f"Il dispositivo ha risposto con errore HTTP {e.code}") from None
    except (urllib.error.URLError, OSError) as e:
        raise DeviceError(f"Dispositivo non raggiungibile ({getattr(e, 'reason', e)})") from None


# =====================================================================================================================
# Collegamento col gestionale


class Server:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.base = cfg["server"].rstrip("/")

    def call(self, method: str, path: str, body=None, timeout: int = 30):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Authorization": f"Agent {self.cfg['token']}", "Content-Type": "application/json",
                                              "User-Agent": f"BluBeautyAgent/{VERSION}"})
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context() if self.base.startswith("https") else None) as r:
            raw = r.read()
        return json.loads(raw) if raw else None


def pair(server: str, code: str) -> dict:
    body = json.dumps({"code": code.strip().upper(), "hostname": socket.gethostname(), "version": VERSION,
                       "platform": f"{platform.system()} {platform.release()}"}).encode()
    req = urllib.request.Request(server.rstrip("/") + "/api/agent/abbina", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": f"BluBeautyAgent/{VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context() if server.startswith("https") else None) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except ValueError:
            pass
        raise SystemExit(f"Abbinamento non riuscito: {detail}") from None
    cfg = load_config()
    cfg.update(server=server.rstrip("/"), token=res["token"], agent_id=res["agent_id"], name=res["name"], local_key=res["local_key"],
               allowed_origins=res.get("allowed_origins", []))
    save_config(cfg)
    return cfg


class Agent:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.server = Server(cfg)
        self.devices: dict[str, dict] = {d["id"]: d for d in cfg.get("devices", [])}
        self.stop = threading.Event()
        self.online = False

    def refresh(self) -> None:
        try:
            res = self.server.call("GET", "/api/agent/configurazione")
            self.devices = {d["id"]: d for d in res["devices"]}
            self.cfg.update(devices=res["devices"], local_key=res.get("local_key", self.cfg.get("local_key")),
                            allowed_origins=res.get("allowed_origins", self.cfg.get("allowed_origins", [])), name=res.get("name"))
            save_config(self.cfg)
            self.online = True
        except Exception as e:  # noqa: BLE001
            self.online = False
            log(f"configurazione non aggiornata: {e}")

    def handle(self, job: dict) -> None:
        dev = job.get("device") or self.devices.get(job.get("device_id"))
        try:
            if not dev:
                raise DeviceError("Dispositivo non configurato su questo computer")
            result = execute(dev, job["kind"], job.get("payload") or {})
            body = {"ok": True, "result": result}
            log(f"lavoro {job['kind']} su {dev.get('name')}: eseguito")
        except DeviceError as e:
            body = {"ok": False, "error": str(e)}
            log(f"lavoro {job['kind']}: {e}")
        except Exception as e:  # noqa: BLE001
            body = {"ok": False, "error": f"Errore imprevisto dell'agent: {e}"}
            log(traceback.format_exc())
        for attempt in range(20):  # l'esito non si perde: si ritenta finché il server lo riceve
            try:
                self.server.call("POST", f"/api/agent/lavori/{job['id']}/esito", body)
                return
            except Exception:  # noqa: BLE001
                time.sleep(min(30, 2 ** attempt))

    def loop(self) -> None:
        last_refresh = 0.0
        while not self.stop.is_set():
            if time.time() - last_refresh > 120:
                self.refresh()
                last_refresh = time.time()
            try:
                jobs = self.server.call("GET", "/api/agent/lavori?attesa=25", timeout=40) or []
                self.online = True
                for job in jobs:
                    threading.Thread(target=self.handle, args=(job,), daemon=True).start()
            except urllib.error.HTTPError as e:
                self.online = False
                if e.code in (401, 403):
                    log("l'agent non è più autorizzato: rifai l'abbinamento dal gestionale")
                    self.stop.wait(300)
                else:
                    self.stop.wait(10)
            except Exception as e:  # noqa: BLE001 — rete assente: si riprova
                self.online = False
                log(f"server non raggiungibile ({e}), riprovo")
                self.stop.wait(10)


def make_local_handler(agent: Agent):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"BluBeautyAgent/{VERSION}"

        def log_message(self, fmt, *args):  # niente log di ogni richiesta
            pass

        def _cors(self):
            origin = self.headers.get("Origin") or ""
            allowed = agent.cfg.get("allowed_origins") or []
            if origin and origin in allowed:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Agent-Key")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Private-Network", "true")

        def _json(self, code: int, body: dict):
            data = json.dumps(body).encode()
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            origin = self.headers.get("Origin")
            if origin and origin not in (agent.cfg.get("allowed_origins") or []):
                return False
            key = agent.cfg.get("local_key")
            return bool(key) and self.headers.get("X-Agent-Key") == key

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            if self.path.startswith("/stato"):
                if not self._authorized():
                    return self._json(403, {"error": "Non autorizzato"})
                return self._json(200, {"version": VERSION, "name": agent.cfg.get("name"), "online": agent.online,
                                        "devices": [{"id": d["id"], "name": d["name"], "kind": d["kind"]} for d in agent.devices.values()]})
            self._json(404, {"error": "Non trovato"})

        def do_POST(self):
            if not self.path.startswith("/lavoro"):
                return self._json(404, {"error": "Non trovato"})
            if not self._authorized():
                return self._json(403, {"error": "Non autorizzato"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                dev = agent.devices.get(body.get("device_id"))
                if not dev:
                    return self._json(404, {"error": "Dispositivo non configurato su questo computer"})
                result = execute(dev, body["kind"], body.get("payload") or {})
                log(f"lavoro locale {body['kind']} su {dev.get('name')}: eseguito")
                return self._json(200, {"ok": True, "result": result})
            except DeviceError as e:
                return self._json(200, {"ok": False, "error": str(e)})
            except Exception as e:  # noqa: BLE001
                log(traceback.format_exc())
                return self._json(500, {"ok": False, "error": f"Errore imprevisto dell'agent: {e}"})

    return Handler


def run_agent() -> None:
    cfg = load_config()
    if not cfg.get("token"):
        raise SystemExit("Agent non abbinato. Genera un codice nel gestionale (Vendita al banco › Computer e periferiche) e lancia:\n"
                         "  python blubeauty_agent.py abbina https://indirizzo-del-gestionale CODICE")
    agent = Agent(cfg)
    agent.refresh()
    port = int(cfg.get("local_port", LOCAL_PORT))
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), make_local_handler(agent))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        log(f"BluBeauty Agent {VERSION} «{cfg.get('name')}»: servizio locale su http://127.0.0.1:{port}")
    except OSError as e:
        log(f"servizio locale non avviato sulla porta {port}: {e}")
    log(f"collegato a {cfg['server']} con {len(agent.devices)} dispositivi")
    try:
        agent.loop()
    except KeyboardInterrupt:
        log("arresto")


def self_test() -> None:
    cfg = load_config()
    agent = Agent(cfg)
    if cfg.get("token"):
        agent.refresh()
    if not agent.devices:
        print("Nessun dispositivo configurato per questo computer.")
    for d in agent.devices.values():
        try:
            execute(d, "status", {})
            print(f"OK   {d['name']} ({d['driver']} {d.get('address') or ''})")
        except DeviceError as e:
            print(f"ERRORE {d['name']}: {e}")


def main(argv: list[str]) -> None:
    if len(argv) >= 4 and argv[1] == "abbina":
        cfg = pair(argv[2], argv[3])
        print(f"Abbinato come «{cfg['name']}». Ora avvia l'agent con: python {Path(argv[0]).name} avvia")
    elif len(argv) >= 2 and argv[1] == "avvia":
        run_agent()
    elif len(argv) >= 2 and argv[1] == "prova":
        self_test()
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
