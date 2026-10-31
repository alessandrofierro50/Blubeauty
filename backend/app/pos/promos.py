"""Promozioni di cassa: prendi N paghi M, N-esimo pezzo scontato, sconto a soglia di spesa.

Tutto in centesimi interi. Lo stesso algoritmo esiste in TypeScript (frontend/src/pages/pos/promos.ts) perché la cassa
deve mostrare il totale anche senza rete: la fixture tests/fixtures/pos_promos.json li tiene allineati.

Regole (come nella grande distribuzione):
- valgono solo gli articoli a pezzi interi, senza sconto manuale sulla riga, con prezzo > 0;
- i pezzi idonei si mettono in fila dal più caro al meno caro e si raggruppano a blocchi di N: in ogni blocco
  è gratis (o scontato) il meno caro; un pezzo usato da una promozione non entra in un'altra;
- le promozioni a pezzi si applicano in ordine (prima "nxm", poi "nesimo", poi per nome); quella a soglia per ultima,
  sul totale già scontato delle righe interessate, e se ne applica una sola (la più conveniente);
- lo sconto diventa una riga negativa per aliquota IVA, così il riepilogo IVA resta esatto."""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

MECHANICS = ("nxm", "nesimo", "soglia")


def rhu(x: Decimal) -> int:
    """Arrotondamento commerciale all'intero (metà verso l'alto in valore assoluto)."""
    return int(Decimal(x).quantize(Decimal(1), ROUND_HALF_UP))


@dataclass
class PLine:
    key: str
    item_id: str | None
    price_cents: int  # prezzo unitario IVA inclusa
    quantity: Decimal
    amount_cents: int  # importo della riga
    vat_rate_id: str | None
    categories: set[str] = field(default_factory=set)
    manual_discount: bool = False


@dataclass
class PPromo:
    id: str
    name: str
    mechanic: str
    item_scope: str
    item_ids: set[str]
    category_ids: set[str]
    buy_qty: int | None
    pay_qty: int | None
    value: Decimal
    price_type: str  # sconto (%) | importo (€)
    threshold_cents: int | None


def _in_scope(p: PPromo, ln: PLine) -> bool:
    if p.item_scope == "tutti":
        return True
    if ln.item_id is None:
        return False
    if p.item_scope == "articoli":
        return ln.item_id in p.item_ids
    return bool(ln.categories & p.category_ids)


def _order(p: PPromo):
    return ({"nxm": 0, "nesimo": 1, "soglia": 2}.get(p.mechanic, 9), p.name.lower(), p.id)


def compute(lines: list[PLine], promos: list[PPromo]) -> list[dict]:
    """Righe di sconto: [{promotion_id, description, vat_rate_id, amount_cents (negativo)}]."""
    units = []  # (price, indice riga, progressivo)
    for i, ln in enumerate(lines):
        q = Decimal(ln.quantity)
        if ln.item_id and not ln.manual_discount and ln.price_cents > 0 and q > 0 and q == q.to_integral_value():
            units += [(ln.price_cents, i, n) for n in range(int(q))]
    used: set[tuple] = set()
    out: list[dict] = []
    unit_disc: dict[int, int] = defaultdict(int)  # sconto per riga (serve alla soglia)
    for p in sorted([p for p in promos if p.mechanic in ("nxm", "nesimo")], key=_order):
        n = int(p.buy_qty or 0)
        if n < 2 or (p.mechanic == "nxm" and not (0 < int(p.pay_qty or 0) < n)):
            continue
        pool = sorted([u for u in units if (u[1], u[2]) not in used and _in_scope(p, lines[u[1]])], key=lambda u: (-u[0], u[1], u[2]))
        groups = len(pool) // n
        if not groups:
            continue
        per_vat: dict = defaultdict(int)
        for g in range(groups):
            block = pool[g * n:(g + 1) * n]
            for u in block:
                used.add((u[1], u[2]))
            free = block[-(n - int(p.pay_qty)):] if p.mechanic == "nxm" else block[-1:]
            for price, li, _ in free:
                d = price if p.mechanic == "nxm" else rhu(Decimal(price) * Decimal(p.value) / 100)
                per_vat[lines[li].vat_rate_id] += d
                unit_disc[li] += d
        label = f"{n}x{p.pay_qty}" if p.mechanic == "nxm" else f"{n}° pezzo −{Decimal(p.value).normalize():f}%"
        for vat, amount in sorted(per_vat.items(), key=lambda x: str(x[0])):
            if amount:
                out.append({"promotion_id": p.id, "description": f"Promo {label} · {p.name}"[:500], "vat_rate_id": vat, "amount_cents": -amount})
    # soglia di spesa: una sola, la più conveniente
    best = None
    for p in sorted([p for p in promos if p.mechanic == "soglia"], key=_order):
        base: dict = defaultdict(int)
        for i, ln in enumerate(lines):
            if ln.amount_cents > 0 and _in_scope(p, ln):
                base[ln.vat_rate_id] += ln.amount_cents - unit_disc.get(i, 0)
        total = sum(base.values())
        if total <= 0 or total < int(p.threshold_cents or 0):
            continue
        disc = rhu(Decimal(total) * Decimal(p.value) / 100) if p.price_type == "sconto" else min(total, rhu(Decimal(p.value) * 100))
        if disc > 0 and (best is None or disc > best[0]):
            best = (disc, p, base, total)
    if best:
        disc, p, base, total = best
        keys = sorted([k for k, v in base.items() if v], key=str)
        left = disc
        for n, vat in enumerate(keys):
            share = left if n == len(keys) - 1 else rhu(Decimal(disc) * base[vat] / total)
            left -= share
            if share:
                what = f"−{Decimal(p.value).normalize():f}%" if p.price_type == "sconto" else f"−{Decimal(p.value):.2f} €".replace(".", ",")
                out.append({"promotion_id": p.id, "description": f"Sconto {what} sulla spesa · {p.name}"[:500], "vat_rate_id": vat,
                            "amount_cents": -share})
    return out
