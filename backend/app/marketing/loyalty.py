"""Raccolta punti e tessere fedeltà: unico punto che scrive loyalty_* e il saldo in agenda_client_profiles.

Regole (ispirate ai software del settore: punti per euro, premi a soglia riscattati in cassa, tessera con codice a barre,
bonus «porta un'amica», avviso quando si raggiunge un premio):
- si accumulano `points_per_euro` punti per ogni euro intero pagato (dopo sconti e premi);
- un premio si riscatta in cassa se il saldo basta: sconto in euro, sconto in percentuale sui servizi o un servizio omaggio;
- alla prima visita pagata di una cliente presentata da un'altra, chi l'ha presentata riceve `referral_points`;
- ogni accredito ha una `dedupe_key`: un doppio clic o un job ripetuto non accredita due volte.
"""

from decimal import ROUND_DOWN, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.anagrafiche.models import Party
from app.marketing.models import LoyaltyCard, LoyaltyMove, LoyaltyReward, LoyaltySettings

DEFAULT_REWARDS = [
    ("Sconto di 5 €", 100, "sconto_euro", 5),
    ("Sconto di 15 €", 250, "sconto_euro", 15),
]


def settings(db: Session, tenant_id, lock: bool = False) -> LoyaltySettings:
    q = select(LoyaltySettings).where(LoyaltySettings.tenant_id == tenant_id)
    s = db.scalar(q.with_for_update() if lock else q)
    if s is None:
        s = LoyaltySettings(tenant_id=tenant_id, enabled=True, points_per_euro=1, welcome_points=0, referral_points=50,
                            card_prefix="BB", next_card_number=1)
        db.add(s)
        db.flush()
        for name, pts, kind, value in DEFAULT_REWARDS:
            db.add(LoyaltyReward(tenant_id=tenant_id, name=name, points=pts, kind=kind, value=value, active=True))
        db.flush()
    return s


def balance(db: Session, party_id) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(LoyaltyMove.points), 0)).where(LoyaltyMove.party_id == party_id)) or 0)


def _sync(db: Session, tenant_id, party: Party) -> int:
    from app.agenda.service import profile
    b = balance(db, party.id)
    profile(db, tenant_id, party).loyalty_points = b
    return b


def add(db: Session, tenant_id, party: Party, points: int, reason: str, *, dedupe_key: str | None = None, note: str | None = None,
        appointment_id=None, document_id=None, reward_id=None, user: str | None = None) -> LoyaltyMove | None:
    if points == 0:
        return None
    if dedupe_key and db.scalar(select(LoyaltyMove.id).where(LoyaltyMove.dedupe_key == dedupe_key)):
        return None
    m = LoyaltyMove(tenant_id=tenant_id, party_id=party.id, points=points, reason=reason, dedupe_key=dedupe_key, note=note,
                    appointment_id=appointment_id, document_id=document_id, reward_id=reward_id, created_by=user)
    db.add(m)
    db.flush()
    _sync(db, tenant_id, party)
    return m


def card(db: Session, party_id) -> LoyaltyCard | None:
    return db.scalar(select(LoyaltyCard).where(LoyaltyCard.party_id == party_id, LoyaltyCard.active.is_(True)))


def issue_card(db: Session, tenant_id, party: Party, user: str | None = None) -> LoyaltyCard:
    """Tessera fedeltà con numero progressivo (contatore bloccato): una attiva per cliente."""
    have = card(db, party.id)
    if have:
        return have
    s = settings(db, tenant_id, lock=True)
    number = f"{s.card_prefix}{s.next_card_number:06d}"
    s.next_card_number += 1
    c = LoyaltyCard(tenant_id=tenant_id, party_id=party.id, number=number, active=True)
    db.add(c)
    db.flush()
    if s.welcome_points:
        add(db, tenant_id, party, s.welcome_points, "benvenuto", dedupe_key=f"benvenuto:{party.id}", user=user)
    return c


def find_by_card(db: Session, number: str) -> Party | None:
    c = db.scalar(select(LoyaltyCard).where(func.upper(LoyaltyCard.number) == number.strip().upper(), LoyaltyCard.active.is_(True)))
    return db.get(Party, c.party_id) if c else None


def rewards(db: Session, tenant_id, active_only: bool = True) -> list[LoyaltyReward]:
    settings(db, tenant_id)
    q = select(LoyaltyReward).order_by(LoyaltyReward.points)
    if active_only:
        q = q.where(LoyaltyReward.active.is_(True))
    return list(db.scalars(q))


def reward_discount(db: Session, reward: LoyaltyReward, services_total: Decimal, service_prices: dict) -> Decimal:
    """Valore in euro del premio su questo conto."""
    if reward.kind == "sconto_euro":
        return min(Decimal(reward.value), services_total)
    if reward.kind == "sconto_percento":
        return (services_total * Decimal(reward.value) / 100).quantize(Decimal("0.01"))
    if reward.kind == "servizio":
        if reward.service_id not in service_prices:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Il premio «{reward.name}» vale solo con il suo servizio")
        return service_prices[reward.service_id]
    raise HTTPException(422, "Premio non valido")


def check_redeem(db: Session, tenant_id, party: Party | None, reward_id) -> LoyaltyReward:
    if party is None:
        raise HTTPException(422, "Per usare un premio serve il cliente")
    r = db.get(LoyaltyReward, reward_id)
    if r is None or not r.active:
        raise HTTPException(404, "Premio non trovato")
    have = balance(db, party.id)
    if have < r.points:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Punti insufficienti: servono {r.points}, ne ha {have}")
    return r


def earn_on_payment(db: Session, tenant_id, party: Party, paid_total: Decimal, *, appointment_id, document_id) -> int:
    """Punti dell'acquisto e bonus «porta un'amica» alla prima visita pagata. Restituisce i punti accreditati."""
    s = settings(db, tenant_id)
    if not s.enabled:
        return 0
    pts = int(Decimal(paid_total).to_integral_value(ROUND_DOWN)) * (s.points_per_euro or 0)
    add(db, tenant_id, party, pts, "acquisto", dedupe_key=f"acquisto:{appointment_id}", appointment_id=appointment_id,
        document_id=document_id)
    from app.agenda.models import ClientProfile
    prof = db.scalar(select(ClientProfile).where(ClientProfile.party_id == party.id))
    if prof and prof.referred_by_party_id and s.referral_points:
        friend = db.get(Party, prof.referred_by_party_id)
        if friend:
            add(db, tenant_id, friend, s.referral_points, "presenta_amica", dedupe_key=f"presenta_amica:{party.id}",
                note=f"Ha presentato {party.name}")
    return pts


def next_reward(db: Session, tenant_id, points: int) -> dict | None:
    """Il premio più vicino non ancora raggiungibile, oppure il migliore già raggiunto."""
    rs = rewards(db, tenant_id)
    reached = [r for r in rs if r.points <= points]
    ahead = [r for r in rs if r.points > points]
    if ahead:
        r = ahead[0]
        return {"name": r.name, "points": r.points, "missing": r.points - points, "reached": False}
    if reached:
        r = reached[-1]
        return {"name": r.name, "points": r.points, "missing": 0, "reached": True}
    return None
