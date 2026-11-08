"""BluBeauty: modelli WhatsApp da far approvare a Meta (richiesta, stato, invio col modello, campagne in bozza)."""

import json

import httpx

from app.marketing import service as msg
from app.marketing import wa_templates as wat
from tests.test_agenda import AG, book, catalog, client_, salon

MK = "/api/marketing"


class FakeMeta:
    """Finta Graph API: crea modelli (in approvazione), li elenca, riceve i messaggi."""

    def __init__(self):
        self.templates, self.sent = {}, []

    def __call__(self, request: httpx.Request):
        body = json.loads(request.content) if request.content else None
        if request.url.path.endswith("/message_templates") and request.method == "POST":
            if body["name"] in self.templates:
                return httpx.Response(400, json={"error": {"message": "Esiste già", "error_user_msg": "Nome già usato"}})
            self.templates[body["name"]] = {"name": body["name"], "status": "PENDING", "category": body["category"], "language": "it",
                                            "components": body["components"]}
            return httpx.Response(200, json={"id": f"t{len(self.templates)}", "status": "PENDING", "category": body["category"]})
        if request.url.path.endswith("/message_templates"):
            return httpx.Response(200, json={"data": list(self.templates.values())})
        self.sent.append(body)
        return httpx.Response(200, json={"messages": [{"id": f"wamid.{len(self.sent)}"}]})


def test_conversione_dei_testi():
    body, params = wat.convert("Ciao {nome}, ti aspettiamo alle {ora}. Disdici qui: {link}")
    assert body == "Ciao {{1}}, ti aspettiamo alle {{2}}. Disdici qui: {{3}}\nA presto!" and params == ["nome", "ora", "link"]
    assert wat.convert("{nome}, auguri!")[0].startswith("Ciao! {{1}}")


def test_modelli_approvazione_e_invio(client, admin_headers):
    _, h = salon(client, admin_headers, "Salone Modelli")
    c = catalog(client, h)
    meta = FakeMeta()
    msg._transport = httpx.MockTransport(meta)
    try:
        # senza WhatsApp Business collegato, o senza WABA ID, niente richiesta
        assert client.post(f"{MK}/modelli/invia", headers=h).status_code == 422
        client.put(f"{MK}/impostazioni", headers=h, json={"whatsapp_mode": "cloud_api", "whatsapp_phone_id": "1234567890",
                                                          "whatsapp_token": "EAAG-segreto"})
        assert "WABA" in client.post(f"{MK}/modelli/invia", headers=h).json()["detail"]
        assert client.put(f"{MK}/impostazioni", headers=h, json={"whatsapp_mode": "cloud_api", "whatsapp_phone_id": "1234567890",
                                                                 "whatsapp_waba_id": "998877"}).json()["whatsapp_waba_id"] == "998877"
        # richiesta di approvazione di tutti gli automatici attivi
        r = client.post(f"{MK}/modelli/invia", headers=h)
        assert r.status_code == 200, r.text
        autos = {a["kind"]: a for a in r.json()["automations"]}
        assert autos["conferma"]["wa"]["status"] == "pending" and autos["conferma"]["wa"]["name"] == "bb_conferma_v1"
        assert autos["clienti_persi"]["wa"]["status"] == "da_inviare"  # disattivato: non inviato
        t = meta.templates["bb_conferma_v1"]
        assert t["category"] == "UTILITY" and meta.templates["bb_compleanno_v1"]["category"] == "MARKETING"
        assert "{{1}}" in t["components"][0]["text"] and t["components"][0]["example"]["body_text"][0][0] == "Giulia"
        assert client.post(f"{MK}/modelli/invia", headers=h).json()["sent"] == []  # già in approvazione
        # in approvazione: si invia il testo libero
        laura = client_(client, h)
        book(client, h, laura, c["piega"], "10:00")
        assert meta.sent[-1]["type"] == "text"
        # Meta approva: invio col modello e i parametri in ordine
        meta.templates["bb_conferma_v1"]["status"] = "APPROVED"
        meta.templates["bb_promemoria_v1"].update(status="REJECTED", rejected_reason="INVALID_FORMAT")
        autos = {a["kind"]: a for a in client.post(f"{MK}/modelli/aggiorna", headers=h).json()["automations"]}
        assert autos["conferma"]["wa"]["status"] == "approved" and autos["promemoria"]["wa"]["reason"] == "INVALID_FORMAT"
        book(client, h, laura, c["piega"], "15:00")
        s = meta.sent[-1]
        assert s["type"] == "template" and s["template"]["name"] == "bb_conferma_v1" and s["template"]["language"] == {"code": "it"}
        params = [p["text"] for p in s["template"]["components"][0]["parameters"]]
        assert params[0] == "Laura" and "15:00" in params and all("\n" not in p for p in params)
        # testo cambiato: modello da rifare (nuova versione), intanto testo libero
        conf = autos["conferma"]
        r = client.put(f"{MK}/automatici/{conf['id']}", headers=h, json={"enabled": True, "template": conf["template"] + " A presto!"})
        assert r.json()["wa"]["status"] == "cambiato"
        assert client.post(f"{MK}/automatici/{conf['id']}/modello", headers=h).json()["wa"]["name"] == "bb_conferma_v2"
        # rifiutato: si può rimandare con un nuovo nome
        assert client.post(f"{MK}/modelli/invia", headers=h).json()["sent"] == ["promemoria"] and "bb_promemoria_v2" in meta.templates
    finally:
        msg._transport = None


def test_campagna_in_bozza_finche_meta_non_approva(client, admin_headers):
    _, h = salon(client, admin_headers, "Salone Campagne")
    client_(client, h, "Laura", "Esposito", "333 1111111", marketing=True)
    meta = FakeMeta()
    msg._transport = httpx.MockTransport(meta)
    try:
        client.put(f"{MK}/impostazioni", headers=h, json={"whatsapp_mode": "cloud_api", "whatsapp_phone_id": "1234567890",
                                                          "whatsapp_token": "EAAG-segreto", "whatsapp_waba_id": "998877"})
        r = client.post(f"{MK}/campagne", headers=h, json={"name": "Promo", "segment": "tutti", "body": "Ciao {nome}! Piega a 15 € da {salone}: {link}"})
        assert r.status_code == 201, r.text
        camp = r.json()
        assert camp["status"] == "bozza" and camp["wa"]["status"] == "pending" and meta.sent == []
        assert client.post(f"{MK}/campagne/{camp['id']}/invia", headers=h).status_code == 409
        name = camp["wa"]["name"]
        assert name.startswith("bb_campagna_") and meta.templates[name]["category"] == "MARKETING"
        meta.templates[name]["status"] = "APPROVED"
        client.post(f"{MK}/modelli/aggiorna", headers=h)
        r = client.post(f"{MK}/campagne/{camp['id']}/invia", headers=h)
        assert r.json()["status"] == "inviata" and r.json()["recipients"] == 1
        assert meta.sent[-1]["template"]["name"] == name
    finally:
        msg._transport = None
