"""Tentata vendita: unico punto che scrive furgoni, giri, carichi, documenti dell'agente, incassi e rientri.

Regole principali
- Il furgone è un magazzino: il carico è un trasferimento dal magazzino centrale, le vendite scaricano il furgone,
  i resi lo caricano. Quello che "deve esserci" sul furgone è quindi la sua giacenza.
- I documenti dell'agente usano il sezionale del furgone (es. DDT 12/A3): i dispositivi senza rete non si sovrappongono.
  Ogni invio porta un `client_uuid`: se arriva due volte (coda offline) si restituisce quello già registrato.
- Il fido si controlla sul dispositivo con i dati scaricati a inizio giro; al server il documento arriva già deciso
  (l'eventuale avviso resta nel documento).
- Rientro: l'agente dichiara km, contanti e assegni; il magazziniere conta (alla cieca se previsto), ogni differenza
  va motivata; le differenze diventano rettifiche del furgone, poi il rimanente rientra in centrale o resta sul mezzo.
"""

import base64
import binascii
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.anagrafiche import price_engine, pricing
from app.anagrafiche.models import (
    Item,
    ItemBarcode,
    ItemVariant,
    Party,
    PartyAddress,
    PaymentTerm,
    VatRate,
)
from app.core import media
from app.core.models import Company, User, Warehouse
from app.documenti import service as docs
from app.documenti import vendite_service as sales
from app.documenti.models import Document, DocumentLine
from app.magazzino import service as stock
from app.magazzino.models import Lot, Serial, StockBalance, StockMovement
from app.scadenzario import service as due
from app.scadenzario.models import FinancialAccount, Installment
from app.tentata.models import Van, VanCollection, VanCount, VanRouteStop, VanTrip

CENT = Decimal("0.01")
DOC_KINDS = {"DDT": "DDT", "FTI": "Fattura", "ORC": "Ordine", "NC": "Reso / nota di credito"}
METHODS = {  # metodo → (etichetta, ModalitaPagamento FatturaPA, tipo di conto)
    "contanti": ("Contanti", "MP01", "cassa"),
    "assegno": ("Assegno", "MP02", "cassa"),
    "pos": ("POS / carta", "MP08", "banca"),
}
REASONS = {
    "rotto": "Merce rotta o danneggiata",
    "scaduto": "Scaduta o deteriorata",
    "ammanco": "Ammanco",
    "errore_carico": "Errore di carico",
    "errore_vendita": "Errore nei documenti",
    "omaggio": "Omaggio non registrato",
    "altro": "Altro",
}
STATUSES = {"preparazione": "In preparazione", "in_corso": "In giro", "rientro": "Rientrato, da verificare", "chiuso": "Chiuso"}
WEEKDAYS = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
MAX_SIGNATURE = 600 * 1024


def fail(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, msg)


def _q(v) -> Decimal:
    return Decimal(str(v)) if v not in (None, "") else Decimal(0)


def nq(v) -> str:
    """Quantità leggibile: 30 e non 3E+1, 1.5 e non 1.5000."""
    d = Decimal(v or 0).normalize()
    return format(d, "f")


def _uuid(v) -> uuid.UUID | None:
    if not v:
        return None
    try:
        return uuid.UUID(str(v))
    except ValueError:
        raise fail("Identificativo non valido") from None


def doc_label(d: Document) -> str:
    num = f"{d.number}/{d.series}" if d.series else str(d.number or "")
    return f"{sales.SALES_TYPES.get(d.doc_type, d.doc_type)} {num}".strip()


def variant_label(v: ItemVariant | None) -> str | None:
    if v is None:
        return None
    return " · ".join(x for x in (v.size, v.color, v.format) if x) or v.code


# ====================================================================== furgoni


def create_van(db: Session, tenant_id, data: dict) -> Van:
    """Nuovo furgone con il suo magazzino (creato qui se non indicato)."""
    company = db.scalar(select(Company).order_by(Company.name))
    series = (data.get("series") or "").strip().upper()
    code = (data.get("code") or "").strip().upper()
    if not series or not series.isalnum():
        raise fail("Il sezionale deve contenere solo lettere e numeri (es. A1)")
    if db.scalar(select(Van.id).where(Van.series == series)):
        raise fail(f"Il sezionale {series} è già usato da un altro furgone")
    if db.scalar(select(Van.id).where(Van.code == code)):
        raise fail(f"Il codice {code} è già usato da un altro furgone")
    wh_id = data.get("warehouse_id")
    if wh_id:
        if db.scalar(select(Van.id).where(Van.warehouse_id == wh_id)):
            raise fail("Questo magazzino è già il magazzino di un altro furgone")
    else:
        wh = Warehouse(tenant_id=tenant_id, company_id=company.id, code=f"FUR-{code}"[:20], name=f"Furgone {data['name']}"[:120])
        db.add(wh)
        db.flush()
        wh_id = wh.id
    van = Van(tenant_id=tenant_id, code=code, series=series, warehouse_id=wh_id, allowed_docs=["DDT", "FTI", "ORC", "NC"])
    db.add(van)
    update_van(db, van, data)
    return van


def update_van(db: Session, van: Van, data: dict) -> None:
    for f in ("name", "vehicle", "plate", "notes"):
        if f in data:
            setattr(van, f, (data[f] or None) if f != "name" else data[f])
    if data.get("plate"):
        van.plate = data["plate"].replace(" ", "").upper()
    if "home_warehouse_id" in data:
        if str(data["home_warehouse_id"]) == str(van.warehouse_id):
            raise fail("Il magazzino di carico deve essere diverso da quello del furgone")
        van.home_warehouse_id = data["home_warehouse_id"]
    if "agent_id" in data:
        agent = db.get(User, data["agent_id"]) if data["agent_id"] else None
        if data["agent_id"] and (agent is None or agent.role not in ("agente", "vendite", "amministratore")):
            raise fail("L'agente deve essere un utente con ruolo «agente»")
        van.agent_id = agent.id if agent else None
    if "max_discount" in data:
        van.max_discount = max(Decimal(0), min(Decimal(100), _q(data["max_discount"])))
    if "allowed_docs" in data:
        docs_ok = [d for d in data["allowed_docs"] if d in DOC_KINDS]
        if not docs_ok:
            raise fail("Scegli almeno un tipo di documento")
        van.allowed_docs = docs_ok
    for f in ("cash_account_id",):
        if f in data:
            setattr(van, f, data[f] or None)
    for f in ("blind_count", "active"):
        if f in data and data[f] is not None:
            setattr(van, f, bool(data[f]))
    if not van.home_warehouse_id:
        van.home_warehouse_id = db.scalar(select(Warehouse.id).where(Warehouse.id != van.warehouse_id).order_by(Warehouse.code))
    db.flush()


def van_stock(db: Session, van: Van) -> list[dict]:
    """Merce sul furgone (giacenza del suo magazzino), per articolo, variante e lotto."""
    rows = db.execute(
        select(StockBalance, Item, ItemVariant, Lot)
        .join(Item, Item.id == StockBalance.item_id)
        .outerjoin(ItemVariant, ItemVariant.id == StockBalance.variant_id)
        .outerjoin(Lot, Lot.id == StockBalance.lot_id)
        .where(StockBalance.warehouse_id == van.warehouse_id, StockBalance.on_hand != 0)
        .order_by(Item.code, ItemVariant.code, Lot.expiry_date)
    ).all()
    return [{"item_id": str(it.id), "code": it.code, "description": it.description, "unit": it.unit,
             "variant_id": str(v.id) if v else None, "variant": variant_label(v),
             "lot_id": str(lot.id) if lot else None, "lot_number": lot.lot_number if lot else None,
             "expiry_date": lot.expiry_date.isoformat() if lot and lot.expiry_date else None,
             "quantity": nq(Decimal(b.on_hand)), "serial_managed": it.serial_managed}
            for b, it, v, lot in rows]


# ====================================================================== giro clienti abituale e giri del giorno


def route_for(db: Session, van: Van, weekday: int | None = None) -> list[VanRouteStop]:
    q = select(VanRouteStop).where(VanRouteStop.van_id == van.id).order_by(VanRouteStop.position)
    rows = db.scalars(q).all()
    return [r for r in rows if weekday is None or weekday in (r.weekdays or [])]


def save_route(db: Session, van: Van, stops: list[dict]) -> None:
    """Sostituisce il giro clienti del furgone: [{party_id, weekdays: [0..6], notes}] nell'ordine di visita."""
    existing = {str(r.party_id): r for r in db.scalars(select(VanRouteStop).where(VanRouteStop.van_id == van.id))}
    seen = set()
    for pos, s in enumerate(stops):
        pid = str(s["party_id"])
        if pid in seen:
            continue
        seen.add(pid)
        party = db.get(Party, _uuid(pid))
        if party is None or not party.is_customer:
            raise fail("Nel giro ci sono soggetti che non sono clienti")
        r = existing.get(pid) or VanRouteStop(tenant_id=van.tenant_id, van_id=van.id, party_id=party.id)
        r.weekdays = sorted({int(w) for w in s.get("weekdays") or [] if 0 <= int(w) <= 6})
        r.position, r.notes = pos, (s.get("notes") or None)
        db.add(r)
    for pid, r in existing.items():
        if pid not in seen:
            db.delete(r)
    db.flush()


def _orders_to_deliver(db: Session, party_ids: list) -> dict:
    """Ordini cliente aperti per cliente: {party_id: [Document]}."""
    out = defaultdict(list)
    if not party_ids:
        return out
    for d in db.scalars(select(Document).where(Document.doc_type == "ORC", Document.status == "confermato",
                                               Document.party_id.in_(party_ids)).order_by(Document.doc_date)):
        out[d.party_id].append(d)
    return out


def create_trip(db: Session, van: Van, trip_date: date, user_id, party_ids: list | None = None) -> VanTrip:
    """Giro del giorno: i clienti del giro abituale per quel giorno della settimana, più quelli con ordini da consegnare."""
    if db.scalar(select(VanTrip.id).where(VanTrip.van_id == van.id, VanTrip.trip_date == trip_date)):
        raise fail(f"Il giro del {trip_date.strftime('%d/%m/%Y')} per questo furgone esiste già", status.HTTP_409_CONFLICT)
    open_trip = db.scalar(select(VanTrip).where(VanTrip.van_id == van.id, VanTrip.status.in_(("in_corso", "rientro"))))
    if open_trip is not None:
        raise fail(f"Il giro del {open_trip.trip_date.strftime('%d/%m/%Y')} non è ancora chiuso: verifica prima il rientro",
                   status.HTTP_409_CONFLICT)
    if party_ids is None:
        stops = [{"party_id": str(r.party_id), "notes": r.notes, "visited": False} for r in route_for(db, van, trip_date.weekday())]
        planned = {s["party_id"] for s in stops}
        route_ids = [r.party_id for r in route_for(db, van)]
        for pid in _orders_to_deliver(db, route_ids):
            if str(pid) not in planned:
                stops.append({"party_id": str(pid), "notes": "Ordine da consegnare", "visited": False})
    else:
        stops = [{"party_id": str(p), "notes": None, "visited": False} for p in dict.fromkeys(str(x) for x in party_ids)]
    trip = VanTrip(tenant_id=van.tenant_id, van_id=van.id, agent_id=van.agent_id, trip_date=trip_date, status="preparazione",
                   stops=stops, load_operations=[], cash_declared={}, signatures={})
    db.add(trip)
    db.flush()
    return trip


def set_stops(db: Session, trip: VanTrip, stops: list[dict]) -> None:
    if trip.status in ("rientro", "chiuso"):
        raise fail("Il giro è già rientrato")
    visited = {s["party_id"]: s.get("visited", False) for s in trip.stops or []}
    out = []
    for s in stops:
        pid = str(s["party_id"])
        party = db.get(Party, _uuid(pid))
        if party is None or not party.is_customer:
            raise fail("Nel giro ci sono soggetti che non sono clienti")
        if any(x["party_id"] == pid for x in out):
            continue
        out.append({"party_id": pid, "notes": s.get("notes") or None, "visited": bool(visited.get(pid, False))})
    trip.stops = out


# ====================================================================== carico


def load_proposal(db: Session, trip: VanTrip) -> list[dict]:
    """Proposta di carico: il massimo tra ordini da consegnare ai clienti del giro e media venduta negli ultimi giri,
    meno quello che è già sul furgone."""
    van = db.get(Van, trip.van_id)
    party_ids = [_uuid(s["party_id"]) for s in trip.stops or []]
    need: dict = defaultdict(lambda: {"orders": Decimal(0), "avg": Decimal(0)})
    for orders in _orders_to_deliver(db, party_ids).values():
        for d in orders:
            for ln in d.lines:
                if ln.item_id and ln.quantity:
                    need[(ln.item_id, ln.variant_id)]["orders"] += max(Decimal(0), _q(ln.quantity) - _q(ln.qty_processed))
    past = db.scalars(select(VanTrip.id).where(VanTrip.van_id == van.id, VanTrip.id != trip.id, VanTrip.trip_date < trip.trip_date)
                      .order_by(VanTrip.trip_date.desc()).limit(8)).all()
    if past:
        rows = db.execute(
            select(DocumentLine.item_id, DocumentLine.variant_id, Document.doc_type, func.sum(DocumentLine.quantity))
            .join(Document, Document.id == DocumentLine.document_id)
            .where(Document.van_trip_id.in_(past), Document.status != "annullato", Document.doc_type.in_(("DDT", "FTI")),
                   DocumentLine.item_id.is_not(None))
            .group_by(DocumentLine.item_id, DocumentLine.variant_id, Document.doc_type)).all()
        for item_id, variant_id, _t, qty in rows:
            need[(item_id, variant_id)]["avg"] += Decimal(qty) / len(past)
    on_van: dict = defaultdict(Decimal)
    central: dict = defaultdict(Decimal)
    for b in db.scalars(select(StockBalance).where(StockBalance.warehouse_id.in_((van.warehouse_id, van.home_warehouse_id)))):
        target = on_van if b.warehouse_id == van.warehouse_id else central
        target[(b.item_id, b.variant_id)] += Decimal(b.on_hand) - (Decimal(b.reserved or 0) if target is central else 0)
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_([k[0] for k in need])))} if need else {}
    variants = {v.id: v for v in db.scalars(select(ItemVariant).where(ItemVariant.id.in_([k[1] for k in need if k[1]])))} \
        if any(k[1] for k in need) else {}
    out = []
    for key, n in need.items():
        it = items.get(key[0])
        if it is None or not it.stock_managed or it.is_kit:
            continue
        avg = n["avg"].quantize(Decimal(1), ROUND_HALF_UP) if n["avg"] else Decimal(0)
        target = max(n["orders"], avg)
        proposed = max(Decimal(0), target - on_van[key])
        out.append({"item_id": str(it.id), "code": it.code, "description": it.description, "unit": it.unit,
                    "variant_id": str(key[1]) if key[1] else None, "variant": variant_label(variants.get(key[1])),
                    "orders": nq(n["orders"]), "avg_sold": str(n["avg"].quantize(Decimal("0.1"))),
                    "on_van": nq(on_van[key]), "available": nq(central[key]),
                    "proposed": nq(proposed), "lot_managed": it.lot_managed, "serial_managed": it.serial_managed})
    out.sort(key=lambda r: (Decimal(r["proposed"]) == 0, r["code"]))
    return out


def load(db: Session, trip: VanTrip, user_id, lines: list[dict]) -> uuid.UUID:
    """Carico (anche più volte): trasferimento dal magazzino centrale al furgone, con lotti FEFO e matricole."""
    if trip.status not in ("preparazione", "in_corso"):
        raise fail("Il giro è già rientrato: non si può più caricare")
    van = db.get(Van, trip.van_id)
    lines = [ln for ln in lines if _q(ln.get("quantity")) > 0]
    if not lines:
        raise fail("Indica almeno un articolo da caricare")
    c = stock.Ctx(tenant_id=trip.tenant_id, user_id=user_id, reference=f"Carico furgone {van.code} del {trip.trip_date.strftime('%d/%m/%Y')}",
                  document_type="CARICO", document_id=trip.id)
    for ln in lines:
        stock.transfer(db, c, from_wh=van.home_warehouse_id, to_wh=van.warehouse_id, item_id=_uuid(ln["item_id"]),
                       qty=_q(ln["quantity"]), variant_id=_uuid(ln.get("variant_id")),
                       lot_number=(ln.get("lot_number") or None), serials=ln.get("serials") or None)
    trip.load_operations = [*(trip.load_operations or []),
                            {"operation_id": str(c.operation_id), "at": datetime.now().astimezone().isoformat(), "user_id": str(user_id) if user_id else None}]
    return c.operation_id


def load_lines(db: Session, trip: VanTrip) -> list[dict]:
    """Righe caricate sul furgone nel giro (entrate nel magazzino del furgone dalle operazioni di carico)."""
    van = db.get(Van, trip.van_id)
    ops = [_uuid(o["operation_id"]) for o in trip.load_operations or []]
    if not ops:
        return []
    rows = db.execute(
        select(StockMovement.item_id, StockMovement.variant_id, StockMovement.lot_id, func.sum(StockMovement.quantity))
        .where(StockMovement.operation_id.in_(ops), StockMovement.warehouse_id == van.warehouse_id)
        .group_by(StockMovement.item_id, StockMovement.variant_id, StockMovement.lot_id)).all()
    return describe_rows(db, [(r[0], r[1], r[2], Decimal(r[3])) for r in rows])


def describe_rows(db: Session, rows: list[tuple]) -> list[dict]:
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_({r[0] for r in rows})))} if rows else {}
    vids = {r[1] for r in rows if r[1]}
    lids = {r[2] for r in rows if r[2]}
    variants = {v.id: v for v in db.scalars(select(ItemVariant).where(ItemVariant.id.in_(vids)))} if vids else {}
    lots = {lt.id: lt for lt in db.scalars(select(Lot).where(Lot.id.in_(lids)))} if lids else {}
    out = []
    for item_id, variant_id, lot_id, qty in rows:
        it, v, lot = items[item_id], variants.get(variant_id), lots.get(lot_id)
        out.append({"item_id": str(it.id), "code": it.code, "description": it.description, "unit": it.unit,
                    "variant_id": str(variant_id) if variant_id else None, "variant": variant_label(v),
                    "lot_id": str(lot_id) if lot_id else None, "lot_number": lot.lot_number if lot else None,
                    "expiry_date": lot.expiry_date.isoformat() if lot and lot.expiry_date else None,
                    "quantity": nq(Decimal(qty))})
    out.sort(key=lambda r: (r["code"], r["variant"] or "", r["lot_number"] or ""))
    return out


def start(db: Session, trip: VanTrip, km_start: int | None) -> None:
    if trip.status != "preparazione":
        raise fail("Il giro è già partito")
    trip.status, trip.started_at = "in_corso", datetime.now().astimezone()
    if km_start is not None:
        trip.km_start = int(km_start)


# ====================================================================== pacchetto per il dispositivo (senza rete)


def _credit(db: Session, party: Party) -> dict:
    st = sales.credit_status(db, party)
    exp = st["exposure"]
    return {"limit": str(st["limit"]) if st["limit"] is not None else None, "policy": party.credit_policy,
            "exposure": str(exp["total"]), "available": str(st["available"]) if st["available"] is not None else None,
            "overdue": str(exp["overdue"]), "overdue_days": exp["overdue_days"], "unpaid": exp["unpaid"],
            "insolvent": st["insolvent"], "over": st["over"]}


def _open_installments(db: Session, party_id) -> list[dict]:
    today = date.today()
    out = []
    for i in db.scalars(select(Installment).where(Installment.party_id == party_id, Installment.direction == "attiva",
                                                  Installment.status != "pagata").order_by(Installment.due_date)):
        res = due.residual(i)
        if res <= 0:
            continue
        out.append({"id": str(i.id), "document_id": str(i.document_id) if i.document_id else None, "description": i.description,
                    "due_date": i.due_date.isoformat(), "residual": str(res), "overdue": i.due_date < today, "unpaid": i.unpaid})
    return out


def party_out(p: Party, addr: PartyAddress | None = None) -> dict:
    street = " ".join(x for x in (p.address, p.street_number) if x)
    return {"id": str(p.id), "code": p.code, "name": p.name, "person_type": p.person_type, "vat_number": p.vat_number,
            "tax_code": p.tax_code, "address": street or None, "zip_code": p.zip_code, "city": p.city, "province": p.province,
            "phone": p.phone, "mobile": p.mobile, "email": p.email, "pec": p.pec,
            "payment_term_id": str(p.payment_term_id) if p.payment_term_id else None,
            "destination": {"id": str(addr.id), "label": addr.label, "address": addr.address, "city": addr.city,
                            "province": addr.province} if addr else None}


def package(db: Session, trip: VanTrip) -> dict:
    """Tutto quello che serve al dispositivo dell'agente per lavorare anche senza rete per l'intero giro."""
    van = db.get(Van, trip.van_id)
    party_ids = [_uuid(s["party_id"]) for s in trip.stops or []]
    parties = {p.id: p for p in db.scalars(select(Party).where(Party.id.in_(party_ids)))} if party_ids else {}
    defaults = {a.party_id: a for a in db.scalars(select(PartyAddress).where(PartyAddress.party_id.in_(party_ids), PartyAddress.is_default))} \
        if party_ids else {}
    orders = _orders_to_deliver(db, party_ids)
    customers = []
    for s in trip.stops or []:
        p = parties.get(_uuid(s["party_id"]))
        if p is None:
            continue
        exempt = db.get(VatRate, p.vat_rate_id) if p.vat_rate_id else None
        customers.append({**party_out(p, defaults.get(p.id)), "stop_notes": s.get("notes"), "visited": s.get("visited", False),
                          "vat_rate": str(exempt.rate) if exempt else None,
                          "credit": _credit(db, p), "installments": _open_installments(db, p.id),
                          "orders": [{"id": str(d.id), "label": doc_label(d), "date": d.doc_date.isoformat(),
                                      "lines": [{"id": str(ln.id), "item_id": str(ln.item_id) if ln.item_id else None,
                                                 "variant_id": str(ln.variant_id) if ln.variant_id else None,
                                                 "description": ln.description, "open": nq(max(Decimal(0), _q(ln.quantity) - _q(ln.qty_processed))),
                                                 "unit_price": str(ln.unit_price), "discount": str(ln.discount1) if ln.discount1 else None}
                                                for ln in d.lines if ln.item_id and _q(ln.quantity) > _q(ln.qty_processed)]}
                                     for d in orders.get(p.id, [])]})
    on_van = van_stock(db, van)
    item_ids = {_uuid(r["item_id"]) for r in on_van}
    for olist in orders.values():
        for d in olist:
            item_ids |= {ln.item_id for ln in d.lines if ln.item_id}
    items_db = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_(item_ids)))} if item_ids else {}
    variants: dict = defaultdict(list)
    for v in db.scalars(select(ItemVariant).where(ItemVariant.item_id.in_(item_ids), ItemVariant.active)) if item_ids else []:
        variants[v.item_id].append(v)
    barcodes: dict = defaultdict(list)
    for b in db.scalars(select(ItemBarcode).where(ItemBarcode.item_id.in_(item_ids))) if item_ids else []:
        barcodes[b.item_id].append({"barcode": b.barcode, "variant_id": str(b.variant_id) if b.variant_id else None,
                                    "quantity": nq(Decimal(b.quantity))})
    vats = {v.id: v for v in db.scalars(select(VatRate))}
    stock_by_item: dict = defaultdict(list)
    for r in on_van:
        stock_by_item[r["item_id"]].append({k: r[k] for k in ("variant_id", "variant", "lot_number", "expiry_date", "quantity")})
    items, prices = [], {}
    keyed: list[tuple[Item, ItemVariant | None]] = []
    for it in sorted(items_db.values(), key=lambda i: i.code):
        vat = vats.get(it.vat_rate_id)
        items.append({"id": str(it.id), "code": it.code, "description": it.description, "unit": it.unit,
                      "vat_rate_id": str(it.vat_rate_id) if it.vat_rate_id else None, "vat_rate": str(vat.rate) if vat else "22",
                      "stock_managed": it.stock_managed, "lot_managed": it.lot_managed, "serial_managed": it.serial_managed,
                      "has_variants": it.has_variants, "image_url": it.image_url,
                      "variants": [{"id": str(v.id), "label": variant_label(v)} for v in variants.get(it.id, [])],
                      "barcodes": barcodes.get(it.id, []), "stock": stock_by_item.get(str(it.id), [])})
        keyed += [(it, v) for v in variants.get(it.id, [])] if it.has_variants else [(it, None)]
    for p in [None, *parties.values()]:
        table = {}
        for it, v in keyed:
            r = price_engine.resolve_price(db, it, p, Decimal(1), trip.trip_date, v.id if v else None)
            if r.unit_price is not None:
                table[f"{it.id}:{v.id if v else ''}"] = {"price": str(r.unit_price.quantize(Decimal("0.0001"))), "source": r.source_label}
        prices[str(p.id) if p else "_"] = table
    terms = [{"id": str(t.id), "code": t.code, "description": t.description, "method": t.method}
             for t in db.scalars(select(PaymentTerm).where(PaymentTerm.active).order_by(PaymentTerm.code))]
    company = db.scalar(select(Company).order_by(Company.name))
    agent = db.get(User, trip.agent_id) if trip.agent_id else None
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "trip": trip_out(db, trip, brief=True),
        "van": van_out(db, van),
        "agent": {"id": str(agent.id), "name": agent.full_name} if agent else None,
        "company": {"name": company.name, "vat_number": company.vat_number, "address": company.address, "zip_code": company.zip_code,
                    "city": company.city, "province": company.province, "phone": company.phone, "email": company.email,
                    "logo_url": media.urls(company.logo_file)["url"] if company.logo_file else None} if company else None,
        "customers": customers, "items": items, "prices": prices, "payment_terms": terms,
        # quello già arrivato in ufficio per questo giro (anche da un altro dispositivo)
        "documents": [doc_out(db, d) for d in trip_documents(db, trip)],
        "collections": [collection_out(db, c) for c in db.scalars(select(VanCollection).where(VanCollection.trip_id == trip.id)
                                                                     .order_by(VanCollection.collected_at))],
        "vat_rates": [{"id": str(v.id), "rate": str(v.rate), "nature": v.nature, "description": v.description} for v in vats.values() if v.active],
        "methods": [{"value": k, "label": v[0]} for k, v in METHODS.items()],
        "doc_kinds": [{"value": k, "label": DOC_KINDS[k]} for k in van.allowed_docs if k in DOC_KINDS],
    }


# ====================================================================== documenti dell'agente


def _signature(data: dict | None) -> dict:
    """Firma del cliente (PNG in data URL) salvata come file; restituisce i dati della consegna."""
    if not data:
        return {}
    out = {k: data.get(k) for k in ("signer_name", "signed_at", "lat", "lon", "accuracy") if data.get(k) not in (None, "")}
    png = data.get("signature_png") or ""
    if png:
        raw = png.split(",", 1)[1] if png.startswith("data:") else png
        try:
            blob = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            raise fail("Firma non valida") from None
        if len(blob) > MAX_SIGNATURE or not blob.startswith(b"\x89PNG"):
            raise fail("Firma non valida")
        out["signature_file"] = media.save_file(blob, "firma.png")
    return out


def _min_price_check(db: Session, van: Van, party: Party, ln: DocumentLine, on: date) -> None:
    """L'agente non può scendere sotto il prezzo del motore prezzi meno lo sconto massimo del furgone."""
    if not ln.item_id:
        return
    item = db.get(Item, ln.item_id)
    ref = price_engine.resolve_price(db, item, party, Decimal(1), on, ln.variant_id).unit_price
    if ref is None:
        return
    floor = (ref * (100 - Decimal(van.max_discount or 0)) / 100).quantize(Decimal("0.0001"), ROUND_HALF_UP)
    net = pricing.cascade(_q(ln.unit_price), ln.discount1)
    if net + Decimal("0.005") < floor:
        raise fail(f"{item.code}: prezzo {net:.2f} € sotto il minimo consentito all'agente ({floor:.2f} €)")


def create_document(db: Session, trip: VanTrip, user: User, body: dict, is_agent: bool) -> tuple[Document, bool]:
    """Documento emesso dall'agente (DDT, fattura, ordine, reso). Restituisce (documento, già registrato)."""
    client_uuid = _uuid(body.get("client_uuid"))
    if client_uuid:
        prev = db.scalar(select(Document).where(Document.client_uuid == client_uuid))
        if prev is not None:
            return prev, True
    if trip.status not in ("in_corso", "rientro"):
        raise fail("Il giro non è in corso: documento non accettato" if trip.status == "preparazione"
                   else "Il giro è già chiuso: documento non accettato", status.HTTP_409_CONFLICT)
    van = db.get(Van, trip.van_id)
    kind = body.get("doc_type")
    if kind not in van.allowed_docs:
        raise fail(f"Il furgone non può emettere «{DOC_KINDS.get(kind, kind)}»")
    party = db.get(Party, _uuid(body.get("party_id")))
    if party is None or not party.is_customer:
        raise fail("Cliente non valido")
    lines = [ln for ln in body.get("lines") or [] if _q(ln.get("quantity")) > 0]
    if not lines:
        raise fail("Il documento non ha righe")
    raw_date = body.get("doc_date") or body.get("date")
    when = date.fromisoformat(str(raw_date)[:10]) if raw_date else trip.trip_date
    company = db.scalar(select(Company).order_by(Company.name))
    d = Document(tenant_id=trip.tenant_id, company_id=company.id, direction="vendita", doc_type=kind, series=van.series,
                 doc_date=when, year=when.year, party_id=party.id, warehouse_id=van.home_warehouse_id if kind == "ORC" else van.warehouse_id,
                 moves_stock=kind != "ORC", payment_term_id=_uuid(body.get("payment_term_id")) or party.payment_term_id,
                 destination_id=_uuid(body.get("destination_id")), client_uuid=client_uuid, van_trip_id=trip.id,
                 created_by=user.id, notes=(body.get("notes") or None), reference=(body.get("reference") or None),
                 transport={"causale": "Reso" if kind == "NC" else "Vendita", "porto": "Franco", "a_cura": "Mittente",
                            "vettore": f"Furgone {van.plate or van.code}", "inizio": datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M")}
                 if kind == "DDT" else {}, attachment_ids=[], print_options={}, fiscal={}, delivery={})
    db.add(d)
    vats = {v.id: v for v in db.scalars(select(VatRate))}
    default_vat = next((v for v in vats.values() if v.code == "22"), None)
    for n, ln in enumerate(lines, start=1):
        item = db.get(Item, _uuid(ln.get("item_id"))) if ln.get("item_id") else None
        if ln.get("item_id") and item is None:
            raise fail("Articolo inesistente")
        disc = _q(ln.get("discount")) or None
        if disc is not None and is_agent and kind != "NC" and disc > Decimal(van.max_discount or 0):
            raise fail(f"Sconto {disc}% oltre il massimo consentito ({nq(van.max_discount)}%)")
        price = _q(ln.get("unit_price"))
        if price < 0:
            raise fail(f"Riga {n}: prezzo non valido")
        vat_id = party.vat_rate_id or (item.vat_rate_id if item else None) or _uuid(ln.get("vat_rate_id")) or (default_vat.id if default_vat else None)
        origin = _uuid(ln.get("origin_line_id"))
        if origin is not None:
            o = db.get(DocumentLine, origin)
            odoc = db.get(Document, o.document_id) if o else None
            if odoc is None or odoc.party_id != party.id or odoc.doc_type != "ORC":
                raise fail("Riga d'ordine non valida")
        row = DocumentLine(tenant_id=trip.tenant_id, line_no=n, item_id=item.id if item else None, variant_id=_uuid(ln.get("variant_id")),
                           description=(ln.get("description") or (item.description if item else ""))[:500] or "Riga",
                           unit=item.unit if item else None, quantity=_q(ln["quantity"]), unit_price=price, discount1=disc,
                           vat_rate_id=vat_id, lot_number=(ln.get("lot_number") or "").strip().upper() or None,
                           serials=[s.strip().upper() for s in ln.get("serials") or [] if s and s.strip()], origin_line_id=origin,
                           price_source=(ln.get("price_source") or "Agente")[:60], notes=(ln.get("notes") or None))
        d.lines.append(row)
        if is_agent and kind != "NC":
            _min_price_check(db, van, party, row, when)
    db.flush()
    if any(ln.origin_line_id for ln in d.lines):
        from app.documenti.models import DocumentLink
        for oid in {db.get(DocumentLine, ln.origin_line_id).document_id for ln in d.lines if ln.origin_line_id}:
            db.add(DocumentLink(tenant_id=trip.tenant_id, from_id=oid, to_id=d.id))
    docs.recompute(db, d)
    warning = sales.confirm_sale(db, d, user.id, force=True)
    delivery = _signature(body.get("delivery"))
    if warning or body.get("credit_warning"):
        delivery["credit_warning"] = body.get("credit_warning") or warning
    delivery.setdefault("sent", [])
    d.delivery = delivery
    _visit(trip, party.id)
    coll = body.get("collection")
    if coll and _q(coll.get("amount")) > 0:
        collect(db, trip, user, {**coll, "party_id": str(party.id), "document_id": str(d.id),
                                 "client_uuid": coll.get("client_uuid") or (str(uuid.uuid5(client_uuid, "incasso")) if client_uuid else None),
                                 "signature": body.get("delivery")}, stored_signature=delivery)
    db.flush()
    return d, False


def _visit(trip: VanTrip, party_id) -> None:
    stops = [dict(s) for s in trip.stops or []]  # copia: modificare il JSON in place non verrebbe salvato
    for s in stops:
        if s["party_id"] == str(party_id):
            s["visited"] = True
            break
    else:
        stops.append({"party_id": str(party_id), "notes": "Fuori giro", "visited": True})
    trip.stops = stops


def mark_visit(db: Session, trip: VanTrip, party_id, notes: str | None) -> None:
    """Visita senza documento (cliente chiuso, nessun ordine…): resta traccia nel giro."""
    stops = [dict(s) for s in trip.stops or []]
    for s in stops:
        if s["party_id"] == str(party_id):
            s["visited"] = True
            if notes:
                s["visit_notes"] = notes[:200]
    trip.stops = stops


# ====================================================================== incassi


def _account_for(db: Session, van: Van, method: str):
    kind = METHODS[method][2]
    if kind == "cassa" and van.cash_account_id:
        return van.cash_account_id
    return db.scalar(select(FinancialAccount.id).where(FinancialAccount.kind == kind, FinancialAccount.active)
                     .order_by(FinancialAccount.is_default.desc(), FinancialAccount.name)) \
        or (due.default_account(db).id if due.default_account(db) else None)


def collect(db: Session, trip: VanTrip, user: User, body: dict, stored_signature: dict | None = None) -> tuple[VanCollection, bool]:
    """Incasso sul posto: chiude le rate del documento indicato o, se no, quelle più vecchie del cliente.
    Quello che avanza resta come acconto da abbinare in ufficio."""
    client_uuid = _uuid(body.get("client_uuid"))
    if client_uuid:
        prev = db.scalar(select(VanCollection).where(VanCollection.client_uuid == client_uuid))
        if prev is not None:
            return prev, True
    if trip.status not in ("in_corso", "rientro"):
        raise fail("Il giro non è in corso: incasso non accettato", status.HTTP_409_CONFLICT)
    method = body.get("method")
    if method not in METHODS:
        raise fail("Metodo di incasso non valido")
    amount = _q(body.get("amount")).quantize(CENT)
    if amount <= 0:
        raise fail("Importo non valido")
    party = db.get(Party, _uuid(body.get("party_id")))
    if party is None:
        raise fail("Cliente non valido")
    van = db.get(Van, trip.van_id)
    doc_id = _uuid(body.get("document_id"))
    wanted = [_uuid(x) for x in body.get("installment_ids") or []]
    q = select(Installment).where(Installment.party_id == party.id, Installment.direction == "attiva", Installment.status != "pagata")
    if wanted:
        q = q.where(Installment.id.in_(wanted))
    elif doc_id:
        q = q.where(Installment.document_id == doc_id)
    rows = db.scalars(q.order_by(Installment.due_date, Installment.seq)).all()
    left, payment_ids = amount, []
    account = _account_for(db, van, method)
    when = trip.trip_date
    for i in rows:
        res = due.residual(i)
        if left <= 0 or res <= 0:
            continue
        take = min(left, res)
        p = due.pay(db, i, pay_date=max(when, i.issue_date), amount=take, account_id=account, method=METHODS[method][1],
                    notes=f"Incasso agente · giro {trip.trip_date.strftime('%d/%m/%Y')}" + (f" · {body['check_info']}" if body.get("check_info") else ""),
                    user_id=user.id)
        payment_ids.append(p.id)
        left -= take
    sig = stored_signature if stored_signature is not None else _signature(body.get("signature"))
    c = VanCollection(tenant_id=trip.tenant_id, trip_id=trip.id, party_id=party.id, document_id=doc_id, method=method, amount=amount,
                      check_info=(body.get("check_info") or None), payment_ids=payment_ids, unallocated=left,
                      signature={k: sig[k] for k in ("signer_name", "signature_file", "signed_at") if k in (sig or {})},
                      client_uuid=client_uuid, created_by=user.id)
    db.add(c)
    _visit(trip, party.id)
    db.flush()
    return c, False


# ====================================================================== rientro e verifica del magazziniere


def declare_return(db: Session, trip: VanTrip, user: User, body: dict) -> None:
    """L'agente rientra: km, contanti e assegni da versare, eventuale conta sua. La giacenza del furgone diventa "attesa"."""
    if trip.status == "rientro":
        raise fail("Rientro già dichiarato: attende la verifica del magazziniere", status.HTTP_409_CONFLICT)
    if trip.status != "in_corso":
        raise fail("Il giro non è in corso")
    van = db.get(Van, trip.van_id)
    if body.get("km_end") is not None:
        km = int(body["km_end"])
        if trip.km_start is not None and km < trip.km_start:
            raise fail("I km di rientro sono inferiori a quelli di partenza")
        trip.km_end = km
    trip.cash_declared = {m: str(_q(body.get("cash", {}).get(m)).quantize(CENT)) for m in METHODS if body.get("cash", {}).get(m) not in (None, "")}
    trip.return_notes = body.get("notes") or None
    agent_counts = {(str(c.get("item_id")), str(c.get("variant_id") or ""), str(c.get("lot_id") or "")): _q(c.get("quantity"))
                    for c in body.get("counts") or []}
    for old in db.scalars(select(VanCount).where(VanCount.trip_id == trip.id)):
        db.delete(old)
    for b in db.scalars(select(StockBalance).where(StockBalance.warehouse_id == van.warehouse_id, StockBalance.on_hand != 0)):
        key = (str(b.item_id), str(b.variant_id or ""), str(b.lot_id or ""))
        db.add(VanCount(tenant_id=trip.tenant_id, trip_id=trip.id, item_id=b.item_id, variant_id=b.variant_id, lot_id=b.lot_id,
                        expected=Decimal(b.on_hand), agent_count=agent_counts.get(key), counted=Decimal(0)))
    sig = _signature(body.get("signature"))
    if sig:
        trip.signatures = {**(trip.signatures or {}), "agente": sig}
    trip.status, trip.returned_at = "rientro", datetime.now().astimezone()
    db.flush()


def refresh_expected(db: Session, trip: VanTrip) -> None:
    """L'atteso è la giacenza del furgone: si riallinea finché il giro non è chiuso, perché documenti rimasti
    nella coda del dispositivo possono arrivare anche dopo la dichiarazione di rientro."""
    if trip.status != "rientro":
        return
    van = db.get(Van, trip.van_id)
    current = {(b.item_id, b.variant_id, b.lot_id): Decimal(b.on_hand)
               for b in db.scalars(select(StockBalance).where(StockBalance.warehouse_id == van.warehouse_id, StockBalance.on_hand != 0))}
    rows = {(c.item_id, c.variant_id, c.lot_id): c for c in db.scalars(select(VanCount).where(VanCount.trip_id == trip.id))}
    for key, c in rows.items():
        c.expected = current.pop(key, Decimal(0))
    for (item_id, variant_id, lot_id), qty in current.items():
        db.add(VanCount(tenant_id=trip.tenant_id, trip_id=trip.id, item_id=item_id, variant_id=variant_id, lot_id=lot_id,
                        expected=qty, counted=Decimal(0)))
    db.flush()


def return_rows(db: Session, trip: VanTrip, reveal: bool) -> list[dict]:
    """Righe della conta. Con `reveal` falso (conta alla cieca in corso) le quantità attese non si vedono."""
    refresh_expected(db, trip)
    rows = db.scalars(select(VanCount).where(VanCount.trip_id == trip.id)).all()
    desc = {(r["item_id"], r["variant_id"], r["lot_id"]): r
            for r in describe_rows(db, [(c.item_id, c.variant_id, c.lot_id, c.expected) for c in rows])}
    out = []
    for c in rows:
        base = desc[(str(c.item_id), str(c.variant_id) if c.variant_id else None, str(c.lot_id) if c.lot_id else None)]
        diff = Decimal(c.counted) - Decimal(c.expected)
        out.append({**{k: base[k] for k in ("item_id", "code", "description", "unit", "variant_id", "variant", "lot_id",
                                              "lot_number", "expiry_date")},
                    "id": str(c.id), "expected": nq(Decimal(c.expected)) if reveal else None,
                    "agent_count": nq(Decimal(c.agent_count)) if c.agent_count is not None and reveal else None,
                    "counted": nq(Decimal(c.counted)) if trip.status == "chiuso" else None,
                    "difference": nq(diff) if trip.status == "chiuso" else None,
                    "reason": c.reason, "reason_label": REASONS.get(c.reason or ""), "notes": c.notes})
    out.sort(key=lambda r: (r["code"], r["variant"] or "", r["lot_number"] or ""))
    return out


def check_return(db: Session, trip: VanTrip, user: User, body: dict) -> dict:
    """Verifica del magazziniere: conte, motivi delle differenze, firme; rettifiche e rientro della merce. Chiude il giro.

    Restituisce le differenze trovate (per mostrarle subito dopo una conta alla cieca)."""
    if trip.status != "rientro":
        raise fail("Il giro non è in attesa di verifica" if trip.status != "chiuso" else "Il giro è già chiuso", status.HTTP_409_CONFLICT)
    van = db.get(Van, trip.van_id)
    refresh_expected(db, trip)
    counts = {str(c["id"]): c for c in body.get("counts") or [] if c.get("id")}
    rows = db.scalars(select(VanCount).where(VanCount.trip_id == trip.id)).all()
    missing = [r for r in rows if str(r.id) not in counts]
    if missing:
        raise fail(f"Mancano le conte di {len(missing)} righe")
    remaining = body.get("remaining") or "rientra"
    if remaining not in ("rientra", "resta"):
        raise fail("Indica se la merce rientra in magazzino o resta sul furgone")
    differences = []
    for r in rows:
        c = counts[str(r.id)]
        if c.get("counted") in (None, ""):
            raise fail("Conta tutte le righe (0 se l'articolo non c'è)")
        r.counted = _q(c["counted"])
        if r.counted < 0:
            raise fail("Quantità contata non valida")
        r.reason, r.notes = (c.get("reason") or None), (c.get("notes") or None)
        if r.counted != Decimal(r.expected):
            differences.append(r)
    # merce trovata sul furgone ma non attesa
    for x in body.get("extra") or []:
        qty = _q(x.get("counted"))
        if qty <= 0:
            continue
        item = db.get(Item, _uuid(x.get("item_id")))
        if item is None:
            raise fail("Articolo inesistente tra la merce in più")
        lot = stock.get_or_create_lot(db, trip.tenant_id, item, x["lot_number"]) if item.lot_managed and x.get("lot_number") else None
        if item.lot_managed and lot is None:
            raise fail(f"{item.code}: indica il lotto della merce in più")
        r = VanCount(tenant_id=trip.tenant_id, trip_id=trip.id, item_id=item.id, variant_id=_uuid(x.get("variant_id")),
                     lot_id=lot.id if lot else None, expected=Decimal(0), counted=qty, reason=x.get("reason") or None,
                     notes=x.get("notes") or None)
        db.add(r)
        rows.append(r)
        differences.append(r)
    unexplained = [r for r in differences if r.reason not in REASONS]
    if unexplained:  # con la conta alla cieca è qui che il magazziniere scopre le righe che non tornano
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "code": "differenze_da_motivare", "message": f"{len(unexplained)} differenze: indica il motivo di ciascuna",
            "differences": [{"id": str(r.id), "expected": nq(Decimal(r.expected)), "counted": nq(Decimal(r.counted))}
                            for r in unexplained]})
    sig_agent, sig_wh = _signature((body.get("signatures") or {}).get("agente")), _signature((body.get("signatures") or {}).get("magazziniere"))
    if not sig_wh.get("signature_file") or not sig_wh.get("signer_name"):
        raise fail("Serve la firma del magazziniere con il nome")
    if not sig_agent and not (trip.signatures or {}).get("agente"):
        raise fail("Serve la firma dell'agente")
    db.flush()
    # 1. differenze → rettifiche sul furgone, con il motivo nel riferimento
    if differences:
        c = stock.Ctx(tenant_id=trip.tenant_id, user_id=user.id, document_type="RIENTRO", document_id=trip.id,
                      reference=f"Rientro furgone {van.code} del {trip.trip_date.strftime('%d/%m/%Y')}")
        for r in differences:
            diff = Decimal(r.counted) - Decimal(r.expected)
            item = db.get(Item, r.item_id)
            lot = db.get(Lot, r.lot_id) if r.lot_id else None
            if item.serial_managed:
                _adjust_serials(db, c, van, item, r, diff)
                continue
            c.reference = f"Rientro furgone {van.code} del {trip.trip_date.strftime('%d/%m/%Y')}: {REASONS.get(r.reason, 'differenza')}"
            stock.move(db, c, warehouse_id=van.warehouse_id, item=item, qty=diff, reason="rettifica", variant_id=r.variant_id,
                       lot=lot, check_negative=False)
        trip.adjust_operation_id = c.operation_id
    # 2. il rimanente rientra in magazzino centrale (o resta sul furgone per il giorno dopo)
    if remaining == "rientra":
        c = stock.Ctx(tenant_id=trip.tenant_id, user_id=user.id, document_type="RIENTRO", document_id=trip.id,
                      reference=f"Rientro merce furgone {van.code} del {trip.trip_date.strftime('%d/%m/%Y')}")
        for r in rows:
            qty = Decimal(r.counted)
            if qty <= 0:
                continue
            item = db.get(Item, r.item_id)
            lot = db.get(Lot, r.lot_id) if r.lot_id else None
            serials = None
            if item.serial_managed:
                serials = [s.serial_number for s in db.scalars(select(Serial).where(
                    Serial.item_id == item.id, Serial.warehouse_id == van.warehouse_id, Serial.status == "disponibile",
                    Serial.variant_id.is_(None) if r.variant_id is None else Serial.variant_id == r.variant_id)
                    .order_by(Serial.serial_number).limit(int(qty)))]
                if len(serials) != int(qty):
                    raise fail(f"{item.code}: matricole sul furgone non sufficienti")
            stock.transfer(db, c, from_wh=van.warehouse_id, to_wh=van.home_warehouse_id, item_id=item.id, qty=qty,
                           variant_id=r.variant_id, lot_number=lot.lot_number if lot else None, serials=serials)
        trip.return_operation_id = c.operation_id
    trip.remaining = remaining
    trip.signatures = {**(trip.signatures or {}), **({"agente": sig_agent} if sig_agent else {}), "magazziniere": sig_wh}
    trip.checked_by, trip.checked_at, trip.status = user.id, datetime.now().astimezone(), "chiuso"
    db.flush()
    return {"differences": len(differences)}


def _adjust_serials(db: Session, c: stock.Ctx, van: Van, item: Item, r: VanCount, diff: Decimal) -> None:
    """Matricole: in meno = dismesse (prima le ultime caricate); in più non si inventano, vanno caricate a mano."""
    if diff > 0:
        raise fail(f"{item.code}: le matricole in più vanno caricate a mano indicando i numeri")
    sers = db.scalars(select(Serial).where(Serial.item_id == item.id, Serial.warehouse_id == van.warehouse_id,
                                           Serial.status == "disponibile").order_by(Serial.serial_number.desc()).limit(int(-diff))).all()
    for s in sers:
        s.status, s.warehouse_id = "dismesso", None
        stock.move(db, c, warehouse_id=van.warehouse_id, item=item, qty=Decimal(-1), reason="rettifica", variant_id=r.variant_id,
                   serial=s, check_negative=False)


# ====================================================================== riepiloghi


def trip_documents(db: Session, trip: VanTrip) -> list[Document]:
    return db.scalars(select(Document).where(Document.van_trip_id == trip.id).order_by(Document.created_at)).all()


def cash_summary(db: Session, trip: VanTrip) -> list[dict]:
    got: dict = defaultdict(Decimal)
    for c in db.scalars(select(VanCollection).where(VanCollection.trip_id == trip.id)):
        got[c.method] += Decimal(c.amount)
    out = []
    for m, (label, _code, _kind) in METHODS.items():
        declared = trip.cash_declared.get(m) if trip.cash_declared else None
        exp = got.get(m, Decimal(0))
        if not exp and declared in (None, "0.00"):
            continue
        out.append({"method": m, "label": label, "collected": str(exp.quantize(CENT)), "declared": declared,
                    "difference": str((_q(declared) - exp).quantize(CENT)) if declared is not None else None,
                    "to_deposit": m != "pos"})
    return out


def summary(db: Session, trip: VanTrip) -> dict:
    docs_ = trip_documents(db, trip)
    by_type: dict = defaultdict(lambda: {"count": 0, "taxable": Decimal(0), "total": Decimal(0)})
    for d in docs_:
        if d.status == "annullato":
            continue
        t = by_type[d.doc_type]
        t["count"] += 1
        sign = -1 if d.doc_type == "NC" else 1
        t["taxable"] += sign * Decimal(d.taxable_total)
        t["total"] += sign * Decimal(d.total)
    sold = sum((v["taxable"] for k, v in by_type.items() if k in ("DDT", "FTI", "NC")), Decimal(0))
    stops = trip.stops or []
    return {
        "documents": {k: {"label": DOC_KINDS.get(k, k), "count": v["count"], "taxable": str(v["taxable"].quantize(CENT)),
                          "total": str(v["total"].quantize(CENT))} for k, v in by_type.items()},
        "sold_taxable": str(sold.quantize(CENT)),
        "cash": cash_summary(db, trip),
        "visits": {"planned": len(stops), "visited": sum(1 for s in stops if s.get("visited"))},
        "km": (trip.km_end - trip.km_start) if trip.km_end is not None and trip.km_start is not None else None,
    }


def van_out(db: Session, v: Van) -> dict:
    agent = db.get(User, v.agent_id) if v.agent_id else None
    wh = db.get(Warehouse, v.warehouse_id)
    home = db.get(Warehouse, v.home_warehouse_id) if v.home_warehouse_id else None
    return {"id": str(v.id), "code": v.code, "name": v.name, "vehicle": v.vehicle, "plate": v.plate, "series": v.series,
            "warehouse_id": str(v.warehouse_id), "warehouse": wh.name if wh else None,
            "home_warehouse_id": str(v.home_warehouse_id) if v.home_warehouse_id else None, "home_warehouse": home.name if home else None,
            "agent_id": str(v.agent_id) if v.agent_id else None, "agent": agent.full_name if agent else None,
            "max_discount": nq(Decimal(v.max_discount or 0)), "allowed_docs": v.allowed_docs,
            "cash_account_id": str(v.cash_account_id) if v.cash_account_id else None, "blind_count": v.blind_count,
            "active": v.active, "notes": v.notes}


def trip_out(db: Session, t: VanTrip, brief: bool = False) -> dict:
    van = db.get(Van, t.van_id)
    agent = db.get(User, t.agent_id) if t.agent_id else None
    out = {"id": str(t.id), "van_id": str(t.van_id), "van": f"{van.code} · {van.name}", "series": van.series,
           "agent": agent.full_name if agent else None, "agent_id": str(t.agent_id) if t.agent_id else None,
           "trip_date": t.trip_date.isoformat(), "weekday": WEEKDAYS[t.trip_date.weekday()], "status": t.status,
           "status_label": STATUSES[t.status], "km_start": t.km_start, "km_end": t.km_end,
           "started_at": t.started_at.isoformat() if t.started_at else None, "returned_at": t.returned_at.isoformat() if t.returned_at else None,
           "checked_at": t.checked_at.isoformat() if t.checked_at else None, "remaining": t.remaining,
           "blind_count": van.blind_count, "loads": len(t.load_operations or [])}
    if brief:
        return out
    party_ids = [_uuid(s["party_id"]) for s in t.stops or []]
    parties = {str(p.id): p for p in db.scalars(select(Party).where(Party.id.in_(party_ids)))} if party_ids else {}
    checker = db.get(User, t.checked_by) if t.checked_by else None
    out.update({
        "stops": [{**s, "name": parties[s["party_id"]].name if s["party_id"] in parties else "?",
                   "city": parties[s["party_id"]].city if s["party_id"] in parties else None} for s in t.stops or []],
        "cash_declared": t.cash_declared or {}, "return_notes": t.return_notes, "checked_by": checker.full_name if checker else None,
        "signatures": {k: {**v, "url": f"/api/media/file/{v['signature_file']}" if v.get("signature_file") else None}
                       for k, v in (t.signatures or {}).items()},
        "summary": summary(db, t),
    })
    return out


def doc_out(db: Session, d: Document) -> dict:
    party = db.get(Party, d.party_id)
    dl = d.delivery or {}
    return {"id": str(d.id), "doc_type": d.doc_type, "label": doc_label(d), "number": d.number, "series": d.series,
            "doc_date": d.doc_date.isoformat(), "party_id": str(d.party_id), "party": party.name if party else None,
            "status": d.status, "taxable_total": str(d.taxable_total), "total": str(d.total),
            "signed": bool(dl.get("signature_file")), "signer_name": dl.get("signer_name"),
            "signature_url": f"/api/media/file/{dl['signature_file']}" if dl.get("signature_file") else None,
            "signed_at": dl.get("signed_at"), "credit_warning": dl.get("credit_warning"), "sent": dl.get("sent", []),
            "client_uuid": str(d.client_uuid) if d.client_uuid else None,
            "created_at": d.created_at.isoformat() if d.created_at else None}


def collection_out(db: Session, c: VanCollection) -> dict:
    party = db.get(Party, c.party_id)
    d = db.get(Document, c.document_id) if c.document_id else None
    return {"id": str(c.id), "party_id": str(c.party_id), "party": party.name if party else None, "method": c.method,
            "method_label": METHODS[c.method][0], "amount": str(c.amount), "unallocated": str(c.unallocated),
            "check_info": c.check_info, "document": doc_label(d) if d else None,
            "collected_at": c.collected_at.isoformat() if c.collected_at else None,
            "client_uuid": str(c.client_uuid) if c.client_uuid else None}


def recent_trip_start(today: date | None = None) -> date:
    return (today or date.today()) - timedelta(days=60)
