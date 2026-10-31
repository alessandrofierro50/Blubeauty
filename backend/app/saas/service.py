import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.models import AuditLog, Plan, SaasSetting, Subscription, Tenant
from app.saas import logic


def today() -> date:
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


@dataclass
class TenantState:
    tenant: Tenant
    subscription: Subscription | None
    plan: Plan | None
    status: str
    access: str
    end_date: date | None
    days_left: int | None
    modules: list[str] = field(default_factory=list)
    limits: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "status_label": logic.STATUS_LABELS[self.status],
            "access": self.access,
            "plan_code": self.plan.code if self.plan else None,
            "plan_name": self.plan.name if self.plan else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "days_left": self.days_left,
            "modules": self.modules,
            "limits": self.limits,
        }


def load_tenant(db: Session, tenant_id: uuid.UUID) -> Tenant | None:
    return db.scalar(
        select(Tenant)
        .where(Tenant.id == tenant_id)
        .options(
            selectinload(Tenant.subscriptions).selectinload(Subscription.plan),
            selectinload(Tenant.extra_modules),
        )
    )


def tenant_state(tenant: Tenant, on: date | None = None) -> TenantState:
    on = on or today()
    subs = list(tenant.subscriptions)
    sub = logic.current_subscription(subs, on)
    end = logic.effective_end(subs, on)
    status = logic.subscription_status(sub, on, tenant.suspended, end)
    plan = sub.plan if sub else None
    extra = [m.module for m in tenant.extra_modules]
    modules = logic.tenant_modules(plan.code if plan else None, plan.modules if plan else None, extra)
    limits = {
        "max_users": tenant.max_users or (plan.max_users if plan else 0),
        "max_companies": tenant.max_companies or (plan.max_companies if plan else 0),
        "max_warehouses": tenant.max_warehouses or (plan.max_warehouses if plan else 0),
        "max_pos": tenant.max_pos if tenant.max_pos is not None else (plan.max_pos if plan else 0),
    }
    return TenantState(
        tenant=tenant,
        subscription=sub,
        plan=plan,
        status=status,
        access=logic.access_level(status),
        end_date=end,
        days_left=(end - on).days if end else None,
        modules=modules if logic.access_level(status) != "none" else [],
        limits=limits,
    )


def audit(
    db: Session,
    entity: str,
    action: str,
    entity_id=None,
    tenant_id=None,
    user_id=None,
    admin_id=None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            entity=entity,
            action=action,
            entity_id=str(entity_id) if entity_id else None,
            tenant_id=tenant_id,
            user_id=user_id,
            admin_id=admin_id,
            before=before,
            after=after,
        )
    )


def lifecycle_settings(db: Session) -> dict:
    """Giorni di tolleranza e sola lettura predefiniti per i nuovi periodi e giorni di avviso della prova
    (modificabili dal pannello; senza riga valgono logic.LIFECYCLE_DEFAULTS)."""
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in logic.LIFECYCLE_DEFAULTS.items()}
    for row in db.scalars(select(SaasSetting).where(SaasSetting.key.in_(list(out)))):
        if row.value is not None:
            out[row.key] = row.value
    return out
