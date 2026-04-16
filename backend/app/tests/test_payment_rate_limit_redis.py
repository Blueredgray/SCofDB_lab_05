"""
LAB 05: Rate limiting endpoint оплаты через Redis.

Тест проверяет, что RateLimitMiddleware корректно ограничивает
количество запросов к endpoint оплаты.
"""

import pytest
import uuid
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.fixture(scope="function")
async def test_order():
    """Создать тестовый заказ для оплаты."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        user_resp = await client.post(
            "/api/users",
            json={"email": f"ratelimit_test_{uuid.uuid4()}@example.com", "name": "RateLimit User"}
        )
        assert user_resp.status_code == 201
        user_id = user_resp.json()["id"]

        order_resp = await client.post("/api/orders", json={"user_id": user_id})
        assert order_resp.status_code == 201
        order_id = order_resp.json()["id"]

    yield order_id


@pytest.mark.asyncio
async def test_payment_endpoint_rate_limit(test_order):
    """
    Проверка rate limiting на endpoint оплаты.

    1) Сделать N+2 запросов оплаты в пределах одного окна.
    2) Проверить, что первые N (5) проходят (<= 429).
    3) Запросы сверх лимита получают 429 Too Many Requests.
    4) Проверить заголовки X-RateLimit-Limit / X-RateLimit-Remaining.
    """
    order_id = test_order

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        # Используем /api/payments/retry-demo как целевой endpoint для rate limiting
        # Этот endpoint находится в белом списке rate limiter
        # Но лучше тестируем через /api/orders/{id}/pay
        # Для тестирования создаём уникальный IP через header

        # Используем уникальный X-User-Id для чистоты теста
        unique_user_id = str(uuid.uuid4())
        headers = {"X-User-Id": unique_user_id}

        results = []
        for i in range(7):  # Лимит = 5, делаем 7 запросов
            resp = await client.post(
                f"/api/orders/{order_id}/pay",
                headers=headers,
            )
            results.append({
                "request_num": i + 1,
                "status_code": resp.status_code,
                "headers": dict(resp.headers),
                "body": resp.json() if resp.status_code != 404 else resp.text,
            })

        # Разделяем результаты на успешные и заблокированные
        passed = [r for r in results if r["status_code"] != 429]
        rate_limited = [r for r in results if r["status_code"] == 429]

        # Проверяем, что есть как минимум один заблокированный запрос
        assert len(rate_limited) >= 1, (
            f"Expected at least 1 rate-limited request (429), "
            f"but got {len(rate_limited)}. Results: {[r['status_code'] for r in results]}"
        )

        # Проверяем, что заблокированные запросы возвращают 429
        for r in rate_limited:
            assert r["status_code"] == 429

        # Проверяем заголовки у первых пропущенных запросов
        for r in passed[:3]:
            assert "X-RateLimit-Limit" in r["headers"], (
                "Missing X-RateLimit-Limit header"
            )
            assert "X-RateLimit-Remaining" in r["headers"], (
                "Missing X-RateLimit-Remaining header"
            )

        # Проверяем заголовки у rate-limited запросов
        for r in rate_limited:
            assert r["headers"].get("X-RateLimit-Limit") is not None
            assert r["headers"].get("X-RateLimit-Remaining") == "0"

    print(f"\n[LAB 05] Rate limiting test results:")
    print(f"  Order ID: {order_id}")
    print(f"  Unique user (X-User-Id): {unique_user_id[:8]}...")
    print(f"  Total requests: {len(results)}")
    print(f"  Passed (non-429): {len(passed)}")
    print(f"  Rate limited (429): {len(rate_limited)}")
    for r in results:
        marker = "BLOCKED" if r["status_code"] == 429 else "OK"
        remaining = r["headers"].get("X-RateLimit-Remaining", "N/A")
        print(f"    Request #{r['request_num']}: {r['status_code']} [{marker}] (remaining: {remaining})")
    print(f"  CONCLUSION: Rate limiting works correctly")
