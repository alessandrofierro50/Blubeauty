"""Calcoli di prezzo: sconti a cascata, scorporo IVA, ricarico e margine."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
Q4 = Decimal("0.0001")


def cascade(price: Decimal, *discounts: Decimal | None) -> Decimal:
    """Applica sconti in cascata: 100 con 10+5 = 85,50."""
    net = Decimal(price)
    for d in discounts:
        if d:
            net = net * (Decimal(100) - Decimal(d)) / Decimal(100)
    return net.quantize(Q4, ROUND_HALF_UP)


def net_of_vat(price: Decimal, vat_rate: Decimal | None, vat_included: bool) -> Decimal:
    if not vat_included or not vat_rate:
        return Decimal(price)
    return (Decimal(price) * Decimal(100) / (Decimal(100) + Decimal(vat_rate))).quantize(Q4, ROUND_HALF_UP)


def markup_margin(sale_net: Decimal, cost: Decimal | None) -> tuple[Decimal | None, Decimal | None]:
    """Ricarico % sul costo e margine % sul prezzo (prezzo al netto IVA)."""
    if not cost or not sale_net:
        return None, None
    cost, sale_net = Decimal(cost), Decimal(sale_net)
    markup = ((sale_net - cost) / cost * 100).quantize(CENT, ROUND_HALF_UP)
    margin = ((sale_net - cost) / sale_net * 100).quantize(CENT, ROUND_HALF_UP)
    return markup, margin


def price_from_markup(cost: Decimal, markup_percent: Decimal, vat_rate: Decimal | None, vat_included: bool) -> Decimal:
    """Prezzo di listino partendo dal costo e dal ricarico (usato anche dall'import fatture)."""
    net = Decimal(cost) * (Decimal(100) + Decimal(markup_percent)) / Decimal(100)
    if vat_included and vat_rate:
        net = net * (Decimal(100) + Decimal(vat_rate)) / Decimal(100)
    return net.quantize(CENT, ROUND_HALF_UP)
