import json, sys, urllib.request, io
B = "http://localhost:3300"
def call(m, path, body=None, tok=None):
    h = {"Content-Type": "application/json"}
    if tok: h["Authorization"] = f"Bearer {tok}"
    r = urllib.request.urlopen(urllib.request.Request(B + path, data=json.dumps(body).encode() if body is not None else None, headers=h, method=m))
    return json.loads(r.read() or b"null")
tok = call("POST", "/api/auth/login", {"email": "salone@demo.blubeauty.it", "password": "Demo2026!"})["token"]
ag = call("POST", "/api/periferiche/computer", {"name": "PC del bancone"}, tok)
rt = call("POST", "/api/periferiche/dispositivi", {"agent_id": ag["id"], "name": "Registratore Custom", "driver": "simulatore_rt", "options": {"serial": "99SIM000001"}}, tok)
pr = call("POST", "/api/periferiche/dispositivi", {"agent_id": ag["id"], "name": "Stampante termica 80 mm", "driver": "simulatore_stampante", "options": {"columns": 48, "charset": "pc858"}}, tok)
reg = call("GET", "/api/pos/casse", None, tok)[0]
body = {k: reg[k] for k in ("code", "name", "store_id", "warehouse_id", "price_list_id", "mode", "cash_account_id", "card_account_id", "quick_keys", "settings", "active")}
call("PUT", f"/api/pos/casse/{reg['id']}", {**body, "devices": {"rt": rt["id"], "printer": pr["id"]}}, tok)
print(ag.get("pairing_code") or ag.get("code") or json.dumps(ag)[:300])
