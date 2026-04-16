-- wrk script: GET order card endpoint
-- Usage:
-- wrk -t4 -c100 -d30s -s loadtest/wrk/order_card.lua http://localhost:8082
--
-- Перед запуском подставьте валидный order_id в path.

wrk.method = "GET"
-- Замените ORDER_ID_HERE на UUID существующего заказа
wrk.path = "/api/cache-demo/orders/ORDER_ID_HERE/card?use_cache=true"
