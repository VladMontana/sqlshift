-- Пример файла с SQL-запросами для тестирования и бенчмарка sqlshift

-- 1. Быстрый точечный запрос (Postgres OLTP)
SELECT id, email, created_at FROM users WHERE id = 100;

-- 2. Вставка записи в лог аудита (Postgres DML)
INSERT INTO audit_logs (user_id, event, created_at) VALUES (100, 'dashboard_view', NOW());

-- 3. Простая агрегация количества событий (ClickHouse OLAP)
SELECT count(*) FROM analytics_events WHERE status = 'completed';

-- 4. Группировка по месяцам с вычислением выручки (ClickHouse OLAP)
SELECT date_trunc('month', paid_at), sum(amount)
FROM payments
GROUP BY 1;

-- 5. Сложное аналитическое соединение таблиц (ClickHouse OLAP)
SELECT u.name, count(o.id) AS total_orders, sum(p.amount) AS total_spent
FROM users u
JOIN orders o ON u.id = o.user_id
JOIN payments p ON o.id = p.order_id
GROUP BY u.name;
