"""
LAB 04: Демонстрация проблемы retry без идемпотентности.

Тест показывает, что без Idempotency-Key повторный запрос на оплату
в режиме 'unsafe' может привести к двойному списанию.
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
            # Создаём пользователя
            await setup_session.execute(
                text("""
                    INSERT INTO users (id, email, name, created_at)
                    VALUES (:user_id, :email, :name, NOW())
                    ON CONFLICT (id) DO NOTHING
                """),
                {
                    "user_id": user_id,
                    "email": f"test_no_idem_{order_id}@example.com",
                    "name": "Test User No Idempotency"
                }
            )

            # Создаём заказ
            await setup_session.execute(
                text("""
                    INSERT INTO orders (id, user_id, status, total_amount, created_at)
                    VALUES (:order_id, :user_id, 'created', 100.00, NOW())
                """),
                {"order_id": order_id, "user_id": user_id}
            )

            # Записываем начальный статус
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
async def test_retry_without_idempotency_can_double_pay(db_session, test_order, test_engine):
    """
    LAB 04: Демонстрация проблемы — без Idempotency-Key
    повторный запрос в режиме unsafe приводит к двойной оплате.

    Сценарий:
    1) Создан заказ в статусе 'created'.
    2) POST /api/payments/test-concurrent запускает две параллельные
       попытки оплаты в режиме 'unsafe' БЕЗ заголовка Idempotency-Key.
    3) Обе транзакции проходят проверку статуса одновременно (barrier).
    4) Ожидаем: в истории заказа 2 записи 'paid' (race condition).
    """
    order_id = test_order

    # Используем endpoint test-concurrent, который запускает
    # две параллельные попытки оплаты с asyncio.Barrier для синхронизации
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/payments/test-concurrent",
            json={"order_id": str(order_id), "mode": "unsafe"}
        )

    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )

    body = response.json()
    history_count = body["summary"]["payment_count_in_history"]
    race_detected = body["summary"]["race_condition_detected"]
    results = body["results"]
    history = body["history"]

    # Без защиты: ожидаем двойную оплату (race condition)
    assert history_count >= 2, (
        f"Ожидалась двойная оплата (>=2 записи paid), "
        f"но получено {history_count}. Race condition не обнаружен."
    )

    assert len(history) >= 2, (
        f"Прямая проверка: ожидалось >=2 записей paid, "
        f"но получено {len(history)}."
    )

    print(f"\n[LAB 04] Результат БЕЗ идемпотентности:")
    print(f"  Order ID: {order_id}")
    print(f"  Количество paid-событий: {len(history)}")
    print(f"  Race condition обнаружен: {race_detected}")
    print(f"  Результаты попыток:")
    for r in results:
        attempt_num = r.get("attempt", "?")
        if r.get("success"):
            print(f"    Попытка {attempt_num}: УСПЕХ - {r.get('result')}")
        else:
            print(f"    Попытка {attempt_num}: ОШИБКА - {r.get('error')}")
    print(f"  ВЫВОД: Двойная оплата подтверждена!")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
