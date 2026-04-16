"""Idempotency middleware для LAB 04.

Реализует идемпотентность POST-запросов оплаты:
- Клиент отправляет заголовок Idempotency-Key.
- При повторе с тем же ключом и payload возвращает кэшированный ответ.
- При reuse ключа с другим payload возвращает 409 Conflict.
- Не вызывает повторно бизнес-логику списания при корректном повторе.
"""

import hashlib
import json
import logging
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Белый список путей, для которых middleware проверяет идемпотентность
IDEMPOTENT_PATHS = {"/api/payments/retry-demo", "/api/payments/pay"}


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Middleware для идемпотентности POST-запросов оплаты.

    Алгоритм:
    1) Пропускает только POST-запросы к платежным endpoint'ам.
    2) Читает Idempotency-Key из заголовков.
       Если ключа нет — обычный call_next(request).
    3) Вычисляет SHA-256 хэш тела запроса.
    4) Проверяет запись в таблице idempotency_keys:
       - Если completed и хэш совпадает — возвращает кэшированный ответ.
       - Если ключ есть, но хэш другой — возвращает 409 Conflict.
       - Если ключа нет — создаёт запись со статусом 'processing'.
    5) Выполняет downstream-запрос через call_next.
    6) Обновляет запись в idempotency_keys статусом 'completed',
       сохраняет status_code и response_body.
    7) Возвращает response клиенту.
    """

    def __init__(self, app, ttl_seconds: int = 24 * 60 * 60):
        super().__init__(app)
        self.ttl_seconds = ttl_seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Шаг 1: пропускаем только POST-запросы к целевым путям
        if request.method != "POST" or request.url.path not in IDEMPOTENT_PATHS:
            return await call_next(request)

        # Шаг 2: читаем Idempotency-Key из заголовков
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return await call_next(request)

        # Шаг 3: читаем и хэшируем тело запроса
        raw_body = await request.body()
        request_hash = self.build_request_hash(raw_body)

        # Шаг 4: проверяем запись в БД
        from app.infrastructure.db import SessionLocal
        from sqlalchemy import text
        from datetime import datetime, timedelta, timezone

        async with SessionLocal() as session:
            async with session.begin():
                # Ищем существующую запись
                lookup = text("""
                    SELECT id, status, request_hash, status_code, response_body
                    FROM idempotency_keys
                    WHERE idempotency_key = :key
                      AND request_method = :method
                      AND request_path = :path
                    LIMIT 1
                """)
                result = await session.execute(lookup, {
                    "key": idempotency_key,
                    "method": request.method,
                    "path": request.url.path,
                })
                row = result.mappings().first()

                if row:
                    existing_hash = row["request_hash"]
                    existing_status = row["status"]

                    # 4a: ключ существует и завершён успешно
                    if existing_status == "completed":
                        if existing_hash == request_hash:
                            # Тот же ключ + тот же payload -> возвращаем кэш
                            logger.info(
                                "Idempotency cache hit: key=%s path=%s",
                                idempotency_key, request.url.path
                            )
                            cached_body = row["response_body"]
                            cached_code = row["status_code"] or 200
                            return JSONResponse(
                                content=cached_body,
                                status_code=cached_code,
                                headers={"X-Idempotency": "cached"},
                            )
                        else:
                            # Тот же ключ + другой payload -> 409 Conflict
                            logger.warning(
                                "Idempotency conflict: key=%s path=%s "
                                "hash_mismatch (existing=%s new=%s)",
                                idempotency_key, request.url.path,
                                existing_hash[:16], request_hash[:16]
                            )
                            return JSONResponse(
                                status_code=409,
                                content={
                                    "detail": (
                                        f"Idempotency-Key '{idempotency_key}' was already used "
                                        f"with a different request payload for "
                                        f"{request.method} {request.url.path}"
                                    )
                                },
                            )
                    # 4b: запись в состоянии processing — конкурентный запрос
                    # Пропускаем, позволяя выполнить бизнес-логику
                    # (в реальном продакшене здесь можно вернуть 425 Too Early)

                # Шаг 4c: создаём запись со статусом 'processing'
                expires_at = datetime.now(timezone.utc) + timedelta(
                    seconds=self.ttl_seconds
                )
                insert_query = text("""
                    INSERT INTO idempotency_keys
                        (idempotency_key, request_method, request_path,
                         request_hash, status, expires_at)
                    VALUES (:key, :method, :path, :hash, 'processing', :expires)
                    ON CONFLICT DO NOTHING
                """)
                await session.execute(insert_query, {
                    "key": idempotency_key,
                    "method": request.method,
                    "path": request.url.path,
                    "hash": request_hash,
                    "expires": expires_at,
                })

        # Шаг 5: выполняем downstream-запрос
        response = await call_next(request)

        # Шаг 6: сохраняем результат
        response_body_bytes = b""
        async for chunk in response.body_iterator:
            response_body_bytes += chunk
        response.body_iterator = self._iterate([response_body_bytes])

        # Парсим тело ответа для кэширования
        try:
            response_body_json = json.loads(response_body_bytes)
        except (json.JSONDecodeError, ValueError):
            response_body_json = response_body_bytes.decode("utf-8", errors="replace")

        # Обновляем запись в БД
        from app.infrastructure.db import SessionLocal as SessionLocal2
        from sqlalchemy import text as text2

        async with SessionLocal2() as session2:
            async with session2.begin():
                update_query = text2("""
                    UPDATE idempotency_keys
                    SET status = :status,
                        status_code = :code,
                        response_body = CAST(:body AS jsonb),
                        updated_at = NOW()
                    WHERE idempotency_key = :key
                      AND request_method = :method
                      AND request_path = :path
                      AND status = 'processing'
                """)
                await session2.execute(update_query, {
                    "status": "completed" if response.status_code < 500 else "failed",
                    "code": response.status_code,
                    "body": json.dumps(response_body_json, ensure_ascii=False),
                    "key": idempotency_key,
                    "method": request.method,
                    "path": request.url.path,
                })

        # Шаг 7: возвращаем response клиенту
        return response

    @staticmethod
    async def _iterate(data):
        """Асинхронный вспомогательный генератор для body_iterator."""
        for chunk in data:
            yield chunk

    @staticmethod
    def build_request_hash(raw_body: bytes) -> str:
        """Стабильный SHA-256 хэш тела запроса."""
        return hashlib.sha256(raw_body).hexdigest()

    @staticmethod
    def encode_response_payload(body_obj) -> str:
        """Сериализация response body для сохранения в idempotency_keys."""
        return json.dumps(body_obj, ensure_ascii=False)
