"""Motore delle promozioni di cassa: casi condivisi col frontend (tests/fixtures/pos_promos.json) e prova nello scontrino."""

import json
import uuid
from decimal import Decimal
from pathlib import Path

from app.pos import promos
from app.pos.service import line_cents
from tests.conftest import activate_and_login, make_tenant
from tests.test_pos import P, qty, sale, setup

CASES = json.loads((Path(__file__).parent / "fixtures" / "pos_promos.json").read_text())["cases"]


def _run(case):
    lines = [promos.PLine(key=str(n), item_id=ln["item_id"], price_cents=promos.rhu(Decimal(ln["price"]) * 100), quantity=Decimal(ln["quantity"]),
                          amount_cents=line_cents(Decimal(ln["price"]), Decimal(ln["quantity"]), Decimal(ln["discount"]) if ln.get("discount") else None),
                          vat_rate_id=ln["vat"], categories=set(ln.get("categories", [])), manual_discount=bool(ln.get("discount")))
             for n, ln in enumerate(case["lines"])]
    pp = [promos.PPromo(id=p["id"], name=p["name"], mechanic=p["mechanic"], item_scope=p["item_scope"], item_ids=set(p.get("item_ids", [])),
                        category_ids=set(p.get("category_ids", [])), buy_qty=p.get("buy_qty"), pay_qty=p.get("pay_qty"), value=Decimal(p["value"]),
                        price_type=p["price_type"], threshold_cents=promos.rhu(Decimal(p["threshold"]) * 100) if p.get("threshold") else None)
          for p in case["promos"]]
    return [{k: r[k] for k in ("promotion_id", "vat_rate_id", "amount_cents")} for r in promos.compute(lines, pp)]


def test_casi_condivisi():
    for case in CASES:
        assert _run(case) == case["expected"], case["name"]


def test_promozioni_nello_scontrino(client, admin_headers):
    h, reg, pane, acqua, dep, cassa, banca = setup(client, admin_headers, "Promo Market Srl")
    today = __import__("datetime").date.today().isoformat()
    r = client.post("/api/anagrafiche/promozioni", headers=h, json={
        "name": "Acqua 3x2", "date_from": today, "date_to": today, "item_scope": "articoli", "item_ids": [acqua["id"]],
        "mechanic": "nxm", "buy_qty": 3, "pay_qty": 2, "price_type": "sconto", "value": "0"})
    assert r.status_code == 201, r.text
    assert client.post("/api/anagrafiche/promozioni", headers=h, json={
        "name": "Sbagliata", "date_from": today, "date_to": today, "item_scope": "tutti", "mechanic": "nxm", "buy_qty": 2, "pay_qty": 3,
        "price_type": "sconto", "value": "0"}).status_code == 422
    client.post("/api/anagrafiche/promozioni", headers=h, json={
        "name": "Spesa da 5 euro", "date_from": today, "date_to": today, "item_scope": "tutti", "mechanic": "soglia", "threshold": "5",
        "price_type": "sconto", "value": "10"})
    cat = client.get(f"{P}/casse/{reg['id']}/catalogo", headers=h).json()
    assert {p["mechanic"] for p in cat["promotions"]} == {"nxm", "soglia"}
    # il prezzo di listino dell'acqua non cambia (la promo di cassa non è un prezzo)
    assert next(i for i in cat["items"] if i["code"] == "ACQUA")["price"] == "0.40"
    client.post(f"{P}/casse/{reg['id']}/apri", headers=h, json={})
    # 6 acque (2 gratis) + 1 kg di pane: 2,40 − 0,80 + 3,50 = 5,10 → soglia 10% su 5,10 = 0,51 → 4,59
    r = sale(client, h, reg, [{"item_id": acqua["id"], "quantity": "6", "unit_price_gross": "0.40"},
                              {"item_id": pane["id"], "quantity": "1", "unit_price_gross": "3.50"}], [{"method": "contanti", "amount": "5"}])
    assert r.status_code == 200, r.text
    sco = r.json()
    promo = [l for l in sco["lines"] if Decimal(l["total"]) < 0]
    assert sorted(Decimal(l["total"]) for l in promo) == [Decimal("-0.80"), Decimal("-0.35"), Decimal("-0.16")]
    assert Decimal(sco["total"]) == Decimal("4.59") and Decimal(sco["change"]) == Decimal("0.41")
    assert sum(Decimal(v["taxable"]) + Decimal(v["vat"]) for v in sco["vat_summary"]) == Decimal("4.59")
    # il cliente non può mandare sconti inventati: le righe negative del client si ignorano
    fake = sale(client, h, reg, [{"item_id": pane["id"], "quantity": "1", "unit_price_gross": "3.50"},
                                 {"description": "Sconto", "quantity": "1", "unit_price_gross": "-3.00"}], [{"method": "contanti", "amount": "3.50"}])
    assert fake.status_code == 200 and Decimal(fake.json()["total"]) == Decimal("3.50")
    # reso: le acque tornano, la riga di sconto si rende al suo valore e il reso non va mai sotto zero
    lines = {l["description"]: l for l in sco["lines"]}
    acq = next(l for l in sco["lines"] if l["item_id"] == acqua["id"])
    p3 = next(l for l in promo if "3x2" in l["description"])
    neg = client.post(f"{P}/casse/{reg['id']}/resi", headers=h, json={"client_uuid": str(uuid.uuid4()), "original_id": sco["id"],
                                                                      "lines": [{"origin_line_id": p3["id"], "quantity": "1", "unit_price_gross": "0"}]})
    assert neg.status_code == 422
    rso = client.post(f"{P}/casse/{reg['id']}/resi", headers=h, json={"client_uuid": str(uuid.uuid4()), "original_id": sco["id"], "lines": [
        {"item_id": acqua["id"], "origin_line_id": acq["id"], "quantity": "6", "unit_price_gross": "0.40"},
        {"origin_line_id": p3["id"], "quantity": "1", "unit_price_gross": "0"}]})
    assert rso.status_code == 200, rso.text
    assert Decimal(rso.json()["total"]) == Decimal("1.60") and qty(client, h, acqua) == 100
    # statistiche: sconti promozioni e quantità senza le righe di sconto
    q = client.post("/api/bi/vendite/query", headers=h, json={"dimensions": [], "measures": ["sconti_promo", "quantita"],
                                                             "date_from": today, "date_to": today}).json()
    assert q["totals"]["quantita"] == "2.000"  # 6 + 1 + 1 − 6
    assert Decimal(q["totals"]["sconti_promo"]) > 0


def test_stessi_risultati_della_cassa():
    """Il motore TypeScript della cassa deve dare gli stessi centesimi (serve node e le dipendenze del frontend)."""
    import shutil
    import subprocess

    import pytest

    front = Path(__file__).resolve().parents[2] / "frontend"
    if not shutil.which("node") or not (front / "node_modules" / "esbuild").exists():
        pytest.skip("node o le dipendenze del frontend non sono installati")
    r = subprocess.run(["node", "scripts/check-promos.mjs"], cwd=front, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
