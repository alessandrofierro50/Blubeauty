"""buoni regalo multiuso: tipo fiscale e cliente che riceve il buono; la vendita del buono multiuso non è un ricavo

Revision ID: 0028_buoni_multiuso
Revises: 0027_prepagati
Create Date: 2026-11-01 08:00:00
"""
import importlib.util
import os

from alembic import op
import sqlalchemy as sa

revision = '0028_buoni_multiuso'
down_revision = '0027_prepagati'
branch_labels = None
depends_on = None


def _view_0019() -> str:
    spec = importlib.util.spec_from_file_location("m0019", os.path.join(os.path.dirname(__file__), "0019_tentata.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.VIEW


STATUS = "  AND d.status IN ('confermato', 'evaso')"


def upgrade() -> None:
    op.add_column('gift_vouchers', sa.Column('beneficiary_party_id', sa.UUID(), nullable=True))
    op.add_column('gift_vouchers', sa.Column('fiscal_mode', sa.String(length=10), server_default='multiuso', nullable=False))
    op.create_index(op.f('ix_gift_vouchers_beneficiary_party_id'), 'gift_vouchers', ['beneficiary_party_id'], unique=False)
    op.create_foreign_key('fk_gift_vouchers_beneficiary', 'gift_vouchers', 'parties', ['beneficiary_party_id'], ['id'], ondelete='SET NULL')
    op.execute("UPDATE gift_vouchers SET fiscal_mode = 'monouso'")  # quelli già venduti avevano lo scontrino alla vendita
    # statistiche: la vendita di un buono multiuso è solo un incasso, il ricavo nasce quando il buono viene usato
    view = _view_0019()
    assert STATUS in view
    view = view.replace(STATUS, STATUS + "\n  AND (d.fiscal ->> 'voucher_sale') IS NULL")
    op.execute(view.replace("CREATE VIEW", "CREATE OR REPLACE VIEW"))


def downgrade() -> None:
    op.execute(_view_0019().replace("CREATE VIEW", "CREATE OR REPLACE VIEW"))
    op.drop_constraint('fk_gift_vouchers_beneficiary', 'gift_vouchers', type_='foreignkey')
    op.drop_index(op.f('ix_gift_vouchers_beneficiary_party_id'), table_name='gift_vouchers')
    op.drop_column('gift_vouchers', 'fiscal_mode')
    op.drop_column('gift_vouchers', 'beneficiary_party_id')
