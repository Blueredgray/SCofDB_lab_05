"""Event-driven cache invalidation для LAB 05."""

import logging
from dataclasses import dataclass

from app.infrastructure.redis_client import get_redis
from app.infrastructure.cache_keys import catalog_key, order_card_key

logger = logging.getLogger(__name__)


@dataclass
class OrderUpdatedEvent:
    """Событие изменения заказа."""

    order_id: str


class CacheInvalidationEventBus:
    """
    Минимальный event bus для LAB 05.

    Реализация (вариант C — синхронная инвалидация):
    - при публикации OrderUpdatedEvent синхронно удаляет
      order_card:v1:{order_id} и catalog:v1 из Redis;
    - выбран минимальный вариант, т.к. в рамках лабораторной
      работы нет необходимости в распределённых подписках.
    """

    async def publish_order_updated(self, event: OrderUpdatedEvent) -> None:
        """
        Обработать событие обновления заказа:
        инвалидировать кэш карточки заказа и каталога.

        Каталог инвалидируется, т.к. изменение total_amount или состава
        заказа может повлиять на агрегаты каталога (avg_price, sold_qty).
        """
        redis = get_redis()

        # Инвалидируем карточку заказа
        card_key = order_card_key(event.order_id)
        await redis.delete(card_key)
        logger.info(
            "Event bus: invalidated order_card cache for order %s (key: %s)",
            event.order_id, card_key,
        )

        # Инвалидируем каталог (изменение заказа может затронуть агрегаты)
        cat_key = catalog_key()
        await redis.delete(cat_key)
        logger.info(
            "Event bus: invalidated catalog cache (key: %s) due to order %s update",
            cat_key, event.order_id,
        )
