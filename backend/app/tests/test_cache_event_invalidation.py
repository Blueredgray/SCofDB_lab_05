"""
LAB 05: Проверка починки через событийную инвалидацию.

Тест проверяет, что после событийной инвалидации
клиент получает свежие данные из БД, а не stale cache.
"""

import pytest
import uuid
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.fixture(scope="function")
async def test_order():
    """
    Создать тестовый заказ через API и вернуть order_id.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        # Создаём пользователя
        user_resp = await client.post(
            "/api/users",
            json={"email": f"event_test_{uuid.uuid4()}@example.com", "name": "Event Test User"}
        )
        assert user_resp.status_code == 201
        user_id = user_resp.json()["id"]

        # Создаём заказ
        order_resp = await client.post("/api/orders", json={"user_id": user_id})
        assert order_resp.status_code == 201
        order_id = order_resp.json()["id"]

        # Добавляем товар
        item_resp = await client.post(
            f"/api/orders/{order_id}/items",
            json={"product_name": "Event Widget", "price": 200.0, "quantity": 2}
        )
        assert item_resp.status_code == 201

    yield order_id


@pytest.mark.asyncio
async def test_order_card_is_fresh_after_event_invalidation(test_order):
    """
    Сценарий починки через событийную инвалидацию:

    1) Прогреть кэш карточки заказа.
    2) Изменить заказ через mutate-with-event-invalidation.
    3) Убедиться, что ключ карточки инвалидирован.
    4) Повторный GET возвращает свежие данные из БД, а не stale cache.
    """
    order_id = test_order
    new_total = 5555.55

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        # Шаг 1: прогрев кэша
        resp_warm = await client.get(
            f"/api/cache-demo/orders/{order_id}/card?use_cache=true"
        )
        assert resp_warm.status_code == 200
        warm_data = resp_warm.json()
        warm_total = warm_data["order_card"]["total_amount"]

        # Шаг 2: изменяем заказ С событийной инвалидацией
        resp_mutate = await client.post(
            f"/api/cache-demo/orders/{order_id}/mutate-with-event-invalidation",
            json={"new_total_amount": new_total}
        )
        assert resp_mutate.status_code == 200
        mutate_data = resp_mutate.json()
        assert mutate_data["cache_invalidated"] is True
        assert "OrderUpdated" in mutate_data["event_published"]

        # Шаг 3: повторный запрос с use_cache=true
        resp_fresh = await client.get(
            f"/api/cache-demo/orders/{order_id}/card?use_cache=true"
        )
        assert resp_fresh.status_code == 200
        fresh_data = resp_fresh.json()
        fresh_total = fresh_data["order_card"]["total_amount"]
        fresh_source = fresh_data["source"]

        # Шаг 4: данные должны быть СВЕЖИМИ (из БД)
        assert fresh_total == new_total, (
            f"Expected fresh total={new_total}, got {fresh_total}. "
            f"Cache was invalidated, so the request should have loaded fresh data from DB."
        )
        assert fresh_total != warm_total, (
            f"Fresh total ({fresh_total}) should differ from warm total ({warm_total})."
        )

        # Источник должен быть 'database' (cache miss после инвалидации)
        assert fresh_source == "database", (
            f"Expected source='database' after invalidation, got '{fresh_source}'. "
            "After event invalidation, the next request should be a cache miss."
        )

    print(f"\n[LAB 05] Event invalidation demonstration:")
    print(f"  Order ID: {order_id}")
    print(f"  Warm-up total (old): {warm_total}")
    print(f"  New total (after mutation): {new_total}")
    print(f"  Fresh total (after invalidation): {fresh_total}")
    print(f"  Source after invalidation: {fresh_source}")
    print(f"  CONCLUSION: Event invalidation works — fresh data returned")
