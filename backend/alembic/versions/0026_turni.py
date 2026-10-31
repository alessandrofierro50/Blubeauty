"""BluBeauty: turni e assenze degli operatori (ferie, malattia, permessi, orari diversi, chiusure del salone)
e settimane alterne

Revision ID: 0026_turni
Revises: 0025_fidelity
Create Date: 2026-11-01 00:40:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0026_turni'
down_revision = '0025_fidelity'
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.create_table('agenda_absences',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('staff_id', sa.UUID(), nullable=True),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('date_from', sa.Date(), nullable=False),
    sa.Column('date_to', sa.Date(), nullable=False),
    sa.Column('hours', JSON, nullable=False),
    sa.Column('note', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['staff_id'], ['agenda_staff.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agenda_absences_tenant_id'), 'agenda_absences', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_agenda_absences_staff_id'), 'agenda_absences', ['staff_id'], unique=False)
    op.create_index(op.f('ix_agenda_absences_date_from'), 'agenda_absences', ['date_from'], unique=False)
    op.create_index(op.f('ix_agenda_absences_date_to'), 'agenda_absences', ['date_to'], unique=False)
    op.add_column('agenda_staff', sa.Column('working_hours_b', JSON, nullable=False, server_default='{}'))
    op.add_column('agenda_staff', sa.Column('alt_week_a', sa.Date(), nullable=True))
    op.execute("ALTER TABLE agenda_absences ENABLE ROW LEVEL SECURITY")
    op.execute(
        """CREATE POLICY tenant_isolation ON agenda_absences
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"""
    )


def downgrade() -> None:
    op.drop_column('agenda_staff', 'alt_week_a')
    op.drop_column('agenda_staff', 'working_hours_b')
    op.drop_table('agenda_absences')
