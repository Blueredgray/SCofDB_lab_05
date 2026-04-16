"""
LAB 04: Проверка идемпотентного повтора запроса.

Тест показывает, что с Idempotency-Key повторный запрос
не приводит к повторному списанию и возвращает кэшированный ответ.
"""

import pytest
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from httpx import AsyncClient, ASGITransport

from app.main import app

import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@db:5432/marketplace"
)


@pytest.fixture(scope="function")
async def test_engine():
    """Создать движок для тестов (function scope = один event loop)."""
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=False,
        pool_size=5,
        max_overflow=10
    )
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    """Создать сессию БД."""
    async with AsyncSession(test_engine) as session:
        yield session


@pytest.fixture
async def test_order(test_engine):
    """Создать тестовый заказ со статусом 'created'."""
    user_id = uuid.uuid4()
    order_id = uuid.uuid4()

    async with AsyncSession(test_engine) as setup_session:
        async with setup_session.begin():
            await setup_session.execute(
                text("""
                    INSERT INTO users (id, email, name, created_at)
                    VALUES (:user_id, :email, :name, NOW())
                    ON CONFLICT (id) DO NOTHING
                """),
                {
                    "user_id": user_id,
                    "email": f"test_idem_{order_id}@example.com",
                    "name": "Test User Idempotency"
                }
            )

            await setup_session.execute(
                text("""
                    INSERT INTO orders (id, user_id, status, total_amount, created_at)
                    VALUES (:order_id, :user_id, 'created', 100.00, NOW())
                """),
                {"order_id": order_id, "user_id": user_id}
            )

            await setup_session.execute(
                text("""
                    INSERT INTO order_status_history (id, order_id, status, changed_at)
                    VALUES (gen_random_uuid(), :order_id, 'created', NOW())
                """),
                {"order_id": order_id}
            )

    yield order_id

    # Очистка после теста
    async with AsyncSession(test_engine) as cleanup_session:
        async with cleanup_session.begin():
            # Удаляем записи идемпотентности
            await cleanup_session.execute(
                text("""
                    DELETE FROM idempotency_keys
                    WHERE request_path LIKE '%payments%'
                """)
            )
            await cleanup_session.execute(
                text("DELETE FROM order_status_history WHERE order_id = :order_id"),
                {"order_id": order_id}
            )
            await cleanup_session.execute(
                text("DELETE FROM orders WHERE id = :order_id"),
                {"order_id": order_id}
            )
            await cleanup_session.execute(
                text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": user_id}
            )


@pytest.mark.asyncio
async def test_retry_with_same_key_returns_cached_response(db_session, test_order):
    """
    LAB 04: Повтор с тем же Idempotency-Key возвращает кэшированный ответ.

    Сценарий:
    1) Создан заказ в статусе 'created'.
    2) Первый POST /api/payments/retry-demo с Idempotency-Key: test-key-123.
       Ожидаем: успешная оплата (200).
    3) Повторный POST с тем же ключом и тем же payload.
       Ожидаем: ответ из кэша (заголовок X-Idempotency: cached),
       статус-код и тело совпадают с первым ответом.
    4) В истории заказа — только ОДНО событие 'paid'.
    """
    order_id = test_order
    idempotency_key = "test-key-retry-123"
    payload = {"order_id": str(order_id), "mode": "for_update"}

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        # Первый запрос с Idempotency-Key
        response1 = await client.post(
            "/api/payments/retry-demo",
            json=payload,
            headers={"Idempotency-Key": idempotency_key}
        )

        assert response1.status_code == 200, (
            f"Первый запрос должен быть успешным, получен {response1.status_code}"
        )
        body1 = response1.json()
        assert body1.get("success") is True, (
            f"Первый запрос вернул ошибку: {body1.get('message')}"
        )

        # Проверяем историю через API
        history_resp1 = await client.get(
            f"/api/payments/history/{order_id}"
        )
        history1 = history_resp1.json()
        count_after_first = history1["payment_count"]

        # Повторный запрос с тем же ключом
        response2 = await client.post(
            "/api/payments/retry-demo",
            json=payload,
            headers={"Idempotency-Key": idempotency_key}
        )

        assert response2.status_code == 200, (
            f"Повторный запрос должен быть 200, получен {response2.status_code}"
        )
        body2 = response2.json()

        # Проверяем, что второй ответ из кэша
        assert response2.headers.get("X-Idempotency") == "cached", (
            "Второй ответ должен иметь заголовок X-Idempotency: cached"
        )

        # Проверяем, что тела ответов совпадают
        assert body1 == body2, "Тела ответов должны совпадать (кэшированный ответ)"

        # Проверяем, что оплата произошла только один раз
        history_resp2 = await client.get(
            f"/api/payments/history/{order_id}"
        )
        history2 = history_resp2.json()
        count_after_second = history2["payment_count"]

        assert count_after_second == 1, (
            f"Ожидалось 1 событие paid, но получено {count_after_second}. "
            f"Повторное списание не должно было произойти!"
        )

    print(f"\n[LAB 04] Результат С идемпотентностью:")
    print(f"  Order ID: {order_id}")
    print(f"  Idempotency-Key: {idempotency_key}")
    print(f"  Первый ответ: {body1}")
    print(f"  Второй ответ: {body2}")
    print(f"  X-Idempotency header: {response2.headers.get('X-Idempotency')}")
    print(f"  Paid-событий после первого запроса: {count_after_first}")
    print(f"  Paid-событий после второго запроса: {count_after_second}")
    print(f"  ВЫВОД: Идемпотентность работает! Повторное списание не произошло.")


@pytest.mark.asyncio
async def test_same_key_different_payload_returns_conflict(db_session, test_order):
    """
    LAB 04: Негативный тест — reuse Idempotency-Key с другим payload.

    Сценарий:
    1) Первый запрос с Idempotency-Key: test-key-conflict-456
       и payload {"order_id": "...", "mode": "for_update"}.
    2) Второй запрос с тем же ключом, но другой payload
       (например, mode: "unsafe" или другой order_id).
    3) Ожидаем: 409 Conflict.
    """
    order_id = test_order
    idempotency_key = "test-key-conflict-456"
    payload1 = {"order_id": str(order_id), "mode": "for_update"}
    # Другой payload — используем другой mode (или другой order_id)
    payload2 = {"order_id": str(order_id), "mode": "unsafe"}

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        # Первый запрос
        response1 = await client.post(
            "/api/payments/retry-demo",
            json=payload1,
            headers={"Idempotency-Key": idempotency_key}
        )

        assert response1.status_code == 200, (
            f"Первый запрос должен быть успешным, получен {response1.status_code}"
        )

        # Второй запрос с тем же ключом, но другим payload
        response2 = await client.post(
            "/api/payments/retry-demo",
            json=payload2,
            headers={"Idempotency-Key": idempotency_key}
        )

        assert response2.status_code == 409, (
            f"Ожидался 409 Conflict при reuse ключа с другим payload, "
            f"получен {response2.status_code}: {response2.text}"
        )

        conflict_body = response2.json()
        assert "detail" in conflict_body, "Ответ 409 должен содержать поле detail"
        assert "Idempotency-Key" in conflict_body["detail"], (
            "Сообщение об ошибке должно упоминать Idempotency-Key"
        )

    print(f"\n[LAB 04] Негативный тест (конфликт payload):")
    print(f"  Order ID: {order_id}")
    print(f"  Idempotency-Key: {idempotency_key}")
    print(f"  Первый payload: {payload1}")
    print(f"  Второй payload: {payload2}")
    print(f"  Статус второго ответа: {response2.status_code}")
    print(f"  Сообщение: {conflict_body['detail']}")
    print(f"  ВЫВОД: Конфликт корректно обнаружен!")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
