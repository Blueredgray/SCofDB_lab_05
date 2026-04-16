"""Rate limiting middleware для LAB 05 — Redis-based rate limiting для endpoint оплаты."""

import re
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.infrastructure.redis_client import get_redis
from app.infrastructure.cache_keys import payment_rate_limit_key


# Паттерн для определения endpoint оплаты
PAYMENT_PATH_PATTERN = re.compile(r"^/api/orders/[^/]+/pay$")
PAYMENT_RETRY_PATH = "/api/payments/retry-demo"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Redis-based rate limiting для endpoint оплаты.

    Цель:
    - защита от DDoS/шторма запросов;
    - защита от случайных повторных кликов пользователя.

    Реализация:
    - policy: limit_per_window запросов за window_seconds секунд;
    - subject: user_id из query/header (при наличии), иначе client IP;
    - Redis INCR + EXPIRE для счётчика;
    - при превышении лимита — 429 Too Many Requests;
    - заголовки ответа: X-RateLimit-Limit, X-RateLimit-Remaining.
    """

    def __init__(self, app, limit_per_window: int = 5, window_seconds: int = 10):
        super().__init__(app)
        self.limit_per_window = limit_per_window
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Шаг 1: проверяем, применяется ли rate limiting к данному пути
        path = request.url.path
        if request.method != "POST":
            return await call_next(request)

        is_payment_endpoint = (
            PAYMENT_PATH_PATTERN.match(path) is not None
            or path == PAYMENT_RETRY_PATH
        )

        if not is_payment_endpoint:
            return await call_next(request)

        # Шаг 2: формируем subject (user_id или client IP)
        subject = self._extract_subject(request)
        redis_key = payment_rate_limit_key(subject)

        # Шаг 3: Redis INCR + EXPIRE
        redis = get_redis()
        current_count = await redis.incr(redis_key)

        # Устанавливаем TTL только при первом запросе (INCR вернёт 1)
        if current_count == 1:
            await redis.expire(redis_key, self.window_seconds)

        # Шаг 4: проверяем лимит
        remaining = max(0, self.limit_per_window - current_count)

        if current_count > self.limit_per_window:
            # Превышен лимит — возвращаем 429
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"Rate limit exceeded: {self.limit_per_window} requests "
                        f"per {self.window_seconds} seconds"
                    )
                },
                headers={
                    "X-RateLimit-Limit": str(self.limit_per_window),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": str(self.window_seconds),
                },
            )

        # Шаг 5: пропускаем запрос, добавляем заголовки
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limit_per_window)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

    @staticmethod
    def _extract_subject(request: Request) -> str:
        """
        Извлечь subject для rate limiting.

        Приоритет:
        1) query-параметр user_id;
        2) заголовок X-User-Id;
        3) client IP (если за прокси — X-Forwarded-For, иначе client.host).
        """
        # Пытаемся получить user_id из query
        user_id = request.query_params.get("user_id")
        if user_id:
            return f"user:{user_id}"

        # Пытаемся получить из заголовка
        user_id_header = request.headers.get("X-User-Id")
        if user_id_header:
            return f"user:{user_id_header}"

        # Fallback: client IP
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"

        return f"ip:{request.client.host if request.client else 'unknown'}"
