"""Buoni regalo e pacchetti di sedute: unico punto che scrive `gift_vouchers`, `gift_voucher_moves`, `service_packages`,
`client_packages`, `client_package_uses`.

Regola fiscale (buono «monouso», il caso tipico di un salone: stessi servizi e aliquota): lo scontrino si emette quando si
VENDE il buono o il pacchetto (pos.create_sale). Quando la cliente li usa non si certifica di nuovo: all'incasso
dell'appuntamento le sedute coperte e la parte pagata col buono escono dal totale; lo scontrino si fa solo per la differenza
e, se è tutto coperto, si stampa una ricevuta NON fiscale con il riepilogo (residuo del buono, sedute rimaste).
"""

import secrets
import uuid
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.anagrafiche.models import Party
from app.prepagati.models import ClientPackage, ClientPackageUse, GiftVoucher, GiftVoucherMove, ServicePackage

CENT = Decimal("0.01")
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # senza lettere e cifre che si confondono (0/O, 1/I/L)
REASON_VOUCHER = "Utilizzo di un buono regalo già pagato"
REASON_PACKAGE = "Seduta di un pacchetto già pagato"


def fail(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, msg)


def q(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(CENT, ROUND_HALF_UP)


def today() -> date:
    from app.agenda.service import TZ
    return datetime.now(TZ).date()


def fmt_eur(v) -> str:
    return f"{q(v):.2f}".replace(".", ",")


# ------------------------------------------------------------------------------------------------------------ buoni
def normalize_code(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def _new_code(db: Session) -> str:
    while True:
        raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
        code = f"BR-{raw[:4]}-{raw[4:]}"
        if db.scalar(select(GiftVoucher.id).where(GiftVoucher.code == code)) is None:
            return code


def voucher_state(v: GiftVoucher) -> str:
    if v.status == "attivo" and v.expires_on and v.expires_on < today():
        return "scaduto"
    return v.status


def find_voucher(db: Session, code: str) -> GiftVoucher:
    n = normalize_code(code)
    if len(n) < 6:
        raise fail("Codice del buono non valido")
    for v in db.scalars(select(GiftVoucher).where(func.replace(GiftVoucher.code, "-", "") == n)):
        return v
    raise fail("Buono non trovato: controlla il codice", status.HTTP_404_NOT_FOUND)


def usable_voucher(db: Session, code: str) -> GiftVoucher:
    v = find_voucher(db, code)
    st = voucher_state(v)
    if st == "scaduto":
        raise fail(f"Il buono {v.code} è scaduto il {v.expires_on:%d/%m/%Y}")
    if st != "attivo" or v.balance <= 0:
        raise fail(f"Il buono {v.code} non ha più credito" if st == "esaurito" else f"Il buono {v.code} è annullato")
    return v


def _register(db: Session, tenant_id, register_id):
    from app.agenda.service import settings as agenda_settings
    from app.pos.models import PosRegister
    if register_id:
        reg = db.get(PosRegister, uuid.UUID(str(register_id)))
    else:
        cfg = agenda_settings(db, tenant_id)
        reg = db.get(PosRegister, cfg.register_id) if cfg.register_id else db.scalar(
            select(PosRegister).where(PosRegister.active.is_(True)).order_by(PosRegister.code))
    if reg is None:
        raise fail("Scegli la cassa (Impostazioni del salone › Cassa predefinita)")
    return reg


def _sale(db: Session, tenant_id, user_id, register_id, client_uuid, description: str, amount: Decimal, payments: list[dict],
          party: Party | None, vat_rate_id=None):
    """Scontrino della vendita del buono o del pacchetto (documento commerciale sul registratore)."""
    from app.agenda.service import settings as agenda_settings
    from app.pos import service as pos
    cfg = agenda_settings(db, tenant_id)
    reg = _register(db, tenant_id, register_id)
    pays = [dict(p) for p in payments]
    if len(pays) == 1 and pays[0].get("method") != "contanti":
        pays[0]["amount"] = str(amount)  # carta/bancomat: l'importo esatto
    body = {"client_uuid": str(client_uuid or uuid.uuid4()), "payments": pays, "customer_id": str(party.id) if party else None,
            "lines": [{"description": description[:120], "quantity": "1", "unit_price_gross": str(q(amount)),
                       "vat_rate_id": str(vat_rate_id) if vat_rate_id else None,
                       "department_id": str(cfg.department_id) if cfg.department_id else None, "price_source": "Prepagati"}]}
    return pos.create_sale(db, reg, user_id, body)


def sell_voucher(db: Session, tenant_id, user_id, *, kind: str, amount=None, service_id=None, purchaser_id=None,
                 beneficiary_name: str | None = None, message: str | None = None, months: int | None = 12,
                 payments: list[dict], register_id=None, client_uuid=None) -> tuple[GiftVoucher, object, Decimal]:
    from app.agenda.models import AgendaService
    from app.documenti.models import Document
    svc = None
    if kind == "servizio":
        svc = db.get(AgendaService, uuid.UUID(str(service_id))) if service_id else None
        if svc is None:
            raise fail("Scegli il servizio del buono")
        amount = svc.price
    elif kind != "importo":
        raise fail("Tipo di buono non valido")
    amount = q(amount)
    if amount <= 0 or amount > 5000:
        raise fail("Importo del buono non valido")
    purchaser = db.get(Party, uuid.UUID(str(purchaser_id))) if purchaser_id else None
    if client_uuid:  # doppio clic: stesso buono
        prev = db.scalar(select(Document).where(Document.client_uuid == uuid.UUID(str(client_uuid))))
        if prev is not None:
            v = db.scalar(select(GiftVoucher).where(GiftVoucher.sale_document_id == prev.id))
            if v is not None:
                return v, prev, Decimal(str((prev.fiscal or {}).get("change") or 0))
    code = _new_code(db)
    label = f"Buono regalo {code}" + (f" · {svc.name}" if svc else "")
    d, change, _ = _sale(db, tenant_id, user_id, register_id, client_uuid, label, amount, payments, purchaser,
                         svc.vat_rate_id if svc else None)
    v = GiftVoucher(tenant_id=tenant_id, code=code, public_token=secrets.token_urlsafe(24), kind=kind, service_id=svc.id if svc else None,
                    initial_amount=amount, balance=amount, purchaser_party_id=purchaser.id if purchaser else None,
                    beneficiary_name=(beneficiary_name or "").strip()[:120] or None, message=(message or "").strip()[:300] or None,
                    expires_on=(today() + timedelta(days=round(30.44 * months))) if months else None,
                    sale_document_id=d.id, created_by=user_id)
    db.add(v)
    db.flush()
    db.add(GiftVoucherMove(tenant_id=tenant_id, voucher_id=v.id, kind="emissione", amount=amount, balance_after=amount,
                           document_id=d.id, user_id=user_id, note=label))
    db.flush()
    return v, d, change


def use_voucher(db: Session, v: GiftVoucher, amount: Decimal, *, appointment_id=None, document_id=None, user_id=None) -> None:
    amount = q(amount)
    if amount <= 0:
        return
    if amount > v.balance:
        raise fail(f"Sul buono {v.code} restano solo {fmt_eur(v.balance)} €")
    v.balance = q(v.balance - amount)
    if v.balance == 0:
        v.status = "esaurito"
    db.add(GiftVoucherMove(tenant_id=v.tenant_id, voucher_id=v.id, kind="utilizzo", amount=-amount, balance_after=v.balance,
                           appointment_id=appointment_id, document_id=document_id, user_id=user_id))
    db.flush()


def cancel_voucher(db: Session, v: GiftVoucher, user_id, note: str | None) -> None:
    if v.status == "annullato":
        return
    db.add(GiftVoucherMove(tenant_id=v.tenant_id, voucher_id=v.id, kind="annullo", amount=-v.balance, balance_after=Decimal(0),
                           user_id=user_id, note=(note or "Annullato")[:200]))
    v.balance, v.status = Decimal(0), "annullato"
    db.flush()


def voucher_out(db: Session, v: GiftVoucher, moves: bool = False) -> dict:
    from app.agenda.models import AgendaService
    from app.agenda.service import public_link
    purchaser = db.get(Party, v.purchaser_party_id) if v.purchaser_party_id else None
    svc = db.get(AgendaService, v.service_id) if v.service_id else None
    out = {"id": str(v.id), "code": v.code, "kind": v.kind, "service_id": str(v.service_id) if v.service_id else None,
           "service": svc.name if svc else None, "initial_amount": str(v.initial_amount), "balance": str(v.balance),
           "status": voucher_state(v), "expires_on": v.expires_on.isoformat() if v.expires_on else None,
           "purchaser_id": str(purchaser.id) if purchaser else None, "purchaser": purchaser.name if purchaser else None,
           "beneficiary_name": v.beneficiary_name, "message": v.message, "created_at": v.created_at.isoformat() if v.created_at else None,
           "sale_document_id": str(v.sale_document_id) if v.sale_document_id else None,
           "public_url": f"{public_link(db, v.tenant_id)}/buono/{v.public_token}"}
    if moves:
        out["moves"] = [{"kind": m.kind, "amount": str(m.amount), "balance_after": str(m.balance_after), "note": m.note,
                         "appointment_id": str(m.appointment_id) if m.appointment_id else None,
                         "created_at": m.created_at.isoformat() if m.created_at else None}
                        for m in db.scalars(select(GiftVoucherMove).where(GiftVoucherMove.voucher_id == v.id).order_by(GiftVoucherMove.created_at))]
    return out


def voucher_print(db: Session, v: GiftVoucher) -> dict:
    """Il buono stampato sulla termica (formato neutro dell'agent), con il logo e l'intestazione delle ricevute."""
    from app.agenda.models import AgendaService
    from app.pos import receipts
    cfg = receipts.settings(db, v.tenant_id)
    svc = db.get(AgendaService, v.service_id) if v.service_id else None
    L = receipts.header_lines(db, cfg)
    L += [{"type": "feed"}, {"text": "BUONO REGALO", "align": "center", "bold": True, "size": 2}, {"type": "feed"}]
    if v.beneficiary_name:
        L.append({"text": f"Per {v.beneficiary_name}", "align": "center", "bold": True})
    L.append({"text": svc.name if svc else f"Valore {fmt_eur(v.initial_amount)} €", "align": "center", "size": 2})
    if svc:
        L.append({"text": f"(valore {fmt_eur(v.initial_amount)} €)", "align": "center"})
    if v.message:
        L += [{"type": "feed"}, {"text": f"«{v.message}»", "align": "center"}]
    L += [{"type": "feed"}, {"type": "barcode", "data": v.code.replace("-", ""), "label": v.code, "align": "center", "rt_skip": True},
          {"text": f"Codice {v.code}", "align": "center", "bold": True}]
    if v.balance != v.initial_amount:
        L.append({"text": f"Credito residuo {fmt_eur(v.balance)} €", "align": "center"})
    if v.expires_on:
        L.append({"text": f"Valido fino al {v.expires_on:%d/%m/%Y}", "align": "center"})
    L += [{"type": "feed"}, {"text": "Utilizzabile anche in più volte. Non convertibile in denaro.", "align": "center"},
          {"type": "cut"}]
    return {"lines": L}


# --------------------------------------------------------------------------------------------------------- pacchetti
def package_items_ok(db: Session, items: list[dict]) -> list[dict]:
    from app.agenda.models import AgendaService
    out = []
    for it in items or []:
        svc = db.get(AgendaService, uuid.UUID(str(it.get("service_id")))) if it.get("service_id") else None
        n = int(it.get("sessions") or 0)
        if svc is None:
            raise fail("Servizio del pacchetto non trovato")
        if not 1 <= n <= 100:
            raise fail(f"{svc.name}: numero di sedute non valido")
        out.append({"service_id": str(svc.id), "sessions": n})
    if not out:
        raise fail("Aggiungi almeno un servizio al pacchetto")
    return out


def save_package(db: Session, tenant_id, data: dict, package_id=None) -> ServicePackage:
    p = db.get(ServicePackage, package_id) if package_id else None
    if package_id and p is None:
        raise fail("Pacchetto non trovato", status.HTTP_404_NOT_FOUND)
    if p is None:
        p = ServicePackage(tenant_id=tenant_id)
        db.add(p)
    p.name = data["name"].strip()[:120]
    p.price = q(data["price"])
    if p.price <= 0:
        raise fail("Prezzo del pacchetto non valido")
    p.items = package_items_ok(db, data.get("items") or [])
    p.validity_days = data.get("validity_days") or None
    p.min_days = data.get("min_days") or None
    p.description = (data.get("description") or "").strip()[:300] or None
    p.active = bool(data.get("active", True))
    p.sort_order = int(data.get("sort_order") or 0)
    db.flush()
    return p


def package_out(db: Session, p: ServicePackage) -> dict:
    from app.agenda.models import AgendaService
    items = []
    listed = Decimal(0)
    for it in p.items or []:
        svc = db.get(AgendaService, uuid.UUID(it["service_id"]))
        items.append({**it, "name": svc.name if svc else "?", "price": str(svc.price) if svc else None})
        listed += (svc.price if svc else 0) * it["sessions"]
    return {"id": str(p.id), "name": p.name, "price": str(p.price), "items": items, "validity_days": p.validity_days,
            "min_days": p.min_days, "description": p.description, "active": p.active, "sort_order": p.sort_order,
            "list_value": str(q(listed)), "saving": str(q(listed - p.price)) if listed > p.price else "0.00"}


def sell_package(db: Session, tenant_id, user_id, *, package_id, party_id, payments: list[dict], register_id=None,
                 client_uuid=None) -> tuple[ClientPackage, object, Decimal]:
    from app.agenda.models import AgendaService
    from app.documenti.models import Document
    p = db.get(ServicePackage, uuid.UUID(str(package_id)))
    if p is None or not p.active:
        raise fail("Pacchetto non disponibile")
    party = db.get(Party, uuid.UUID(str(party_id))) if party_id else None
    if party is None:
        raise fail("Scegli la cliente")
    if client_uuid:
        prev = db.scalar(select(Document).where(Document.client_uuid == uuid.UUID(str(client_uuid))))
        if prev is not None:
            cp = db.scalar(select(ClientPackage).where(ClientPackage.sale_document_id == prev.id))
            if cp is not None:
                return cp, prev, Decimal(str((prev.fiscal or {}).get("change") or 0))
    first = db.get(AgendaService, uuid.UUID(p.items[0]["service_id"]))
    d, change, _ = _sale(db, tenant_id, user_id, register_id, client_uuid, f"Pacchetto {p.name}", p.price, payments, party,
                         first.vat_rate_id if first else None)
    items = []
    for it in p.items:
        svc = db.get(AgendaService, uuid.UUID(it["service_id"]))
        items.append({"service_id": it["service_id"], "name": svc.name if svc else "?", "sessions": it["sessions"],
                      "price": str(svc.price) if svc else "0"})
    cp = ClientPackage(tenant_id=tenant_id, package_id=p.id, party_id=party.id, name=p.name, price=p.price, items=items,
                       min_days=p.min_days, expires_on=(today() + timedelta(days=p.validity_days)) if p.validity_days else None,
                       sale_document_id=d.id, created_by=user_id)
    db.add(cp)
    db.flush()
    return cp, d, change


def package_state(cp: ClientPackage) -> str:
    if cp.status == "attivo" and cp.expires_on and cp.expires_on < today():
        return "scaduto"
    return cp.status


def used_counts(db: Session, cp_ids: list) -> dict:
    """{(client_package_id, service_id): sedute usate}"""
    out: dict = {}
    if not cp_ids:
        return out
    for u in db.scalars(select(ClientPackageUse).where(ClientPackageUse.client_package_id.in_(cp_ids), ClientPackageUse.cancelled.is_(False))):
        k = (u.client_package_id, str(u.service_id))
        out[k] = out.get(k, 0) + 1
    return out


def client_package_out(db: Session, cp: ClientPackage, used: dict | None = None) -> dict:
    used = used if used is not None else used_counts(db, [cp.id])
    items = []
    for it in cp.items:
        n = used.get((cp.id, it["service_id"]), 0)
        items.append({**it, "used": n, "remaining": max(0, it["sessions"] - n)})
    last = db.scalar(select(func.max(ClientPackageUse.created_at)).where(ClientPackageUse.client_package_id == cp.id,
                                                                          ClientPackageUse.cancelled.is_(False)))
    party = db.get(Party, cp.party_id)
    return {"id": str(cp.id), "name": cp.name, "price": str(cp.price), "party_id": str(cp.party_id), "client": party.name if party else None,
            "items": items, "sessions": sum(i["sessions"] for i in items), "used": sum(i["used"] for i in items),
            "remaining": sum(i["remaining"] for i in items), "expires_on": cp.expires_on.isoformat() if cp.expires_on else None,
            "status": package_state(cp), "min_days": cp.min_days, "last_use": last.isoformat() if last else None,
            "created_at": cp.created_at.isoformat() if cp.created_at else None}


def active_packages(db: Session, party_id) -> list[ClientPackage]:
    return [cp for cp in db.scalars(select(ClientPackage).where(ClientPackage.party_id == party_id, ClientPackage.status == "attivo")
                                    .order_by(ClientPackage.expires_on.nulls_last(), ClientPackage.created_at))
            if package_state(cp) == "attivo"]


def cancel_package(db: Session, cp: ClientPackage) -> None:
    cp.status = "annullato"
    db.flush()


# ------------------------------------------------------------------------------------------- utilizzo all'incasso
def plan_checkout(db: Session, appt, *, voucher_code: str | None = None, voucher_amount=None, use_packages: bool = True,
                  products_total: Decimal = Decimal(0), discount: Decimal = Decimal(0)) -> dict:
    """Cosa coprono pacchetti e buono per questo appuntamento (senza scrivere nulla): sedute scalate per servizio,
    importo del buono, totale da pagare con scontrino. Usato dall'anteprima nella finestra d'incasso e dall'incasso."""
    from app.agenda.models import AgendaService
    covered = []  # [(item, client_package)]
    if use_packages and appt.party_id:
        pkgs = active_packages(db, appt.party_id)
        used = used_counts(db, [p.id for p in pkgs])
        taken: dict = {}
        for it in appt.items:
            for cp in pkgs:
                k = (cp.id, str(it.service_id))
                spec = next((x for x in cp.items if x["service_id"] == str(it.service_id)), None)
                if spec and spec["sessions"] - used.get(k, 0) - taken.get(k, 0) > 0:
                    taken[k] = taken.get(k, 0) + 1
                    covered.append((it, cp, used.get(k, 0) + taken[k], spec["sessions"]))
                    break
    covered_ids = {id(c[0]) for c in covered}
    services = sum((i.price for i in appt.items if id(i) not in covered_ids), Decimal(0))
    base = max(Decimal(0), q(services - min(q(discount), services) + q(products_total)))
    voucher = None
    v_amount = Decimal(0)
    if voucher_code:
        voucher = usable_voucher(db, voucher_code)
        want = q(voucher_amount) if voucher_amount not in (None, "") else voucher.balance
        v_amount = min(want, voucher.balance, base)
    return {"covered": covered, "voucher": voucher, "voucher_amount": q(v_amount), "to_pay": q(base - v_amount),
            "services_names": {str(i.id): (db.get(AgendaService, i.service_id).name if i.service_id else "") for i in appt.items}}


def plan_out(db: Session, plan: dict) -> dict:
    v = plan["voucher"]
    return {"packages": [{"item_id": str(it.id), "service": plan["services_names"][str(it.id)], "package": cp.name,
                          "client_package_id": str(cp.id), "session": n, "of": tot, "value": str(it.price)}
                         for it, cp, n, tot in plan["covered"]],
            "voucher": {"code": v.code, "balance": str(v.balance), "use": str(plan["voucher_amount"]),
                        "left": str(q(v.balance - plan["voucher_amount"])), "expires_on": v.expires_on.isoformat() if v.expires_on else None}
            if v else None,
            "to_pay": str(plan["to_pay"])}


def summary(plan: dict) -> dict:
    """Riepilogo per le ricevute (Document.fiscal["prepaid"])."""
    v = plan["voucher"]
    out = {"packages": [{"name": cp.name, "service": plan["services_names"][str(it.id)], "session": n, "of": tot,
                         "remaining": tot - n, "expires_on": cp.expires_on.isoformat() if cp.expires_on else None}
                        for it, cp, n, tot in plan["covered"]]}
    if v is not None and plan["voucher_amount"] > 0:
        out["voucher"] = {"code": v.code, "used": str(plan["voucher_amount"]), "left": str(q(v.balance - plan["voucher_amount"])),
                          "expires_on": v.expires_on.isoformat() if v.expires_on else None}
    return out


def apply_plan(db: Session, plan: dict, appt, document_id, user_id) -> None:
    """Dopo lo scontrino (o la ricevuta non fiscale): registra le sedute usate e scala il buono."""
    for it, cp, n, tot in plan["covered"]:
        db.add(ClientPackageUse(tenant_id=cp.tenant_id, client_package_id=cp.id, service_id=it.service_id, appointment_id=appt.id,
                                document_id=document_id, value=Decimal(0), user_id=user_id))
    db.flush()
    pkgs = {cp.id: cp for _, cp, _, _ in plan["covered"]}
    used = used_counts(db, list(pkgs))
    for cp in pkgs.values():
        if all(used.get((cp.id, x["service_id"]), 0) >= x["sessions"] for x in cp.items):
            cp.status = "esaurito"
    if plan["voucher"] is not None and plan["voucher_amount"] > 0:
        use_voucher(db, plan["voucher"], plan["voucher_amount"], appointment_id=appt.id, document_id=document_id, user_id=user_id)
    db.flush()


def receipt_lines(prepaid: dict | None) -> list[dict]:
    """Righe del riepilogo (buono e pacchetti) per le ricevute: residuo e sedute rimaste."""
    if not prepaid:
        return []
    L = []
    for p in prepaid.get("packages") or []:
        exp = f" · scade il {date.fromisoformat(p['expires_on']):%d/%m/%Y}" if p.get("expires_on") else ""
        L += [{"text": f"Pacchetto «{p['name']}»", "bold": True},
              {"text": f"  {p['service']}: seduta {p['session']} di {p['of']}"},
              {"text": f"  Sedute rimaste: {p['remaining']}{exp}"}]
    v = prepaid.get("voucher")
    if v:
        exp = f" · valido fino al {date.fromisoformat(v['expires_on']):%d/%m/%Y}" if v.get("expires_on") else ""
        L += [{"text": f"Buono regalo {v['code']}", "bold": True},
              {"text": "  Usati oggi", "right": fmt_eur(v["used"])},
              {"text": "  Credito residuo", "right": fmt_eur(v["left"]), "bold": True}]
        if exp:
            L.append({"text": f" {exp.strip(' ·')}"})
    return L
