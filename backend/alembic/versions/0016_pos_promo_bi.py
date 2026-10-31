"""Promozioni di cassa (prendi N paghi M, N-esimo scontato, soglia di spesa); vista BI con reparto, cassa, cassiere e ora

Revision ID: 0016_pos_promo_bi
Revises: 0015_pos
"""
import os

from alembic import op
import sqlalchemy as sa

revision = '0016_pos_promo_bi'
down_revision = '0015_pos'
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get('APP_DB_ROLE', 'blubeauty_app')

VIEW = """
CREATE VIEW bi_sales WITH (security_invoker = true) AS
SELECT
    l.id AS line_id,
    l.tenant_id,
    d.id AS document_id,
    d.doc_type,
    d.number AS doc_number,
    d.year AS doc_year,
    d.doc_date,
    (CASE WHEN d.register_id IS NOT NULL OR d.doc_type IN ('SCO', 'RSO') THEN 'banco' ELSE 'fattura' END)::varchar(10) AS channel,
    d.party_id,
    p.name AS party_name,
    p.city AS party_city,
    p.province AS party_province,
    p.customer_category_id,
    cc.name AS customer_category,
    l.item_id,
    i.code AS item_code,
    i.description AS item_description,
    i.category_id,
    c.name AS category_name,
    COALESCE(c2.id, c1.id, c.id) AS root_category_id,
    COALESCE(c2.name, c1.name, c.name) AS root_category_name,
    i.brand_id,
    b.name AS brand_name,
    d.warehouse_id,
    w.name AS warehouse_name,
    l.description AS line_description,
    l.unit,
    (CASE WHEN d.doc_type IN ('NC', 'RSO') THEN -1 ELSE 1 END) * l.quantity AS quantity,
    (CASE WHEN d.doc_type IN ('NC', 'RSO') THEN -1 ELSE 1 END) * l.line_total AS revenue,
    (CASE WHEN d.doc_type IN ('NC', 'RSO') THEN -1 ELSE 1 END) * COALESCE(l.unit_cost, 0) * l.quantity AS cost,
    (l.unit_cost IS NULL AND l.item_id IS NOT NULL) AS missing_cost,
    COALESCE(l.department_id, i.pos_department_id) AS department_id,
    dep.name AS department_name,
    d.register_id,
    reg.name AS register_name,
    d.created_by AS cashier_id,
    u.full_name AS cashier_name,
    CAST(EXTRACT(HOUR FROM d.created_at AT TIME ZONE 'Europe/Rome') AS integer) AS sale_hour,
    COALESCE(l.price_source = 'Promo cassa', false) AS is_promo
FROM document_lines l
JOIN documents d ON d.id = l.document_id
LEFT JOIN parties p ON p.id = d.party_id
LEFT JOIN customer_categories cc ON cc.id = p.customer_category_id
LEFT JOIN items i ON i.id = l.item_id
LEFT JOIN categories c ON c.id = i.category_id
LEFT JOIN categories c1 ON c1.id = c.parent_id
LEFT JOIN categories c2 ON c2.id = c1.parent_id
LEFT JOIN brands b ON b.id = i.brand_id
LEFT JOIN warehouses w ON w.id = d.warehouse_id
LEFT JOIN pos_departments dep ON dep.id = COALESCE(l.department_id, i.pos_department_id)
LEFT JOIN pos_registers reg ON reg.id = d.register_id
LEFT JOIN users u ON u.id = d.created_by
WHERE d.direction = 'vendita'
  AND d.doc_type IN ('FTI', 'FTD', 'NC', 'SCO', 'RSO')
  AND d.status IN ('confermato', 'evaso')
  AND l.line_total <> 0
"""

VIEW_0015 = """
CREATE VIEW bi_sales WITH (security_invoker = true) AS
SELECT
    l.id AS line_id,
    l.tenant_id,
    d.id AS document_id,
    d.doc_type,
    d.number AS doc_number,
    d.year AS doc_year,
    d.doc_date,
    (CASE WHEN d.register_id IS NOT NULL OR d.doc_type IN ('SCO', 'RSO') THEN 'banco' ELSE 'fattura' END)::varchar(10) AS channel,
    d.party_id,
    p.name AS party_name,
    p.city AS party_city,
    p.province AS party_province,
    p.customer_category_id,
    cc.name AS customer_category,
    l.item_id,
    i.code AS item_code,
    i.description AS item_description,
    i.category_id,
    c.name AS category_name,
    COALESCE(c2.id, c1.id, c.id) AS root_category_id,
    COALESCE(c2.name, c1.name, c.name) AS root_category_name,
    i.brand_id,
    b.name AS brand_name,
    d.warehouse_id,
    w.name AS warehouse_name,
    l.description AS line_description,
    l.unit,
    (CASE WHEN d.doc_type IN ('NC', 'RSO') THEN -1 ELSE 1 END) * l.quantity AS quantity,
    (CASE WHEN d.doc_type IN ('NC', 'RSO') THEN -1 ELSE 1 END) * l.line_total AS revenue,
    (CASE WHEN d.doc_type IN ('NC', 'RSO') THEN -1 ELSE 1 END) * COALESCE(l.unit_cost, 0) * l.quantity AS cost,
    (l.unit_cost IS NULL AND l.item_id IS NOT NULL) AS missing_cost
FROM document_lines l
JOIN documents d ON d.id = l.document_id
LEFT JOIN parties p ON p.id = d.party_id
LEFT JOIN customer_categories cc ON cc.id = p.customer_category_id
LEFT JOIN items i ON i.id = l.item_id
LEFT JOIN categories c ON c.id = i.category_id
LEFT JOIN categories c1 ON c1.id = c.parent_id
LEFT JOIN categories c2 ON c2.id = c1.parent_id
LEFT JOIN brands b ON b.id = i.brand_id
LEFT JOIN warehouses w ON w.id = d.warehouse_id
WHERE d.direction = 'vendita'
  AND d.doc_type IN ('FTI', 'FTD', 'NC', 'SCO', 'RSO')
  AND d.status IN ('confermato', 'evaso')
  AND l.line_total <> 0
"""


def upgrade() -> None:
    op.add_column('promotions', sa.Column('mechanic', sa.String(length=10), server_default='prezzo', nullable=False))
    op.add_column('promotions', sa.Column('buy_qty', sa.Integer(), nullable=True))
    op.add_column('promotions', sa.Column('pay_qty', sa.Integer(), nullable=True))
    op.add_column('promotions', sa.Column('threshold', sa.Numeric(precision=14, scale=4), nullable=True))
    # le nuove colonne si aggiungono in coda: CREATE OR REPLACE basta
    op.execute(VIEW.replace("CREATE VIEW", "CREATE OR REPLACE VIEW"))


def downgrade() -> None:
    op.execute("DROP VIEW bi_sales")
    op.execute(VIEW_0015)
    op.execute(f"GRANT SELECT ON bi_sales TO {APP_ROLE}")
    op.drop_column('promotions', 'threshold')
    op.drop_column('promotions', 'pay_qty')
    op.drop_column('promotions', 'buy_qty')
    op.drop_column('promotions', 'mechanic')
