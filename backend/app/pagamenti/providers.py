"""Gestori di pagamento via REST con httpx (nessuna libreria dei gestori): Stripe Checkout e PayPal Orders v2.

Sicurezza:
- i dati della carta non passano mai da qui: il cliente paga sulla pagina di Stripe o di PayPal;
- gli importi li manda il server, presi dal listino (`Payment.total`); il browser non manda mai un prezzo;
- le notifiche (webhook) si accettano solo con la firma verificata: Stripe con HMAC SHA-256 e tolleranza di 5 minuti
  (`Stripe-Signature`), PayPal chiedendo a PayPal la verifica (`/v1/notifications/verify-webhook-signature`).

Google Pay e Apple Pay arrivano da soli con Stripe Checkout (metodo «card»): non si limita `payment_method_types`,
così Stripe mostra i metodi attivati nella sua dashboard (Impostazioni › Metodi di pagamento)."""

import hashlib
import hmac
import json
import logging
import time
from decimal import Decimal

import httpx

from app.core.config import get_settings

log = logging.getLogger(__name__)
_transport: httpx.BaseTransport | None = None  # nei test: httpx.MockTransport che simula Stripe e PayPal

STRIPE_API = "https://api.stripe.com"
PAYPAL_API = {"sandbox": "https://api-m.sandbox.paypal.com", "live": "https://api-m.paypal.com"}
SIGNATURE_TOLERANCE = 300  # secondi (come le librerie ufficiali di Stripe)


class ProviderError(Exception):
    pass


def _http() -> httpx.Client:
    return httpx.Client(timeout=30, transport=_transport)


def cents(v: Decimal) -> int:
    return int((Decimal(v) * 100).quantize(Decimal(1)))


# ====================================================================== Stripe


def stripe_configured() -> bool:
    s = get_settings()
    return bool(s.stripe_secret_key and s.stripe_webhook_secret)


def stripe_checkout(*, payment_id: str, tenant_id: str, description: str, total: Decimal, email: str | None,
                    success_url: str, cancel_url: str) -> dict:
    """Crea la sessione di Stripe Checkout. Restituisce {"id", "url"}. Idempotency-Key = id del pagamento."""
    s = get_settings()
    form = {
        "mode": "payment",
        "client_reference_id": payment_id,
        "metadata[payment_id]": payment_id,
        "metadata[tenant_id]": tenant_id,
        "payment_intent_data[metadata][payment_id]": payment_id,
        "payment_intent_data[description]": description,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "eur",
        "line_items[0][price_data][unit_amount]": str(cents(total)),
        "line_items[0][price_data][product_data][name]": description,
        "locale": "it",
        # le fatture degli abbonamenti le emette BluCode: niente Managed Payments (Stripe venditore al posto nostro)
        "managed_payments[enabled]": "false",
        "success_url": success_url,
        "cancel_url": cancel_url,
    }
    if s.stripe_tax_code:
        form["line_items[0][price_data][product_data][tax_code]"] = s.stripe_tax_code
    if email:
        form["customer_email"] = email
    with _http() as c:
        r = c.post(f"{STRIPE_API}/v1/checkout/sessions", data=form,
                   headers={"Authorization": f"Bearer {s.stripe_secret_key}", "Idempotency-Key": f"checkout-{payment_id}"})
    if r.status_code >= 400:
        log.warning("Stripe checkout %s: %s", r.status_code, r.text[:300])
        raise ProviderError("Il pagamento con carta non è disponibile in questo momento: riprova o scegli un altro metodo")
    data = r.json()
    return {"id": data["id"], "url": data["url"]}


def stripe_expire(session_id: str) -> None:
    """Chiude una sessione ancora aperta (pagamento annullato dal pannello). Gli errori si ignorano."""
    s = get_settings()
    try:
        with _http() as c:
            c.post(f"{STRIPE_API}/v1/checkout/sessions/{session_id}/expire",
                   headers={"Authorization": f"Bearer {s.stripe_secret_key}"})
    except httpx.HTTPError:
        log.warning("Sessione Stripe %s non chiusa", session_id)


def stripe_verify(payload: bytes, header: str | None, secret: str | None = None, now: float | None = None) -> dict:
    """Verifica `Stripe-Signature` (t=<timestamp>,v1=<hmac>) e restituisce l'evento. Firma su "<t>.<corpo grezzo>".
    Rifiuta firme sbagliate e quelle più vecchie di 5 minuti (replay)."""
    secret = secret or get_settings().stripe_webhook_secret
    if not secret or not header:
        raise ProviderError("firma assente")
    parts: dict[str, list[str]] = {}
    for item in header.split(","):
        k, _, v = item.strip().partition("=")
        parts.setdefault(k, []).append(v)
    try:
        ts = int(parts.get("t", [""])[0])
    except ValueError:
        raise ProviderError("firma non valida") from None
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in parts.get("v1", [])):
        raise ProviderError("firma non valida")
    if abs((now or time.time()) - ts) > SIGNATURE_TOLERANCE:
        raise ProviderError("firma scaduta")
    try:
        return json.loads(payload)
    except ValueError:
        raise ProviderError("evento non leggibile") from None


def stripe_sign(payload: bytes, secret: str, ts: int | None = None) -> str:
    """Intestazione `Stripe-Signature` come la calcola Stripe (per i test e per provare l'endpoint in sviluppo)."""
    ts = int(ts if ts is not None else time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


# ====================================================================== PayPal


def paypal_configured() -> bool:
    s = get_settings()
    return bool(s.paypal_client_id and s.paypal_secret and s.paypal_webhook_id)


def _paypal_base() -> str:
    return PAYPAL_API["live" if get_settings().paypal_mode == "live" else "sandbox"]


def _paypal_token(c: httpx.Client) -> str:
    s = get_settings()
    r = c.post(f"{_paypal_base()}/v1/oauth2/token", data={"grant_type": "client_credentials"},
               auth=(s.paypal_client_id, s.paypal_secret))
    if r.status_code >= 400:
        log.warning("PayPal token %s: %s", r.status_code, r.text[:300])
        raise ProviderError("PayPal non è disponibile in questo momento: riprova o scegli un altro metodo")
    return r.json()["access_token"]


def paypal_create_order(*, payment_id: str, causale: str, description: str, total: Decimal,
                        return_url: str, cancel_url: str) -> dict:
    """Ordine PayPal (intent CAPTURE) creato lato server. Restituisce {"id", "url"} con l'URL di approvazione."""
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": payment_id, "custom_id": payment_id, "invoice_id": causale, "description": description[:127],
            "amount": {"currency_code": "EUR", "value": f"{Decimal(total):.2f}"},
        }],
        "payment_source": {"paypal": {"experience_context": {
            "brand_name": "BluCode Informatica", "locale": "it-IT", "shipping_preference": "NO_SHIPPING",
            "user_action": "PAY_NOW", "return_url": return_url, "cancel_url": cancel_url,
        }}},
    }
    with _http() as c:
        token = _paypal_token(c)
        r = c.post(f"{_paypal_base()}/v2/checkout/orders", json=body,
                   headers={"Authorization": f"Bearer {token}", "PayPal-Request-Id": f"order-{payment_id}"})
    if r.status_code >= 400:
        log.warning("PayPal ordine %s: %s", r.status_code, r.text[:300])
        raise ProviderError("PayPal non è disponibile in questo momento: riprova o scegli un altro metodo")
    data = r.json()
    url = next((ln["href"] for ln in data.get("links", []) if ln.get("rel") in ("payer-action", "approve")), None)
    if not url:
        raise ProviderError("PayPal non ha restituito la pagina di pagamento")
    return {"id": data["id"], "url": url}


def paypal_capture(order_id: str, payment_id: str) -> dict:
    """Cattura l'ordine approvato dal cliente. La conferma del pagamento arriva poi dal webhook PAYMENT.CAPTURE.COMPLETED.
    Un ordine già catturato (ORDER_ALREADY_CAPTURED) non è un errore."""
    with _http() as c:
        token = _paypal_token(c)
        r = c.post(f"{_paypal_base()}/v2/checkout/orders/{order_id}/capture", json={},
                   headers={"Authorization": f"Bearer {token}", "PayPal-Request-Id": f"capture-{payment_id}"})
    if r.status_code == 422 and "ORDER_ALREADY_CAPTURED" in r.text:
        return {"status": "COMPLETED", "already": True}
    if r.status_code >= 400:
        log.warning("PayPal cattura %s: %s", r.status_code, r.text[:300])
        raise ProviderError("PayPal non ha completato il pagamento")
    return r.json()


def paypal_verify(headers, event: dict) -> bool:
    """Verifica la firma del webhook chiedendola a PayPal, con il PAYPAL_WEBHOOK_ID dell'endpoint."""
    s = get_settings()
    need = {"auth_algo": "paypal-auth-algo", "cert_url": "paypal-cert-url", "transmission_id": "paypal-transmission-id",
            "transmission_sig": "paypal-transmission-sig", "transmission_time": "paypal-transmission-time"}
    body = {k: headers.get(h) for k, h in need.items()}
    if not s.paypal_webhook_id or not all(body.values()):
        return False
    body.update({"webhook_id": s.paypal_webhook_id, "webhook_event": event})
    try:
        with _http() as c:
            token = _paypal_token(c)
            r = c.post(f"{_paypal_base()}/v1/notifications/verify-webhook-signature", json=body,
                       headers={"Authorization": f"Bearer {token}"})
    except (httpx.HTTPError, ProviderError):
        log.exception("Verifica del webhook PayPal non riuscita")
        return False
    return r.status_code == 200 and r.json().get("verification_status") == "SUCCESS"
