-- ============================================
-- LAB 04: Идемпотентность платежных запросов
-- ============================================

-- Создание таблицы idempotency_keys для хранения
-- информации об идемпотентных запросах.
-- Каждый уникальный ключ связан с конкретным endpoint
-- и хранит хэш тела запроса, статус обработки и кэш ответа.

CREATE TABLE IF NOT EXISTS idempotency_keys (
    -- Уникальный идентификатор записи
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Идемпотентный ключ, передаваемый клиентом в заголовке Idempotency-Key
    idempotency_key VARCHAR(255) NOT NULL,

    -- HTTP-метод запроса (POST, PUT и т.д.)
    request_method VARCHAR(16) NOT NULL,

    -- Путь endpoint'а (например /api/payments/retry-demo)
    request_path TEXT NOT NULL,

    -- SHA-256 хэш тела запроса для обнаружения reuse ключа с другим payload
    request_hash TEXT NOT NULL,

    -- Статус обработки: processing — запрос выполняется,
    -- completed — запрос успешно обработан,
    -- failed — запрос завершился ошибкой
    status VARCHAR(32) NOT NULL DEFAULT 'processing',

    -- HTTP статус-код ответа
    status_code INTEGER,

    -- Кэшированное тело ответа в формате JSON
    response_body JSONB,

    -- Временные метки
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,

    -- Ограничение на допустимые значения статуса
    CONSTRAINT idempotency_status_check CHECK (status IN ('processing', 'completed', 'failed'))
);

-- Уникальный constraint: один idempotency key может быть использован
-- только с одним endpoint (method + path).
-- Это гарантирует, что один и тот же ключ нельзя применить к разным endpoint'ам.
CREATE UNIQUE INDEX IF NOT EXISTS idx_idempotency_key_unique
    ON idempotency_keys (idempotency_key, request_method, request_path);

-- Индекс для быстрого lookup по ключу, методу и пути — основной запрос middleware
CREATE INDEX IF NOT EXISTS idx_idempotency_lookup
    ON idempotency_keys (idempotency_key, request_method, request_path, status);

-- Индекс для очистки просроченных ключей (cron/手动)
CREATE INDEX IF NOT EXISTS idx_idempotency_expires
    ON idempotency_keys (expires_at);

-- Триггер для автоматического обновления updated_at при изменении записи
CREATE OR REPLACE FUNCTION update_idempotency_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_idempotency_updated_at ON idempotency_keys;
CREATE TRIGGER trg_idempotency_updated_at
    BEFORE UPDATE ON idempotency_keys
    FOR EACH ROW
    EXECUTE FUNCTION update_idempotency_updated_at();
