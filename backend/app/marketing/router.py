"""API di comunicazione e marketing.

- Automatici dell'agenda (conferma, promemoria, disdetta): modulo `agenda`.
- Automatici di marketing (grazie + recensione, richiamo, compleanno, clienti persi), campagne e segmenti: modulo `marketing`.
"""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.agenda import service as agenda
from app.core.deps import TenantContext, require_module
from app.marketing import service as msg
from app.marketing.models import Automation, Campaign, Message

router = APIRouter(prefix="/api/marketing", tags=["marketing"])
agenda_reader = require_module("agenda")
mk_reader = require_module("marketing")


def _admin(ctx: TenantContext) -> TenantContext:
    if ctx.user.role not in ("amministratore", "amministrazione"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo l'amministratore può modificare il marketing")
    return ctx


def agenda_admin(ctx: TenantContext = Depends(agenda_reader)) -> TenantContext:
    return _admin(ctx)


def mk_admin(ctx: TenantContext = Depends(mk_reader)) -> TenantContext:
    return _admin(ctx)


def settings_out(ctx: TenantContext) -> dict:
    st = msg.settings(ctx.db, ctx.tenant_id)
    return {"whatsapp_mode": st.whatsapp_mode, "whatsapp_phone_id": st.whatsapp_phone_id,
            "whatsapp_token_set": bool(st.whatsapp_token_enc), "review_url": st.review_url, "sender_name": st.sender_name}


@router.get("/impostazioni")
def get_settings_(ctx: TenantContext = Depends(agenda_reader)):
    return settings_out(ctx)


class SettingsIn(BaseModel):
    whatsapp_mode: str = Field("simulato", pattern="^(simulato|cloud_api)$")
    whatsapp_phone_id: str | None = Field(None, max_length=40)
    whatsapp_token: str | None = Field(None, max_length=1000)  # vuoto = lascia quello salvato
    review_url: str | None = Field(None, max_length=300)
    sender_name: str | None = Field(None, max_length=80)


@router.put("/impostazioni")
def put_settings(body: SettingsIn, ctx: TenantContext = Depends(agenda_admin)):
    from app.fatturapa.service import encrypt
    st = msg.settings(ctx.db, ctx.tenant_id)
    if body.whatsapp_mode == "cloud_api" and not (body.whatsapp_phone_id and (body.whatsapp_token or st.whatsapp_token_enc)):
        raise HTTPException(422, "Per WhatsApp Business servono Phone number ID e token di accesso")
    st.whatsapp_mode, st.whatsapp_phone_id = body.whatsapp_mode, body.whatsapp_phone_id
    st.review_url, st.sender_name = body.review_url, body.sender_name
    if body.whatsapp_token:
        st.whatsapp_token_enc = encrypt(body.whatsapp_token.strip())
    ctx.db.flush()
    return settings_out(ctx)


def automation_out(a: Automation, modules: list[str]) -> dict:
    needs = "agenda" if a.kind in msg.AGENDA_KINDS else "marketing"
    return {"id": str(a.id), "kind": a.kind, "label": msg.KIND_LABEL[a.kind], "enabled": a.enabled, "channel": a.channel,
            "offset": a.offset, "template": a.template, "module": needs, "available": needs in modules}


@router.get("/automatici")
def list_automations(ctx: TenantContext = Depends(agenda_reader)):
    return [automation_out(a, ctx.state.modules) for a in msg.ensure_automations(ctx.db, ctx.tenant_id)]


class AutomationIn(BaseModel):
    enabled: bool
    template: str = Field(min_length=5, max_length=1000)
    offset: int | None = Field(None, ge=0, le=365)


@router.put("/automatici/{auto_id}")
def update_automation(auto_id: uuid.UUID, body: AutomationIn, ctx: TenantContext = Depends(agenda_admin)):
    a = ctx.db.get(Automation, auto_id)
    if a is None:
        raise HTTPException(404, "Non trovato")
    if a.kind not in msg.AGENDA_KINDS and "marketing" not in ctx.state.modules:
        raise HTTPException(403, {"code": "modulo_non_incluso", "module": "marketing",
                                  "message": "I messaggi di marketing sono nel pacchetto Salone."})
    a.enabled, a.template = body.enabled, body.template
    if a.offset is not None or body.offset is not None:
        a.offset = body.offset
    ctx.db.flush()
    return automation_out(a, ctx.state.modules)


@router.get("/riepilogo")
def summary(ctx: TenantContext = Depends(agenda_reader)):
    since = datetime.now(msg.TZ) - timedelta(days=30)
    sent = ctx.db.scalar(select(func.count()).select_from(Message).where(Message.created_at >= since, Message.inbound.is_(False)))
    read = ctx.db.scalar(select(func.count()).select_from(Message).where(Message.created_at >= since, Message.status == "letto"))
    from app.agenda.models import Appointment, ClientProfile
    online = ctx.db.scalar(select(func.count()).select_from(Appointment).where(Appointment.channel == "online",
                                                                               Appointment.created_at >= since))
    consent = ctx.db.scalar(select(func.count()).select_from(ClientProfile).where(ClientProfile.marketing_consent_at.is_not(None)))
    recent = ctx.db.scalars(select(Message).order_by(Message.created_at.desc()).limit(10)).all()
    return {"sent_30": sent or 0, "read_30": read or 0, "online_30": online or 0, "consent": consent or 0,
            "mode": msg.settings(ctx.db, ctx.tenant_id).whatsapp_mode,
            "booking_url": agenda.public_link(ctx.db, ctx.tenant_id),
            "recent": [{"id": str(m.id), "kind": m.kind, "label": msg.KIND_LABEL.get(m.kind, m.kind), "to": m.to,
                        "status": m.status, "created_at": m.created_at.isoformat(), "party_id": str(m.party_id) if m.party_id else None}
                       for m in recent]}


@router.get("/segmenti")
def segments(ctx: TenantContext = Depends(mk_reader)):
    return [{"code": k, "label": v, "count": len(msg.segment_parties(ctx.db, k))} for k, v in msg.SEGMENTS.items()]


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    segment: str
    body: str = Field(min_length=10, max_length=1000)


def campaign_out(c: Campaign) -> dict:
    return {"id": str(c.id), "name": c.name, "segment": c.segment, "segment_label": msg.SEGMENTS.get(c.segment, c.segment),
            "body": c.body, "status": c.status, "recipients": c.recipients, "created_at": c.created_at.isoformat(),
            "sent_at": c.sent_at.isoformat() if c.sent_at else None}


@router.get("/campagne")
def list_campaigns(ctx: TenantContext = Depends(mk_reader)):
    return [campaign_out(c) for c in ctx.db.scalars(select(Campaign).order_by(Campaign.created_at.desc()).limit(50))]


@router.post("/campagne", status_code=201)
def send_campaign(body: CampaignIn, ctx: TenantContext = Depends(mk_admin)):
    """Crea e invia subito la campagna ai clienti del segmento che hanno dato il consenso marketing."""
    if body.segment not in msg.SEGMENTS:
        raise HTTPException(422, "Segmento non valido")
    if not msg.segment_parties(ctx.db, body.segment):
        raise HTTPException(422, "Nessun cliente con consenso marketing in questo segmento")
    c = Campaign(tenant_id=ctx.tenant_id, name=body.name, segment=body.segment, body=body.body, created_by=ctx.user.full_name)
    ctx.db.add(c)
    ctx.db.flush()
    msg.send_campaign(ctx.db, ctx.tenant_id, c, {"salone": agenda.salon_name(ctx.db, ctx.tenant_id),
                                                   "link": agenda.public_link(ctx.db, ctx.tenant_id)})
    return campaign_out(c)


# ------------------------------------------------------------------------------------- raccolta punti e tessere
from app.anagrafiche.models import Party  # noqa: E402
from app.marketing import loyalty  # noqa: E402
from app.marketing.models import LoyaltyReward  # noqa: E402


def loyalty_settings_out(ctx: TenantContext) -> dict:
    st = loyalty.settings(ctx.db, ctx.tenant_id)
    return {"enabled": st.enabled, "points_per_euro": st.points_per_euro, "welcome_points": st.welcome_points,
            "referral_points": st.referral_points, "card_prefix": st.card_prefix,
            "rewards": [reward_out(r) for r in loyalty.rewards(ctx.db, ctx.tenant_id, active_only=False)]}


def reward_out(r: LoyaltyReward) -> dict:
    return {"id": str(r.id), "name": r.name, "points": r.points, "kind": r.kind, "value": r.value,
            "service_id": str(r.service_id) if r.service_id else None, "active": r.active}


@router.get("/fidelity")
def get_loyalty(ctx: TenantContext = Depends(mk_reader)):
    return loyalty_settings_out(ctx)


class LoyaltyIn(BaseModel):
    enabled: bool = True
    points_per_euro: int = Field(1, ge=0, le=100)
    welcome_points: int = Field(0, ge=0, le=10000)
    referral_points: int = Field(50, ge=0, le=10000)
    card_prefix: str = Field("BB", pattern=r"^[A-Z0-9]{1,6}$")


@router.put("/fidelity")
def put_loyalty(body: LoyaltyIn, ctx: TenantContext = Depends(mk_admin)):
    st = loyalty.settings(ctx.db, ctx.tenant_id)
    for k, v in body.model_dump().items():
        setattr(st, k, v)
    ctx.db.flush()
    return loyalty_settings_out(ctx)


class RewardIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    points: int = Field(ge=1, le=100000)
    kind: str = Field("sconto_euro", pattern="^(sconto_euro|sconto_percento|servizio)$")
    value: int = Field(0, ge=0, le=1000)
    service_id: uuid.UUID | None = None
    active: bool = True


@router.post("/fidelity/premi", status_code=201)
def create_reward(body: RewardIn, ctx: TenantContext = Depends(mk_admin)):
    if body.kind == "servizio" and not body.service_id:
        raise HTTPException(422, "Scegli il servizio in omaggio")
    loyalty.settings(ctx.db, ctx.tenant_id)
    r = LoyaltyReward(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(r)
    ctx.db.flush()
    return reward_out(r)


@router.put("/fidelity/premi/{reward_id}")
def update_reward(reward_id: uuid.UUID, body: RewardIn, ctx: TenantContext = Depends(mk_admin)):
    r = ctx.db.get(LoyaltyReward, reward_id)
    if r is None:
        raise HTTPException(404, "Premio non trovato")
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    ctx.db.flush()
    return reward_out(r)


def _party(ctx: TenantContext, party_id) -> Party:
    p = ctx.db.get(Party, party_id)
    if p is None:
        raise HTTPException(404, "Cliente non trovato")
    return p


@router.post("/fidelity/clienti/{party_id}/tessera", status_code=201)
def issue_card(party_id: uuid.UUID, ctx: TenantContext = Depends(mk_reader)):
    p = _party(ctx, party_id)
    c = loyalty.issue_card(ctx.db, ctx.tenant_id, p, user=ctx.user.full_name)
    return {"number": c.number, "points": loyalty.balance(ctx.db, p.id), "name": p.name,
            "salon": agenda.salon_name(ctx.db, ctx.tenant_id)}


class AdjustIn(BaseModel):
    points: int = Field(ge=-100000, le=100000)
    note: str = Field(min_length=1, max_length=200)


@router.post("/fidelity/clienti/{party_id}/rettifica")
def adjust(party_id: uuid.UUID, body: AdjustIn, ctx: TenantContext = Depends(mk_admin)):
    p = _party(ctx, party_id)
    if loyalty.balance(ctx.db, p.id) + body.points < 0:
        raise HTTPException(422, "Il saldo non può diventare negativo")
    loyalty.add(ctx.db, ctx.tenant_id, p, body.points, "rettifica", note=body.note, user=ctx.user.full_name)
    return {"points": loyalty.balance(ctx.db, p.id)}


@router.get("/fidelity/tessera/{number}")
def find_card(number: str, ctx: TenantContext = Depends(mk_reader)):
    """Lettura della tessera col lettore di codici a barre: porta alla scheda del cliente."""
    p = loyalty.find_by_card(ctx.db, number)
    if p is None:
        raise HTTPException(404, "Tessera non trovata")
    return {"party_id": str(p.id), "name": p.name, "points": loyalty.balance(ctx.db, p.id)}
