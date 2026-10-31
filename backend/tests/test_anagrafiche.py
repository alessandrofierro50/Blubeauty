from decimal import Decimal

from app.anagrafiche import pricing
from app.anagrafiche.bootstrap import field_groups_for_sector
from app.anagrafiche.demo import demo_vat
from app.anagrafiche.validators import make_internal_ean13, valid_ean, valid_tax_code_it, valid_vat_it
from tests.conftest import activate_and_login, make_tenant


def setup(client, admin_headers, name="Ferramenta Test", sector="Ferramenta", plan="BASE"):
    t = make_tenant(client, admin_headers, name, plan=plan, sector=sector)
    return t, activate_and_login(client, t)


def table(client, h, kind):
    return client.get(f"/api/anagrafiche/tabelle/{kind}", headers=h).json()


# ---------------------------------------------------------------- funzioni pure


def test_validatori():
    assert valid_vat_it("01114601006")
    assert not valid_vat_it("01114601007")
    assert valid_tax_code_it("RSSMRA85T10A562S")
    assert not valid_tax_code_it("RSSMRA85T10A562X")
    ean = make_internal_ean13("200", 1)
    assert len(ean) == 13 and valid_ean(ean)
    assert valid_vat_it(demo_vat("0712345678"))


def test_prezzi():
    assert pricing.cascade(Decimal("100"), Decimal("10"), Decimal("5")) == Decimal("85.5000")
    assert pricing.net_of_vat(Decimal("122"), Decimal("22"), True) == Decimal("100.0000")
    assert pricing.markup_margin(Decimal("150"), Decimal("100")) == (Decimal("50.00"), Decimal("33.33"))
    assert pricing.price_from_markup(Decimal("10"), Decimal("50"), Decimal("22"), True) == Decimal("18.30")


def test_gruppi_campi_per_settore():
    assert field_groups_for_sector("Abbigliamento")["varianti"] is True
    assert field_groups_for_sector("Panetteria")["lotti"] is True
    assert field_groups_for_sector("Panetteria")["matricole"] is False
    assert field_groups_for_sector("Ferramenta")["matricole"] is True


# ---------------------------------------------------------------- API


def test_dati_iniziali_e_impostazioni(client, admin_headers):
    _, h = setup(client, admin_headers, sector="Panetteria")
    assert {v["code"] for v in table(client, h, "aliquote-iva")} >= {"22", "10", "4", "N4"}
    assert any(p["code"] == "BB30" for p in table(client, h, "pagamenti"))
    s = client.get("/api/anagrafiche/settings", headers=h).json()
    assert s["field_groups"]["lotti"] is True and s["field_groups"]["varianti"] is False
    r = client.put("/api/anagrafiche/settings/field-groups", headers=h, json={"field_groups": {"lotti": True, "varianti": True}})
    assert r.json()["varianti"] is True


def test_cliente_con_validazioni(client, admin_headers):
    _, h = setup(client, admin_headers)
    bad = client.post("/api/anagrafiche/soggetti", headers=h, json={"name": "Errata Srl", "vat_number": "12345678901"})
    assert bad.status_code == 422 and "Partita IVA" in bad.json()["detail"]["message"]
    r = client.post("/api/anagrafiche/soggetti", headers=h, json={
        "name": "Edil Test Srl", "vat_number": "IT 01114601006", "sdi_code": "abc1234", "province": "le",
        "zip_code": "73100", "addresses": [{"label": "Cantiere", "address": "Via Mare 1", "city": "Otranto"}]})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["code"] == "C00001" and p["vat_number"] == "01114601006" and p["sdi_code"] == "ABC1234"
    assert p["province"] == "LE" and len(p["addresses"]) == 1
    # privato: codice SDI 0000000 automatico, nome da cognome e nome
    r = client.post("/api/anagrafiche/soggetti", headers=h, json={"person_type": "privato", "first_name": "Anna", "last_name": "Verdi"})
    assert r.json()["name"] == "Verdi Anna" and r.json()["sdi_code"] == "0000000"
    # fornitore: codice F
    r = client.post("/api/anagrafiche/soggetti", headers=h, json={"name": "Grossista Srl", "is_customer": False, "is_supplier": True, "vat_number": demo_vat("0712345678")})
    assert r.json()["code"] == "F00001"
    lst = client.get("/api/anagrafiche/soggetti?tipo=fornitori", headers=h).json()
    assert lst["total"] == 1
    assert client.get("/api/anagrafiche/soggetti?q=edil", headers=h).json()["total"] == 1


def _supplier(client, h):
    return client.post("/api/anagrafiche/soggetti", headers=h, json={
        "name": "Fornitore Srl", "is_customer": False, "is_supplier": True, "vat_number": demo_vat("0612345678")}).json()


def test_articolo_completo(client, admin_headers):
    _, h = setup(client, admin_headers)
    lists = {p["code"]: p["id"] for p in table(client, h, "listini")}
    vat22 = next(v["id"] for v in table(client, h, "aliquote-iva") if v["code"] == "22")
    sup = _supplier(client, h)
    bc = client.get("/api/anagrafiche/articoli/genera-barcode", headers=h).json()["barcode"]
    body = {
        "description": "Trapano 18V", "vat_rate_id": vat22, "last_cost": "80", "serial_managed": True,
        "warranty_months": 24, "unit": "PZ",
        "barcodes": [{"barcode": bc}],
        "units": [{"unit": "CT", "factor": "4"}],
        "suppliers": [{"supplier_id": sup["id"], "supplier_code": "TR-18", "last_cost": "80"}],
        "prices": [{"price_list_id": lists["PUBBLICO"], "price": "146.40"},
                   {"price_list_id": lists["PUBBLICO"], "min_qty": "5", "price": "134.20"},
                   {"price_list_id": lists["RIVEND"], "price": "120", "discount1": "10"}],
    }
    r = client.post("/api/anagrafiche/articoli", headers=h, json=body)
    assert r.status_code == 201, r.text
    it = r.json()
    assert it["code"] == "ART00001"
    pub = next(p for p in it["prices"] if p["price_list_code"] == "PUBBLICO" and Decimal(p["min_qty"]) == 0)
    assert Decimal(pub["net_ex_vat"]) == Decimal("120.0000") and Decimal(pub["markup"]) == Decimal("50.00")
    riv = next(p for p in it["prices"] if p["price_list_code"] == "RIVEND")
    assert Decimal(riv["net_price"]) == Decimal("108.0000")
    # ricerca per codice a barre e per codice fornitore
    assert client.get(f"/api/anagrafiche/articoli?q={bc}", headers=h).json()["total"] == 1
    assert client.get("/api/anagrafiche/articoli?q=TR-18", headers=h).json()["total"] == 1
    assert client.get(f"/api/anagrafiche/articoli/cerca-barcode/{bc}", headers=h).json()["code"] == "ART00001"
    # modifica: sostituisce le righe figlie senza conflitti sui vincoli unici
    body["prices"][0]["price"] = "150"
    r = client.put(f"/api/anagrafiche/articoli/{it['id']}", headers=h, json=body)
    assert r.status_code == 200, r.text
    assert len(r.json()["prices"]) == 3 and len(r.json()["barcodes"]) == 1


def test_varianti_e_barcode_duplicato(client, admin_headers):
    _, h = setup(client, admin_headers, name="Moda Test", sector="Abbigliamento")
    bc1 = client.get("/api/anagrafiche/articoli/genera-barcode", headers=h).json()["barcode"]
    r = client.post("/api/anagrafiche/articoli", headers=h, json={
        "code": "TSHIRT", "description": "T-shirt",
        "variants": [{"code": "TSHIRT-S", "size": "S"}, {"code": "TSHIRT-M", "size": "M"}],
        "barcodes": [{"barcode": bc1, "variant_code": "TSHIRT-M"}]})
    assert r.status_code == 201, r.text
    assert r.json()["has_variants"] and r.json()["barcodes"][0]["variant_code"] == "TSHIRT-M"
    look = client.get(f"/api/anagrafiche/articoli/cerca-barcode/{bc1}", headers=h).json()
    assert look["variant_code"] == "TSHIRT-M"
    dup = client.post("/api/anagrafiche/articoli", headers=h, json={"description": "Altro", "barcodes": [{"barcode": bc1}]})
    assert dup.status_code == 409
    wrong = client.post("/api/anagrafiche/articoli", headers=h, json={"description": "X", "barcodes": [{"barcode": "8001234567891"}]})
    assert wrong.status_code == 422


def test_kit_e_regole(client, admin_headers):
    _, h = setup(client, admin_headers)
    a = client.post("/api/anagrafiche/articoli", headers=h, json={"description": "Vite"}).json()
    b = client.post("/api/anagrafiche/articoli", headers=h, json={"description": "Tassello"}).json()
    kit = client.post("/api/anagrafiche/articoli", headers=h, json={
        "description": "Kit", "components": [{"component_id": a["id"], "quantity": "10"}, {"component_id": b["id"], "quantity": "10"}]})
    assert kit.status_code == 201 and kit.json()["is_kit"] and len(kit.json()["components"]) == 2
    both = client.post("/api/anagrafiche/articoli", headers=h, json={"description": "X", "lot_managed": True, "serial_managed": True})
    assert both.status_code == 422


def test_tabelle_non_eliminabili_se_usate(client, admin_headers):
    _, h = setup(client, admin_headers)
    cat = client.post("/api/anagrafiche/tabelle/categorie", headers=h, json={"name": "Utensili"}).json()
    client.post("/api/anagrafiche/articoli", headers=h, json={"description": "Martello", "category_id": cat["id"]})
    r = client.delete(f"/api/anagrafiche/tabelle/categorie/{cat['id']}", headers=h)
    assert r.status_code == 409


def test_import_export_csv(client, admin_headers):
    _, h = setup(client, admin_headers)
    csv_text = "code;description;unit;category;brand;vat;price;last_cost;barcode\n" \
               "V001;Viti 4x40;CF;Viteria;Ferrox;22;6,90;2,40;\n" \
               ";Martello 500 g;PZ;Utensili;;22;12,50;5,00;\n" \
               "V003;;PZ;;;;;;\n"
    r = client.post("/api/anagrafiche/articoli-import", headers=h, json={"content": csv_text})
    res = r.json()
    assert res["created"] == 2 and len(res["errors"]) == 1
    exp = client.get("/api/anagrafiche/articoli-export.csv", headers=h)
    assert "Viti 4x40" in exp.text and "6,9" in exp.text
    pcsv = "name;vat_number;city;province\nCliente Uno Srl;01114601006;Lecce;LE\nCliente Errato;123;Bari;BA\n"
    r = client.post("/api/anagrafiche/soggetti-import", headers=h, json={"content": pcsv})
    assert r.json()["created"] == 1 and len(r.json()["errors"]) == 1


def test_ruolo_cassa_solo_lettura(client, admin_headers):
    t, h = setup(client, admin_headers, plan="PLUS")
    u = client.post("/api/app/users", headers=h, json={"full_name": "Cassiera", "email": "cassa@test.it", "role": "cassa"}).json()
    token = u["activation_link"].split("token=")[1]
    hc = {"Authorization": "Bearer " + client.post("/api/auth/activate", json={"token": token, "password": "password-123"}).json()["token"]}
    assert client.get("/api/anagrafiche/articoli", headers=hc).status_code == 200
    assert client.post("/api/anagrafiche/articoli", headers=hc, json={"description": "X"}).status_code == 403


def test_isolamento_anagrafiche(client, admin_headers):
    _, ha = setup(client, admin_headers, name="Azienda A")
    _, hb = setup(client, admin_headers, name="Azienda B")
    it = client.post("/api/anagrafiche/articoli", headers=ha, json={"description": "Segreto di A"}).json()
    assert client.get("/api/anagrafiche/articoli", headers=hb).json()["total"] == 0
    assert client.get(f"/api/anagrafiche/articoli/{it['id']}", headers=hb).status_code == 404
    # stesso codice consentito in aziende diverse
    assert client.post("/api/anagrafiche/articoli", headers=hb, json={"code": it["code"], "description": "B"}).status_code == 201


def test_import_excel_guidato_ed_export(client, admin_headers):
    import io

    import openpyxl
    _, h = setup(client, admin_headers)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Cod. Art.", "Descrizione articolo", "Reparto", "Sottogruppo", "Marchio", "IVA", "Prezzo al pubblico", "Costo acquisto", "EAN", "Fornitore", "Cod fornitore", "Colonna inutile"])
    ws.append(["A1", "Pinza universale", "Utensili", "Manuali", "Ferrox", 22, 9.9, 3.2, "", "Grossista Sud", "GS-1", "x"])
    ws.append(["A2", "Cacciavite", "Utensili", "Manuali", "Ferrox", "22%", "4,50", "1,10", "", "Grossista Sud", "GS-2", "y"])
    ws.append(["A3", "", "Utensili", "", "", "", "", "", "", "", "", ""])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/api/anagrafiche/import/anteprima?tipo=articoli", headers=h,
                    files={"file": ("listino.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    prev = r.json()
    m = prev["mapping"]
    assert m["0"] == "code" and m["1"] == "description" and m["2"] == "category" and m["3"] == "subcategory"
    assert m["4"] == "brand" and m["6"] == "price" and m["7"] == "last_cost" and m["9"] == "supplier" and m["10"] == "supplier_code"
    assert m["11"] is None and prev["total"] == 3
    rows = [{m[str(i)]: v for i, v in enumerate(row) if m[str(i)]} for row in prev["rows"]]
    res = client.post("/api/anagrafiche/articoli-import", headers=h, json={"rows": rows}).json()
    assert res["created"] == 2 and res["errors_total"] == 1
    lst = client.get("/api/anagrafiche/articoli?q=Pinza", headers=h).json()["rows"][0]
    assert lst["category"] == "Manuali" and lst["price"] == "9.9000" and lst["brand"] == "Ferrox"
    assert client.get("/api/anagrafiche/articoli?q=GS-2", headers=h).json()["total"] == 1  # codice fornitore collegato
    assert client.get("/api/anagrafiche/soggetti?tipo=fornitori&q=Grossista", headers=h).json()["total"] == 1
    x = client.get("/api/anagrafiche/articoli-export.xlsx", headers=h)
    assert x.status_code == 200
    wb2 = openpyxl.load_workbook(io.BytesIO(x.content))
    ws2 = wb2.active
    assert ws2.cell(1, 2).value == "Descrizione" and ws2.max_row == 3
    assert client.get("/api/anagrafiche/soggetti-export.xlsx", headers=h).status_code == 200
