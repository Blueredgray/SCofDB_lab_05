"""Cache consistency demo endpoints для LAB 05."""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import get_db
from app.application.cache_service import CacheService
from app.application.cache_events import CacheInvalidationEventBus, OrderUpdatedEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cache-demo", tags=["cache-demo"])

cache_service = CacheService()
event_bus = CacheInvalidationEventBus()


class UpdateOrderRequest(BaseModel):
    """Payload для изменения заказа в demo-сценариях."""

    new_total_amount: float


@router.get("/catalog")
async def get_catalog(use_cache: bool = True, db: AsyncSession = Depends(get_db)) -> Any:
    """
    Кэш каталога товаров в Redis.

    Требования:
    1) При use_cache=true читать/писать Redis.
    2) При cache miss грузить из БД и класть в кэш.
    3) Добавить TTL (300 секунд).

    Каталог — это агрегат по order_items.product_name с count, sum, avg.
    """
    try:
        catalog = await cache_service.get_catalog(use_cache=use_cache, db=db)
        return {
            "source": "cache" if use_cache else "database",
            "count": len(catalog),
            "items": catalog,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/orders/{order_id}/card")
async def get_order_card(
    order_id: uuid.UUID,
    use_cache: bool = True,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Кэш карточки заказа в Redis.

    Требования:
    1) Ключ вида order_card:v1:{order_id}.
    2) При use_cache=true возвращать данные из кэша.
    3) При miss грузить из БД и сохранять в кэш.
    """
    try:
        order_card = await cache_service.get_order_card(
            str(order_id), use_cache=use_cache, db=db
        )
        return {
            "source": "cache" if use_cache else "database",
            "order_card": order_card,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/orders/{order_id}/mutate-without-invalidation")
async def mutate_without_invalidation(
    order_id: uuid.UUID,
    payload: UpdateOrderRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Намеренно сломанный сценарий консистентности.

    Нужно:
    1) Изменить заказ в БД (total_amount).
    2) НЕ инвалидировать кэш.
    3) Последующий GET /orders/{id}/card вернёт stale data.
    """
    # Проверяем существование заказа
    result = await db.execute(
        text("SELECT id, status, total_amount FROM orders WHERE id = :order_id"),
        {"order_id": str(order_id)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

    old_total = float(row["total_amount"])

    # Изменяем total_amount в БД (БЕЗ инвалидации кэша!)
    await db.execute(
        text("UPDATE orders SET total_amount = :amount WHERE id = :order_id"),
        {"amount": payload.new_total_amount, "order_id": str(order_id)},
    )

    return {
        "order_id": str(order_id),
        "old_total_amount": old_total,
        "new_total_amount": payload.new_total_amount,
        "cache_invalidated": False,
        "warning": "Cache was NOT invalidated. Subsequent GET may return stale data.",
    }


@router.post("/orders/{order_id}/mutate-with-event-invalidation")
async def mutate_with_event_invalidation(
    order_id: uuid.UUID,
    payload: UpdateOrderRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Починка через событийную инвалидацию.

    Нужно:
    1) Изменить заказ в БД.
    2) Сгенерировать событие OrderUpdated.
    3) Обработчик события инвалидирует:
       - order_card:v1:{order_id}
       - catalog:v1
    """
    # Проверяем существование заказа
    result = await db.execute(
        text("SELECT id, status, total_amount FROM orders WHERE id = :order_id"),
        {"order_id": str(order_id)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

    old_total = float(row["total_amount"])

    # Изменяем total_amount в БД
    await db.execute(
        text("UPDATE orders SET total_amount = :amount WHERE id = :order_id"),
        {"amount": payload.new_total_amount, "order_id": str(order_id)},
    )

    # Генерируем событие обновления заказа
    event = OrderUpdatedEvent(order_id=str(order_id))
    await event_bus.publish_order_updated(event)

    return {
        "order_id": str(order_id),
        "old_total_amount": old_total,
        "new_total_amount": payload.new_total_amount,
        "cache_invalidated": True,
        "event_published": f"OrderUpdated(order_id={order_id})",
        "keys_invalidated": [
            f"order_card:v1:{order_id}",
            "catalog:v1",
        ],
    }
