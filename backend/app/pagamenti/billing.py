"""Dati di fatturazione del cliente (contratto comune §Flusso 1): obbligatori prima di pagare, salvati su
`tenants.billing_data` e modificabili dalla pagina «Abbonamento».

Tipi di cliente:
- `azienda`: partita IVA obbligatoria (cifra di controllo), codice fiscale facoltativo;
- `privato`: nome, cognome e codice fiscale (16 caratteri); codice destinatario `0000000`;
- `pa`: Pubblica Amministrazione, codice fiscale (11 cifre) e codice univoco ufficio di 6 caratteri (FPA12).
"""

import re

from pydantic import BaseModel, Field

from app.anagrafiche.validators import PROVINCES, valid_tax_code_it, valid_vat_it

KINDS = ("azienda", "privato", "pa")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class BillingIn(BaseModel):
    tipo: str = Field("azienda", pattern="^(azienda|privato|pa)$")
    denominazione: str | None = Field(None, max_length=80)  # aziende e PA
    nome: str | None = Field(None, max_length=60)  # privati
    cognome: str | None = Field(None, max_length=60)
    partita_iva: str | None = Field(None, max_length=20)
    codice_fiscale: str | None = Field(None, max_length=16)
    indirizzo: str = Field(max_length=60)
    cap: str = Field(max_length=10)
    comune: str = Field(max_length=60)
    provincia: str | None = Field(None, max_length=2)
    nazione: str = Field("IT", max_length=2)
    codice_destinatario: str | None = Field(None, max_length=7)
    pec: str | None = Field(None, max_length=200)
    email: str | None = Field(None, max_length=200)  # dove mandare la ricevuta (vuoto = email dell'azienda)


def normalize(data: dict) -> dict:
    """Pulizia: maiuscole sui codici, niente spazi, prefisso IT tolto dalla partita IVA."""
    out = {k: (v.strip() if isinstance(v, str) else v) for k, v in data.items()}
    for k in ("partita_iva", "codice_fiscale", "codice_destinatario", "provincia", "nazione"):
        if out.get(k):
            out[k] = re.sub(r"\s", "", out[k]).upper()
    if out.get("partita_iva", "") and out["partita_iva"].startswith("IT") and (out.get("nazione") or "IT") == "IT":
        out["partita_iva"] = out["partita_iva"][2:]
    for k in ("pec", "email"):
        if out.get(k):
            out[k] = out[k].lower()
    out["nazione"] = out.get("nazione") or "IT"
    if out.get("tipo") == "privato" and not out.get("codice_destinatario") and not out.get("pec"):
        out["codice_destinatario"] = "0000000"
    return {k: v for k, v in out.items() if v not in (None, "")}


def problems(d: dict) -> list[str]:
    """Errori bloccanti (testo per il cliente). Lista vuota = dati completi e validi."""
    errs: list[str] = []
    tipo = d.get("tipo") or "azienda"
    if tipo not in KINDS:
        return ["Tipo di cliente non valido"]
    italy = (d.get("nazione") or "IT") == "IT"
    if tipo == "privato":
        if not d.get("nome") or not d.get("cognome"):
            errs.append("Indica nome e cognome")
    elif not d.get("denominazione"):
        errs.append("Indica la ragione sociale")
    vat, cf = d.get("partita_iva"), d.get("codice_fiscale")
    if tipo == "azienda" and not vat:
        errs.append("La partita IVA è obbligatoria per le aziende")
    if vat and italy and not valid_vat_it(vat):
        errs.append("Partita IVA non valida (controlla le cifre)")
    if tipo in ("privato", "pa") and not cf and italy:
        errs.append("Il codice fiscale è obbligatorio")
    if cf and italy:
        if tipo == "privato" and len(cf) != 16:
            errs.append("Il codice fiscale di una persona ha 16 caratteri")
        elif not valid_tax_code_it(cf):
            errs.append("Codice fiscale non valido")
    for k, label in (("indirizzo", "l'indirizzo"), ("cap", "il CAP"), ("comune", "il comune")):
        if not d.get(k):
            errs.append(f"Indica {label}")
    if italy:
        if d.get("cap") and not re.fullmatch(r"\d{5}", d["cap"]):
            errs.append("Il CAP ha 5 cifre")
        if not d.get("provincia"):
            errs.append("Indica la provincia")
        elif d["provincia"] not in PROVINCES:
            errs.append("Sigla della provincia non valida")
    elif not re.fullmatch(r"[A-Z]{2}", d.get("nazione") or ""):
        errs.append("Nazione: usa la sigla di 2 lettere (es. IT, DE)")
    code, pec = d.get("codice_destinatario"), d.get("pec")
    if tipo == "pa":
        if not code or not re.fullmatch(r"[A-Z0-9]{6}", code):
            errs.append("Per la Pubblica Amministrazione serve il codice univoco ufficio (6 caratteri)")
    elif italy:
        if code and not re.fullmatch(r"[A-Z0-9]{7}", code):
            errs.append("Il codice destinatario ha 7 caratteri (0000000 se non ne hai uno)")
        if not code and not pec:
            errs.append("Indica il codice destinatario SDI oppure la PEC")
    if pec and not _EMAIL.match(pec):
        errs.append("PEC non valida")
    if d.get("email") and not _EMAIL.match(d["email"]):
        errs.append("Email per la ricevuta non valida")
    return errs


def display_name(d: dict) -> str:
    if d.get("tipo") == "privato":
        return f"{d.get('nome', '')} {d.get('cognome', '')}".strip()
    return d.get("denominazione") or ""


def is_complete(d: dict | None) -> bool:
    return bool(d) and not problems(d)
