"""Pulsante «Guarda il video»: indirizzi dei tutorial inseriti dal super amministratore, letti dalle schermate."""

from tests.conftest import activate_and_login, make_tenant


def test_video_aiuto(client, admin_headers):
    r = client.get("/api/admin/video-aiuto", headers=admin_headers)
    assert r.status_code == 200
    videos = r.json()
    assert len(videos) == 8 and all(v["url"] is None for v in videos)
    assert all(v["effective_url"] == v["default_url"] and v["default_url"].startswith("/video-aiuto/") for v in videos)

    r = client.put("/api/admin/video-aiuto", headers=admin_headers,
                   json={"urls": {"agenda": " https://youtu.be/abc123 ", "cassa": "", "sconosciuto": "https://x.it/v.mp4"}})
    assert r.status_code == 200, r.text
    by_key = {v["key"]: v["url"] for v in r.json()}
    assert by_key["agenda"] == "https://youtu.be/abc123" and by_key["cassa"] is None and "sconosciuto" not in by_key

    assert client.put("/api/admin/video-aiuto", headers=admin_headers,
                      json={"urls": {"cassa": "javascript:alert(1)"}}).status_code == 422

    h = activate_and_login(client, make_tenant(client, admin_headers, "Salone Video", plan="SALONE"))
    app = client.get("/api/app/video-aiuto", headers=h).json()
    assert app["agenda"]["url"] == "https://youtu.be/abc123"
    # senza indirizzo nel pannello vale il video incluso in BluBeauty
    assert app["buoni_abbonamenti"] == {"title": "Gestione di abbonamenti e buoni", "url": "/video-aiuto/08-buoni-abbonamenti.mp4"}

    # svuotare un indirizzo riporta il video incluso
    client.put("/api/admin/video-aiuto", headers=admin_headers, json={"urls": {"agenda": None}})
    assert client.get("/api/app/video-aiuto", headers=h).json()["agenda"]["url"] == "/video-aiuto/01-agenda.mp4"
