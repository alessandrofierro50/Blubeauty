"""Impostazioni dei documenti di vendita: sezionali, numerazioni modificabili a mano e imposta di bollo.

- Sezionali: per fatture (FT: immediate, differite e note di credito insieme), DDT, preventivi e ordini; il sezionale
  vuoto ("") è il principale. Il numero si stampa come n/sezionale/anno.
- Prossimo numero: si può cambiare (es. si riparte da 1 dopo le prove, o si continua da 6 dopo le fatture fatte
  altrove). Non si può scendere sotto un numero già usato da un documento valido; i documenti annullati e mai
  trasmessi a SDI con un numero in conflitto perdono il numero.
- Numero manuale sul singolo documento alla conferma: deve essere libero e rispettare l'ordine delle date."""

import re

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.anagrafiche.models import AppSetting
from app.documenti import service as docs
from app.documenti.models import Document, Numbering

KEYS = {"FT": ("Fatture e note di credito", ("FTI", "FTD", "NC")), "DDT": ("DDT", ("DDT",)),
        "PRV": ("Preventivi", ("PRV",)), "ORC": ("Ordini cliente", ("ORC",))}
SERIES_RE = re.compile(r"^[A-Z0-9]{1,10}$")
INVOICE_TYPES = ("FTI", "FTD", "NC")


def key_of(doc_type: str) -> str:
    return "FT" if doc_type in INVOICE_TYPES else doc_type


def settings(db: Session, tenant_id) -> dict:
    row = db.get(AppSetting, (tenant_id, "vendite"))
    v = dict(row.value or {}) if row else {}
    series = {k: [x for x in (v.get("series") or {}).get(k, []) if SERIES_RE.match(x.get("code", ""))] for k in KEYS}
    defaults = {k: (v.get("default_series") or {}).get(k, "") for k in KEYS}
    formats = {k: {sc: f for sc, f in ((v.get("formats") or {}).get(k) or {}).items() if valid_format(f)} for k in KEYS}
    return {"bollo_mode": docs.stamp_mode(db, tenant_id), "series": series, "formats": formats,
            "default_series": {k: d if d in [x["code"] for x in series[k]] else "" for k, d in defaults.items()}}


# Formato del numero stampato e scritto nell'XML (campo Numero, max 20 caratteri), per tipo e sezionale.
# Segnaposto: {n} numero, {s} sezionale, {aaaa} anno, {aa} anno a due cifre. Esempio: "FPR {n}/{aa}" → FPR 3/26.
FORMAT_RE = re.compile(r"^[A-Za-z0-9 /._{}-]{1,30}$")


def valid_format(f: str | None) -> bool:
    return bool(f) and "{n}" in f and bool(FORMAT_RE.match(f)) and len(render(f, 9999999, "AAAAAAAAAA", 2026)) <= 20


def render(fmt: str, number: int, series: str, year: int) -> str:
    return (fmt.replace("{n}", str(number)).replace("{s}", series).replace("{aaaa}", str(year))
            .replace("{aa}", f"{year % 100:02d}")).strip()


def number_label(db: Session, d: Document) -> str | None:
    """Numero da mostrare: quello col formato scelto, altrimenti n/sezionale/anno."""
    if not d.number:
        return None
    fmt = (settings(db, d.tenant_id)["formats"].get(key_of(d.doc_type)) or {}).get(d.series or "")
    return render(fmt, d.number, d.series or "", d.year) if fmt else f"{d.number}" + (f"/{d.series}" if d.series else "") + f"/{d.year}"


def display_number(db: Session, d: Document, cfg: dict | None = None) -> str | None:
    """Numero del documento come si stampa e va nell'XML (senza formato: n/sezionale)."""
    if not d.number:
        return None
    fmt = ((cfg or settings(db, d.tenant_id))["formats"].get(key_of(d.doc_type)) or {}).get(d.series or "")
    return render(fmt, d.number, d.series or "", d.year) if fmt else f"{d.number}" + (f"/{d.series}" if d.series else "")


def save_settings(db: Session, tenant_id, body: dict) -> dict:
    series = {}
    for k in KEYS:
        seen, out = set(), []
        for x in (body.get("series") or {}).get(k, []):
            code = (x.get("code") or "").strip().upper()
            if not SERIES_RE.match(code):
                raise docs.fail(f"Sezionale «{code}»: solo lettere e numeri, al massimo 10 caratteri")
            if code in seen:
                raise docs.fail(f"Sezionale {code} ripetuto")
            seen.add(code)
            out.append({"code": code, "description": (x.get("description") or "").strip()[:60]})
        series[k] = out
    row = db.get(AppSetting, (tenant_id, "vendite"))
    if row is None:
        row = AppSetting(tenant_id=tenant_id, key="vendite", value={})
        db.add(row)
    formats = {}
    for k in KEYS:
        out = {}
        for sc, f in ((body.get("formats") or {}).get(k) or {}).items():
            f = (f or "").strip()
            if not f:
                continue
            if not valid_format(f):
                raise docs.fail(f"Formato del numero «{f}» non valido: deve contenere {{n}} e restare entro 20 caratteri")
            out[(sc or "").strip().upper()] = f
        formats[k] = out
    row.value = {**(row.value or {}), "series": series, "formats": formats, "default_series": body.get("default_series") or {}}
    if body.get("bollo_mode") in docs.STAMP_MODES:
        b = db.get(AppSetting, (tenant_id, "bollo"))
        if b is None:
            db.add(AppSetting(tenant_id=tenant_id, key="bollo", value={"mode": body["bollo_mode"]}))
        else:
            b.value = {"mode": body["bollo_mode"]}
    db.flush()
    return settings(db, tenant_id)


def check_series(db: Session, tenant_id, doc_type: str, series: str | None) -> str:
    """Sezionale scelto sul documento (vuoto = quello predefinito per il tipo)."""
    k = key_of(doc_type)
    if k not in KEYS:
        return ""
    st = settings(db, tenant_id)
    series = (series if series is not None else st["default_series"][k]) or ""
    series = series.strip().upper()
    if series and series not in [x["code"] for x in st["series"][k]]:
        raise docs.fail(f"Sezionale {series} non previsto per {KEYS[k][0].lower()}: aggiungilo in Impostazioni › Documenti di vendita")
    return series


def _used(db: Session, company_id, key: str, year: int, series: str):
    return select(Document).where(Document.direction == "vendita", Document.company_id == company_id,
                                  Document.doc_type.in_(KEYS[key][1]), Document.year == year, Document.series == series,
                                  Document.number.is_not(None))


def counters(db: Session, tenant_id, company_id, year: int) -> list[dict]:
    """Numerazioni dell'anno: una riga per tipo e sezionale (anche quelli non ancora usati)."""
    tenant_series = {}
    rows = {(n.doc_type, n.series): n.last_number for n in db.scalars(select(Numbering).where(
        Numbering.company_id == company_id, Numbering.year == year, Numbering.doc_type.in_(list(KEYS))))}
    used = db.execute(select(Document.doc_type, Document.series, func.max(Document.number), func.count()).where(
        Document.direction == "vendita", Document.company_id == company_id, Document.year == year,
        Document.number.is_not(None), Document.status != "annullato").group_by(Document.doc_type, Document.series)).all()
    for t, s_, mx, cnt in used:
        k = key_of(t)
        if k in KEYS:
            cur = tenant_series.setdefault((k, s_), [0, 0])
            cur[0], cur[1] = max(cur[0], mx), cur[1] + cnt
    out = []
    keys = set(rows) | set(tenant_series)
    for k, lst in settings(db, tenant_id)["series"].items():
        keys.add((k, ""))
        keys.update((k, x["code"]) for x in lst)
    for k, s_ in sorted(keys, key=lambda x: (list(KEYS).index(x[0]) if x[0] in KEYS else 9, x[1])):
        if k not in KEYS:
            continue
        mx, cnt = tenant_series.get((k, s_), [0, 0])
        last = rows.get((k, s_), 0)
        out.append({"key": k, "label": KEYS[k][0], "series": s_, "year": year, "last_number": last, "next_number": last + 1,
                    "max_used": mx, "documents": cnt})
    return out


def set_next(db: Session, tenant_id, company_id, key: str, year: int, series: str, next_number: int) -> list[str]:
    """Imposta il prossimo numero. Restituisce le note sui documenti annullati che hanno perso il numero."""
    if key not in KEYS:
        raise docs.fail("Numerazione sconosciuta")
    if next_number < 1:
        raise docs.fail("Il numero deve essere almeno 1")
    clash = db.scalars(_used(db, company_id, key, year, series).where(Document.number >= next_number)
                       .order_by(Document.number)).all()
    valid = [d for d in clash if d.status != "annullato"]
    if valid:
        nums = ", ".join(str(d.number) for d in valid[:8]) + ("…" if len(valid) > 8 else "")
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "code": "numeri_usati", "message": f"I numeri {nums} sono già usati da {KEYS[key][0].lower()} valide del {year}"
            f"{' (sezionale ' + series + ')' if series else ''}. Per ripartire da {next_number} annulla prima quei documenti "
            f"(se erano prove), oppure scegli un numero dopo il {valid[-1].number}."})
    notes = []
    if clash:
        from app.fatturapa.models import EInvoice
        sent = set(db.scalars(select(EInvoice.document_id).where(EInvoice.document_id.in_([d.id for d in clash]),
                                                                  EInvoice.filename.is_not(None))))
        for d in clash:
            if d.id in sent:
                raise docs.fail(f"Il documento annullato n. {d.number} è stato trasmesso a SDI: il suo numero non si può riusare")
        for d in clash:
            notes.append(f"{docs.DOC_TYPES.get(d.doc_type, (d.doc_type,))[0]} annullato n. {d.number} senza numero")
            d.number = None
    docs.next_number(db, tenant_id, company_id, key, year, series)  # crea la riga se manca (e la blocca)
    row = db.scalar(select(Numbering).where(Numbering.company_id == company_id, Numbering.doc_type == key,
                                            Numbering.year == year, Numbering.series == series).with_for_update())
    row.last_number = next_number - 1
    db.flush()
    return notes


def manual_number(db: Session, d: Document, number: int) -> int:
    """Numero scelto a mano alla conferma: libero e coerente con le date dei documenti vicini."""
    if number < 1:
        raise docs.fail("Il numero deve essere almeno 1")
    key = key_of(d.doc_type)
    base = _used(db, d.company_id, key, d.year, d.series).where(Document.status != "annullato", Document.id != d.id)
    if db.scalar(base.where(Document.number == number).limit(1)):
        raise docs.fail(f"Il numero {number} è già usato nel {d.year}{' (sezionale ' + d.series + ')' if d.series else ''}")
    if key == "FT":
        prev = db.scalar(base.where(Document.number < number).order_by(Document.number.desc()).limit(1))
        nxt = db.scalar(base.where(Document.number > number).order_by(Document.number).limit(1))
        if prev and prev.doc_date > d.doc_date:
            raise docs.fail(f"Con il numero {number} la data non può precedere quella della n. {prev.number} "
                            f"({prev.doc_date.strftime('%d/%m/%Y')})")
        if nxt and nxt.doc_date < d.doc_date:
            raise docs.fail(f"Con il numero {number} la data non può seguire quella della n. {nxt.number} "
                            f"({nxt.doc_date.strftime('%d/%m/%Y')})")
    docs.next_number(db, d.tenant_id, d.company_id, key, d.year, d.series)
    row = db.scalar(select(Numbering).where(Numbering.company_id == d.company_id, Numbering.doc_type == key,
                                            Numbering.year == d.year, Numbering.series == d.series).with_for_update())
    row.last_number = max(row.last_number - 1, number)  # next_number l'aveva già incrementato
    return number
