"""Eliminazione definitiva di un'azienda cliente, solo dopo un archivio completo.

Procedura (tutta dal pannello super admin):
1. l'azienda deve essere SOSPESA (così i dati non cambiano più);
2. «Crea archivio»: ZIP con tutte le righe di tutte le tabelle dell'azienda (JSON) e i file caricati (immagini,
   allegati), salvato sul server in ARCHIVE_DIR con la sua impronta SHA-256, e scaricato sul computer del tecnico;
3. «Elimina»: serve scrivere il nome dell'azienda e la parola ELIMINA, e l'impronta SHA-256 del file scaricato
   deve coincidere con quella della copia sul server (prova che il file è arrivato intero sul computer);
4. mai se esistono pagamenti «pagato» (le fatture degli abbonamenti vanno conservate).
L'eliminazione è registrata nel log (senza azienda, perché sparisce) e l'archivio sul server resta.
"""

import hashlib
import io
import json
import os
import re
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import set_tenant
from app.core.media import media_dir
from app.core.models import TENANT_TABLES, AuditLog, Subscription, Tenant, TenantModule
from app.pagamenti.models import Payment

CONFIRM_WORD = "ELIMINA"
ARCHIVE_VALID = timedelta(hours=6)
_HEX = re.compile(r"[0-9a-f]{32}")
_SAFE = re.compile(r"^[A-Za-z0-9_.-]+\.zip$")


def archive_dir() -> str:
    path = get_settings().archive_dir or os.path.join(os.path.dirname(os.path.abspath(media_dir())), "archivi")
    os.makedirs(path, exist_ok=True)
    return path


def _json_default(o):
    if isinstance(o, (datetime,)):
        return o.isoformat()
    if isinstance(o, (Decimal, uuid.UUID)):
        return str(o)
    if isinstance(o, (bytes, bytearray, memoryview)):
        return bytes(o).hex()
    return str(o)


def _rows(db: Session, sql: str, params: dict) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(sql), params)]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "azienda"


def _paid_count(db: Session, tenant_id: uuid.UUID) -> int:
    set_tenant(db, tenant_id)
    return db.scalar(select(func.count()).select_from(Payment).where(Payment.status == "pagato")) or 0


def check_deletable(db: Session, t: Tenant) -> None:
    if not t.suspended:
        raise HTTPException(status.HTTP_409_CONFLICT, "Prima sospendi l'azienda: così i dati non cambiano durante l'archivio.")
    n = _paid_count(db, t.id)
    if n:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Non eliminabile: ci sono {n} pagamenti con fattura da conservare. Lascia l'azienda sospesa.")


def create_archive(db: Session, t: Tenant, admin_id) -> dict:
    """Crea lo ZIP sul server e ne restituisce nome, impronta e dimensione."""
    check_deletable(db, t)
    set_tenant(db, t.id)
    tables: dict[str, list[dict]] = {}
    for name in TENANT_TABLES:
        rows = _rows(db, f'SELECT * FROM "{name}" WHERE tenant_id = :t', {"t": t.id})
        if rows:
            tables[name] = rows
    tid = {"t": t.id}
    system = {
        "tenants": _rows(db, "SELECT * FROM tenants WHERE id = :t", tid),
        "subscriptions": _rows(db, "SELECT * FROM subscriptions WHERE tenant_id = :t", tid),
        "tenant_modules": _rows(db, "SELECT * FROM tenant_modules WHERE tenant_id = :t", tid),
        "audit_log": _rows(db, "SELECT * FROM audit_log WHERE tenant_id = :t", tid),
        "email_log": _rows(db, "SELECT * FROM email_log WHERE tenant_id = :t", tid),
    }
    blobs = {name: json.dumps(rows, default=_json_default, ensure_ascii=False, indent=1)
             for name, rows in {**system, **tables}.items()}

    # file caricati: ogni nome di 32 cifre esadecimali citato nei dati (con la sua miniatura)
    wanted = set()
    for text_ in blobs.values():
        wanted.update(_HEX.findall(text_))
    mdir = media_dir()
    media_files = sorted(f for f in os.listdir(mdir) if _HEX.match(f) and f[:32] in wanted)

    now = datetime.now(timezone.utc)
    fname = f"{_slug(t.name)}_{str(t.id)[:8]}_{now:%Y%m%d-%H%M%S}.zip"
    path = os.path.join(archive_dir(), fname)
    summary = {name: len(rows) for name, rows in {**system, **tables}.items()}
    info = {"azienda": t.name, "id": str(t.id), "creato": now.isoformat(), "righe_per_tabella": summary,
            "file_caricati": len(media_files)}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("LEGGIMI.txt", f"Archivio di {t.name} creato il {now:%d/%m/%Y %H:%M} UTC prima dell'eliminazione.\n"
                                  "dati/<tabella>.json = righe di ogni tabella; media/ = file caricati.\n")
        z.writestr("indice.json", json.dumps(info, ensure_ascii=False, indent=1))
        for name, blob in blobs.items():
            z.writestr(f"dati/{name}.json", blob)
        for f in media_files:
            z.write(os.path.join(mdir, f), f"media/{f}")
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    with open(path + ".json", "w") as fh:
        json.dump({"tenant_id": str(t.id), "sha256": digest, "created": now.isoformat(), "media": media_files,
                   "size": os.path.getsize(path)}, fh)
    db.add(AuditLog(entity="tenant", action="archivio_creato", entity_id=str(t.id), tenant_id=t.id, admin_id=admin_id,
                    after={"file": fname, "sha256": digest}))
    return {"file": fname, "sha256": digest, "size": os.path.getsize(path), "created": now.isoformat(),
            "rows": sum(summary.values()), "media": len(media_files)}


def archive_path(t_id: uuid.UUID, fname: str) -> str:
    if not _SAFE.match(fname) or str(t_id)[:8] not in fname:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Archivio non trovato")
    path = os.path.join(archive_dir(), fname)
    if not os.path.isfile(path) or not os.path.isfile(path + ".json"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Archivio non trovato")
    return path


def delete_tenant(db: Session, t: Tenant, admin_id, *, name: str, confirm: str, sha256: str, file: str) -> dict:
    check_deletable(db, t)
    if name.strip() != t.name or confirm.strip() != CONFIRM_WORD:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Scrivi il nome esatto dell'azienda e la parola {CONFIRM_WORD}.")
    path = archive_path(t.id, file)
    meta = json.load(open(path + ".json"))
    if meta["tenant_id"] != str(t.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "L'archivio non appartiene a questa azienda.")
    if (sha256 or "").strip().lower() != meta["sha256"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Il file scaricato sul computer non coincide con la copia sul server: scaricalo di nuovo.")
    if datetime.now(timezone.utc) - datetime.fromisoformat(meta["created"]) > ARCHIVE_VALID:
        raise HTTPException(status.HTTP_409_CONFLICT, "Archivio troppo vecchio: creane uno nuovo.")
    # nessuna modifica ai dati dopo l'archivio (l'azienda è sospesa, ma l'assistenza può aver scritto)
    set_tenant(db, t.id)
    last = db.scalar(select(func.max(AuditLog.at)).where(AuditLog.tenant_id == t.id, AuditLog.action != "archivio_creato"))
    if last and last > datetime.fromisoformat(meta["created"]):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ci sono modifiche successive all'archivio: creane uno nuovo.")

    info = {"id": str(t.id), "name": t.name, "contact_email": t.contact_email, "archive": file, "sha256": meta["sha256"]}
    db.add(AuditLog(entity="tenant", action="eliminazione", entity_id=str(t.id), tenant_id=None, admin_id=admin_id, before=info))
    db.flush()
    # tutte le tabelle dell'azienda hanno la chiave su tenants con ON DELETE CASCADE
    db.execute(delete(Subscription).where(Subscription.tenant_id == t.id))
    db.execute(delete(TenantModule).where(TenantModule.tenant_id == t.id))
    db.expunge(t)
    db.execute(delete(Tenant).where(Tenant.id == t.id))
    db.commit()
    mdir = media_dir()
    removed = 0
    for f in meta["media"]:
        try:
            os.remove(os.path.join(mdir, f))
            removed += 1
        except FileNotFoundError:
            pass
    return {"deleted": True, "archive": file, "media_removed": removed}
