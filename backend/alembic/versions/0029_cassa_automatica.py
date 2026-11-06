"""cassa automatica VNE: incassi in attesa dell'esito della macchina (vendita bloccata finché la cassa risponde)

Revision ID: 0029_cassa_automatica
Revises: 0028_buoni_multiuso
Create Date: 2026-11-06 10:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0029_cassa_automatica'
down_revision = '0028_buoni_multiuso'
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.create_table('pos_cash_machine_payments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('register_id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.Column('device_id', sa.UUID(), nullable=True),
    sa.Column('job_id', sa.UUID(), nullable=True),
    sa.Column('client_uuid', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=14), nullable=False),
    sa.Column('total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('sale', JSON, nullable=False),
    sa.Column('result', JSON, nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('cancel_request', sa.Integer(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=True),
    sa.Column('resolution', JSON, nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['register_id'], ['pos_registers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['pos_sessions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['job_id'], ['device_jobs.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'client_uuid')
    )
    op.create_index(op.f('ix_pos_cash_machine_payments_tenant_id'), 'pos_cash_machine_payments', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_pos_cash_machine_payments_register_id'), 'pos_cash_machine_payments', ['register_id'], unique=False)
    op.create_index(op.f('ix_pos_cash_machine_payments_device_id'), 'pos_cash_machine_payments', ['device_id'], unique=False)
    op.create_index(op.f('ix_pos_cash_machine_payments_job_id'), 'pos_cash_machine_payments', ['job_id'], unique=False)
    op.create_index(op.f('ix_pos_cash_machine_payments_status'), 'pos_cash_machine_payments', ['status'], unique=False)
    op.execute("ALTER TABLE pos_cash_machine_payments ENABLE ROW LEVEL SECURITY")
    op.execute(
        """CREATE POLICY tenant_isolation ON pos_cash_machine_payments
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"""
    )


def downgrade() -> None:
    op.drop_table('pos_cash_machine_payments')
