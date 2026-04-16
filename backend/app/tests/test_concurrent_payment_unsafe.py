"""Тест демонстрации проблемы race condition.

Этот тест ПРОХОДИТ, подтверждая что pay_order_unsafe() ломается.
"""
import asyncio
import pytest
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from app.application.payment_service import PaymentService
from app.domain.exceptions import OrderAlreadyPaidError, OrderNotFoundError

import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@db:5432/marketplace"
)


@pytest.fixture(scope="module")
async def test_engine():
    """Создать движок для тестов."""
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20
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
                    "email": f"test_{order_id}@example.com",
                    "name": "Test User"
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
async def test_concurrent_payment_unsafe_demonstrates_race_condition(
    db_session, test_order, test_engine
):
    """Тест демонстрирует race condition при pay_order_unsafe().

    ОЖИДАЕТСЯ: Тест ПРОХОДИТ, заказ оплачен дважды.
    """
    order_id = test_order

    async def payment_attempt_1():
        async with AsyncSession(test_engine) as session1:
            service1 = PaymentService(session1)
            return await service1.pay_order_unsafe(order_id)

    async def payment_attempt_2():
        async with AsyncSession(test_engine) as session2:
            service2 = PaymentService(session2)
            return await service2.pay_order_unsafe(order_id)

    # Запускаем параллельно
    results = await asyncio.gather(
        payment_attempt_1(),
        payment_attempt_2(),
        return_exceptions=True
    )

    await asyncio.sleep(0.2)

    # Проверяем историю
    async with AsyncSession(test_engine) as check_session:
        service = PaymentService(check_session)
        history = await service.get_payment_history(order_id)

    # Две записи об оплате - RACE CONDITION!
    assert len(history) == 2, f"Ожидалось 2 записи, получено {len(history)}"

    print(f"\n RACE CONDITION DETECTED!")
    print(f"Order {order_id} was paid TWICE:")
    for record in history:
        print(f"  - {record['changed_at']}: status = {record['status']}")

    print(f"Попытка 1: {'Успешно' if not isinstance(results[0], Exception) else f'Ошибка: {type(results[0]).__name__}'}")
    print(f"Попытка 2: {'Успешно' if not isinstance(results[1], Exception) else f'Ошибка: {type(results[1]).__name__}'}")


if __name__ == "__main__":
    """Запуск: pytest app/tests/test_concurrent_payment_unsafe.py -v -s"""
    pytest.main([__file__, "-v", "-s"])
