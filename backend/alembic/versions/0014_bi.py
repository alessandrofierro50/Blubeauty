"""Business Intelligence: vista dei fatti di vendita (modello a stella)

Revision ID: 0014_bi
Revises: 0013_fatturapa
Create Date: 2026-10-28 17:00:00

Una riga per ogni riga fatturata (fatture immediate e differite, note di credito con segno negativo), già
arricchita con gli attributi delle dimensioni. security_invoker: la vista applica la RLS di chi la interroga,
quindi ogni azienda vede solo i propri dati.
"""
import os

from alembic import op

revision = '0014_bi'
down_revision = '0013_fatturapa'
branch_labels = None
depends_on = None

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
    'fattura'::varchar(10) AS channel,
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
    (CASE WHEN d.doc_type = 'NC' THEN -1 ELSE 1 END) * l.quantity AS quantity,
    (CASE WHEN d.doc_type = 'NC' THEN -1 ELSE 1 END) * l.line_total AS revenue,
    (CASE WHEN d.doc_type = 'NC' THEN -1 ELSE 1 END) * COALESCE(l.unit_cost, 0) * l.quantity AS cost,
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
  AND d.doc_type IN ('FTI', 'FTD', 'NC')
  AND d.status IN ('confermato', 'evaso')
  AND l.line_total <> 0
"""


def upgrade() -> None:
    op.execute(VIEW)
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_sales_date ON documents (tenant_id, doc_date) WHERE direction = 'vendita'")
    op.execute(f"GRANT SELECT ON bi_sales TO {os.environ.get('APP_DB_ROLE', 'blubeauty_app')}")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_sales_date")
    op.execute("DROP VIEW IF EXISTS bi_sales")
