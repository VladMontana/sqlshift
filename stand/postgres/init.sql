-- PostgreSQL Store Stand Schema & Deterministic Seed
-- Total orders: 10 rows, exact amount sum = 2300.00
-- Total returns: 3 rows, exact refund_amount sum = 720.00

CREATE TABLE IF NOT EXISTS orders (
    id BIGINT PRIMARY KEY,
    customer_id INT NOT NULL,
    order_date DATE NOT NULL,
    status VARCHAR(32) NOT NULL,
    amount NUMERIC(10, 2) NOT NULL,
    items_count INT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS returns (
    id BIGINT PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id),
    return_date DATE NOT NULL,
    reason VARCHAR(255) NOT NULL,
    refund_amount NUMERIC(10, 2) NOT NULL,
    status VARCHAR(32) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_returns_order ON returns(order_id);

INSERT INTO orders (id, customer_id, order_date, status, amount, items_count, created_at) VALUES
(1, 101, '2026-01-15', 'paid', 150.00, 2, '2026-01-15 10:00:00'),
(2, 102, '2026-01-18', 'paid', 320.50, 4, '2026-01-18 11:30:00'),
(3, 101, '2026-01-20', 'shipped', 75.20, 1, '2026-01-20 14:15:00'),
(4, 103, '2026-02-05', 'paid', 210.00, 3, '2026-02-05 09:00:00'),
(5, 104, '2026-02-12', 'cancelled', 450.00, 5, '2026-02-12 16:45:00'),
(6, 102, '2026-02-22', 'shipped', 99.90, 1, '2026-02-22 13:20:00'),
(7, 105, '2026-03-01', 'processing', 55.00, 1, '2026-03-01 10:10:00'),
(8, 101, '2026-03-05', 'paid', 500.00, 6, '2026-03-05 15:00:00'),
(9, 106, '2026-03-10', 'shipped', 125.40, 2, '2026-03-10 12:00:00'),
(10, 104, '2026-03-15', 'paid', 314.00, 3, '2026-03-15 17:30:00')
ON CONFLICT (id) DO NOTHING;

INSERT INTO returns (id, order_id, return_date, reason, refund_amount, status) VALUES
(1, 2, '2026-01-22', 'Defective item', 120.00, 'approved'),
(2, 5, '2026-02-15', 'Customer cancelled before dispatch', 450.00, 'completed'),
(3, 8, '2026-03-12', 'Wrong size delivered', 150.00, 'pending')
ON CONFLICT (id) DO NOTHING;
