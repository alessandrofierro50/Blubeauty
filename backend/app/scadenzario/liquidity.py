"""Fotografia della liquidità a una data (anche passata) e previsione dei flussi per settimana e per mese.

A una data D si considerano le scadenze già "nate" (data documento ≤ D) e gli incassi/pagamenti registrati fino a D:
la situazione è quella che si sarebbe vista quel giorno."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.anagrafiche.models import Party
from app.scadenzario.models import FinancialAccount, Installment, InstallmentPayment
from app.scadenzario.service import account_balance

MONTHS = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]


def s(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.01")))


def snapshot(db: Session, as_of: date, weeks: int = 8, months: int = 6) -> dict:
    accounts = db.scalars(select(FinancialAccount).order_by(FinancialAccount.kind, FinancialAccount.name)).all()
    acc_rows = [{"id": str(a.id), "name": a.name, "kind": a.kind, "active": a.active, "balance": account_balance(db, a, as_of)}
                for a in accounts]
    liquidity = sum((a["balance"] for a in acc_rows), Decimal(0))

    rows = db.scalars(select(Installment).where(Installment.issue_date <= as_of).options(selectinload(Installment.payments))).all()
    open_rows = []
    for i in rows:
        paid = sum((Decimal(p.amount) for p in i.payments if p.pay_date <= as_of), Decimal(0))
        res = Decimal(i.amount) - paid
        if res != 0:
            open_rows.append((i, res))

    tot = {k: {"open": Decimal(0), "overdue": Decimal(0), "count": 0, "overdue_count": 0} for k in ("attiva", "passiva")}
    for i, res in open_rows:
        t = tot[i.direction]
        t["open"] += res
        t["count"] += 1
        if i.due_date < as_of:
            t["overdue"] += res
            t["overdue_count"] += 1

    # incassi e pagamenti dall'inizio dell'anno, mese per mese
    year_start = as_of.replace(month=1, day=1)
    flows = db.execute(select(Installment.direction, InstallmentPayment.pay_date, InstallmentPayment.amount)
                       .join(Installment, Installment.id == InstallmentPayment.installment_id)
                       .where(InstallmentPayment.pay_date >= year_start, InstallmentPayment.pay_date <= as_of)).all()
    by_month = defaultdict(lambda: {"in": Decimal(0), "out": Decimal(0)})
    for direction, d, amt in flows:
        by_month[d.month]["in" if direction == "attiva" else "out"] += Decimal(amt)
    ytd = [{"month": f"{MONTHS[m - 1]} {as_of.year}", "in": s(v["in"]), "out": s(v["out"]), "net": s(v["in"] - v["out"])}
           for m, v in sorted(by_month.items())]

    def forecast(buckets: list[tuple[str, date, date]]) -> list[dict]:
        out = []
        balance = liquidity
        overdue_in = sum((r for i, r in open_rows if i.direction == "attiva" and i.due_date < as_of), Decimal(0))
        overdue_out = sum((r for i, r in open_rows if i.direction == "passiva" and i.due_date < as_of), Decimal(0))
        balance += overdue_in - overdue_out
        out.append({"label": "Già scaduto", "from": None, "to": as_of.isoformat(), "in": s(overdue_in), "out": s(overdue_out),
                    "net": s(overdue_in - overdue_out), "balance": s(balance), "overdue": True})
        for label, a, b in buckets:
            i_in = sum((r for i, r in open_rows if i.direction == "attiva" and a <= i.due_date <= b), Decimal(0))
            i_out = sum((r for i, r in open_rows if i.direction == "passiva" and a <= i.due_date <= b), Decimal(0))
            balance += i_in - i_out
            out.append({"label": label, "from": a.isoformat(), "to": b.isoformat(), "in": s(i_in), "out": s(i_out),
                        "net": s(i_in - i_out), "balance": s(balance)})
        later_in = sum((r for i, r in open_rows if i.direction == "attiva" and i.due_date > buckets[-1][2]), Decimal(0))
        later_out = sum((r for i, r in open_rows if i.direction == "passiva" and i.due_date > buckets[-1][2]), Decimal(0))
        if later_in or later_out:
            balance += later_in - later_out
            out.append({"label": "Oltre", "from": (buckets[-1][2] + timedelta(days=1)).isoformat(), "to": None,
                        "in": s(later_in), "out": s(later_out), "net": s(later_in - later_out), "balance": s(balance)})
        return out

    week_start = as_of
    wb = []
    for n in range(weeks):
        a = week_start + timedelta(days=7 * n)
        b = a + timedelta(days=6)
        wb.append((f"{a.strftime('%d/%m')} – {b.strftime('%d/%m')}", a, b))
    mb = []
    for n in range(months):
        a = as_of if n == 0 else (as_of.replace(day=1) + relativedelta(months=n))
        b = (as_of.replace(day=1) + relativedelta(months=n + 1)) - timedelta(days=1)
        mb.append((f"{MONTHS[a.month - 1]} {a.year}", a, b))

    # clienti con più scaduto alla data
    by_party = defaultdict(Decimal)
    for i, res in open_rows:
        if i.direction == "attiva" and i.due_date < as_of and res > 0 and i.party_id:
            by_party[i.party_id] += res
    names = {p.id: p.name for p in db.scalars(select(Party).where(Party.id.in_(list(by_party))))} if by_party else {}
    top_overdue = [{"party_id": str(k), "name": names.get(k), "amount": s(v)}
                   for k, v in sorted(by_party.items(), key=lambda x: -x[1])[:10]]

    rec, pay = tot["attiva"], tot["passiva"]
    return {
        "as_of": as_of.isoformat(),
        "accounts": [{**a, "balance": s(a["balance"])} for a in acc_rows],
        "liquidity": s(liquidity),
        "receivables": {k: (s(v) if isinstance(v, Decimal) else v) for k, v in rec.items()},
        "payables": {k: (s(v) if isinstance(v, Decimal) else v) for k, v in pay.items()},
        "net_position": s(liquidity + rec["open"] - pay["open"]),
        "collected_ytd": s(sum((Decimal(r["in"]) for r in ytd), Decimal(0))),
        "paid_ytd": s(sum((Decimal(r["out"]) for r in ytd), Decimal(0))),
        "ytd": ytd,
        "weeks": forecast(wb),
        "months": forecast(mb),
        "top_overdue": top_overdue,
    }


def to_excel(data: dict, title: str) -> bytes:
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="2340A8")

    def table(ws, header, rows, start_row):
        for c, h in enumerate(header, start=1):
            cell = ws.cell(row=start_row, column=c, value=h)
            cell.font, cell.fill = head, fill
        for r, row in enumerate(rows, start=start_row + 1):
            for c, v in enumerate(row, start=1):
                ws.cell(row=r, column=c, value=float(v) if isinstance(v, str) and _num(v) else v)
        return start_row + len(rows) + 2

    ws = wb.active
    ws.title = "Situazione"
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Situazione al {date.fromisoformat(data['as_of']).strftime('%d/%m/%Y')}"
    r = table(ws, ["Voce", "Importo €"], [
        ["Liquidità (cassa e banche)", data["liquidity"]],
        ["Crediti da incassare", data["receivables"]["open"]], ["di cui scaduti", data["receivables"]["overdue"]],
        ["Debiti da pagare", data["payables"]["open"]], ["di cui scaduti", data["payables"]["overdue"]],
        ["Posizione netta", data["net_position"]],
        ["Incassato da inizio anno", data["collected_ytd"]], ["Pagato da inizio anno", data["paid_ytd"]],
    ], 4)
    table(ws, ["Conto", "Tipo", "Saldo €"], [[a["name"], a["kind"], a["balance"]] for a in data["accounts"]], r)
    for key, name in (("weeks", "Previsione settimane"), ("months", "Previsione mesi")):
        w = wb.create_sheet(name)
        table(w, ["Periodo", "Entrate €", "Uscite €", "Saldo periodo €", "Saldo progressivo €"],
              [[x["label"], x["in"], x["out"], x["net"], x["balance"]] for x in data[key]], 1)
    for w in wb.worksheets:
        for col in ("A", "B", "C", "D", "E"):
            w.column_dimensions[col].width = 26 if col == "A" else 18
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _num(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False
