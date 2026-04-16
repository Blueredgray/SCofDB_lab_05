-- Схема БД маркетплейса

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Таблица статусов заказов
CREATE TABLE IF NOT EXISTS order_statuses (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL
);

INSERT INTO order_statuses (name) VALUES
('created'), ('paid'), ('cancelled'), ('shipped'), ('completed')
ON CONFLICT (name) DO NOTHING;

-- Таблица пользователей
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT email_check CHECK (email ~* '^[A-Za-z0-9._%-]+@[A-Za-z0-9.-]+[.][A-Za-z]+$')
);

-- Таблица заказов
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL DEFAULT 'created',
    total_amount DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT total_amount_check CHECK (total_amount >= 0)
);

-- Таблица товаров в заказе
CREATE TABLE IF NOT EXISTS order_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_name VARCHAR(255) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    quantity INTEGER NOT NULL,
    CONSTRAINT price_check CHECK (price >= 0),
    CONSTRAINT quantity_check CHECK (quantity > 0)
);

-- Таблица истории статусов
CREATE TABLE IF NOT EXISTS order_status_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL,
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_order_status_history_order_id ON order_status_history(order_id);

-- ==================================================
-- ТРИГГЕР: Логирование изменений статуса
-- Можно отключить через SET LOCAL app.skip_log_trigger = 'true'
-- ==================================================

CREATE OR REPLACE FUNCTION log_status_change()
RETURNS TRIGGER AS $$
DECLARE
    skip_trigger text;
BEGIN
    skip_trigger := current_setting('app.skip_log_trigger', true);
    IF skip_trigger = 'true' THEN
        RETURN NEW;
    END IF;

    IF (TG_OP = 'INSERT') OR (OLD.status IS DISTINCT FROM NEW.status) THEN
        INSERT INTO order_status_history (id, order_id, status, changed_at)
        VALUES (uuid_generate_v4(), NEW.id, NEW.status, NOW());
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_log_status_change ON orders;
CREATE TRIGGER trg_log_status_change
AFTER INSERT OR UPDATE ON orders
FOR EACH ROW
EXECUTE FUNCTION log_status_change();

-- ==================================================
-- ТРИГГЕР: Предотвращение двойной оплаты
-- Можно обойти через SET LOCAL app.bypass_payment_check = 'true'
-- ==================================================

CREATE OR REPLACE FUNCTION prevent_double_payment()
RETURNS TRIGGER AS $$
DECLARE
    bypass_check text;
BEGIN
    bypass_check := current_setting('app.bypass_payment_check', true);
    IF bypass_check = 'true' THEN
        RETURN NEW;
    END IF;

    IF NEW.status = 'paid' THEN
        IF EXISTS (
            SELECT 1 FROM order_status_history
            WHERE order_id = NEW.id AND status = 'paid'
        ) THEN
            RAISE EXCEPTION 'Order % has already been paid.', NEW.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_prevent_double_payment ON orders;
CREATE TRIGGER trg_prevent_double_payment
BEFORE UPDATE ON orders
FOR EACH ROW
EXECUTE FUNCTION prevent_double_payment();
