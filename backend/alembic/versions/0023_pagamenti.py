"""pagamenti online degli abbonamenti: pagamenti, indice di sistema, eventi dei webhook, contatori delle fatture

Revision ID: 0023_pagamenti
Revises: 0022_abbonamenti
Create Date: 2026-10-29 20:00:00.000000

Contratto comune: progetto_blucode_informatica/comune/pagamenti.md.
- payments: tabella del cliente (tenant_id + RLS);
- payment_routes, payment_events, invoice_counters: tabelle di sistema senza RLS (webhook senza utente, contatore unico
  per sezionale e anno). I GRANT al ruolo dell'app arrivano dai default privileges della 0001.
- Modelli email di scadenza non personalizzati: il pulsante diventa «Rinnova ora» verso la pagina di pagamento.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0023_pagamenti'
down_revision = '0022_abbonamenti'
branch_labels = None
depends_on = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')
OLD_BUTTON = '<p><a href="{link_accesso}" style="background:#2340a8;color:#fff;padding:10px 18px;\nborder-radius:6px;text-decoration:none">{label}</a></p>'
NEW_BUTTON = ('<p><a href="{link_rinnovo}" style="background:#2340a8;color:#fff;padding:10px 18px;\nborder-radius:6px;'
              'text-decoration:none">Rinnova ora</a> &nbsp; <a href="{link_accesso}" style="color:#2340a8">{label}</a></p>')
TEMPLATES = {"scadenza_avviso": "Accedi a BluBeauty", "scadenza_oggi": "Accedi a BluBeauty", "fine_tolleranza": "Accedi a BluBeauty",
             "sospensione": "Vedi il tuo abbonamento", "prova_avviso": "Accedi a BluBeauty", "prova_oggi": "Accedi a BluBeauty",
             "prova_scaduta": "Vedi il tuo abbonamento"}


def upgrade() -> None:
    op.create_table(
        'payments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('plan_code', sa.String(length=20), nullable=False),
        sa.Column('plan_name', sa.String(length=80), nullable=False),
        sa.Column('period', sa.String(length=20), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('stamp', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('stamp_duty', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('total', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('method', sa.String(length=12), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('causale', sa.String(length=60), nullable=False),
        sa.Column('provider_ref', sa.String(length=120), nullable=True),
        sa.Column('provider_payment_ref', sa.String(length=120), nullable=True),
        sa.Column('billing', JSONB, nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('confirmed_by', sa.String(length=80), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('subscription_id', sa.UUID(), nullable=True),
        sa.Column('period_start', sa.Date(), nullable=True),
        sa.Column('period_end', sa.Date(), nullable=True),
        sa.Column('invoice_sezionale', sa.String(length=10), nullable=True),
        sa.Column('invoice_year', sa.Integer(), nullable=True),
        sa.Column('invoice_number', sa.Integer(), nullable=True),
        sa.Column('invoice_date', sa.Date(), nullable=True),
        sa.Column('invoice_format', sa.String(length=5), nullable=True),
        sa.Column('invoice_xml', sa.LargeBinary(), nullable=True),
        sa.Column('invoice_pdf', sa.LargeBinary(), nullable=True),
        sa.Column('invoice_errors', JSONB, nullable=False),
        sa.Column('sdi_status', sa.String(length=24), nullable=True),
        sa.Column('sdi_filename', sa.String(length=80), nullable=True),
        sa.Column('sdi_error', sa.Text(), nullable=True),
        sa.Column('customer_email_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('admin_email_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('email_error', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['plan_id'], ['plans.id']),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('causale'),
        sa.UniqueConstraint('invoice_sezionale', 'invoice_year', 'invoice_number', name='uq_payment_invoice_number'),
    )
    op.create_index(op.f('ix_payments_tenant_id'), 'payments', ['tenant_id'], unique=False)
    op.execute("ALTER TABLE payments ENABLE ROW LEVEL SECURITY")
    op.execute(
        """CREATE POLICY tenant_isolation ON payments
           USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
           WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"""
    )

    # indice di sistema (senza RLS): webhook, elenco del pannello, console
    op.create_table(
        'payment_routes',
        sa.Column('payment_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('provider', sa.String(length=12), nullable=False),
        sa.Column('provider_ref', sa.String(length=120), nullable=True),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('plan_code', sa.String(length=20), nullable=False),
        sa.Column('period', sa.String(length=20), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('total', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('causale', sa.String(length=60), nullable=False),
        sa.Column('invoice', sa.String(length=30), nullable=True),
        sa.Column('subscription_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('payment_id'),
        sa.UniqueConstraint('provider_ref'),
    )
    op.create_index(op.f('ix_payment_routes_tenant_id'), 'payment_routes', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_payment_routes_status'), 'payment_routes', ['status'], unique=False)
    op.create_index(op.f('ix_payment_routes_paid_at'), 'payment_routes', ['paid_at'], unique=False)

    # eventi dei webhook già elaborati (contro i replay)
    op.create_table(
        'payment_events',
        sa.Column('provider', sa.String(length=12), nullable=False),
        sa.Column('event_id', sa.String(length=120), nullable=False),
        sa.Column('event_type', sa.String(length=80), nullable=True),
        sa.Column('payment_id', sa.UUID(), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('provider', 'event_id'),
    )

    # numerazione delle fatture: un contatore per sezionale e anno solare
    op.create_table(
        'invoice_counters',
        sa.Column('sezionale', sa.String(length=10), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('last_number', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('sezionale', 'year'),
    )

    for code, label in TEMPLATES.items():
        op.execute(sa.text("UPDATE email_templates SET body = replace(body, :old, :new) WHERE code = :code")
                   .bindparams(old=OLD_BUTTON.replace('{label}', label), new=NEW_BUTTON.replace('{label}', label), code=code))


def downgrade() -> None:
    for code, label in TEMPLATES.items():
        op.execute(sa.text("UPDATE email_templates SET body = replace(body, :new, :old) WHERE code = :code")
                   .bindparams(old=OLD_BUTTON.replace('{label}', label), new=NEW_BUTTON.replace('{label}', label), code=code))
    op.drop_table('invoice_counters')
    op.drop_table('payment_events')
    op.drop_index(op.f('ix_payment_routes_paid_at'), table_name='payment_routes')
    op.drop_index(op.f('ix_payment_routes_status'), table_name='payment_routes')
    op.drop_index(op.f('ix_payment_routes_tenant_id'), table_name='payment_routes')
    op.drop_table('payment_routes')
    op.drop_index(op.f('ix_payments_tenant_id'), table_name='payments')
    op.drop_table('payments')
