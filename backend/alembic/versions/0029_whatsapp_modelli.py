"""WhatsApp: ID dell'account Business e modelli dei messaggi da far approvare a Meta

Revision ID: 0029_whatsapp_modelli
Revises: 0028_buoni_multiuso
Create Date: 2026-11-08 09:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0029_whatsapp_modelli'
down_revision = '0028_buoni_multiuso'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('marketing_settings', sa.Column('whatsapp_waba_id', sa.String(length=40), nullable=True))
    for t in ('automations', 'campaigns'):
        op.add_column(t, sa.Column('wa_template', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))


def downgrade() -> None:
    for t in ('automations', 'campaigns'):
        op.drop_column(t, 'wa_template')
    op.drop_column('marketing_settings', 'whatsapp_waba_id')
