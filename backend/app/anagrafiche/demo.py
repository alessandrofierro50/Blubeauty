"""Anagrafiche di esempio per le tre aziende demo (nomi e marchi di fantasia)."""

import itertools
import uuid
from decimal import Decimal as D

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anagrafiche.models import (
    Brand,
    Category,
    Item,
    ItemBarcode,
    ItemComponent,
    ItemPrice,
    ItemSupplier,
    ItemUnit,
    ItemVariant,
    Party,
    PaymentTerm,
    PriceList,
    VatRate,
)
from app.anagrafiche.validators import make_internal_ean13, valid_vat_it


def demo_vat(base: str) -> str:
    """Partita IVA con cifra di controllo corretta, a partire da 10 cifre."""
    for d in range(10):
        if valid_vat_it(base + str(d)):
            return base + str(d)
    raise ValueError(base)


class Loader:
    def __init__(self, db: Session, tenant_id: uuid.UUID):
        self.db, self.t = db, tenant_id
        self.vat = {v.code: v.id for v in db.scalars(select(VatRate).where(VatRate.tenant_id == tenant_id))}
        self.pay = {p.code: p.id for p in db.scalars(select(PaymentTerm).where(PaymentTerm.tenant_id == tenant_id))}
        self.lists = {p.code: p.id for p in db.scalars(select(PriceList).where(PriceList.tenant_id == tenant_id))}
        self.cats: dict[str, uuid.UUID] = {}
        self.brands: dict[str, uuid.UUID] = {}
        self.ean = itertools.count(1)
        self.n_item = itertools.count(1)
        self.n_c = itertools.count(1)
        self.n_f = itertools.count(1)

    def category(self, name: str, parent: str | None = None) -> uuid.UUID:
        c = Category(tenant_id=self.t, name=name, parent_id=self.cats.get(parent) if parent else None)
        self.db.add(c)
        self.db.flush()
        self.cats[name] = c.id
        return c.id

    def brand(self, name: str) -> uuid.UUID:
        b = Brand(tenant_id=self.t, name=name)
        self.db.add(b)
        self.db.flush()
        self.brands[name] = b.id
        return b.id

    def party(self, name: str, *, supplier=False, privato=False, **kw) -> Party:
        code = f"F{next(self.n_f):05d}" if supplier else f"C{next(self.n_c):05d}"
        kw.setdefault("person_type", "privato" if privato else "azienda")
        p = Party(tenant_id=self.t, code=code, name=name, is_customer=not supplier, is_supplier=supplier,
                  country="IT", custom={}, **kw)
        if privato and not p.sdi_code:
            p.sdi_code = "0000000"
        self.db.add(p)
        self.db.flush()
        return p

    def item(self, description: str, *, price: str, cost: str, vat="22", rivend: str | None = None,
             variants: list[dict] | None = None, supplier: Party | None = None, supplier_code: str | None = None,
             **kw) -> Item:
        it = Item(tenant_id=self.t, code=f"ART{next(self.n_item):05d}", description=description,
                  vat_rate_id=self.vat[vat], last_cost=D(cost), avg_cost=D(cost), tags=kw.pop("tags", []), custom={},
                  preferred_supplier_id=supplier.id if supplier else None, **kw)
        self.db.add(it)
        self.db.flush()
        self.db.add(ItemPrice(tenant_id=self.t, item_id=it.id, price_list_id=self.lists["PUBBLICO"], min_qty=0, price=D(price)))
        if rivend:
            self.db.add(ItemPrice(tenant_id=self.t, item_id=it.id, price_list_id=self.lists["RIVEND"], min_qty=0, price=D(rivend)))
        if supplier:
            self.db.add(ItemSupplier(tenant_id=self.t, item_id=it.id, supplier_id=supplier.id,
                                     supplier_code=supplier_code, last_cost=D(cost)))
        if variants:
            it.has_variants = True
            for v in variants:
                var = ItemVariant(tenant_id=self.t, item_id=it.id, code=f"{it.code}-{v['suffix']}",
                                  size=v.get("size"), color=v.get("color"))
                self.db.add(var)
                self.db.flush()
                self.db.add(ItemBarcode(tenant_id=self.t, item_id=it.id, variant_id=var.id,
                                        barcode=make_internal_ean13("200", next(self.ean))))
        elif it.item_type == "articolo":
            self.db.add(ItemBarcode(tenant_id=self.t, item_id=it.id, barcode=make_internal_ean13("200", next(self.ean))))
        self.db.flush()
        return it


def grid(sizes: list[str], colors: list[str] | None = None) -> list[dict]:
    if not colors:
        return [{"suffix": s, "size": s} for s in sizes]
    return [{"suffix": f"{c[:3].upper()}-{s}", "size": s, "color": c} for c in colors for s in sizes]


def abbigliamento(L: Loader) -> None:
    for parent in ("Uomo", "Donna", "Accessori"):
        L.category(parent)
    L.category("T-shirt", "Uomo"), L.category("Jeans", "Uomo"), L.category("Felpe", "Donna"), L.category("Abiti", "Donna")
    levante, nordica = L.brand("Levante"), L.brand("Nordica")
    tess = L.party("Tessile Adriatica Srl", supplier=True, vat_number=demo_vat("0712345678"), city="Barletta",
                   province="BT", zip_code="76121", address="Via del Lavoro 8", payment_term_id=L.pay["BB3060"])
    conf = L.party("Confezioni Murgia Spa", supplier=True, vat_number=demo_vat("0634567890"), city="Matera",
                   province="MT", zip_code="75100", address="Zona PAIP 21", payment_term_id=L.pay["RB60"])
    L.party("Bianchi Mario", privato=True, first_name="Mario", last_name="Bianchi", city="Bari", province="BA",
            zip_code="70122", email="mario.bianchi@example.it")
    L.party("Boutique Eleganza Snc", vat_number=demo_vat("0598765432"), sdi_code="M5UXCR1", city="Monopoli",
            province="BA", zip_code="70043", address="Piazza Garibaldi 3", price_list_id=L.lists["RIVEND"],
            payment_term_id=L.pay["BB30"])
    L.item("T-shirt basic cotone", price="19.90", cost="5.80", rivend="11.00", unit="PZ", category_id=L.cats["T-shirt"],
           brand_id=levante, season="Tutto l'anno", supplier=tess, supplier_code="TS-100",
           variants=grid(["S", "M", "L", "XL"], ["Bianco", "Nero", "Blu"]), tags=["cotone", "basic"])
    L.item("Jeans slim fit", price="59.00", cost="21.50", rivend="34.00", category_id=L.cats["Jeans"], brand_id=nordica,
           season="Autunno-Inverno 2026", supplier=conf, supplier_code="JS-42", variants=grid(["44", "46", "48", "50", "52"]))
    L.item("Felpa con cappuccio", price="45.00", cost="14.20", rivend="26.00", category_id=L.cats["Felpe"], brand_id=levante,
           season="Autunno-Inverno 2026", supplier=tess, supplier_code="FC-07",
           variants=grid(["XS", "S", "M", "L"], ["Grigio", "Rosa"]))
    L.item("Sciarpa in lana", price="29.00", cost="8.90", category_id=L.cats["Accessori"], brand_id=nordica, supplier=conf)
    L.item("Servizio orlo pantaloni", price="8.00", cost="0", item_type="servizio", stock_managed=False, unit="NR")


def panetteria(L: Loader) -> None:
    for c in ("Pane", "Prodotti da forno", "Dolci", "Materie prime"):
        L.category(c)
    molino = L.party("Molino del Tavoliere Srl", supplier=True, vat_number=demo_vat("0345678901"), city="Foggia",
                     province="FG", zip_code="71121", address="SS 16 km 680", payment_term_id=L.pay["BB30FM"])
    caseif = L.party("Oleificio Terre di Puglia Srl", supplier=True, vat_number=demo_vat("0456789012"), city="Andria",
                     province="BT", zip_code="76123", payment_term_id=L.pay["BB30"])
    L.party("Bar Centrale Snc", vat_number=demo_vat("0567890123"), sdi_code="KRRH6B9", city="Altamura", province="BA",
            zip_code="70022", address="Piazza Duomo 1", price_list_id=L.lists["RIVEND"], payment_term_id=L.pay["BB30FM"])
    L.party("Ristorante La Murgia Srl", vat_number=demo_vat("0678901234"), pec="lamurgia@pec.example.it",
            city="Gravina in Puglia", province="BA", zip_code="70024", price_list_id=L.lists["RIVEND"],
            payment_term_id=L.pay["BB30"])
    L.party("Lorusso Anna", privato=True, first_name="Anna", last_name="Lorusso", city="Altamura", province="BA")
    L.item("Pane di Altamura DOP", price="3.80", cost="1.10", vat="4", rivend="2.60", unit="KG", category_id=L.cats["Pane"],
           lot_managed=True, shelf_life_days=4, tags=["dop"])
    L.item("Focaccia barese", price="2.50", cost="0.70", vat="10", rivend="1.70", unit="PZ",
           category_id=L.cats["Prodotti da forno"], lot_managed=True, shelf_life_days=2)
    L.item("Taralli all'olio 500 g", price="4.20", cost="1.60", vat="10", rivend="2.90", unit="CF",
           category_id=L.cats["Prodotti da forno"], lot_managed=True, shelf_life_days=120)
    L.item("Cornetto alla crema", price="1.30", cost="0.35", vat="10", unit="PZ", category_id=L.cats["Dolci"],
           lot_managed=True, shelf_life_days=1)
    L.item("Semola rimacinata di grano duro", price="1.20", cost="0.62", vat="4", unit="KG",
           category_id=L.cats["Materie prime"], lot_managed=True, shelf_life_days=365, supplier=molino,
           supplier_code="SRG-25", min_stock=D("200"), reorder_point=D("300"), reorder_qty=D("500"))
    L.item("Olio extravergine di oliva", price="9.50", cost="6.80", vat="4", unit="LT",
           category_id=L.cats["Materie prime"], lot_managed=True, shelf_life_days=540, supplier=caseif,
           supplier_code="EVO-5L", min_stock=D("20"))


def salone(L: Loader) -> None:
    """Parrucchiere ed estetica: prodotti in vendita al banco e prodotti d'uso interno (prezzi di listino IVA esclusa)."""
    for c in ("Capelli", "Viso e corpo", "Uso interno"):
        L.category(c)
    lab = L.brand("Aurora Lab")
    cosm = L.party("Cosmetica Sud Srl", supplier=True, vat_number=demo_vat("0123987654"), city="Bari", province="BA",
                   zip_code="70126", address="Via Amendola 160", payment_term_id=L.pay["BB30"])
    L.item("Shampoo riparatore 250 ml", price="14.75", cost="5.90", category_id=L.cats["Capelli"], brand_id=lab, supplier=cosm,
           supplier_code="SH-250", min_stock=D("6"))
    L.item("Maschera nutriente 200 ml", price="19.67", cost="7.80", category_id=L.cats["Capelli"], brand_id=lab, supplier=cosm,
           supplier_code="MA-200", min_stock=D("4"))
    L.item("Olio sublimante 100 ml", price="23.77", cost="9.20", category_id=L.cats["Capelli"], brand_id=lab, supplier=cosm,
           supplier_code="OL-100", min_stock=D("3"))
    L.item("Crema viso idratante 50 ml", price="28.69", cost="11.50", category_id=L.cats["Viso e corpo"], supplier=cosm,
           supplier_code="CV-50", min_stock=D("3"))
    L.item("Smalto semipermanente", price="9.84", cost="3.90", category_id=L.cats["Viso e corpo"], supplier=cosm, supplier_code="SM-01")
    L.item("Tinta 6.3 biondo scuro dorato 60 ml", price="0.00", cost="4.80", category_id=L.cats["Uso interno"], supplier=cosm,
           supplier_code="TN-63", min_stock=D("10"), unit="PZ")


def barber(L: Loader) -> None:
    for c in ("Barba", "Capelli"):
        L.category(c)
    L.party("Forniture Barber Srl", supplier=True, vat_number=demo_vat("0234876543"), city="Napoli", province="NA", zip_code="80143",
            payment_term_id=L.pay["BB30"])
    L.item("Olio da barba 30 ml", price="12.30", cost="4.50", category_id=L.cats["Barba"])
    L.item("Cera opaca 100 ml", price="13.93", cost="5.10", category_id=L.cats["Capelli"])


def ferramenta(L: Loader) -> None:
    for c in ("Elettroutensili", "Viteria e fissaggio", "Giardinaggio", "Idraulica"):
        L.category(c)
    forza, ferrox = L.brand("Forza Tools"), L.brand("Ferrox")
    uts = L.party("Utensileria Salentina Srl", supplier=True, vat_number=demo_vat("0789012345"), city="Lecce",
                  province="LE", zip_code="73100", address="Zona Industriale lotto 12", payment_term_id=L.pay["RB60"])
    idr = L.party("Idrotermica Sud Spa", supplier=True, vat_number=demo_vat("0890123456"), city="Brindisi",
                  province="BR", zip_code="72100", payment_term_id=L.pay["BB3060"])
    L.party("Edil Rossi Costruzioni Srl", vat_number=demo_vat("0901234567"), sdi_code="T04ZHR3", city="Maglie",
            province="LE", zip_code="73024", address="Via Roma 50", price_list_id=L.lists["RIVEND"],
            payment_term_id=L.pay["RB60"], credit_limit=D("15000"), discount1=D("5"))
    L.party("Comune di Lecce - Ufficio Tecnico", vat_number=demo_vat("0011223344"), person_type="pa", sdi_code="UFABCD",
            city="Lecce", province="LE", zip_code="73100", split_payment=True, payment_term_id=L.pay["BB30"])
    L.party("Greco Paolo", privato=True, first_name="Paolo", last_name="Greco", city="Lecce", province="LE")
    L.item("Trapano avvitatore 18V con 2 batterie", price="149.00", cost="82.00", rivend="119.00",
           category_id=L.cats["Elettroutensili"], brand_id=forza, serial_managed=True, warranty_months=24,
           supplier=uts, supplier_code="FT-DRL18", weight_net=D("1.6"), length=D("22"), width=D("8"), height=D("24"),
           location="A-03")
    L.item("Smerigliatrice angolare 125 mm 900W", price="69.00", cost="38.50", rivend="55.00",
           category_id=L.cats["Elettroutensili"], brand_id=forza, serial_managed=True, warranty_months=24,
           supplier=uts, supplier_code="FT-SM125", location="A-04")
    viti = L.item("Viti legno 4x40 zincate (conf. 200 pz)", price="6.90", cost="2.40", rivend="4.80", unit="CF",
                  category_id=L.cats["Viteria e fissaggio"], brand_id=ferrox, supplier=uts, supplier_code="FX-V440",
                  min_stock=D("30"), location="C-12")
    L.db.add(ItemUnit(tenant_id=L.t, item_id=viti.id, unit="CT", factor=D("20")))
    tass = L.item("Tassello nylon 8 mm", price="0.12", cost="0.03", unit="PZ", category_id=L.cats["Viteria e fissaggio"],
                  brand_id=ferrox, supplier=uts, supplier_code="FX-T8", min_stock=D("500"), location="C-14")
    L.db.add(ItemUnit(tenant_id=L.t, item_id=tass.id, unit="CF", factor=D("100")))
    L.db.add(ItemPrice(tenant_id=L.t, item_id=tass.id, price_list_id=L.lists["PUBBLICO"], min_qty=D("100"), price=D("0.09")))
    kit = L.item("Kit fissaggio mensole", price="9.90", cost="3.10", unit="PZ", category_id=L.cats["Viteria e fissaggio"],
                 is_kit=True, location="C-01")
    L.db.add(ItemComponent(tenant_id=L.t, item_id=kit.id, component_id=viti.id, quantity=D("0.05")))
    L.db.add(ItemComponent(tenant_id=L.t, item_id=kit.id, component_id=tass.id, quantity=D("10")))
    L.item("Tubo irrigazione 1/2\" magliato", price="1.90", cost="0.75", unit="MT", category_id=L.cats["Giardinaggio"],
           supplier=uts, supplier_code="GD-TB12")
    L.item("Rubinetto a sfera 3/4\"", price="12.50", cost="5.20", category_id=L.cats["Idraulica"], supplier=idr,
           supplier_code="IS-RS34")
    L.db.flush()


def extras(db: Session, tenant_id: uuid.UUID, kind: str) -> None:
    """Categorie clienti, una promozione in corso e un catalogo di esempio."""
    from datetime import date, timedelta

    from app.anagrafiche.models import Catalog, CustomerCategory, Promotion

    if db.scalar(select(Promotion).where(Promotion.tenant_id == tenant_id).limit(1)):
        return
    cc = {}
    for name in ("Dettaglio", "Ingrosso", "Ristorazione"):
        c = CustomerCategory(tenant_id=tenant_id, name=name)
        db.add(c)
        db.flush()
        cc[name] = c.id
    for p in db.scalars(select(Party).where(Party.tenant_id == tenant_id, Party.is_customer)):
        p.customer_category_id = cc["Dettaglio"] if p.person_type == "privato" else cc["Ingrosso"]
    cats = {c.name: c.id for c in db.scalars(select(Category).where(Category.tenant_id == tenant_id))}
    today = date.today()
    promo = {
        "abbigliamento": ("Saldi di fine stagione", ["Felpe", "Accessori"], "sconto", D("30")),
        "panetteria": ("Taralli in offerta", ["Prodotti da forno"], "sconto", D("15")),
        "ferramenta": ("Promo elettroutensili", ["Elettroutensili"], "sconto", D("10")),
        "salone": ("Prodotti capelli -15%", ["Capelli"], "sconto", D("15")),
        "barber": ("Promo barba", ["Barba"], "sconto", D("10")),
    }[kind]
    db.add(Promotion(tenant_id=tenant_id, name=promo[0], date_from=today - timedelta(days=3), date_to=today + timedelta(days=20),
                     item_scope="categorie", category_ids=[cats[c] for c in promo[1] if c in cats],
                     customer_scope="tutti", price_type=promo[2], value=promo[3], vat_included=True))
    db.add(Catalog(tenant_id=tenant_id, name="Catalogo generale", title="Catalogo prodotti", layout="griglia",
                   category_ids=list(cats.values()), vat_included=True))
    db.flush()


def load_demo(db: Session, tenant_id: uuid.UUID, kind: str) -> None:
    if not db.scalar(select(Item).where(Item.tenant_id == tenant_id).limit(1)):
        {"abbigliamento": abbigliamento, "panetteria": panetteria, "ferramenta": ferramenta, "salone": salone,
         "barber": barber}[kind](Loader(db, tenant_id))
    extras(db, tenant_id, kind)
