"""Fatturazione elettronica: invio a SDI tramite Aruba, stati e notifiche, fatture ricevute.

Due modi di collegarsi ad Aruba, scelti per azienda:
- "piattaforma": l'utenza Premium di BluBeauty (variabili ARUBA_*), l'azienda è un suo cedente (multicedente);
- "proprio": l'azienda inserisce le sue credenziali Aruba (conservate cifrate)."""

import base64
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from cryptography.fernet import Fernet, InvalidToken
from lxml import etree
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.anagrafiche.models import AppSetting, Party
from app.core import media
from app.core.config import get_settings
from app.core.models import Company
from app.documenti import service as docs
from app.documenti.fatturapa_import import extract_xml, parse_xml
from app.documenti.models import Document
from app.fatturapa import xml_builder as xb
from app.fatturapa.aruba import ArubaClient, ArubaError, parse_date
from app.fatturapa.models import FINAL, FINAL_PA, RESENDABLE, STATUSES, EInvoice, EInvoiceInbox, EInvoiceRoute

log = logging.getLogger(__name__)
_transport = None  # nei test: httpx.MockTransport che simula Aruba

TEXT_STATUS = {"presa in carico": "presa_in_carico", "errore elaborazione": "errore_elaborazione", "inviata": "inviata",
               "scartata": "scartata", "non consegnata": "non_consegnata", "recapito impossibile": "recapito_impossibile",
               "consegnata": "consegnata", "accettata": "accettata", "rifiutata": "rifiutata", "decorrenza termini": "decorrenza_termini"}
NOTIFY_STATUS = {"NS": "scartata", "MC": "non_consegnata", "AT": "recapito_impossibile", "RC": "consegnata", "DT": "decorrenza_termini"}
DEFAULTS = {"mode": "piattaforma", "username": "", "password": "", "auto_send": False, "sign_domain": "", "sign_credential": "",
            "last_in_sync": None}


def fail(msg: str):
    return docs.fail(msg)


# ====================================================================== impostazioni e credenziali


def _fernet() -> Fernet:
    key = hashlib.sha256(("blubeauty-fatturapa:" + get_settings().secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(v: str) -> str:
    return _fernet().encrypt(v.encode()).decode() if v else ""


def decrypt(v: str) -> str:
    if not v:
        return ""
    try:
        return _fernet().decrypt(v.encode()).decode()
    except InvalidToken:
        return ""


def settings(db: Session, tenant_id) -> dict:
    s = db.get(AppSetting, (tenant_id, "fatturapa"))
    return {**DEFAULTS, **(s.value if s and s.value else {})}


def public_settings(db: Session, tenant_id) -> dict:
    s = settings(db, tenant_id)
    cfg = get_settings()
    return {"mode": s["mode"], "username": s["username"], "has_password": bool(s["password"]), "auto_send": s["auto_send"],
            "sign_domain": s["sign_domain"], "has_sign_credential": bool(s["sign_credential"]), "last_in_sync": s["last_in_sync"],
            "platform_available": bool(cfg.aruba_username and cfg.aruba_password), "environment": cfg.aruba_env,
            "recipient_code": "KRRH6B9"}


def save_settings(db: Session, tenant_id, body: dict) -> dict:
    row = db.get(AppSetting, (tenant_id, "fatturapa"))
    if row is None:
        row = AppSetting(tenant_id=tenant_id, key="fatturapa", value={})
        db.add(row)
    cur = settings(db, tenant_id)
    cur.update({k: body[k] for k in ("mode", "username", "auto_send", "sign_domain") if k in body})
    if body.get("password"):
        cur["password"] = encrypt(body["password"])
    if body.get("sign_credential"):
        cur["sign_credential"] = encrypt(body["sign_credential"])
    row.value = cur
    db.flush()
    ensure_route(db, tenant_id)
    return public_settings(db, tenant_id)


def client_for(db: Session, tenant_id) -> ArubaClient:
    s = settings(db, tenant_id)
    cfg = get_settings()
    if s["mode"] == "proprio":
        if not s["username"] or not s["password"]:
            raise ArubaError("Inserisci le credenziali Aruba in Impostazioni › Fatturazione elettronica")
        return ArubaClient(s["username"], decrypt(s["password"]), cfg.aruba_env, transport=_transport)
    if not cfg.aruba_username or not cfg.aruba_password:
        raise ArubaError("Il collegamento ad Aruba della piattaforma non è ancora attivo: contatta l'assistenza "
                         "oppure inserisci le tue credenziali Aruba")
    return ArubaClient(cfg.aruba_username, cfg.aruba_password, cfg.aruba_env, transport=_transport)


def ensure_route(db: Session, tenant_id) -> None:
    """Registra la partita IVA dell'azienda per ricondurre le callback di Aruba all'azienda giusta."""
    co = db.scalar(select(Company).order_by(Company.name))
    if co is None or not co.vat_number:
        return
    country, vat = xb.split_vat(co.vat_number)
    db.execute(insert(EInvoiceRoute).values(vat_key=f"{country}{vat}", tenant_id=tenant_id)
               .on_conflict_do_update(index_elements=["vat_key"], set_={"tenant_id": tenant_id}))


def tenant_for_vat(db: Session, country: str | None, vat: str | None):
    if not vat:
        return None
    return db.scalar(select(EInvoiceRoute.tenant_id).where(EInvoiceRoute.vat_key == f"{(country or 'IT').upper()}{vat}"))


# ====================================================================== invio


def latest(db: Session, doc_id) -> EInvoice | None:
    return db.scalar(select(EInvoice).where(EInvoice.document_id == doc_id).order_by(EInvoice.attempt.desc()).limit(1))


def prepare(db: Session, d: Document, progressive: str = "00000") -> tuple[xb.Check, bytes | None, list[str]]:
    chk = xb.precheck(db, d)
    if not chk.ok:
        return chk, None, []
    xml = xb.build(db, d, progressive)
    return chk, xml, xb.validate(xml)


def verify(db: Session, d: Document) -> dict:
    """Controlli locali + verifica di Aruba senza invio (dryRun), se il collegamento è configurato."""
    chk, xml, xsd = prepare(db, d)
    out = {"errors": chk.errors + [f"Schema: {e}" for e in xsd], "warnings": chk.warnings, "aruba": None}
    if xml and not xsd:
        try:
            client_for(db, d.tenant_id).upload(xml, dry_run=True)
            out["aruba"] = "ok"
        except ArubaError as exc:
            if exc.code:
                out["errors"].append(str(exc))
            else:
                out["aruba"] = str(exc)
    out["ok"] = not out["errors"]
    return out


def send(db: Session, d: Document, user_id=None) -> EInvoice:
    prev = latest(db, d.id)
    if prev is not None and prev.status not in RESENDABLE:
        raise fail(f"La fattura è già stata trasmessa (stato: {prev.status.replace('_', ' ')})")
    chk, xml, xsd = prepare(db, d)
    if not chk.ok:
        raise fail("Correggi prima di inviare: " + "; ".join(chk.errors))
    if xsd:
        raise fail("Il file non rispetta lo schema FatturaPA: " + "; ".join(xsd[:3]))
    n = docs.next_number(db, d.tenant_id, d.company_id, "SDI", 0)
    progressive = xb.progressive_code(n)
    xml = xb.build(db, d, progressive)
    s = settings(db, d.tenant_id)
    e = EInvoice(tenant_id=d.tenant_id, document_id=d.id, attempt=(prev.attempt + 1) if prev else 1, progressive=progressive,
                 format=xb.transmission_format(db.get(Party, d.party_id)), xml_file=media.save_file(xml, "fattura.xml"),
                 status="da_inviare", errors=[], notifications=[], sent_by=user_id)
    db.add(e)
    db.flush()
    ensure_route(db, d.tenant_id)
    try:
        r = client_for(db, d.tenant_id).upload(xml, domain=s["sign_domain"] or None, credential=decrypt(s["sign_credential"]) or None)
    except ArubaError as exc:
        e.status = "errore_elaborazione"
        e.errors = [{"code": exc.code or "", "description": str(exc)}]
        db.flush()
        return e
    e.filename = r.get("uploadFileName")
    e.status = "presa_in_carico"
    e.sent_at = datetime.now(timezone.utc)
    db.flush()
    return e


def is_final(db: Session, e: EInvoice) -> bool:
    return e.status in (FINAL_PA if e.format == "FPA12" else FINAL)


def refresh(db: Session, e: EInvoice, client: ArubaClient | None = None) -> EInvoice:
    if not e.filename:
        return e
    client = client or client_for(db, e.tenant_id)
    det = client.sent_detail(e.filename)
    inv = (det.get("invoices") or [{}])[0]
    status = TEXT_STATUS.get((inv.get("status") or "").strip().lower())
    if status:
        e.status = status
    e.sdi_id = det.get("idSdi") or e.sdi_id
    e.aruba_id = det.get("id") or e.aruba_id
    errs = det.get("sdiErrors") or []
    if errs:
        e.errors = [{"code": str(x.get("code") or x.get("codice") or ""), "description": x.get("description") or x.get("descrizione") or str(x)}
                    if isinstance(x, dict) else {"code": "", "description": str(x)} for x in errs]
    elif inv.get("statusDescription") and status == "errore_elaborazione":
        e.errors = [{"code": "", "description": inv["statusDescription"]}]
    try:
        notes = client.sent_notifications(e.filename)
        e.notifications = [{"type": n.get("docType"), "date": n.get("date"), "filename": n.get("filename"), "result": n.get("result")}
                           for n in notes]
        for n in notes:
            if n.get("docType") == "NE" and n.get("result") in ("EC01", "EC02"):
                e.status = "accettata" if n["result"] == "EC01" else "rifiutata"
    except ArubaError:
        pass
    e.checked_at = datetime.now(timezone.utc)
    db.flush()
    return e


# ====================================================================== notifiche e callback


def _notification_info(xml_b64: str | None) -> dict:
    """Dalla notifica SDI: nome del file fattura, esito (NE) e lista errori (NS)."""
    out = {"invoice_filename": None, "result": None, "errors": []}
    if not xml_b64:
        return out
    try:
        root = etree.fromstring(base64.b64decode(xml_b64), etree.XMLParser(resolve_entities=False, no_network=True))
    except Exception:  # noqa: BLE001
        return out
    for el in root.iter():
        el.tag = etree.QName(el).localname if isinstance(el.tag, str) else el.tag
    out["invoice_filename"] = root.findtext(".//NomeFile")
    out["result"] = root.findtext(".//EsitoCommittente/Esito") or root.findtext(".//Esito")
    for err in root.findall(".//ListaErrori/Errore"):
        out["errors"].append({"code": err.findtext("Codice") or "", "description": err.findtext("Descrizione") or ""})
    return out


def apply_notification(db: Session, e: EInvoice, notify_type: str, when: str | None, filename: str | None, xml_b64: str | None) -> None:
    info = _notification_info(xml_b64)
    t = (notify_type or "").upper()
    status = NOTIFY_STATUS.get(t)
    if t.startswith("NE"):
        res = info["result"] or ("EC01" if t.endswith("EC01") else "EC02" if t.endswith("EC02") else None)
        status = "accettata" if res == "EC01" else "rifiutata" if res == "EC02" else None
    if status:
        e.status = status
    if info["errors"]:
        e.errors = info["errors"]
    if not any(n.get("filename") == filename for n in e.notifications or []):
        e.notifications = [*(e.notifications or []), {"type": t, "date": when, "filename": filename, "result": info["result"]}]
    db.flush()


def find_out(db: Session, filename: str | None = None, sdi_id: str | None = None) -> EInvoice | None:
    if filename:
        e = db.scalar(select(EInvoice).where(EInvoice.filename == filename))
        if e:
            return e
    if sdi_id:
        return db.scalar(select(EInvoice).where(EInvoice.sdi_id == str(sdi_id)))
    return None


def callback_status(db: Session, payload: dict) -> bool:
    e = find_out(db, payload.get("invoiceFileName"), payload.get("sdiIdentification"))
    if e is None:
        return False
    st = TEXT_STATUS.get((payload.get("status") or "").strip().lower())
    if st:
        e.status = st
    if payload.get("sdiIdentification"):
        e.sdi_id = str(payload["sdiIdentification"])
    if payload.get("errorDescription"):
        e.errors = [{"code": "", "description": payload["errorDescription"]}]
    db.flush()
    return True


def callback_notification(db: Session, payload: dict) -> bool:
    if (payload.get("inOut") or "").upper() != "OUT":
        return True  # notifiche sulle fatture ricevute: per ora non servono
    info = _notification_info(payload.get("notifyXmlBase64"))
    e = find_out(db, info["invoice_filename"], payload.get("sdiIdentification"))
    if e is None:
        return False
    if payload.get("sdiIdentification"):
        e.sdi_id = str(payload["sdiIdentification"])
    apply_notification(db, e, payload.get("notifyType"), payload.get("notificationDate"), payload.get("notifyFileName"),
                       payload.get("notifyXmlBase64"))
    return True


def store_received(db: Session, tenant_id, filename: str, raw: bytes, aruba_id=None, sdi_id=None) -> EInvoiceInbox | None:
    """Salva una fattura ricevuta (XML o p7m) nella casella, una sola volta per file."""
    if db.scalar(select(EInvoiceInbox.id).where(EInvoiceInbox.filename == filename)):
        return None
    try:
        xml = extract_xml(filename, raw)
    except Exception:  # noqa: BLE001
        xml = None
    if not xml:
        log.warning("Fattura ricevuta illeggibile: %s", filename)
        return None
    invs = parse_xml(filename, xml)
    inv = invs[0] if invs else None
    row = EInvoiceInbox(tenant_id=tenant_id, filename=filename, aruba_id=str(aruba_id) if aruba_id else None,
                        sdi_id=str(sdi_id) if sdi_id else None, xml_file=media.save_file(xml, "fattura.xml"), status="da_registrare")
    if inv is not None:
        row.supplier_name = (inv.supplier.get("name") or "")[:200]
        row.supplier_vat = f"{inv.supplier.get('vat_country') or ''}{inv.supplier.get('vat_number') or ''}"[:30] or None
        row.number, row.invoice_date, row.doc_type = (inv.number or "")[:40], inv.date, inv.doc_type
        row.total = sum((Decimal(i.total) for i in invs if i.total is not None), Decimal(0)) if any(i.total is not None for i in invs) else None
    db.add(row)
    db.flush()
    return row


def callback_invoice(db: Session, tenant_id, payload: dict) -> bool:
    raw = base64.b64decode(payload.get("invoiceXmlBase64") or "")
    store_received(db, tenant_id, payload.get("sdiInvoiceFileName") or f"sdi-{payload.get('sdiIdentification')}.xml", raw,
                   sdi_id=payload.get("sdiIdentification"))
    return True


def sync_received(db: Session, tenant_id, until: datetime | None = None) -> int:
    """Scarica da Aruba le fatture ricevute dall'ultima sincronizzazione (finestre di 2 giorni, come richiede l'API)."""
    s = settings(db, tenant_id)
    client = client_for(db, tenant_id)
    until = until or datetime.now(timezone.utc)
    start = datetime.fromisoformat(s["last_in_sync"]) if s.get("last_in_sync") else until - timedelta(days=10)
    start = max(start - timedelta(hours=1), until - timedelta(days=60))
    co = db.scalar(select(Company).order_by(Company.name))
    vat = xb.split_vat(co.vat_number)[1] if co and co.vat_number else None
    premium = s["mode"] != "proprio"
    n = 0
    cur = start
    while cur < until:
        end = min(cur + timedelta(days=2), until)
        page = 1
        while True:
            res = client.received(cur, end, page, receiver_vat=vat if premium else None)
            for it in res.get("content") or []:
                fn = it.get("filename")
                if not fn or db.scalar(select(EInvoiceInbox.id).where(EInvoiceInbox.filename == fn)):
                    continue
                det = client.received_detail(fn)
                raw = base64.b64decode(det.get("file") or "")
                if store_received(db, tenant_id, fn, raw, aruba_id=det.get("id"), sdi_id=det.get("idSdi")):
                    n += 1
            if res.get("last", True) or page >= int(res.get("totalPages") or 1):
                break
            page += 1
        cur = end
    row = db.get(AppSetting, (tenant_id, "fatturapa"))
    if row is None:
        row = AppSetting(tenant_id=tenant_id, key="fatturapa", value=dict(DEFAULTS))
        db.add(row)
    row.value = {**settings(db, tenant_id), "last_in_sync": until.isoformat()}
    db.flush()
    return n


def poll_tenant(db: Session, tenant_id, max_refresh: int = 20) -> dict:
    client = client_for(db, tenant_id)
    open_rows = [e for e in db.scalars(select(EInvoice).where(EInvoice.filename.is_not(None)).order_by(EInvoice.checked_at.nulls_first()))
                 if not is_final(db, e)][:max_refresh]
    updated = 0
    for e in open_rows:
        try:
            refresh(db, e, client)
            updated += 1
        except ArubaError as exc:
            log.warning("Aggiornamento stato SDI non riuscito per %s: %s", e.filename, exc)
            if exc.status == 429:
                break
    received = sync_received(db, tenant_id)
    return {"updated": updated, "received": received}


def status_label(e: EInvoice | None) -> str | None:
    from app.fatturapa.models import STATUS_LABELS
    return STATUS_LABELS.get(e.status) if e else None


def clean_filename(v: str) -> str:
    return re.sub(r"[^\w.\-]", "_", v)[:120]


__all__ = ["STATUSES"]
