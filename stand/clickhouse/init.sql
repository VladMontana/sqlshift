-- ClickHouse Store Stand Schema & Deterministic Seed
-- Only analytical table orders is created here (returns is kept exclusively in PostgreSQL)
-- Total orders: 10 rows, exact amount sum = 2300.00

CREATE TABLE IF NOT EXISTS orders (
    id UInt64,
    customer_id UInt32,
    order_date Date,
    status LowCardinality(String),
    amount Decimal(10, 2),
    items_count UInt32,
    created_at DateTime
) ENGINE = MergeTree()
ORDER BY id;

INSERT INTO orders (id, customer_id, order_date, status, amount, items_count, created_at) VALUES (1, 101, '2026-01-15', 'paid', 150.00, 2, '2026-01-15 10:00:00'), (2, 102, '2026-01-18', 'paid', 320.50, 4, '2026-01-18 11:30:00'), (3, 101, '2026-01-20', 'shipped', 75.20, 1, '2026-01-20 14:15:00'), (4, 103, '2026-02-05', 'paid', 210.00, 3, '2026-02-05 09:00:00'), (5, 104, '2026-02-12', 'cancelled', 450.00, 5, '2026-02-12 16:45:00'), (6, 102, '2026-02-22', 'shipped', 99.90, 1, '2026-02-22 13:20:00'), (7, 105, '2026-03-01', 'processing', 55.00, 1, '2026-03-01 10:10:00'), (8, 101, '2026-03-05', 'paid', 500.00, 6, '2026-03-05 15:00:00'), (9, 106, '2026-03-10', 'shipped', 125.40, 2, '2026-03-10 12:00:00'), (10, 104, '2026-03-15', 'paid', 314.00, 3, '2026-03-15 17:30:00');
