"""tentata vendita: furgoni, giro clienti, giri, conte al rientro, incassi; documenti col giro e la consegna firmata

Revision ID: 0019_tentata
Revises: 0018_bi_pro
Create Date: 2026-10-28 21:14:51.201244
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0019_tentata'
down_revision = '0018_bi_pro'
branch_labels = None
depends_on = None

VIEW_0016 = """
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

# vista delle vendite con furgone e agente (canale "furgone"): colonne nuove in coda, CREATE OR REPLACE basta
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
    (CASE WHEN vt.van_id IS NOT NULL THEN 'furgone' WHEN d.register_id IS NOT NULL OR d.doc_type IN ('SCO', 'RSO') THEN 'banco' ELSE 'fattura' END)::varchar(10) AS channel,
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
    COALESCE(l.price_source = 'Promo cassa', false) AS is_promo,
    vt.van_id,
    v.name AS van_name,
    vt.agent_id,
    ag.full_name AS agent_name
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
-- giro del furgone: del documento, o del DDT dell'agente da cui nasce la fattura differita
LEFT JOIN LATERAL (
    SELECT t.van_id, t.agent_id FROM van_trips t
    WHERE t.id = COALESCE(d.van_trip_id, (SELECT od.van_trip_id FROM document_lines ol JOIN documents od ON od.id = ol.document_id
                                          WHERE ol.id = l.origin_line_id))
) vt ON true
LEFT JOIN vans v ON v.id = vt.van_id
LEFT JOIN users ag ON ag.id = vt.agent_id
WHERE d.direction = 'vendita'
  AND d.doc_type IN ('FTI', 'FTD', 'NC', 'SCO', 'RSO')
  AND d.status IN ('confermato', 'evaso')
  AND l.line_total <> 0
"""

TABLES = ("vans", "van_route_stops", "van_trips", "van_counts", "van_collections")


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('vans',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=10), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('vehicle', sa.String(length=60), nullable=True),
    sa.Column('plate', sa.String(length=12), nullable=True),
    sa.Column('warehouse_id', sa.UUID(), nullable=False),
    sa.Column('home_warehouse_id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=True),
    sa.Column('series', sa.String(length=10), nullable=False),
    sa.Column('max_discount', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('allowed_docs', postgresql.ARRAY(sa.String()), nullable=False),
    sa.Column('cash_account_id', sa.UUID(), nullable=True),
    sa.Column('blind_count', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['cash_account_id'], ['financial_accounts.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['home_warehouse_id'], ['warehouses.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'code'),
    sa.UniqueConstraint('tenant_id', 'series'),
    sa.UniqueConstraint('warehouse_id')
    )
    op.create_index(op.f('ix_vans_agent_id'), 'vans', ['agent_id'], unique=False)
    op.create_index(op.f('ix_vans_tenant_id'), 'vans', ['tenant_id'], unique=False)
    op.create_table('van_route_stops',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('van_id', sa.UUID(), nullable=False),
    sa.Column('party_id', sa.UUID(), nullable=False),
    sa.Column('weekdays', postgresql.ARRAY(sa.SmallInteger()), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['party_id'], ['parties.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['van_id'], ['vans.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('van_id', 'party_id')
    )
    op.create_index(op.f('ix_van_route_stops_tenant_id'), 'van_route_stops', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_van_route_stops_van_id'), 'van_route_stops', ['van_id'], unique=False)
    op.create_table('van_trips',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('van_id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=True),
    sa.Column('trip_date', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('stops', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('load_operations', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('km_start', sa.Integer(), nullable=True),
    sa.Column('km_end', sa.Integer(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('returned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cash_declared', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('return_notes', sa.Text(), nullable=True),
    sa.Column('checked_by', sa.UUID(), nullable=True),
    sa.Column('checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('remaining', sa.String(length=10), nullable=True),
    sa.Column('signatures', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('return_operation_id', sa.UUID(), nullable=True),
    sa.Column('adjust_operation_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['checked_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['van_id'], ['vans.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('van_id', 'trip_date')
    )
    op.create_index(op.f('ix_van_trips_tenant_id'), 'van_trips', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_van_trips_van_id'), 'van_trips', ['van_id'], unique=False)
    op.create_table('van_counts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('trip_id', sa.UUID(), nullable=False),
    sa.Column('item_id', sa.UUID(), nullable=False),
    sa.Column('variant_id', sa.UUID(), nullable=True),
    sa.Column('lot_id', sa.UUID(), nullable=True),
    sa.Column('expected', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('agent_count', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('counted', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('reason', sa.String(length=20), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['lot_id'], ['lots.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['trip_id'], ['van_trips.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['variant_id'], ['item_variants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_van_counts_tenant_id'), 'van_counts', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_van_counts_trip_id'), 'van_counts', ['trip_id'], unique=False)
    op.create_table('van_collections',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('trip_id', sa.UUID(), nullable=False),
    sa.Column('party_id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=True),
    sa.Column('method', sa.String(length=10), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('check_info', sa.String(length=120), nullable=True),
    sa.Column('payment_ids', postgresql.ARRAY(sa.UUID()), nullable=False),
    sa.Column('unallocated', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('signature', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('client_uuid', sa.UUID(), nullable=True),
    sa.Column('collected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['party_id'], ['parties.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['trip_id'], ['van_trips.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'client_uuid')
    )
    op.create_index(op.f('ix_van_collections_tenant_id'), 'van_collections', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_van_collections_trip_id'), 'van_collections', ['trip_id'], unique=False)
    op.add_column('documents', sa.Column('van_trip_id', sa.UUID(), nullable=True))
    op.add_column('documents', sa.Column('delivery', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), server_default='{}', nullable=False))
    op.create_index(op.f('ix_documents_van_trip_id'), 'documents', ['van_trip_id'], unique=False)
    op.create_foreign_key('fk_documents_van_trip', 'documents', 'van_trips', ['van_trip_id'], ['id'], ondelete='SET NULL')
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"""
        )
    op.execute(VIEW.replace("CREATE VIEW", "CREATE OR REPLACE VIEW"))
    # ### end Alembic commands ###


def downgrade() -> None:
    import os
    op.execute("DROP VIEW bi_sales")
    op.execute(VIEW_0016)
    op.execute(f"GRANT SELECT ON bi_sales TO {os.environ.get('APP_DB_ROLE', 'blubeauty_app')}")
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('fk_documents_van_trip', 'documents', type_='foreignkey')
    op.drop_index(op.f('ix_documents_van_trip_id'), table_name='documents')
    op.drop_column('documents', 'delivery')
    op.drop_column('documents', 'van_trip_id')
    op.drop_index(op.f('ix_van_collections_trip_id'), table_name='van_collections')
    op.drop_index(op.f('ix_van_collections_tenant_id'), table_name='van_collections')
    op.drop_table('van_collections')
    op.drop_index(op.f('ix_van_counts_trip_id'), table_name='van_counts')
    op.drop_index(op.f('ix_van_counts_tenant_id'), table_name='van_counts')
    op.drop_table('van_counts')
    op.drop_index(op.f('ix_van_trips_van_id'), table_name='van_trips')
    op.drop_index(op.f('ix_van_trips_tenant_id'), table_name='van_trips')
    op.drop_table('van_trips')
    op.drop_index(op.f('ix_van_route_stops_van_id'), table_name='van_route_stops')
    op.drop_index(op.f('ix_van_route_stops_tenant_id'), table_name='van_route_stops')
    op.drop_table('van_route_stops')
    op.drop_index(op.f('ix_vans_tenant_id'), table_name='vans')
    op.drop_index(op.f('ix_vans_agent_id'), table_name='vans')
    op.drop_table('vans')
    # ### end Alembic commands ###
