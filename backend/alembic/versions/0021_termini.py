"""accettazione dei termini di utilizzo sull'azienda (prova dal sito)

Revision ID: 0021_termini
Revises: 0020_password
Create Date: 2026-10-29 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0021_termini'
down_revision = '0020_password'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # tenants è una tabella di sistema (non in TENANT_TABLES, senza RLS): bastano le colonne
    op.add_column('tenants', sa.Column('terms_version', sa.String(length=20), nullable=True))
    op.add_column('tenants', sa.Column('terms_accepted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tenants', sa.Column('terms_accepted_ip', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('tenants', 'terms_accepted_ip')
    op.drop_column('tenants', 'terms_accepted_at')
    op.drop_column('tenants', 'terms_version')
