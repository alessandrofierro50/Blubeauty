"""Fatturazione elettronica: da modulo del pacchetto Base a modulo extra a pagamento

Revision ID: 0011_fatturapa_extra
Revises: 0010_vendite
Create Date: 2026-10-28 13:58:00
"""
from alembic import op

revision = '0011_fatturapa_extra'
down_revision = '0010_vendite'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Chi aveva già un abbonamento con la fatturazione elettronica la conserva come modulo extra.
    op.execute("""
        INSERT INTO tenant_modules (tenant_id, module)
        SELECT DISTINCT s.tenant_id, 'fatturapa' FROM subscriptions s JOIN plans p ON p.id = s.plan_id
        WHERE 'fatturapa' = ANY(p.modules) AND s.end_date >= CURRENT_DATE
        ON CONFLICT DO NOTHING
    """)
    op.execute("UPDATE plans SET modules = array_remove(modules, 'fatturapa')")


def downgrade() -> None:
    op.execute("UPDATE plans SET modules = array_append(modules, 'fatturapa') WHERE code IN ('BASE', 'PLUS', 'PRO') AND NOT 'fatturapa' = ANY(modules)")
