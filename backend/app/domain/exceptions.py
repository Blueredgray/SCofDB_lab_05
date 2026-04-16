"""Доменные исключения для нарушений бизнес-правил."""


class DomainException(Exception):
    """Базовое исключение для доменных ошибок."""
    pass


class InvalidEmailError(DomainException):
    """Выбрасывается при неверном формате email."""

    def __init__(self, email: str):
        self.email = email
        super().__init__(f"Invalid email format: {email}")


class OrderAlreadyPaidError(DomainException):
    """Выбрасывается при попытке оплатить уже оплаченный заказ."""

    def __init__(self, order_id):
        self.order_id = order_id
        super().__init__(f"Order {order_id} is already paid")


class OrderCancelledError(DomainException):
    """Выбрасывается при попытке изменить отменённый заказ."""

    def __init__(self, order_id):
        self.order_id = order_id
        super().__init__(f"Order {order_id} is cancelled")


class InvalidQuantityError(DomainException):
    """Выбрасывается когда количество не положительное."""

    def __init__(self, quantity: int):
        self.quantity = quantity
        super().__init__(f"Quantity must be positive, got: {quantity}")


class InvalidPriceError(DomainException):
    """Выбрасывается когда цена отрицательная."""

    def __init__(self, price):
        self.price = price
        super().__init__(f"Price cannot be negative, got: {price}")


class InvalidAmountError(DomainException):
    """Выбрасывается когда сумма отрицательная."""

    def __init__(self, amount):
        self.amount = amount
        super().__init__(f"Amount cannot be negative, got: {amount}")


class UserNotFoundError(DomainException):
    """Выбрасывается когда пользователь не найден."""

    def __init__(self, user_id):
        self.user_id = user_id
        super().__init__(f"User {user_id} not found")


class OrderNotFoundError(DomainException):
    """Выбрасывается когда заказ не найден."""

    def __init__(self, order_id):
        self.order_id = order_id
        super().__init__(f"Order {order_id} not found")


class EmailAlreadyExistsError(DomainException):
    """Выбрасывается когда email уже зарегистрирован."""

    def __init__(self, email: str):
        self.email = email
        super().__init__(f"Email already exists: {email}")
