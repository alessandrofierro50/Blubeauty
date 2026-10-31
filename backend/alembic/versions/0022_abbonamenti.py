"""standard comune degli abbonamenti: avviso a 3 giorni, nuovo testo di fine tolleranza, credenziali dalla Console

Revision ID: 0022_abbonamenti
Revises: 0021_termini
Create Date: 2026-10-29 18:00:00.000000

saas_settings (tolleranza, sola lettura e avvisi della prova modificabili dal pannello);
super_admins: token_version (invalida le sessioni quando la Console cambia le credenziali), created_at
(il super amministratore principale è il primo creato), credentials_changed_at. I modelli email nuovi (sospensione, prova_avviso, prova_oggi, prova_scaduta) li
aggiunge il seed all'avvio (entrypoint: alembic upgrade head e poi python -m app.seed).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = '0022_abbonamenti'
down_revision = '0021_termini'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('super_admins', sa.Column('token_version', sa.Integer(), server_default='0', nullable=False))
    op.add_column('super_admins', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                                            nullable=False))
    op.add_column('super_admins', sa.Column('credentials_changed_at', sa.DateTime(timezone=True), nullable=True))
    # impostazioni del ciclo di vita modificabili dal pannello (tabella di sistema, senza RLS; GRANT dai default privileges)
    op.create_table('saas_settings',
                    sa.Column('key', sa.String(length=60), nullable=False),
                    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
                    sa.PrimaryKeyConstraint('key'))
    # 30, 15, 7, 3, 1, 0: si aggiunge il 3 alle regole esistenti (restano modificabili dal pannello)
    op.execute("INSERT INTO reminder_rules (days_before, active) SELECT 3, true "
               "WHERE EXISTS (SELECT 1 FROM reminder_rules) ON CONFLICT (days_before) DO NOTHING")
    # «fine_tolleranza» ora parte l'ultimo giorno di tolleranza («da domani sola lettura»): il vecchio testo
    # («è ora in sola lettura») si toglie solo se mai personalizzato, e il seed lo ricrea col testo nuovo.
    op.execute("DELETE FROM email_templates WHERE code = 'fine_tolleranza' AND subject = 'BluBeauty è ora in sola lettura'")


def downgrade() -> None:
    op.drop_table('saas_settings')
    op.drop_column('super_admins', 'credentials_changed_at')
    op.drop_column('super_admins', 'created_at')
    op.drop_column('super_admins', 'token_version')
    op.execute("DELETE FROM reminder_rules WHERE days_before = 3")
