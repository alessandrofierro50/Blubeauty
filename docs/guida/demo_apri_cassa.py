import json, urllib.request
B = "http://localhost:3300"
def call(m, path, body=None, tok=None):
    h = {"Content-Type": "application/json", **({"Authorization": f"Bearer {tok}"} if tok else {})}
    return json.loads(urllib.request.urlopen(urllib.request.Request(B + path, data=json.dumps(body).encode() if body is not None else None, headers=h, method=m)).read() or b"null")
tok = call("POST", "/api/auth/login", {"email": "salone@demo.blubeauty.it", "password": "Demo2026!"})["token"]
reg = call("GET", "/api/pos/casse", None, tok)[0]
try:
    call("POST", f"/api/pos/casse/{reg['id']}/apri", {"opening_float": "100"}, tok)
except Exception as e:
    print("apertura:", e)
print(reg["id"])
