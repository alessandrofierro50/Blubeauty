"""BI Pro: fatti acquisti, scadenze, preventivi e ordini, movimenti di magazzino (viste con RLS); report salvati e dashboard

Revision ID: 0018_bi_pro
Revises: 0017_periferiche
"""
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0018_bi_pro'
down_revision = '0017_periferiche'
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get('APP_DB_ROLE', 'blubeauty_app')

CATEGORY_JOINS = """
LEFT JOIN items i ON i.id = l.item_id
LEFT JOIN categories c ON c.id = i.category_id
LEFT JOIN categories c1 ON c1.id = c.parent_id
LEFT JOIN categories c2 ON c2.id = c1.parent_id
LEFT JOIN brands b ON b.id = i.brand_id"""

VIEWS = {
    # righe delle fatture e note di credito dei fornitori (spesa = imponibile, note di credito in negativo)
    "bi_purchases": f"""
CREATE VIEW bi_purchases WITH (security_invoker = true) AS
SELECT l.id AS line_id, l.tenant_id, d.id AS document_id, d.doc_type, d.number AS doc_number, d.external_number, d.year AS doc_year,
    d.doc_date, d.party_id, p.name AS party_name, p.province AS party_province,
    l.item_id, i.code AS item_code, i.description AS item_description, i.category_id, c.name AS category_name,
    COALESCE(c2.id, c1.id, c.id) AS root_category_id, COALESCE(c2.name, c1.name, c.name) AS root_category_name,
    i.brand_id, b.name AS brand_name, d.warehouse_id, w.name AS warehouse_name, l.description AS line_description, l.unit,
    (CASE WHEN d.doc_type = 'NCF' THEN -1 ELSE 1 END) * l.quantity AS quantity,
    (CASE WHEN d.doc_type = 'NCF' THEN -1 ELSE 1 END) * l.line_total AS amount
FROM document_lines l
JOIN documents d ON d.id = l.document_id
LEFT JOIN parties p ON p.id = d.party_id{CATEGORY_JOINS}
LEFT JOIN warehouses w ON w.id = d.warehouse_id
WHERE d.direction = 'acquisto' AND d.doc_type IN ('FTF', 'NCF') AND d.status IN ('confermato', 'evaso') AND l.line_total <> 0
""",
    # scadenze attive e passive con incassato, residuo e ritardo
    "bi_installments": """
CREATE VIEW bi_installments WITH (security_invoker = true) AS
SELECT s.id AS installment_id, s.tenant_id, s.direction, s.party_id, p.name AS party_name, p.province AS party_province,
    s.document_id, d.doc_type, d.number AS doc_number, d.external_number, d.year AS doc_year, s.issue_date, s.due_date,
    s.amount, s.paid_amount, s.amount - s.paid_amount AS residual, s.status, s.unpaid, s.method, s.account_id,
    fa.name AS account_name, s.reminder_level, s.description,
    lp.last_payment AS last_payment_date,
    CASE WHEN s.amount - s.paid_amount <> 0 AND s.due_date < CURRENT_DATE THEN s.amount - s.paid_amount ELSE 0 END AS overdue,
    CASE WHEN s.status = 'pagata' AND lp.last_payment IS NOT NULL THEN GREATEST(0, lp.last_payment - s.due_date)
         WHEN s.amount - s.paid_amount <> 0 AND s.due_date < CURRENT_DATE THEN CURRENT_DATE - s.due_date END AS delay_days
FROM installments s
LEFT JOIN parties p ON p.id = s.party_id
LEFT JOIN documents d ON d.id = s.document_id
LEFT JOIN financial_accounts fa ON fa.id = s.account_id
LEFT JOIN LATERAL (SELECT max(x.pay_date) AS last_payment FROM installment_payments x WHERE x.installment_id = s.id) lp ON true
""",
    # preventivi e ordini dei clienti: conversione, inevaso, tempi
    "bi_pipeline": """
CREATE VIEW bi_pipeline WITH (security_invoker = true) AS
SELECT d.id AS document_id, d.tenant_id, d.doc_type, d.number AS doc_number, d.year AS doc_year, d.doc_date, d.status,
    d.party_id, p.name AS party_name, p.province AS party_province, d.created_by, u.full_name AS seller_name,
    d.taxable_total AS amount,
    (d.status = 'evaso') AS converted,
    CASE WHEN d.doc_type = 'ORC' AND d.status = 'confermato'
         THEN COALESCE((SELECT sum(CASE WHEN x.quantity <> 0 THEN x.line_total * (x.quantity - x.qty_processed) / x.quantity ELSE 0 END)
                        FROM document_lines x WHERE x.document_id = d.id), 0)
         ELSE 0 END AS open_amount,
    nx.next_date - d.doc_date AS lead_days
FROM documents d
LEFT JOIN parties p ON p.id = d.party_id
LEFT JOIN users u ON u.id = d.created_by
LEFT JOIN LATERAL (SELECT min(d2.doc_date) AS next_date FROM document_links k JOIN documents d2 ON d2.id = k.to_id
                   WHERE k.from_id = d.id AND d2.status <> 'annullato') nx ON true
WHERE d.direction = 'vendita' AND d.doc_type IN ('PRV', 'ORC') AND d.status <> 'bozza'
""",
    # movimenti di magazzino valorizzati al costo del movimento (o al costo medio dell'articolo)
    "bi_stock_moves": f"""
CREATE VIEW bi_stock_moves WITH (security_invoker = true) AS
SELECT m.id AS move_id, m.tenant_id, (m.moved_at AT TIME ZONE 'Europe/Rome')::date AS move_date, m.warehouse_id, w.name AS warehouse_name,
    m.item_id, i.code AS item_code, i.description AS item_description, i.category_id, c.name AS category_name,
    COALESCE(c2.id, c1.id, c.id) AS root_category_id, COALESCE(c2.name, c1.name, c.name) AS root_category_name,
    i.brand_id, b.name AS brand_name, i.unit, m.reason, m.party_id, p.name AS party_name, m.document_type, m.document_id,
    m.quantity, m.quantity * COALESCE(m.unit_cost, i.avg_cost, i.last_cost, 0) AS value
FROM stock_movements m
CROSS JOIN LATERAL (SELECT m.item_id AS item_id) l{CATEGORY_JOINS}
LEFT JOIN warehouses w ON w.id = m.warehouse_id
LEFT JOIN parties p ON p.id = m.party_id
""",
}


def upgrade() -> None:
    for sql in VIEWS.values():
        op.execute(sql)
    for name in VIEWS:
        op.execute(f"GRANT SELECT ON {name} TO {APP_ROLE}")

    op.create_table('saved_reports',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('cube', sa.String(length=20), nullable=False),
        sa.Column('config', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
        sa.Column('owner_id', sa.UUID(), nullable=True),
        sa.Column('shared', sa.Boolean(), nullable=False),
        sa.Column('schedule', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
        sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_saved_reports_tenant_id'), 'saved_reports', ['tenant_id'], unique=False)
    op.create_table('dashboards',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('owner_id', sa.UUID(), nullable=True),
        sa.Column('shared', sa.Boolean(), nullable=False),
        sa.Column('widgets', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_dashboards_tenant_id'), 'dashboards', ['tenant_id'], unique=False)
    for table in ("saved_reports", "dashboards"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"""
        )


def downgrade() -> None:
    op.drop_index(op.f('ix_dashboards_tenant_id'), table_name='dashboards')
    op.drop_table('dashboards')
    op.drop_index(op.f('ix_saved_reports_tenant_id'), table_name='saved_reports')
    op.drop_table('saved_reports')
    for name in VIEWS:
        op.execute(f"DROP VIEW {name}")
