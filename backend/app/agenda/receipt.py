"""Ricevuta NON fiscale dell'appuntamento, nel formato neutro dell'agent (print.text / rt.nonfiscal).

Si stampa sulla stampante termica da 80 mm (ESC/POS) o sul registratore telematico come documento non fiscale.
Prima dell'incasso vale come promemoria/preconto; dopo l'incasso riporta il pagato, i punti fedeltà e il prossimo appuntamento.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agenda import service as svc
from app.agenda.models import AgendaService, AgendaStaff, Appointment
from app.anagrafiche.models import Party


def euro(v) -> str:
    return f"{Decimal(str(v)):.2f}".replace(".", ",")


def build(db: Session, tenant_id, appt: Appointment, with_marketing: bool = True) -> dict:
    from app.core.models import Company
    co = db.scalar(select(Company).order_by(Company.name))
    party = db.get(Party, appt.party_id) if appt.party_id else None
    staff = {s.id: s.first_name for s in db.scalars(select(AgendaStaff))}
    paid = appt.status == "pagato"
    L: list[dict] = [{"text": svc.salon_name(db, tenant_id), "align": "center", "bold": True, "size": 2}]
    if co:
        addr = " ".join(x for x in [co.address, co.zip_code, co.city] if x)
        if addr:
            L.append({"text": addr, "align": "center"})
        if co.phone:
            L.append({"text": f"Tel. {co.phone}", "align": "center"})
    title = "RICEVUTA NON FISCALE" if paid else "PROMEMORIA APPUNTAMENTO"
    L += [{"type": "line"}, {"text": title, "align": "center", "bold": True}, {"type": "line"}]
    if party:
        L.append({"text": f"Cliente: {party.name}"})
    L.append({"text": f"{svc.fmt_date(appt.starts_at).capitalize()} ore {svc.fmt_time(appt.starts_at)}"})
    L.append({"type": "feed"})
    total = Decimal(0)
    for it in appt.items:
        name = db.get(AgendaService, it.service_id).name
        who = staff.get(it.staff_id)
        L.append({"text": f"{name}{' (' + who + ')' if who else ''}", "right": euro(it.price)})
        total += it.price
    doc = None
    if appt.document_id:
        from app.documenti.models import Document
        doc = db.get(Document, appt.document_id)
        for ln in doc.lines:
            if ln.item_id:  # prodotti venduti insieme ai servizi
                amount = Decimal(str(ln.unit_price_gross or 0)) * Decimal(str(ln.quantity))
                L.append({"text": f"{Decimal(str(ln.quantity)).normalize()} x {ln.description}", "right": euro(amount)})
        total = Decimal(str(doc.total))
    L += [{"type": "line"}, {"text": "TOTALE" if paid else "TOTALE PREVISTO", "right": euro(total), "bold": True}]
    if doc is not None:
        rt = (doc.fiscal or {}).get("rt") or {}
        what = "Fattura" if doc.doc_type == "FTI" else "Scontrino fiscale"
        L.append({"text": f"{what} n. {rt.get('number') or doc.number} del {doc.doc_date.strftime('%d/%m/%Y')}"})
    if party and with_marketing:
        from app.marketing import loyalty
        if loyalty.settings(db, tenant_id).enabled:
            pts = loyalty.balance(db, party.id)
            L += [{"type": "feed"}, {"text": f"I tuoi punti fedeltà: {pts}", "bold": True}]
            nxt = loyalty.next_reward(db, tenant_id, pts)
            if nxt:
                L.append({"text": f"Premio disponibile: {nxt['name']}" if nxt["reached"]
                          else f"Ancora {nxt['missing']} punti per: {nxt['name']}"})
            card = loyalty.card(db, party.id)
            if card:
                L.append({"type": "barcode", "data": card.number, "label": f"Tessera {card.number}", "align": "center"})
    if party:
        nxt_appt = db.scalar(select(Appointment).where(Appointment.party_id == party.id, Appointment.starts_at > appt.starts_at,
                                                       Appointment.status.in_(("prenotato", "confermato")))
                             .order_by(Appointment.starts_at))
        if nxt_appt:
            L += [{"type": "feed"}, {"text": "Prossimo appuntamento:", "bold": True},
                  {"text": f"{svc.fmt_date(nxt_appt.starts_at).capitalize()} ore {svc.fmt_time(nxt_appt.starts_at)}"}]
    L += [{"type": "feed"}, {"text": "Prenota dal telefono:", "align": "center"},
          {"type": "qr", "data": svc.public_link(db, tenant_id), "label": svc.public_link(db, tenant_id), "align": "center"},
          {"type": "line"}, {"text": "DOCUMENTO NON FISCALE", "align": "center"},
          {"text": datetime.now(svc.TZ).strftime("%d/%m/%Y %H:%M"), "align": "center"}, {"type": "cut"}]
    return {"lines": L}
