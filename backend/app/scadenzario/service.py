"""Scadenze: nascono dalle fatture confermate, si chiudono con incassi e pagamenti (anche parziali).

Unico punto che crea, aggiorna ed elimina scadenze e movimenti di incasso/pagamento."""

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.anagrafiche.models import AppSetting, Party, PaymentTerm
from app.documenti.models import Document
from app.scadenzario.models import FinancialAccount, Installment, InstallmentPayment

CENT = Decimal("0.01")
DOC_TYPES = {"FTI": "attiva", "FTD": "attiva", "NC": "attiva", "FTF": "passiva", "NCF": "passiva"}
CREDIT_NOTES = ("NC", "NCF")
METHODS = {
    "MP01": "Contanti", "MP02": "Assegno", "MP03": "Assegno circolare", "MP05": "Bonifico", "MP08": "Carta di pagamento",
    "MP09": "RID", "MP12": "Ri.Ba.", "MP15": "Giroconto", "MP19": "SEPA Direct Debit", "MP23": "PagoPA",
}


def fail(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, msg)


def _q(v) -> Decimal:
    return Decimal(v or 0)


def end_of_month(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def residual(i: Installment) -> Decimal:
    return _q(i.amount) - _q(i.paid_amount)


# ====================================================================== piano delle rate


def split(total: Decimal, start: date, installments: list[dict], eom: bool) -> list[tuple[date, Decimal]]:
    """Rate da una condizione di pagamento: [{"days": 30, "percent": 50}, ...]; "fine mese" = fine del mese di scadenza."""
    rows = installments or [{"days": 0, "percent": 100}]
    out: list[tuple[date, Decimal]] = []
    left = total
    for n, r in enumerate(rows):
        due = start + timedelta(days=int(r.get("days", 0)))
        if eom:
            due = end_of_month(due)
        if n == len(rows) - 1:
            amount = left
        else:
            amount = (total * Decimal(str(r.get("percent", 0))) / 100).quantize(CENT, ROUND_HALF_UP)
            left -= amount
        out.append((due, amount))
    return out


def amount_due(db: Session, d: Document) -> Decimal:
    """Quanto si incassa/paga davvero: senza ritenuta d'acconto e, in split payment, senza l'IVA (la versa la PA)."""
    total = _q(d.total) - _q(d.withholding_total)
    if d.direction == "vendita":
        party = db.get(Party, d.party_id)
        if party is not None and party.split_payment:
            total -= _q(d.vat_total)
    return total.quantize(CENT, ROUND_HALF_UP)


def default_account(db: Session) -> FinancialAccount | None:
    return db.scalar(select(FinancialAccount).where(FinancialAccount.active)
                     .order_by(FinancialAccount.is_default.desc(), FinancialAccount.kind.desc(), FinancialAccount.name))


def create_for_document(db: Session, d: Document, user_id=None) -> list[Installment]:
    direction = DOC_TYPES.get(d.doc_type)
    if direction is None:
        return []
    if db.scalar(select(Installment.id).where(Installment.document_id == d.id).limit(1)):
        return []
    total = amount_due(db, d)
    sign = Decimal(-1) if d.doc_type in CREDIT_NOTES else Decimal(1)
    term = db.get(PaymentTerm, d.payment_term_id) if d.payment_term_id else None
    start = (d.external_date or d.doc_date) if direction == "passiva" else d.doc_date
    plan: list[tuple[date, Decimal, str | None]] = []
    if d.doc_type in CREDIT_NOTES:
        plan = [(d.doc_date, total, term.method if term else None)]  # da compensare o rimborsare
    elif d.payment_schedule:  # scadenze lette dalla fattura elettronica
        rows = [p for p in d.payment_schedule if p.get("amount")]
        if rows and abs(sum((Decimal(str(p["amount"])) for p in rows), Decimal(0)) - total) <= Decimal("0.05"):
            for p in rows:
                due = date.fromisoformat(p["due_date"][:10]) if p.get("due_date") else start
                plan.append((due, Decimal(str(p["amount"])), p.get("method")))
    if not plan:
        plan = [(due, amt, term.method if term else None)
                for due, amt in split(total, start, term.installments if term else [], term.end_of_month if term else False)]
    party = db.get(Party, d.party_id)
    label = {"FTI": "Fattura", "FTD": "Fattura", "NC": "Nota di credito", "FTF": "Fattura", "NCF": "Nota di credito"}[d.doc_type]
    number = d.number if direction == "attiva" else (d.external_number or d.number)
    acc = default_account(db)
    out = []
    for n, (due, amt, method) in enumerate(plan, start=1):
        i = Installment(tenant_id=d.tenant_id, direction=direction, party_id=d.party_id, document_id=d.id, seq=n,
                        total_seq=len(plan), issue_date=d.doc_date, due_date=due, amount=(amt * sign).quantize(CENT),
                        paid_amount=Decimal(0), method=method, account_id=acc.id if acc and direction == "attiva" else None,
                        status="aperta", created_by=user_id,
                        description=f"{label} n. {number} del {d.doc_date.strftime('%d/%m/%Y')}"
                                    + (f" – rata {n}/{len(plan)}" if len(plan) > 1 else "")
                                    + (f" – {party.name}" if party else ""))
        db.add(i)
        out.append(i)
    db.flush()
    return out


def remove_for_document(db: Session, d: Document) -> None:
    rows = db.scalars(select(Installment).where(Installment.document_id == d.id)).all()
    if any(_q(i.paid_amount) != 0 for i in rows):
        raise fail("Ci sono incassi o pagamenti registrati su questo documento: eliminali prima dallo scadenzario",
                   status.HTTP_409_CONFLICT)
    for i in rows:
        db.delete(i)
    db.flush()


# ====================================================================== incassi e pagamenti


def refresh(db: Session, i: Installment) -> None:
    paid = sum((_q(p.amount) for p in i.payments), Decimal(0))
    i.paid_amount = paid
    amt = _q(i.amount)
    if amt == 0 or (amt > 0 and paid >= amt) or (amt < 0 and paid <= amt):
        i.status = "pagata"
        i.unpaid = False
    elif paid != 0:
        i.status = "parziale"
    else:
        i.status = "aperta"
    if i.document_id:
        doc = db.get(Document, i.document_id)
        if doc is not None:
            db.flush()
            others = db.scalars(select(Installment.status).where(Installment.document_id == doc.id)).all()
            doc.settled = bool(others) and all(s == "pagata" for s in others)


def pay(db: Session, i: Installment, *, pay_date: date, amount: Decimal | None = None, account_id=None, method=None,
        notes=None, user_id=None) -> InstallmentPayment:
    amount = residual(i) if amount is None else Decimal(amount)
    if amount == 0:
        raise fail("Importo a zero")
    if (residual(i) > 0 and amount > residual(i)) or (residual(i) < 0 and amount < residual(i)):
        raise fail(f"L'importo supera il residuo della scadenza ({residual(i):.2f} €)")
    if pay_date < i.issue_date:
        raise fail("La data dell'incasso precede quella del documento")
    if account_id is None:
        acc = default_account(db)
        account_id = acc.id if acc else None
    p = InstallmentPayment(tenant_id=i.tenant_id, installment_id=i.id, pay_date=pay_date, amount=amount,
                           account_id=account_id, method=method or i.method, notes=notes, created_by=user_id)
    i.payments.append(p)
    db.flush()
    refresh(db, i)
    return p


def delete_payment(db: Session, p: InstallmentPayment) -> None:
    i = db.get(Installment, p.installment_id)
    i.payments.remove(p)
    db.flush()
    refresh(db, i)


def settle_document(db: Session, d: Document, settled: bool, on: date, user_id=None) -> None:
    """Segna tutta la fattura come incassata (registra il residuo di ogni rata) o annulla gli incassi."""
    rows = db.scalars(select(Installment).where(Installment.document_id == d.id)).all()
    if not rows:
        rows = create_for_document(db, d, user_id)
    for i in rows:
        if settled and i.status != "pagata":
            pay(db, i, pay_date=max(on, i.issue_date), user_id=user_id)
        elif not settled:
            for p in list(i.payments):
                i.payments.remove(p)
            db.flush()
            refresh(db, i)
    d.settled = settled


# ====================================================================== situazione del cliente


def party_position(db: Session, party_id, direction: str = "attiva", on: date | None = None) -> dict:
    on = on or date.today()
    rows = db.scalars(select(Installment).where(Installment.party_id == party_id, Installment.direction == direction,
                                                Installment.status != "pagata")).all()
    open_total = sum((residual(i) for i in rows), Decimal(0))
    overdue = [i for i in rows if i.due_date < on and residual(i) > 0]
    return {
        "open": open_total,
        "overdue": sum((residual(i) for i in overdue), Decimal(0)),
        "overdue_days": max(((on - i.due_date).days for i in overdue), default=0),
        "unpaid": sum(1 for i in rows if i.unpaid),
        "max_reminder_level": max((i.reminder_level for i in overdue), default=0),
    }


DEFAULT_SETTINGS = {
    "auto": False,
    "days": [7, 30, 60],  # giorni di ritardo per il 1°, 2° e 3° livello
    "block_overdue_days": None,  # blocco/avviso in vendita oltre questi giorni di ritardo (vuoto = no)
    "templates": {
        "1": {"subject": "Promemoria di pagamento – {azienda}",
              "body": "<p>Gentile {cliente},</p><p>da un controllo amministrativo risultano ancora da saldare i seguenti documenti:</p>"
                      "{elenco}<p>per un totale di <b>{totale}</b>.</p><p>Se ha già provveduto al pagamento, la preghiamo di "
                      "non considerare questo messaggio. In caso contrario, può effettuare il bonifico sull'IBAN {iban}.</p>"
                      "<p>Cordiali saluti,<br>{azienda}</p>"},
        "2": {"subject": "Secondo sollecito di pagamento – {azienda}",
              "body": "<p>Gentile {cliente},</p><p>nonostante il nostro precedente promemoria, risultano ancora insoluti i seguenti documenti:</p>"
                      "{elenco}<p>per un totale di <b>{totale}</b>, scaduto da {giorni} giorni.</p><p>La invitiamo a provvedere "
                      "al pagamento entro 10 giorni (IBAN {iban}) o a contattarci per concordare una soluzione.</p>"
                      "<p>Distinti saluti,<br>{azienda}</p>"},
        "3": {"subject": "Diffida di pagamento – {azienda}",
              "body": "<p>Spett.le {cliente},</p><p>con la presente la diffidiamo a saldare entro 15 giorni dal ricevimento "
                      "i seguenti documenti, scaduti da oltre {giorni} giorni:</p>{elenco}<p>per un totale di <b>{totale}</b> "
                      "(IBAN {iban}).</p><p>Trascorso inutilmente tale termine, ci vedremo costretti a tutelare i nostri "
                      "diritti nelle sedi opportune, con aggravio di spese a suo carico.</p><p>{azienda}</p>"},
    },
    "whatsapp": "Gentile {cliente}, le ricordiamo che risultano da saldare documenti per {totale} ({documenti}). "
                "IBAN {iban}. Grazie, {azienda}",
}


def settings(db: Session, tenant_id) -> dict:
    s = db.get(AppSetting, (tenant_id, "solleciti"))
    value = dict(DEFAULT_SETTINGS)
    if s and s.value:
        value.update({k: v for k, v in s.value.items() if k in DEFAULT_SETTINGS})
        value["templates"] = {**DEFAULT_SETTINGS["templates"], **(s.value.get("templates") or {})}
    return value


def save_settings(db: Session, tenant_id, value: dict) -> dict:
    s = db.get(AppSetting, (tenant_id, "solleciti"))
    if s is None:
        s = AppSetting(tenant_id=tenant_id, key="solleciti", value={})
        db.add(s)
    s.value = {k: value[k] for k in DEFAULT_SETTINGS if k in value}
    db.flush()
    return settings(db, tenant_id)


def account_balance(db: Session, acc: FinancialAccount, on: date) -> Decimal:
    """Saldo del conto a fine giornata `on`: saldo iniziale + incassi − pagamenti registrati sul conto."""
    if acc.opening_date and acc.opening_date > on:
        return Decimal(0)
    q = (select(Installment.direction, func.coalesce(func.sum(InstallmentPayment.amount), 0))
         .join(Installment, Installment.id == InstallmentPayment.installment_id)
         .where(InstallmentPayment.account_id == acc.id, InstallmentPayment.pay_date <= on)
         .group_by(Installment.direction))
    if acc.opening_date:
        q = q.where(InstallmentPayment.pay_date >= acc.opening_date)
    moves = {d: Decimal(v) for d, v in db.execute(q)}
    # incassi al banco (scontrini e resi, non le fatture al banco che passano dalle rate)
    from app.pos.models import PosPayment
    pq = (select(func.coalesce(func.sum(PosPayment.amount), 0)).join(Document, Document.id == PosPayment.document_id)
          .where(PosPayment.account_id == acc.id, Document.doc_date <= on, Document.status != "annullato"))
    if acc.opening_date:
        pq = pq.where(Document.doc_date >= acc.opening_date)
    pos = Decimal(db.scalar(pq) or 0)
    return _q(acc.opening_balance) + moves.get("attiva", Decimal(0)) - moves.get("passiva", Decimal(0)) + pos


def backfill(db: Session, tenant_id) -> int:
    """Crea le scadenze mancanti per le fatture già confermate (documenti nati prima dello scadenzario)."""
    docs = db.scalars(select(Document).where(Document.doc_type.in_(list(DOC_TYPES)), Document.status.in_(("confermato", "evaso")),
                                             ~Document.id.in_(select(Installment.document_id).where(Installment.document_id.is_not(None))))).all()
    n = 0
    for d in docs:
        rows = create_for_document(db, d)
        if d.settled:
            for i in rows:
                pay(db, i, pay_date=i.due_date if i.due_date <= date.today() else date.today())
        n += len(rows)
    return n

