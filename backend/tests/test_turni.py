"""BluBeauty: turni e assenze degli operatori (ferie, malattia, permessi, orari diversi, chiusure, settimane alterne)."""

from datetime import timedelta

from app.agenda import service as agenda_svc
from tests.test_agenda import AG, TUE, book, catalog, client_, salon


def slots(client, h, service, day, staff=None):
    q = {"service_id": service["id"], "day": day.isoformat()}
    if staff:
        q["staff_id"] = staff["id"]
    r = client.get(f"{AG}/disponibilita", headers=h, params=q)
    assert r.status_code == 200, r.text
    return [x["time"] for x in r.json()]


def test_ferie_permessi_e_chiusure(client, admin_headers):
    _, h = salon(client, admin_headers, "Salone Turni")
    c = catalog(client, h)
    giulia, sara = c["giulia"], c["sara"]
    laura = client_(client, h)
    a = book(client, h, laura, c["piega"], "10:00", staff=giulia)
    assert a.status_code == 201, a.text
    assert "10:00" in slots(client, h, c["piega"], TUE, sara)

    # ferie di Giulia: niente orari per lei, e l'appuntamento già preso viene segnalato da spostare
    r = client.post(f"{AG}/turni/assenze", headers=h, json={"staff_id": giulia["id"], "kind": "ferie",
                                                            "date_from": TUE.isoformat(), "date_to": (TUE + timedelta(days=3)).isoformat()})
    assert r.status_code == 201, r.text
    ferie = r.json()
    assert [x["id"] for x in ferie["conflicts"]] == [a.json()["id"]] and ferie["conflicts"][0]["client"].startswith("Esposito")
    assert slots(client, h, c["piega"], TUE, giulia) == []
    assert slots(client, h, c["colore"], TUE) == []  # il colore lo fa solo Giulia
    assert book(client, h, laura, c["piega"], "15:00", staff=giulia).status_code == 409
    assert "15:00" in slots(client, h, c["piega"], TUE)  # Sara c'è
    t = client.get(f"{AG}/turni", headers=h, params={"dal": TUE.isoformat(), "giorni": 7}).json()
    assert t["plan"][giulia["id"]][TUE.isoformat()] == {"hours": [], "absence": {**ferie["absence"]}}
    assert t["plan"][sara["id"]][TUE.isoformat()]["hours"] == [["09:00", "19:30"]]

    # permesso di Sara 12-15: fuori solo quelle ore; il permesso si può togliere
    r = client.post(f"{AG}/turni/assenze", headers=h, json={"staff_id": sara["id"], "kind": "permesso", "date_from": TUE.isoformat(),
                                                            "date_to": TUE.isoformat(), "hours": [["12:00", "15:00"]], "note": "Dentista"})
    assert r.status_code == 201, r.text
    s = slots(client, h, c["piega"], TUE, sara)
    assert "11:30" in s and "11:45" not in s and "13:00" not in s and "15:00" in s
    assert client.get(f"{AG}/orari", headers=h, params={"giorno": TUE.isoformat()}).json()[sara["id"]]["hours"] == [
        ["09:00", "12:00"], ["15:00", "19:30"]]
    assert client.delete(f"{AG}/turni/assenze/{r.json()['absence']['id']}", headers=h).status_code == 204
    assert "13:00" in slots(client, h, c["piega"], TUE, sara)

    # orario diverso di Sara il martedì dopo: solo 14-18
    tue2 = TUE + timedelta(days=7)
    r = client.post(f"{AG}/turni/assenze", headers=h, json={"staff_id": sara["id"], "kind": "orario", "date_from": tue2.isoformat(),
                                                            "date_to": tue2.isoformat(), "hours": [["14:00", "18:00"]]})
    assert r.status_code == 201
    s = slots(client, h, c["piega"], tue2, sara)
    assert s[0] == "14:00" and s[-1] == "17:30"

    # chiusura del salone: nessun orario per nessuno, anche online
    wed = TUE + timedelta(days=1)
    r = client.post(f"{AG}/turni/assenze", headers=h, json={"kind": "chiusura", "date_from": wed.isoformat(), "date_to": wed.isoformat(),
                                                            "note": "Inventario"})
    assert r.status_code == 201, r.text
    assert slots(client, h, c["piega"], wed) == []
    assert client.get(f"{AG}/turni", headers=h, params={"dal": wed.isoformat(), "giorni": 1}).json()["closures"][wed.isoformat()]["note"] == "Inventario"

    # controlli: chiusura senza operatore, permesso con le ore, date in ordine; i dati restano di questa azienda
    bad = [{"staff_id": giulia["id"], "kind": "chiusura", "date_from": wed.isoformat(), "date_to": wed.isoformat()},
           {"kind": "ferie", "date_from": wed.isoformat(), "date_to": wed.isoformat()},
           {"staff_id": sara["id"], "kind": "permesso", "date_from": wed.isoformat(), "date_to": wed.isoformat()},
           {"staff_id": sara["id"], "kind": "ferie", "date_from": wed.isoformat(), "date_to": TUE.isoformat()}]
    for b in bad:
        assert client.post(f"{AG}/turni/assenze", headers=h, json=b).status_code == 422, b
    _, h2 = salon(client, admin_headers, "Altro Salone")
    assert client.get(f"{AG}/turni", headers=h2, params={"dal": TUE.isoformat()}).json()["absences"] == []
    assert client.delete(f"{AG}/turni/assenze/{ferie['absence']['id']}", headers=h2).status_code == 404


def test_settimane_alterne(client, admin_headers):
    _, h = salon(client, admin_headers, "Salone Alterne")
    c = catalog(client, h)
    sara = c["sara"]
    week_b = {"tue": [["14:00", "19:00"]]}
    r = client.put(f"{AG}/operatori/{sara['id']}", headers=h, json={**sara, "working_hours": {}, "working_hours_b": week_b})
    assert r.status_code == 422  # serve la settimana A
    r = client.put(f"{AG}/operatori/{sara['id']}", headers=h, json={**sara, "working_hours": {}, "working_hours_b": week_b,
                                                                     "alt_week_a": TUE.isoformat()})
    assert r.status_code == 200, r.text
    assert slots(client, h, c["piega"], TUE, sara)[0] == "09:00"  # settimana A: orario del salone
    assert slots(client, h, c["piega"], TUE + timedelta(days=7), sara)[0] == "14:00"  # settimana B
    assert slots(client, h, c["piega"], TUE + timedelta(days=14), sara)[0] == "09:00"


def test_sottrai_fasce():
    sub = agenda_svc.subtract_ranges
    assert sub([["09:00", "19:00"]], [["12:00", "14:00"]]) == [["09:00", "12:00"], ["14:00", "19:00"]]
    assert sub([["09:00", "13:00"], ["15:00", "19:00"]], [["08:00", "16:00"]]) == [["16:00", "19:00"]]
    assert sub([["09:00", "13:00"]], [["09:00", "13:00"]]) == []
