"""
LAB 05: Демонстрация неконсистентности кэша.

Тест проверяет, что при изменении данных в БД без инвалидации кэша
клиент получает stale (устаревшие) данные.
"""

import pytest
import uuid
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.fixture(scope="function")
async def test_order():
    """
    Создать тестовый заказ через API и вернуть order_id.
    Заказ создаётся со статусом 'created' и total_amount=100.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        # Создаём пользователя
        user_resp = await client.post(
            "/api/users",
            json={"email": f"stale_test_{uuid.uuid4()}@example.com", "name": "Stale Test User"}
        )
        assert user_resp.status_code == 201
        user_id = user_resp.json()["id"]

        # Создаём заказ
        order_resp = await client.post("/api/orders", json={"user_id": user_id})
        assert order_resp.status_code == 201
        order_id = order_resp.json()["id"]

        # Добавляем товар в заказ
        item_resp = await client.post(
            f"/api/orders/{order_id}/items",
            json={"product_name": "Test Widget", "price": 100.0, "quantity": 1}
        )
        assert item_resp.status_code == 201

    yield order_id


@pytest.mark.asyncio
async def test_stale_order_card_when_db_updated_without_invalidation(test_order):
    """
    Сценарий stale cache:

    1) Прогреть кэш карточки заказа (GET /api/cache-demo/orders/{id}/card?use_cache=true).
    2) Изменить заказ в БД через endpoint mutate-without-invalidation.
    3) Повторно запросить карточку с use_cache=true.
    4) Проверить, что клиент получает stale данные из кэша.
    """
    order_id = test_order
    new_total = 9999.99

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        # Шаг 1: прогрев кэша — первый запрос должен загрузить данные из БД
        resp_warm = await client.get(
            f"/api/cache-demo/orders/{order_id}/card?use_cache=true"
        )
        assert resp_warm.status_code == 200
        warm_data = resp_warm.json()
        warm_total = warm_data["order_card"]["total_amount"]
        warm_source = warm_data["source"]

        # Шаг 2: изменяем заказ в БД БЕЗ инвалидации кэша
        resp_mutate = await client.post(
            f"/api/cache-demo/orders/{order_id}/mutate-without-invalidation",
            json={"new_total_amount": new_total}
        )
        assert resp_mutate.status_code == 200
        mutate_data = resp_mutate.json()
        assert mutate_data["cache_invalidated"] is False

        # Шаг 3: повторный запрос с use_cache=true — должен вернуть stale data
        resp_stale = await client.get(
            f"/api/cache-demo/orders/{order_id}/card?use_cache=true"
        )
        assert resp_stale.status_code == 200
        stale_data = resp_stale.json()
        stale_total = stale_data["order_card"]["total_amount"]
        stale_source = stale_data["source"]

        # Шаг 4: проверяем stale data
        # Данные из кэша должны быть старыми (до мутации)
        assert stale_total == warm_total, (
            f"Stale data expected: total_amount={warm_total}, got {stale_total}. "
            f"Cache should return old value because invalidation was NOT performed."
        )
        assert stale_total != new_total, (
            "Cache returned NEW data, but invalidation was NOT performed. "
            "This should not happen — the cache should contain stale data."
        )

        # Проверяем, что источник — кэш (не БД)
        assert stale_source == "cache", (
            f"Expected source='cache', got '{stale_source}'. "
            "After cache warm-up and no invalidation, response should come from cache."
        )

        # Дополнительно: убеждаемся, что без кэша данные актуальные
        resp_fresh = await client.get(
            f"/api/cache-demo/orders/{order_id}/card?use_cache=false"
        )
        fresh_data = resp_fresh.json()
        fresh_total = fresh_data["order_card"]["total_amount"]
        assert fresh_total == new_total, (
            f"DB should contain new total={new_total}, got {fresh_total}"
        )

    print(f"\n[LAB 05] Stale cache demonstration:")
    print(f"  Order ID: {order_id}")
    print(f"  Warm-up total (from DB): {warm_total}")
    print(f"  Mutated total (in DB): {new_total}")
    print(f"  Cached total (stale): {stale_total}")
    print(f"  Fresh total (no cache): {fresh_total}")
    print(f"  Source: {stale_source}")
    print(f"  CONCLUSION: Cache returned stale data (no invalidation)")
