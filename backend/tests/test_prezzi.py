import io
from datetime import date, timedelta
from decimal import Decimal

from PIL import Image

from tests.conftest import activate_and_login, make_tenant
from tests.test_anagrafiche import table


def setup(client, admin_headers):
    t = make_tenant(client, admin_headers, "Prezzi Srl", sector="Ferramenta")
    h = activate_and_login(client, t)
    lists = {p["code"]: p["id"] for p in table(client, h, "listini")}
    vat22 = next(v["id"] for v in table(client, h, "aliquote-iva") if v["code"] == "22")
    cat = client.post("/api/anagrafiche/tabelle/categorie", headers=h, json={"name": "Utensili"}).json()
    sub = client.post("/api/anagrafiche/tabelle/categorie", headers=h, json={"name": "Trapani", "parent_id": cat["id"]}).json()
    item = client.post("/api/anagrafiche/articoli", headers=h, json={
        "description": "Trapano", "vat_rate_id": vat22, "last_cost": "50", "category_id": sub["id"],
        "prices": [{"price_list_id": lists["PUBBLICO"], "price": "122"},           # 100 + IVA
                   {"price_list_id": lists["PUBBLICO"], "min_qty": "10", "price": "109.80"},  # 90 + IVA
                   {"price_list_id": lists["RIVEND"], "price": "80"}]}).json()
    ccat = client.post("/api/anagrafiche/tabelle/categorie-clienti", headers=h, json={"name": "Ingrosso"}).json()
    cust = client.post("/api/anagrafiche/soggetti", headers=h, json={
        "name": "Cliente Srl", "vat_number": "01114601006", "discount1": "10", "customer_category_id": ccat["id"]}).json()
    return h, lists, cat, item, cust, ccat


def price(client, h, item, party=None, qty=1, on=None):
    q = f"/api/anagrafiche/prezzo?item_id={item['id']}&qty={qty}"
    if party:
        q += f"&party_id={party['id']}"
    if on:
        q += f"&on={on}"
    return client.get(q, headers=h).json()


def test_listino_scaglioni_e_sconti_cliente(client, admin_headers):
    h, lists, cat, item, cust, _ = setup(client, admin_headers)
    p = price(client, h, item)
    assert p["source"] == "listino" and Decimal(p["unit_price"]) == Decimal("100") and p["unit_price_vat_included"] == "122.00"
    assert Decimal(price(client, h, item, qty=10)["unit_price"]) == Decimal("90")
    pc = price(client, h, item, cust)
    assert Decimal(pc["unit_price"]) == Decimal("90") and pc["discounts"] == ["10.00"]  # 100 - 10%
    assert Decimal(pc["markup"]) == Decimal("80.00")  # su costo 50


def test_promozione_vince_se_conviene(client, admin_headers):
    h, lists, cat, item, cust, ccat = setup(client, admin_headers)
    today = date.today()
    r = client.post("/api/anagrafiche/promozioni", headers=h, json={
        "name": "Promo autunno", "date_from": str(today - timedelta(days=1)), "date_to": str(today + timedelta(days=10)),
        "item_scope": "categorie", "category_ids": [cat["id"]], "customer_scope": "categorie",
        "customer_category_ids": [ccat["id"]], "price_type": "sconto", "value": "20"})
    assert r.status_code == 201, r.text
    assert r.json()["state"] == "attiva"
    p = price(client, h, item, cust)  # categoria padre "Utensili" vale anche per "Trapani"
    assert p["source"] == "promozione" and p["source_label"] == "Promo autunno" and Decimal(p["unit_price"]) == Decimal("80")
    assert any(a["source"] == "listino" for a in p["alternatives"])
    # senza cliente (o cliente di un'altra categoria) la promo non vale
    assert price(client, h, item)["source"] == "listino"
    # fuori periodo non vale
    assert price(client, h, item, cust, on=str(today + timedelta(days=30)))["source"] == "listino"


def test_promo_prezzo_fisso_iva_inclusa(client, admin_headers):
    h, lists, cat, item, cust, _ = setup(client, admin_headers)
    today = date.today()
    client.post("/api/anagrafiche/promozioni", headers=h, json={
        "name": "Sottocosto", "date_from": str(today), "date_to": str(today), "item_scope": "articoli",
        "item_ids": [item["id"]], "price_type": "prezzo", "value": "61", "vat_included": True})
    p = price(client, h, item)
    assert p["source"] == "promozione" and Decimal(p["unit_price"]) == Decimal("50")


def test_prezzo_netto_cliente_ha_priorita(client, admin_headers):
    h, lists, cat, item, cust, _ = setup(client, admin_headers)
    today = date.today()
    r = client.put(f"/api/anagrafiche/soggetti/{cust['id']}/prezzi", headers=h, json=[
        {"item_id": item["id"], "net_price": "70"},
        {"item_id": item["id"], "min_qty": "20", "net_price": "65"},
        {"item_id": item["id"], "net_price": "60", "valid_from": str(today + timedelta(days=5))}])
    assert r.status_code == 200 and len(r.json()) == 3
    assert Decimal(price(client, h, item, cust)["unit_price"]) == Decimal("70")
    assert Decimal(price(client, h, item, cust, qty=25)["unit_price"]) == Decimal("65")
    assert price(client, h, item, cust)["source"] == "cliente"
    # aumento del 10%
    client.post(f"/api/anagrafiche/soggetti/{cust['id']}/prezzi/variazione", headers=h, json={"percent": "10"})
    assert Decimal(price(client, h, item, cust)["unit_price"]) == Decimal("77")
    # copia su un altro cliente
    other = client.post("/api/anagrafiche/soggetti", headers=h, json={"name": "Altro Srl", "vat_number": "01114601006"}).json()
    assert client.post(f"/api/anagrafiche/soggetti/{other['id']}/prezzi/copia-da/{cust['id']}", headers=h).json()["copied"] == 3
    assert len(client.get(f"/api/anagrafiche/articoli/{item['id']}/prezzi-clienti", headers=h).json()) == 6


def test_validazione_promozioni(client, admin_headers):
    h, *_ = setup(client, admin_headers)
    today = str(date.today())
    bad = client.post("/api/anagrafiche/promozioni", headers=h, json={
        "name": "Vuota", "date_from": today, "date_to": today, "item_scope": "articoli", "price_type": "sconto", "value": "5"})
    assert bad.status_code == 422


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2000, 1000), (30, 91, 216)).save(buf, "PNG")
    return buf.getvalue()


def test_immagini_articolo(client, admin_headers, tmp_path, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "media_dir", str(tmp_path))
    h, lists, cat, item, cust, _ = setup(client, admin_headers)
    files = [("files", ("a.png", _png(), "image/png")), ("files", ("b.png", _png(), "image/png"))]
    r = client.post(f"/api/anagrafiche/articoli/{item['id']}/immagini", headers=h, files=files)
    assert r.status_code == 201, r.text
    imgs = r.json()
    assert len(imgs) == 2
    got = client.get(imgs[0]["url"])
    assert got.status_code == 200 and got.headers["content-type"] == "image/webp"
    assert Image.open(io.BytesIO(got.content)).size == (1600, 800)  # ridimensionata
    # immagine principale e copertina in elenco
    r = client.post(f"/api/anagrafiche/articoli/{item['id']}/immagini/{imgs[1]['id']}/principale", headers=h)
    assert r.json()[0]["id"] == imgs[1]["id"]
    detail = client.get(f"/api/anagrafiche/articoli/{item['id']}", headers=h).json()
    assert detail["image_url"] == imgs[1]["url"]
    lst = client.get("/api/anagrafiche/articoli", headers=h).json()["rows"]
    assert lst[0]["thumb_url"] == imgs[1]["thumb_url"]
    # file non immagine rifiutato, eliminazione
    bad = client.post(f"/api/anagrafiche/articoli/{item['id']}/immagini", headers=h, files=[("files", ("x.txt", b"ciao", "text/plain"))])
    assert bad.status_code == 422
    r = client.delete(f"/api/anagrafiche/articoli/{item['id']}/immagini/{imgs[1]['id']}", headers=h)
    assert len(r.json()) == 1
    assert client.get(imgs[1]["url"]).status_code == 404
    assert client.get("/api/media/../../etc/passwd").status_code == 404


def test_catalogo(client, admin_headers):
    h, lists, cat, item, cust, _ = setup(client, admin_headers)
    other = client.post("/api/anagrafiche/articoli", headers=h, json={
        "description": "Martello", "prices": [{"price_list_id": lists["PUBBLICO"], "price": "12.20"}]}).json()
    excluded = client.post("/api/anagrafiche/articoli", headers=h, json={"description": "Escluso", "category_id": item["category_id"]}).json()
    body = {"name": "Catalogo utensili", "category_ids": [cat["id"]], "include_item_ids": [other["id"]],
            "exclude_item_ids": [excluded["id"]], "price_list_id": lists["PUBBLICO"], "vat_included": True}
    prev = client.post("/api/anagrafiche/cataloghi/anteprima", headers=h, json=body).json()
    names = [i["description"] for g in prev["groups"] for i in g["items"]]
    assert sorted(names) == ["Martello", "Trapano"]  # sottocategoria inclusa, escluso tolto, articolo aggiunto
    trapano = next(i for g in prev["groups"] for i in g["items"] if i["description"] == "Trapano")
    assert trapano["price"] == "122.00" and trapano["group"] == "Utensili › Trapani"
    c = client.post("/api/anagrafiche/cataloghi", headers=h, json={**body, "party_id": cust["id"], "vat_included": False}).json()
    content = client.get(f"/api/anagrafiche/cataloghi/{c['id']}/contenuto", headers=h).json()
    trapano = next(i for g in content["groups"] for i in g["items"] if i["description"] == "Trapano")
    assert trapano["price"] == "90.00"  # prezzi del cliente (sconto 10%) IVA esclusa
    assert "Trapano" in client.get(f"/api/anagrafiche/cataloghi/{c['id']}/export.csv", headers=h).text


def test_allegati_e_intestazione(client, admin_headers, tmp_path, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "media_dir", str(tmp_path))
    h, lists, cat, item, cust, _ = setup(client, admin_headers)
    pdf = b"%PDF-1.4\n%test\n"
    r = client.post(f"/api/anagrafiche/articoli/{item['id']}/allegati?kind=scheda_tecnica", headers=h,
                    files={"file": ("Scheda trapano.pdf", pdf, "application/pdf")})
    assert r.status_code == 201, r.text
    att = r.json()
    assert att["title"] == "Scheda trapano" and att["attach_to_quotes"] is True
    got = client.get(att["url"])
    assert got.status_code == 200 and got.content == pdf and got.headers["content-type"] == "application/pdf"
    bad = client.post(f"/api/anagrafiche/articoli/{item['id']}/allegati", headers=h, files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 422
    fake = client.post(f"/api/anagrafiche/articoli/{item['id']}/allegati", headers=h, files={"file": ("x.pdf", b"ciao", "application/pdf")})
    assert fake.status_code == 422
    client.patch(f"/api/anagrafiche/articoli/{item['id']}/allegati/{att['id']}", headers=h, json={"attach_to_quotes": False})
    assert client.get(f"/api/anagrafiche/articoli/{item['id']}/allegati", headers=h).json()[0]["attach_to_quotes"] is False
    client.delete(f"/api/anagrafiche/articoli/{item['id']}/allegati/{att['id']}", headers=h)
    assert client.get(att["url"]).status_code == 404
    # intestazione e logo
    head = client.get("/api/app/intestazione", headers=h).json()
    assert head["print_settings"]["primary_color"] == "#2340a8" and head["logo_url"] is None
    r = client.post(f"/api/app/azienda/{head['id']}/logo", headers=h, files={"file": ("logo.png", _png(), "image/png")})
    assert r.json()["logo_url"]
    body = {k: head[k] for k in ("name", "vat_number", "city")}
    body.update({"iban": "IT60X0542811101000000123456", "print_settings": {"primary_color": "#C2185B", "footer": "Grazie!", "hacker": 1}})
    r = client.put(f"/api/app/azienda/{head['id']}", headers=h, json=body).json()
    assert r["print_settings"]["primary_color"] == "#C2185B" and "hacker" not in r["print_settings"] and r["iban"].startswith("IT60")
