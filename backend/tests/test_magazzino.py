import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

from tests.conftest import activate_and_login, make_tenant

M = "/api/magazzino"


def setup(client, admin_headers, plan="PRO"):
    t = make_tenant(client, admin_headers, "Magazzino Srl", plan=plan, sector="Generico")
    h = activate_and_login(client, t)
    mk = lambda body: client.post("/api/anagrafiche/articoli", headers=h, json=body).json()  # noqa: E731
    items = {
        "vite": mk({"code": "VITE", "description": "Vite", "unit": "PZ", "min_stock": "50"}),
        "farina": mk({"code": "FARINA", "description": "Farina", "unit": "KG", "lot_managed": True, "shelf_life_days": 100}),
        "trapano": mk({"code": "TRAP", "description": "Trapano", "serial_managed": True, "warranty_months": 24}),
        "tshirt": mk({"code": "TS", "description": "T-shirt", "variants": [
            {"code": "TS-BIA-M", "size": "M", "color": "Bianco"}, {"code": "TS-BIA-L", "size": "L", "color": "Bianco"},
            {"code": "TS-NER-M", "size": "M", "color": "Nero"}]}),
        "servizio": mk({"code": "SERV", "description": "Montaggio", "item_type": "servizio", "stock_managed": False}),
    }
    items["kit"] = mk({"code": "KIT", "description": "Kit viti", "components": [{"component_id": items["vite"]["id"], "quantity": "10"}]})
    wh = client.get(f"{M}/magazzini", headers=h).json()["rows"][0]["id"]
    return h, items, wh


def op(client, h, kind, wh, lines, **extra):
    return client.post(f"{M}/movimenti", headers=h, json={"kind": kind, "warehouse_id": wh, "lines": lines, **extra})


def stock(client, h, item_id):
    return client.get(f"{M}/giacenze/{item_id}", headers=h).json()


def test_carico_scarico_e_costo_medio(client, admin_headers):
    h, it, wh = setup(client, admin_headers)
    assert op(client, h, "carico", wh, [{"item_id": it["vite"]["id"], "quantity": "100", "unit_cost": "0.10"}]).status_code == 201
    assert op(client, h, "carico", wh, [{"item_id": it["vite"]["id"], "quantity": "100", "unit_cost": "0.20"}]).status_code == 201
    d = stock(client, h, it["vite"]["id"])
    assert Decimal(d["warehouses"][0]["on_hand"]) == 200 and Decimal(d["item"]["avg_cost"]) == Decimal("0.15")
    assert Decimal(d["item"]["last_cost"]) == Decimal("0.20")
    op(client, h, "scarico", wh, [{"item_id": it["vite"]["id"], "quantity": "170"}])
    lst = client.get(f"{M}/giacenze?filtro=sotto_scorta", headers=h).json()
    assert [r["code"] for r in lst["rows"]] == ["VITE"]  # 30 < scorta minima 50
    # servizio: nessun movimento; kit: scarica i componenti
    op(client, h, "scarico", wh, [{"item_id": it["kit"]["id"], "quantity": "2"}])
    assert Decimal(stock(client, h, it["vite"]["id"])["warehouses"][0]["on_hand"]) == 10
    assert op(client, h, "carico", wh, [{"item_id": it["kit"]["id"], "quantity": "1"}]).status_code == 422


def test_giacenza_negativa_bloccabile(client, admin_headers):
    h, it, wh = setup(client, admin_headers)
    assert op(client, h, "scarico", wh, [{"item_id": it["vite"]["id"], "quantity": "5"}]).status_code == 201  # consentito di default
    client.put(f"{M}/impostazioni", headers=h, json={"allow_negative": False})
    r = op(client, h, "scarico", wh, [{"item_id": it["vite"]["id"], "quantity": "1"}])
    assert r.status_code == 422 and "insufficiente" in r.json()["detail"]
    # operazione con più righe: se una fallisce non si registra nulla
    r = op(client, h, "carico", wh, [{"item_id": it["vite"]["id"], "quantity": "10"}, {"item_id": it["farina"]["id"], "quantity": "5"}])
    assert r.status_code == 422  # farina senza lotto
    assert Decimal(stock(client, h, it["vite"]["id"])["warehouses"][0]["on_hand"]) == -5


def test_lotti_fefo(client, admin_headers):
    h, it, wh = setup(client, admin_headers)
    f = it["farina"]["id"]
    today = date.today()
    op(client, h, "carico", wh, [{"item_id": f, "quantity": "10", "lot_number": "l-tardi", "expiry_date": str(today + timedelta(days=60))},
                                 {"item_id": f, "quantity": "10", "lot_number": "L-PRESTO", "expiry_date": str(today + timedelta(days=5))},
                                 {"item_id": f, "quantity": "4", "lot_number": "L-AUTO"}])  # scadenza da durata standard
    r = op(client, h, "scarico", wh, [{"item_id": f, "quantity": "12"}])  # 10 dal primo in scadenza + 2 dal successivo
    assert r.status_code == 201 and r.json()["movements"] == 2
    lots = {l["lot_number"]: l for l in stock(client, h, f)["lots"]}
    assert "L-PRESTO" not in lots and Decimal(lots["L-TARDI"]["on_hand"]) == 8
    assert lots["L-AUTO"]["expiry_date"] == str(today + timedelta(days=100))
    assert Decimal(lots["L-AUTO"]["on_hand"]) == 4
    expiring = client.get(f"{M}/lotti?entro_giorni=70", headers=h).json()
    assert [x["lot_number"] for x in expiring] == ["L-TARDI"]
    assert op(client, h, "scarico", wh, [{"item_id": f, "quantity": "100"}]).status_code == 422


def test_matricole_e_garanzia(client, admin_headers):
    h, it, wh = setup(client, admin_headers)
    t = it["trapano"]["id"]
    assert op(client, h, "carico", wh, [{"item_id": t, "quantity": "2", "serials": ["sn1", "SN2"]}]).status_code == 201
    assert op(client, h, "carico", wh, [{"item_id": t, "quantity": "1", "serials": ["SN1"]}]).status_code == 422  # già presente
    assert op(client, h, "carico", wh, [{"item_id": t, "quantity": "2", "serials": ["SN9"]}]).status_code == 422  # numero errato
    op(client, h, "scarto", wh, [{"item_id": t, "quantity": "1", "serials": ["SN2"]}])
    found = client.get(f"{M}/matricole?q=SN2", headers=h).json()[0]
    assert found["status"] == "dismesso" and len(found["history"]) == 2
    d = stock(client, h, t)
    assert Decimal(d["warehouses"][0]["on_hand"]) == 1 and {x["serial_number"]: x["status"] for x in d["serials"]} == {"SN1": "disponibile", "SN2": "dismesso"}


def test_varianti_griglia_e_trasferimento(client, admin_headers):
    h, it, wh = setup(client, admin_headers)
    ts = client.get(f"/api/anagrafiche/articoli/{it['tshirt']['id']}", headers=h).json()
    v = {x["code"]: x["id"] for x in ts["variants"]}
    assert op(client, h, "carico", wh, [{"item_id": ts["id"], "quantity": "3"}]).status_code == 422  # serve la variante
    op(client, h, "carico", wh, [{"item_id": ts["id"], "variant_id": v["TS-BIA-M"], "quantity": "5"},
                                 {"item_id": ts["id"], "variant_id": v["TS-NER-M"], "quantity": "2"}])
    # punto vendita con magazzino proprio (creato in automatico) e trasferimento
    r = client.post(f"{M}/punti-vendita", headers=h, json={"code": "NEG2", "name": "Negozio centro"})
    assert r.status_code == 201
    stores = client.get(f"{M}/punti-vendita", headers=h).json()
    wh2 = stores[0]["warehouse_id"]
    assert wh2 != wh
    r = client.post(f"{M}/trasferimenti", headers=h, json={"from_warehouse_id": wh, "to_warehouse_id": wh2,
                    "lines": [{"item_id": ts["id"], "variant_id": v["TS-BIA-M"], "quantity": "2"}]})
    assert r.status_code == 201 and r.json()["movements"] == 2
    grid = {x["code"]: x["stock"] for x in stock(client, h, ts["id"])["grid"]["variants"]}
    assert Decimal(grid["TS-BIA-M"][wh]) == 3 and Decimal(grid["TS-BIA-M"][wh2]) == 2 and grid["TS-BIA-L"] == {}
    # secondo punto vendita che condivide il magazzino comune
    client.post(f"{M}/punti-vendita", headers=h, json={"code": "NEG3", "name": "Corner", "warehouse_id": wh})
    client.post(f"{M}/punti-vendita", headers=h, json={"code": "NEG1", "name": "Sede", "warehouse_id": wh})
    shared = {s["code"]: s["shared_warehouse"] for s in client.get(f"{M}/punti-vendita", headers=h).json()}
    assert shared == {"NEG1": True, "NEG2": False, "NEG3": True}


def test_limite_magazzini(client, admin_headers):
    h, it, wh = setup(client, admin_headers, plan="BASE")  # BASE: 1 magazzino
    r = client.post(f"{M}/magazzini", headers=h, json={"code": "MAG2", "name": "Secondo"})
    assert r.status_code == 403


def test_inventario_completo(client, admin_headers):
    h, it, wh = setup(client, admin_headers)
    ts = client.get(f"/api/anagrafiche/articoli/{it['tshirt']['id']}", headers=h).json()
    v = {x["code"]: x["id"] for x in ts["variants"]}
    op(client, h, "carico", wh, [{"item_id": it["vite"]["id"], "quantity": "100", "unit_cost": "0.1"},
                                 {"item_id": it["farina"]["id"], "quantity": "10", "lot_number": "A1"},
                                 {"item_id": it["trapano"]["id"], "quantity": "2", "serials": ["S1", "S2"]},
                                 {"item_id": ts["id"], "variant_id": v["TS-BIA-M"], "quantity": "4"},
                                 {"item_id": ts["id"], "variant_id": v["TS-NER-M"], "quantity": "3"}])
    s = client.post(f"{M}/inventari", headers=h, json={"name": "Fine anno", "warehouse_id": wh}).json()
    # conteggi dallo smartphone (uno reinviato due volte)
    cu = str(uuid.uuid4())
    counts = [
        {"client_uuid": cu, "item_id": it["vite"]["id"], "quantity": "60"},
        {"client_uuid": cu, "item_id": it["vite"]["id"], "quantity": "60"},
        {"client_uuid": str(uuid.uuid4()), "item_id": it["vite"]["id"], "quantity": "35"},
        {"client_uuid": str(uuid.uuid4()), "item_id": it["farina"]["id"], "quantity": "8", "lot_number": "a1"},
        {"client_uuid": str(uuid.uuid4()), "item_id": it["farina"]["id"], "quantity": "3", "lot_number": "B2",
         "expiry_date": str(date.today() + timedelta(days=30))},
        {"client_uuid": str(uuid.uuid4()), "item_id": it["trapano"]["id"], "quantity": "1", "serial_number": "S1"},
        {"client_uuid": str(uuid.uuid4()), "item_id": it["trapano"]["id"], "quantity": "1", "serial_number": "S3"},
        {"client_uuid": str(uuid.uuid4()), "item_id": ts["id"], "variant_id": v["TS-BIA-M"], "quantity": "5"},
    ]
    assert client.post(f"{M}/inventari/{s['id']}/conteggi", headers=h, json=counts).json()["added"] == 7
    d = client.get(f"{M}/inventari/{s['id']}", headers=h).json()
    rows = {(r["code"], r["variant_code"], r["lot_number"]): r for r in d["rows"]}
    assert Decimal(rows[("VITE", None, None)]["counted"]) == 95
    assert rows[("TS", "TS-NER-M", None)]["counted"] is None  # non contata: nessun azzeramento automatico
    assert rows[("TS", "TS-NER-M", None)]["is_counted"] is False and d["totals"]["rows_uncounted"] >= 1
    # revisione: scarto un conteggio della vite, correggo a mano la t-shirt bianca
    vite_counts = rows[("VITE", None, None)]["counts"]
    small = next(c["id"] for c in vite_counts if c["quantity"] == "35.0000")
    d = client.post(f"{M}/inventari/{s['id']}/accetta", headers=h, json={"count_ids": [small], "accepted": False}).json()
    assert Decimal(next(r for r in d["rows"] if r["code"] == "VITE")["counted"]) == 60
    d = client.put(f"{M}/inventari/{s['id']}/quantita", headers=h, json=[{"item_id": ts["id"], "variant_id": v["TS-BIA-M"], "quantity": "6"}]).json()
    assert Decimal(next(r for r in d["rows"] if r["variant_code"] == "TS-BIA-M")["counted"]) == 6
    # import da Excel
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.append(["Codice", "Qtà"])
    wb.active.append(["TS-NER-M", 1])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(f"{M}/inventari/{s['id']}/import", headers=h, files={"file": ("conta.xlsx", buf.getvalue())})
    assert r.json()["added"] == 1, r.text
    # chiusura come inventario concluso: i non contati vengono azzerati (S2 non letta → dismessa)
    r = client.post(f"{M}/inventari/{s['id']}/chiudi", headers=h, json={"zero_uncounted": True})
    assert r.status_code == 200 and r.json()["status"] == "chiuso"
    assert Decimal(stock(client, h, it["vite"]["id"])["warehouses"][0]["on_hand"]) == 60
    f = {l["lot_number"]: Decimal(l["on_hand"]) for l in stock(client, h, it["farina"]["id"])["lots"]}
    assert f == {"A1": 8, "B2": 3}
    tr = {x["serial_number"]: x["status"] for x in stock(client, h, it["trapano"]["id"])["serials"]}
    assert tr == {"S1": "disponibile", "S2": "dismesso", "S3": "disponibile"}
    grid = {x["code"]: x["stock"] for x in stock(client, h, ts["id"])["grid"]["variants"]}
    assert Decimal(grid["TS-BIA-M"][wh]) == 6 and Decimal(grid["TS-NER-M"][wh]) == 1
    assert client.post(f"{M}/inventari/{s['id']}/conteggi", headers=h, json=counts).status_code == 409


def test_inventario_parziale_non_azzera(client, admin_headers):
    h, it, wh = setup(client, admin_headers)
    op(client, h, "carico", wh, [{"item_id": it["vite"]["id"], "quantity": "100"},
                                 {"item_id": it["trapano"]["id"], "quantity": "2", "serials": ["S1", "S2"]}])
    s = client.post(f"{M}/inventari", headers=h, json={"name": "Parziale", "warehouse_id": wh}).json()
    client.post(f"{M}/inventari/{s['id']}/conteggi", headers=h, json=[
        {"client_uuid": str(uuid.uuid4()), "item_id": it["trapano"]["id"], "quantity": "1", "serial_number": "S1"}])
    r = client.post(f"{M}/inventari/{s['id']}/chiudi", headers=h, json={"zero_uncounted": False})
    assert r.status_code == 200
    assert Decimal(stock(client, h, it["vite"]["id"])["warehouses"][0]["on_hand"]) == 100  # non contato: invariato
    assert {x["serial_number"]: x["status"] for x in stock(client, h, it["trapano"]["id"])["serials"]} == {"S1": "disponibile", "S2": "disponibile"}


def test_ricerca_scanner(client, admin_headers):
    h, it, wh = setup(client, admin_headers)
    bc = client.get("/api/anagrafiche/articoli/genera-barcode", headers=h).json()["barcode"]
    ts = client.get(f"/api/anagrafiche/articoli/{it['tshirt']['id']}", headers=h).json()
    body = {k: ts[k] for k in ("description", "variants")}
    body["barcodes"] = [{"barcode": bc, "variant_code": "TS-NER-M"}]
    client.put(f"/api/anagrafiche/articoli/{ts['id']}", headers=h, json=body)
    r = client.get(f"{M}/cerca?code={bc}", headers=h).json()
    assert r[0]["code"] == "TS" and r[0]["variant_id"] == next(x["id"] for x in ts["variants"] if x["code"] == "TS-NER-M")
    assert client.get(f"{M}/cerca?code=https://negozio.it/p/VITE", headers=h).json()[0]["code"] == "VITE"  # QR con URL
    assert client.get(f"{M}/cerca?code=fari", headers=h).json()[0]["code"] == "FARINA"


def test_modulo_bloccato_senza_pacchetto(client, admin_headers, owner_db):
    from sqlalchemy import text
    h, it, wh = setup(client, admin_headers)
    owner_db.execute(text("UPDATE plans SET modules = array_remove(modules, 'magazzino')"))
    owner_db.commit()
    assert client.get(f"{M}/giacenze", headers=h).status_code == 403


def test_ricerca_articoli_per_i_documenti(client, admin_headers):
    """Nei documenti di vendita e acquisto la ricerca per descrizione trova anche servizi e kit; nelle conte no."""
    h, it, wh = setup(client, admin_headers)
    assert client.get(f"{M}/cerca?code=montag", headers=h).json() == []
    found = client.get(f"{M}/cerca?code=montag&tutti=true", headers=h).json()
    assert [r["code"] for r in found] == ["SERV"]
    assert [r["code"] for r in client.get(f"{M}/cerca?code=SERV", headers=h).json()] == ["SERV"]  # il codice esatto vale sempre
