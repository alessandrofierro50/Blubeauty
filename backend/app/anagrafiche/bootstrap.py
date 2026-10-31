"""Dati iniziali di ogni nuova azienda cliente: aliquote IVA, pagamenti, unità di misura, listini
e gruppi di campi articolo adatti al settore. Idempotente."""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anagrafiche.models import AppSetting, PaymentTerm, PriceList, Unit, VatRate

VAT_RATES = [
    ("22", "IVA 22%", "22", None, None),
    ("10", "IVA 10%", "10", None, None),
    ("5", "IVA 5%", "5", None, None),
    ("4", "IVA 4%", "4", None, None),
    ("N1", "Escluso art. 15", "0", "N1", "Art. 15 DPR 633/72"),
    ("N2.2", "Non soggetto (forfettario/altri casi)", "0", "N2.2", "Art. 1 c. 54-89 L. 190/2014"),
    ("N3.1", "Non imponibile esportazioni", "0", "N3.1", "Art. 8 c.1 lett. a) DPR 633/72"),
    ("N3.5", "Non imponibile dichiarazione d'intento", "0", "N3.5", "Art. 8 c.1 lett. c) DPR 633/72"),
    ("N4", "Esente art. 10", "0", "N4", "Art. 10 DPR 633/72"),
    ("N6.3", "Reverse charge subappalto edilizia", "0", "N6.3", "Art. 17 c.6 lett. a) DPR 633/72"),
]

PAYMENT_TERMS = [
    ("CONT", "Contanti", "MP01", [{"days": 0, "percent": 100}], False),
    ("CARTA", "Carta di pagamento", "MP08", [{"days": 0, "percent": 100}], False),
    ("BB0", "Bonifico bancario vista fattura", "MP05", [{"days": 0, "percent": 100}], False),
    ("BB30", "Bonifico 30 gg data fattura", "MP05", [{"days": 30, "percent": 100}], False),
    ("BB30FM", "Bonifico 30 gg fine mese", "MP05", [{"days": 30, "percent": 100}], True),
    ("BB3060", "Bonifico 30/60 gg fine mese", "MP05", [{"days": 30, "percent": 50}, {"days": 60, "percent": 50}], True),
    ("RB60", "Ri.Ba. 60 gg fine mese", "MP12", [{"days": 60, "percent": 100}], True),
]

UNITS = [
    ("PZ", "Pezzi", 0), ("KG", "Chilogrammi", 3), ("GR", "Grammi", 0), ("LT", "Litri", 3), ("MT", "Metri", 2),
    ("MQ", "Metri quadri", 2), ("CF", "Confezione", 0), ("CT", "Cartone", 0), ("PL", "Pallet", 0),
    ("PA", "Paia", 0), ("H", "Ore", 2), ("NR", "Numero", 0),
]

FIELD_GROUPS = ["varianti", "lotti", "matricole", "dimensioni", "intrastat", "distinta_base"]


def field_groups_for_sector(sector: str | None) -> dict[str, bool]:
    """Gruppi di campi articolo visibili. Tutto resta attivabile dalle impostazioni."""
    s = (sector or "").lower()
    if any(k in s for k in ("abbigliament", "moda", "calzatur", "boutique")):
        on = {"varianti"}
    elif any(k in s for k in ("panett", "panific", "aliment", "pasticc", "gastronom", "bar", "ristor", "farmac", "cosmet")):
        on = {"lotti"}
    elif any(k in s for k in ("ferrament", "elettron", "informatic", "elettrodom", "edil")):
        on = {"matricole", "distinta_base", "dimensioni"}
    else:
        on = set(FIELD_GROUPS)
    return {g: g in on for g in FIELD_GROUPS}


def bootstrap_tenant(db: Session, tenant_id: uuid.UUID, sector: str | None) -> None:
    if not db.scalar(select(VatRate).where(VatRate.tenant_id == tenant_id).limit(1)):
        for code, desc, rate, nature, ref in VAT_RATES:
            db.add(VatRate(tenant_id=tenant_id, code=code, description=desc, rate=Decimal(rate), nature=nature,
                           legal_reference=ref))
    if not db.scalar(select(PaymentTerm).where(PaymentTerm.tenant_id == tenant_id).limit(1)):
        for code, desc, method, inst, eom in PAYMENT_TERMS:
            db.add(PaymentTerm(tenant_id=tenant_id, code=code, description=desc, method=method,
                               installments=inst, end_of_month=eom))
    if not db.scalar(select(Unit).where(Unit.tenant_id == tenant_id).limit(1)):
        for code, desc, dec in UNITS:
            db.add(Unit(tenant_id=tenant_id, code=code, description=desc, decimals=dec))
    if not db.scalar(select(PriceList).where(PriceList.tenant_id == tenant_id).limit(1)):
        db.add(PriceList(tenant_id=tenant_id, code="PUBBLICO", name="Listino al pubblico", vat_included=True,
                         is_default=True))
        db.add(PriceList(tenant_id=tenant_id, code="RIVEND", name="Listino rivenditori", vat_included=False))
    if not db.get(AppSetting, (tenant_id, "item_field_groups")):
        db.add(AppSetting(tenant_id=tenant_id, key="item_field_groups", value=field_groups_for_sector(sector)))
    db.flush()
