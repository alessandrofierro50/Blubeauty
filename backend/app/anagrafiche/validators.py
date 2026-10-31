"""Controlli formali sui dati fiscali italiani e sui codici a barre."""

import re

PROVINCES = set(
    "AG AL AN AO AP AQ AR AT AV BA BG BI BL BN BO BR BS BT BZ CA CB CE CH CL CN CO CR CS CT CZ EN FC FE FG FI FM FR GE GO "
    "GR IM IS KR LC LE LI LO LT LU MB MC ME MI MN MO MS MT NA NO NU OR PA PC PD PE PG PI PN PO PR PT PU PV PZ RA RC RE RG "
    "RI RM RN RO SA SI SO SP SR SS SU SV TA TE TN TO TP TR TS TV UD VA VB VC VE VI VR VT VV".split()
)


def valid_vat_it(vat: str) -> bool:
    """Partita IVA italiana: 11 cifre con carattere di controllo (algoritmo di Luhn modificato)."""
    if not re.fullmatch(r"\d{11}", vat):
        return False
    total = 0
    for i, ch in enumerate(vat[:10]):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return (10 - total % 10) % 10 == int(vat[10])


_CF_ODD = {
    **dict(zip("0123456789", [1, 0, 5, 7, 9, 13, 15, 17, 19, 21])),
    **dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
               [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23])),
}


def valid_tax_code_it(cf: str) -> bool:
    """Codice fiscale: 16 caratteri per le persone fisiche (con controllo) oppure 11 cifre per le società."""
    cf = cf.upper()
    if re.fullmatch(r"\d{11}", cf):
        return valid_vat_it(cf)
    if not re.fullmatch(r"[A-Z]{6}[0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]", cf):
        return False
    total = 0
    for i, ch in enumerate(cf[:15]):
        if i % 2 == 0:
            total += _CF_ODD[ch]
        else:
            total += int(ch) if ch.isdigit() else ord(ch) - ord("A")
    return chr(ord("A") + total % 26) == cf[15]


def ean_check_digit(digits: str) -> int:
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
    return (10 - total % 10) % 10


def valid_ean(code: str) -> bool:
    if not re.fullmatch(r"\d{8}|\d{12}|\d{13}|\d{14}", code):
        return False
    return ean_check_digit(code[:-1]) == int(code[-1])


def make_internal_ean13(prefix: str, number: int) -> str:
    """EAN-13 interno (prefisso 2xx riservato all'uso in negozio)."""
    body = f"{prefix}{number:0{12 - len(prefix)}d}"[:12]
    return body + str(ean_check_digit(body))


def party_problems(data: dict) -> list[str]:
    """Avvisi bloccanti sui dati fiscali di cliente/fornitore."""
    problems = []
    country = (data.get("country") or "IT").upper()
    vat = (data.get("vat_number") or "").strip()
    cf = (data.get("tax_code") or "").strip()
    if country == "IT":
        if vat and not valid_vat_it(vat):
            problems.append("Partita IVA non valida")
        if cf and not valid_tax_code_it(cf):
            problems.append("Codice fiscale non valido")
        prov = (data.get("province") or "").upper()
        if prov and prov not in PROVINCES:
            problems.append("Sigla provincia non valida")
        zip_code = data.get("zip_code") or ""
        if zip_code and not re.fullmatch(r"\d{5}", zip_code):
            problems.append("CAP non valido (5 cifre)")
        sdi = (data.get("sdi_code") or "").upper()
        if sdi:
            expected = 6 if data.get("person_type") == "pa" else 7
            if not re.fullmatch(rf"[A-Z0-9]{{{expected}}}", sdi):
                problems.append(f"Codice destinatario SDI non valido ({expected} caratteri)")
        if data.get("person_type") == "azienda" and data.get("is_customer") and not vat and not cf:
            problems.append("Per un'azienda serve almeno partita IVA o codice fiscale")
    return problems
