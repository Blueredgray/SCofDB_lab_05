"""Cache service для LAB 05 — кэширование каталога и карточки заказа через Redis."""

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.redis_client import get_redis
from app.infrastructure.cache_keys import catalog_key, order_card_key

logger = logging.getLogger(__name__)

# TTL по умолчанию: 300 секунд (5 минут)
DEFAULT_TTL = 300


class CacheService:
    """
    Сервис кэширования каталога и карточки заказа.

    Реализация:
    - чтение/запись через Redis (json-сериализация);
    - TTL по умолчанию 300 секунд;
    - версионирование ключей через cache_keys.py.
    """

    async def get_catalog(self, *, use_cache: bool = True, db: AsyncSession = None) -> list[dict[str, Any]]:
        """
        Получить каталог товаров.

        1) При use_cache=true — попытаться вернуть из Redis.
        2) При miss — загрузить из БД (агрегат по order_items).
        3) Положить результат в Redis с TTL.
        """
        if use_cache:
            redis = get_redis()
            cached = await redis.get(catalog_key())
            if cached is not None:
                logger.debug("Cache hit: catalog")
                return json.loads(cached)

        # Cache miss или use_cache=false — грузим из БД
        if db is None:
            raise ValueError("db session is required when cache is not hit")

        result = await db.execute(text("""
            SELECT
                oi.product_name,
                count(*) AS order_lines,
                sum(oi.quantity) AS sold_qty,
                round(avg(oi.price)::numeric, 2) AS avg_price
            FROM order_items oi
            GROUP BY oi.product_name
            ORDER BY sold_qty DESC
            LIMIT 100
        """))
        rows = result.mappings().all()
        catalog = [dict(row) for row in rows]

        if use_cache:
            redis = get_redis()
            await redis.setex(catalog_key(), DEFAULT_TTL, json.dumps(catalog, default=str))
            logger.debug("Cache miss: catalog loaded from DB and cached")

        return catalog

    async def get_order_card(self, order_id: str, *, use_cache: bool = True, db: AsyncSession = None) -> dict[str, Any]:
        """
        Получить карточку заказа.

        1) При use_cache=true — попытаться вернуть из Redis.
        2) При miss — загрузить из БД.
        3) Положить результат в Redis с TTL.
        """
        if use_cache:
            redis = get_redis()
            cached = await redis.get(order_card_key(order_id))
            if cached is not None:
                logger.debug("Cache hit: order_card %s", order_id)
                return json.loads(cached)

        # Cache miss — грузим из БД
        if db is None:
            raise ValueError("db session is required when cache is not hit")

        # Загружаем заказ
        order_result = await db.execute(text("""
            SELECT id, user_id, status, total_amount, created_at
            FROM orders WHERE id = :order_id
        """), {"order_id": order_id})
        order_row = order_result.mappings().first()
        if not order_row:
            raise ValueError(f"Order {order_id} not found")

        # Загружаем товары
        items_result = await db.execute(text("""
            SELECT id, product_name, price, quantity
            FROM order_items WHERE order_id = :order_id
        """), {"order_id": order_id})
        items = [dict(r) for r in items_result.mappings().all()]

        order_card = {
            "order_id": str(order_row["id"]),
            "user_id": str(order_row["user_id"]),
            "status": order_row["status"],
            "total_amount": float(order_row["total_amount"]),
            "created_at": str(order_row["created_at"]),
            "items": items,
        }

        if use_cache:
            redis = get_redis()
            await redis.setex(order_card_key(order_id), DEFAULT_TTL, json.dumps(order_card, default=str))
            logger.debug("Cache miss: order_card %s loaded from DB and cached", order_id)

        return order_card

    async def invalidate_order_card(self, order_id: str) -> None:
        """Удалить ключ карточки заказа из Redis."""
        redis = get_redis()
        await redis.delete(order_card_key(order_id))
        logger.info("Cache invalidated: order_card %s", order_id)

    async def invalidate_catalog(self) -> None:
        """Удалить ключ каталога из Redis."""
        redis = get_redis()
        await redis.delete(catalog_key())
        logger.info("Cache invalidated: catalog")
