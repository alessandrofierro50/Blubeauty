"""Dati demo dell'agenda: operatori, cabine, listino con tempi di posa, clienti, appuntamenti e messaggi.

Si caricano col ruolo dell'applicazione e il tenant impostato (RLS), come farebbe un utente.
"""

import random
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal as D

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agenda import service as svc
from app.agenda.models import (AgendaResource, AgendaService, AgendaServiceCategory, AgendaServiceResource, AgendaServiceStaff,
                               AgendaStaff, Appointment, TechnicalCard)
from app.marketing import service as msg
from app.marketing.models import Campaign, Message

SALONE = {
    "slug": "aurora",
    "staff": [("Giulia", "Rossi", "#2340a8"), ("Marco", "Bianchi", "#0b8a6e"), ("Sara", "Verdi", "#c2255c")],
    "resources": [("Cabina 1", "cabina")],
    "services": [
        # categoria, nome, prezzo, durata, (inizio posa, posa), operatori (indici), risorsa, richiamo
        ("Capelli", "Shampoo e piega", "22", 30, None, [0, 1], False, None),
        ("Capelli", "Taglio donna", "35", 45, None, [0, 1], False, None),
        ("Capelli", "Taglio uomo", "20", 30, None, [1], False, 30),
        ("Capelli", "Colore + piega", "65", 80, (20, 35), [0], False, 35),
        ("Capelli", "Balayage", "120", 150, (45, 40), [0], False, 70),
        ("Estetica", "Manicure semipermanente", "30", 50, None, [2], False, 21),
        ("Estetica", "Pulizia viso", "55", 60, None, [2], True, 45),
        ("Estetica", "Ceretta gambe complete", "28", 40, None, [2], True, 28),
        ("Estetica", "Pressoterapia", "40", 45, None, [2], True, None),
    ],
    "clients": [
        ("Laura", "Esposito", "333 1111111", True), ("Francesca", "Romano", "333 2222222", True),
        ("Chiara", "Colombo", "333 3333333", True), ("Alessia", "Ricci", "333 4444444", True),
        ("Martina", "Gallo", "333 5555555", True), ("Valentina", "Conti", "333 6666666", True),
        ("Giorgia", "De Luca", "333 7777777", True), ("Elena", "Mancini", "333 8888888", False),
        ("Sofia", "Costa", "333 9999999", True), ("Federica", "Giordano", "334 1010101", True),
        ("Silvia", "Rizzo", "334 2020202", True), ("Paola", "Lombardi", "334 3030303", False),
        ("Luca", "Moretti", "334 4040404", True), ("Davide", "Barbieri", "334 5050505", True),
    ],
}

BARBER = {
    "slug": "il-baffo",
    "staff": [("Antonio", "Greco", "#2340a8"), ("Salvatore", "Esposito", "#0b2147")],
    "resources": [],
    "services": [
        ("Barberia", "Taglio uomo", "18", 30, None, [0, 1], False, 30),
        ("Barberia", "Barba", "12", 20, None, [0, 1], False, None),
        ("Barberia", "Taglio + barba", "26", 45, None, [0, 1], False, 30),
    ],
    "clients": [("Luca", "Moretti", "335 1111111", True), ("Davide", "Barbieri", "335 2222222", True),
                ("Marco", "Ferri", "335 3333333", False)],
}


def load_agenda_demo(db: Session, tenant_id: uuid.UUID, kind: str) -> None:
    if db.scalar(select(AgendaStaff.id).limit(1)):
        return
    data = SALONE if kind == "salone" else BARBER
    cfg = svc.settings(db, tenant_id)
    cfg.opening_hours = {d: [["09:00", "19:30"]] for d in ("tue", "wed", "thu", "fri")} | {"sat": [["08:30", "18:00"]]}
    cfg.welcome_text = "Benvenuta! Scegli il servizio e l'orario che preferisci: ti confermiamo su WhatsApp." if kind == "salone" else None
    svc.set_slug(db, tenant_id, data["slug"])
    from app.pos.models import PosDepartment, PosRegister
    cfg.register_id = db.scalar(select(PosRegister.id).limit(1))
    cfg.department_id = db.scalar(select(PosDepartment.id).where(PosDepartment.code == "SERV"))
    ms = msg.settings(db, tenant_id)
    ms.review_url = "https://g.page/r/esempio-salone/review"
    msg.ensure_automations(db, tenant_id)

    staff = []
    for n, (fn, ln, color) in enumerate(data["staff"]):
        st = AgendaStaff(tenant_id=tenant_id, first_name=fn, last_name=ln, color=color, sort_order=n, active=True,
                         bookable_online=True, working_hours={})
        db.add(st)
        staff.append(st)
    res = [AgendaResource(tenant_id=tenant_id, name=nm, kind=k, active=True) for nm, k in data["resources"]]
    db.add_all(res)
    db.flush()
    cats: dict = {}
    services: dict = {}
    for n, (cat, name, price, dur, posa, who, needs_res, recall) in enumerate(data["services"]):
        if cat not in cats:
            cats[cat] = AgendaServiceCategory(tenant_id=tenant_id, name=cat, sort_order=len(cats))
            db.add(cats[cat])
            db.flush()
        x = AgendaService(tenant_id=tenant_id, category_id=cats[cat].id, name=name, price=D(price), duration_min=dur,
                          processing_start_min=posa[0] if posa else None, processing_min=posa[1] if posa else None,
                          bookable_online=True, active=True, sort_order=n, recall_days=recall)
        x.staff_links = [AgendaServiceStaff(tenant_id=tenant_id, staff_id=staff[i].id) for i in who]
        x.resource_links = [AgendaServiceResource(tenant_id=tenant_id, resource_id=r.id) for r in res] if needs_res else []
        db.add(x)
        services[name] = x
    db.flush()

    today = date.today()
    clients = []
    for n, (fn, ln, phone, mk) in enumerate(data["clients"]):
        p = svc.new_client(db, tenant_id, fn, ln, phone, privacy=True, marketing=mk)
        prof = svc.profile(db, tenant_id, p)
        if n in (2, 5):
            prof.birth_date = date(1990, today.month, min(28, today.day + n))
        clients.append(p)
    if kind == "salone":
        fr = clients[1]  # dati per la fattura elettronica
        fr.tax_code, fr.address, fr.zip_code, fr.city, fr.province, fr.sdi_code = (
            "RMNFNC85M41H501D", "Via Appia Nuova 100", "00183", "Roma", "RM", "0000000")
        db.add(TechnicalCard(tenant_id=tenant_id, party_id=clients[0].id, kind="colore", title="Colore abituale",
                             data={"Marca": "Aurora Lab", "Tonalità": "6.3 biondo scuro dorato", "Ossidante": "20 vol", "Posa (min)": "35"},
                             created_by="Giulia"))
        db.add(TechnicalCard(tenant_id=tenant_id, party_id=fr.id, kind="anamnesi", title="Anamnesi pressoterapia",
                             data={"Allergie": "Nessuna", "Controindicazioni": "Nessuna", "Farmaci": "—"}, signed_at=svc.now(),
                             created_by="Sara"))
    db.flush()

    rnd = random.Random(str(tenant_id))
    names = list(services)

    def place(party, service, day: date, hhmm: str, status: str, channel: str = "salone", staff_i: int | None = None):
        x = services[service]
        who = x.staff_links[0].staff_id if staff_i is None else staff[staff_i].id
        a = svc.book(db, tenant_id, party=party, start=svc.at(day, hhmm), items=[{"service_id": x.id, "staff_id": who}],
                     channel=channel, created_by="Demo", check=False)
        a.status = status
        if a.starts_at < svc.now():
            a.created_at = a.starts_at - timedelta(days=rnd.randint(2, 10))
            db.execute(update(Message).where(Message.appointment_id == a.id).values(created_at=a.created_at, status="letto"))
        return a

    if kind == "salone":
        # storico (visite pagate) per statistiche, segmenti e richiami
        for k in range(40):
            d = today - timedelta(days=rnd.randint(3, 120))
            if d.weekday() in (0, 6):
                continue
            p = rnd.choice(clients)
            place(p, rnd.choice(names), d, f"{rnd.randint(9, 17):02d}:{rnd.choice(['00', '30'])}", "pagato",
                  rnd.choice(["salone", "online", "telefono"]))
        # oggi (se il salone è aperto) e i prossimi giorni
        days = [today + timedelta(days=i) for i in range(0, 7)]
        days = [d for d in days if d.weekday() not in (0, 6)]
        if days:
            d0 = days[0]
            place(clients[0], "Colore + piega", d0, "09:00", "confermato", staff_i=0)
            place(clients[3], "Shampoo e piega", d0, "09:30", "confermato", "online", staff_i=0)
            place(clients[2], "Taglio donna", d0, "10:00", "confermato", "telefono", staff_i=1)
            place(clients[1], "Pressoterapia", d0, "11:00", "confermato", staff_i=2)
            place(clients[4], "Manicure semipermanente", d0, "15:00", "confermato", "online", staff_i=2)
            place(clients[5], "Taglio donna", d0, "16:00", "prenotato", staff_i=0)
        for d in days[1:]:
            for _ in range(rnd.randint(2, 4)):
                place(rnd.choice(clients), rnd.choice(names[:6]), d, f"{rnd.randint(9, 17):02d}:{rnd.choice(['00', '30'])}",
                      "confermato", rnd.choice(["online", "online", "telefono", "salone"]))
        # una campagna già inviata
        camp = Campaign(tenant_id=tenant_id, name="Promo autunno colore", segment="tutti", status="bozza",
                        body="Ciao {nome}! 🍂 Questo mese colore + piega a 55 € invece di 65 €. Prenota qui: {link}", created_by="Demo")
        db.add(camp)
        db.flush()
        msg.send_campaign(db, tenant_id, camp, {"salone": svc.salon_name(db, tenant_id), "link": svc.public_link(db, tenant_id)})
        when = svc.now() - timedelta(days=9)
        camp.sent_at = camp.created_at = when
        db.execute(update(Message).where(Message.campaign_id == camp.id).values(created_at=when, status="letto"))
    else:
        days = [today + timedelta(days=i) for i in range(0, 5) if (today + timedelta(days=i)).weekday() not in (0, 6)]
        for d in days:
            place(clients[0], "Taglio + barba", d, "10:00", "confermato", "online", staff_i=0)
    db.flush()
