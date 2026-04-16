"""Сервис оплаты с демонстрацией race condition."""
import uuid
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.exceptions import OrderAlreadyPaidError, OrderNotFoundError


class PaymentService:
    """Сервис обработки платежей с разными уровнями изоляции."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def pay_order_unsafe(self, order_id: uuid.UUID, barrier: asyncio.Barrier = None) -> dict:
        """Небезопасная оплата - демонстрация race condition.

        Две транзакции одновременно проходят проверку и вставляют
        записи в историю - имитация двойной оплаты.
        """
        async with self.session.begin():
            # Отключаем триггеры для демонстрации race condition
            await self.session.execute(
                text("SET LOCAL app.bypass_payment_check = 'true'")
            )
            await self.session.execute(
                text("SET LOCAL app.skip_log_trigger = 'true'")
            )

            # Синхронизация: обе транзакции начнут SELECT одновременно
            if barrier:
                await barrier.wait()

            # READ COMMITTED - видит только закоммиченные данные
            result = await self.session.execute(
                text("SELECT status FROM orders WHERE id = :order_id"),
                {"order_id": order_id}
            )
            row = result.fetchone()

            if row is None:
                raise OrderNotFoundError(f"Order {order_id} not found")

            status = row[0]

            if status != 'created':
                raise OrderAlreadyPaidError(f"Order {order_id} already paid")

            # Имитация задержки (проверка баланса, платёжный шлюз...)
            await asyncio.sleep(0.2)

            # ВСТАВЛЯЕМ ЗАПИСЬ ОБ ОПЛАТЕ НАПРЯМУЮ
            # Это имитирует что произошло бы без правильной синхронизации
            await self.session.execute(
                text("""
                    INSERT INTO order_status_history (id, order_id, status, changed_at)
                    VALUES (gen_random_uuid(), :order_id, 'paid', NOW())
                """),
                {"order_id": order_id}
            )

            # UPDATE статуса
            await self.session.execute(
                text("UPDATE orders SET status = 'paid' WHERE id = :order_id"),
                {"order_id": order_id}
            )

        return {
            "order_id": str(order_id),
            "status": "paid",
            "message": "Order paid successfully (unsafe)"
        }

    async def pay_order_safe(self, order_id: uuid.UUID, barrier: asyncio.Barrier = None) -> dict:
        """Безопасная оплата - REPEATABLE READ + FOR UPDATE.

        FOR UPDATE блокирует строку при SELECT, вторая транзакция ждёт.
        После коммита первой, вторая видит status='paid' и падает с ошибкой.
        """
        async with self.session.begin():
            # REPEATABLE READ - транзакция видит снапшот данных
            await self.session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            )

            # Синхронизация: обе транзакции начнут SELECT одновременно
            if barrier:
                await barrier.wait()

            # FOR UPDATE блокирует строку СРАЗУ при SELECT
            result = await self.session.execute(
                text("""
                    SELECT status FROM orders
                    WHERE id = :order_id FOR UPDATE
                """),
                {"order_id": order_id}
            )
            row = result.fetchone()

            if row is None:
                raise OrderNotFoundError(f"Order {order_id} not found")

            status = row[0]

            if status != 'created':
                raise OrderAlreadyPaidError(f"Order {order_id} already paid")

            # Имитация задержки - строка заблокирована FOR UPDATE!
            await asyncio.sleep(0.2)

            # UPDATE статуса - триггер log_status_change добавит запись в историю
            await self.session.execute(
                text("UPDATE orders SET status = 'paid' WHERE id = :order_id"),
                {"order_id": order_id}
            )

        return {
            "order_id": str(order_id),
            "status": "paid",
            "message": "Order paid successfully (safe)"
        }

    async def get_payment_history(self, order_id: uuid.UUID) -> list[dict]:
        """Получить историю оплат заказа."""
        result = await self.session.execute(
            text("""
                SELECT id, order_id, status, changed_at
                FROM order_status_history
                WHERE order_id = :order_id AND status = 'paid'
                ORDER BY changed_at
            """),
            {"order_id": order_id}
        )

        rows = result.fetchall()
        history = []

        for row in rows:
            history.append({
                "id": str(row[0]),
                "order_id": str(row[1]),
                "status": row[2],
                "changed_at": str(row[3])
            })

        return history
