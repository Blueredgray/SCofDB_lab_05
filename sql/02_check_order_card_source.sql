\timing on

-- ============================================
-- LAB 05: Проверка "истины" в БД для карточки заказа
-- ============================================
--
-- Замените ORDER_ID_HERE на UUID заказа, который тестируете.

SELECT
    o.id,
    o.user_id,
    o.status,
    o.total_amount,
    o.created_at
FROM orders o
WHERE o.id = 'ORDER_ID_HERE'::uuid;

SELECT
    oi.order_id,
    oi.product_name,
    oi.price,
    oi.quantity
FROM order_items oi
WHERE oi.order_id = 'ORDER_ID_HERE'::uuid
ORDER BY oi.product_name;
