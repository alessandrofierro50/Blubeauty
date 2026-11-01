"""BluBeauty: ricevuta non fiscale al posto dello scontrino, layout come il documento commerciale, logo e intestazione."""

import io

from PIL import Image

from tests.test_periferiche import done, jobs, with_devices
from tests.test_pos import P, sale


def texts(payload, rt=False):
    """Testi come li stampa il registratore (rt=True: senza intestazione, testi alternativi) o la termica."""
    out = []
    for x in payload["lines"]:
        if rt and x.get("rt_skip"):
            continue
        t = (x.get("rt_text") if rt else None) or x.get("text")
        if t:
            out.append((t, x.get("right")))
    return out


def test_ricevuta_non_fiscale_al_posto_dello_scontrino(client, admin_headers):
    h, reg, pane, acqua, ah, rt, pr, _ = with_devices(client, admin_headers, "Salone Non Fiscale")
    client.post(f"{P}/casse/{reg['id']}/apri", headers=h, json={"opening_float": "50"})
    r = sale(client, h, reg, [{"item_id": acqua["id"], "quantity": "2", "unit_price_gross": "0.40"}],
             [{"method": "contanti", "amount": "5"}], nonfiscal_reason="Buono regalo venduto")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["fiscal"]["nonfiscal"]["reason"] == "Buono regalo venduto" and d["fiscal"]["rt"] is None
    js = jobs(client, ah)
    assert [j["kind"] for j in js] == ["rt.nonfiscal"]  # niente documento commerciale: la ricevuta va sul registratore
    t = texts(js[0]["payload"], rt=True)
    words = [x for x, _ in t]
    assert "RICEVUTA NON FISCALE" in words and words[-1] == "NON VALIDO COME DOC. COMMERCIALE"
    assert ("TOTALE COMPLESSIVO", "0,80") in t and ("Pagamento contante", "5,00") in t and ("Resto", "4,20") in t
    assert any(x == "DESCRIZIONE" for x in words) and "Motivo: Buono regalo venduto" in words
    assert not any("Fiscale Srl" in x or "Salone Non Fiscale" in x for x in words)  # l'intestazione la stampa il registratore
    done(client, ah, js[0])
    # «riprova fiscale» non manda niente al registratore
    client.post(f"{P}/scontrini/{d['id']}/fiscale", headers=h, json={})
    assert jobs(client, ah) == []
    # reso della ricevuta non fiscale: anche il reso è non fiscale
    line = d["lines"][0]
    rr = client.post(f"{P}/casse/{reg['id']}/resi", headers=h, json={"client_uuid": "6c3a3b2e-8a8d-4e0b-9d9d-000000000001", "original_id": d["id"],
                                                                      "lines": [{"item_id": acqua["id"], "origin_line_id": line["id"], "quantity": "1",
                                                                                 "unit_price_gross": "0.40"}]})
    assert rr.status_code == 200, rr.text
    assert rr.json()["fiscal"]["nonfiscal"] and [j["kind"] for j in jobs(client, ah)] == ["rt.nonfiscal"]
    # la fattura non può essere «non fiscale»; la cassa può disattivare la funzione
    body = {k: reg[k] for k in ("code", "name", "store_id", "warehouse_id", "price_list_id", "mode", "cash_account_id", "card_account_id",
                                "quick_keys", "active", "devices")}
    client.put(f"{P}/casse/{reg['id']}", headers=h, json={**body, "settings": {**reg["settings"], "nonfiscal_allowed": False}})
    r = sale(client, h, reg, [{"item_id": acqua["id"], "unit_price_gross": "0.40"}], [{"method": "contanti", "amount": "1"}], nonfiscal_reason="Prova")
    assert r.status_code == 422 and "disattivata" in r.text


def test_logo_intestazione_e_layout(client, admin_headers):
    h, reg, pane, acqua, ah, rt, pr, _ = with_devices(client, admin_headers, "Salone Logo")
    cfg = client.get(f"{P}/ricevute", headers=h).json()
    assert cfg["logo"] == "azienda" and cfg["preview"]["lines"] and cfg["default_header"]
    # intestazione e piede personalizzati, intestazione anche sul registratore
    r = client.put(f"{P}/ricevute", headers=h, json={"logo": "azienda", "logo_width_mm": 40, "header": ["AURORA HAIR", "Via Roma 1 - Lecce", ""],
                                                     "footer": ["Grazie!", "Seguici su Instagram"], "header_on_rt": True, "show_vat": True})
    assert r.status_code == 200, r.text
    assert r.json()["header"] == ["AURORA HAIR", "Via Roma 1 - Lecce"]
    # logo proprio delle ricevute: sulla termica come immagine in bianco e nero
    buf = io.BytesIO()
    Image.new("RGB", (300, 100), "white").save(buf, "PNG")
    up = client.post(f"{P}/ricevute/logo", headers=h, files={"file": ("logo.png", buf.getvalue(), "image/png")})
    assert up.status_code == 200, up.text
    assert up.json()["logo"] == "proprio" and up.json()["own_logo_url"]
    png = client.get(f"{P}/ricevute/logo-termica.png", headers=h)
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(png.content)).size == (320, 107)  # 40 mm × 8 punti
    # stampa di prova sulla termica: logo, intestazione e layout del documento commerciale
    assert client.post(f"{P}/ricevute/prova", headers=h, json={"register_id": reg["id"], "where": "termica"}).status_code == 200
    j = jobs(client, ah)[0]
    lines = j["payload"]["lines"]
    assert j["kind"] == "print.text" and lines[0]["type"] == "image" and lines[0]["width_bytes"] == 40
    t = texts(j["payload"])
    assert t[0][0] == "AURORA HAIR" and ("Grazie!", None) in t and ("DESCRIZIONE", " IVA  Prezzo(€)") in t
    done(client, ah, j)
    # sul registratore con header_on_rt: la nostra intestazione c'è, il logo no
    client.post(f"{P}/ricevute/prova", headers=h, json={"register_id": reg["id"], "where": "registratore"})
    j = jobs(client, ah)[0]
    assert j["kind"] == "rt.nonfiscal" and texts(j["payload"], rt=True)[0][0] == "AURORA HAIR"
    done(client, ah, j)
    # le righe per la stampa dal computer hanno l'indirizzo del logo, non i dati raster
    client.post(f"{P}/casse/{reg['id']}/apri", headers=h, json={"opening_float": "0"})
    d = sale(client, h, reg, [{"item_id": acqua["id"], "unit_price_gross": "0.40"}], [{"method": "carta", "amount": "0.40"}]).json()
    pc = client.get(f"{P}/scontrini/{d['id']}/ricevuta", headers=h).json()
    assert "raster" not in pc["lines"][0] and pc["lines"][0]["logo_url"].startswith("/api/media/")
    assert ("Pagamento elettronico", "0,40") in texts(pc)
    # togliere il logo proprio torna al logo dell'azienda; solo l'amministratore modifica
    assert client.delete(f"{P}/ricevute/logo", headers=h).json()["logo"] == "azienda"
