"""
Tests for domain layer invariants.

These tests verify that students correctly implemented domain invariants.
All tests must pass for the lab to be accepted.

DO NOT MODIFY THIS FILE!
"""

import pytest
import uuid
from decimal import Decimal

from app.domain.user import User
from app.domain.order import Order, OrderItem, OrderStatus
from app.domain.exceptions import (
    InvalidEmailError,
    OrderAlreadyPaidError,
    OrderCancelledError,
    InvalidQuantityError,
    InvalidPriceError,
    InvalidAmountError,
)


class TestUserInvariants:
    """Tests for User domain invariants."""

    def test_create_user_with_valid_email(self):
        user = User(email="test@example.com")
        assert user.email == "test@example.com"
        assert user.id is not None

    def test_create_user_with_name(self):
        user = User(email="test@example.com", name="John Doe")
        assert user.name == "John Doe"

    def test_create_user_with_empty_email_fails(self):
        with pytest.raises(InvalidEmailError):
            User(email="")

    def test_create_user_with_whitespace_email_fails(self):
        with pytest.raises(InvalidEmailError):
            User(email="   ")

    def test_create_user_with_invalid_email_no_at(self):
        with pytest.raises(InvalidEmailError):
            User(email="invalid")

    def test_create_user_with_invalid_email_no_domain(self):
        with pytest.raises(InvalidEmailError):
            User(email="invalid@")

    def test_create_user_with_invalid_email_no_local(self):
        with pytest.raises(InvalidEmailError):
            User(email="@example.com")


class TestOrderItemInvariants:
    """Tests for OrderItem domain invariants."""

    def test_create_order_item_with_valid_data(self):
        item = OrderItem(
            product_name="Test Product",
            price=Decimal("99.99"),
            quantity=2,
        )
        assert item.product_name == "Test Product"
        assert item.price == Decimal("99.99")
        assert item.quantity == 2

    def test_order_item_subtotal_calculation(self):
        item = OrderItem(
            product_name="Test Product",
            price=Decimal("10.00"),
            quantity=3,
        )
        assert item.subtotal == Decimal("30.00")

    def test_order_item_with_zero_quantity_fails(self):
        with pytest.raises(InvalidQuantityError):
            OrderItem(product_name="Test", price=Decimal("10.00"), quantity=0)

    def test_order_item_with_negative_quantity_fails(self):
        with pytest.raises(InvalidQuantityError):
            OrderItem(product_name="Test", price=Decimal("10.00"), quantity=-1)

    def test_order_item_with_negative_price_fails(self):
        with pytest.raises(InvalidPriceError):
            OrderItem(product_name="Test", price=Decimal("-10.00"), quantity=1)

    def test_order_item_with_zero_price_succeeds(self):
        item = OrderItem(product_name="Free Item", price=Decimal("0.00"), quantity=1)
        assert item.price == Decimal("0.00")


class TestOrderInvariants:
    """Tests for Order domain invariants."""

    def test_create_order(self):
        user_id = uuid.uuid4()
        order = Order(user_id=user_id)
        assert order.user_id == user_id
        assert order.status == OrderStatus.CREATED
        assert order.total_amount == Decimal("0")

    def test_add_item_to_order(self):
        order = Order(user_id=uuid.uuid4())
        item = order.add_item("Product", Decimal("100.00"), 2)
        assert len(order.items) == 1
        assert order.total_amount == Decimal("200.00")

    def test_order_total_recalculates_on_add_item(self):
        order = Order(user_id=uuid.uuid4())
        order.add_item("Product 1", Decimal("100.00"), 1)
        order.add_item("Product 2", Decimal("50.00"), 2)
        assert order.total_amount == Decimal("200.00")

    def test_pay_order(self):
        order = Order(user_id=uuid.uuid4())
        order.add_item("Product", Decimal("100.00"), 1)
        order.pay()
        assert order.status == OrderStatus.PAID

    def test_cannot_pay_order_twice(self):
        """CRITICAL INVARIANT: Order cannot be paid twice!"""
        order = Order(user_id=uuid.uuid4())
        order.add_item("Product", Decimal("100.00"), 1)
        order.pay()
        with pytest.raises(OrderAlreadyPaidError):
            order.pay()

    def test_cannot_pay_cancelled_order(self):
        order = Order(user_id=uuid.uuid4())
        order.cancel()
        with pytest.raises(OrderCancelledError):
            order.pay()

    def test_cancel_order(self):
        order = Order(user_id=uuid.uuid4())
        order.cancel()
        assert order.status == OrderStatus.CANCELLED

    def test_cannot_cancel_paid_order(self):
        order = Order(user_id=uuid.uuid4())
        order.pay()
        with pytest.raises(OrderAlreadyPaidError):
            order.cancel()

    def test_cannot_add_items_to_cancelled_order(self):
        order = Order(user_id=uuid.uuid4())
        order.cancel()
        with pytest.raises(OrderCancelledError):
            order.add_item("Product", Decimal("100.00"), 1)

    def test_ship_order_requires_paid_status(self):
        order = Order(user_id=uuid.uuid4())
        with pytest.raises(ValueError):
            order.ship()

    def test_complete_order_requires_shipped_status(self):
        order = Order(user_id=uuid.uuid4())
        order.pay()
        with pytest.raises(ValueError):
            order.complete()


class TestCriticalPaymentInvariant:
    """Special test class for the CRITICAL invariant: cannot pay twice."""

    def test_cannot_pay_twice_basic(self):
        order = Order(user_id=uuid.uuid4())
        order.pay()
        with pytest.raises(OrderAlreadyPaidError):
            order.pay()

    def test_cannot_pay_twice_with_items(self):
        order = Order(user_id=uuid.uuid4())
        order.add_item("Product", Decimal("100.00"), 1)
        order.pay()
        with pytest.raises(OrderAlreadyPaidError):
            order.pay()

    def test_order_remains_paid_after_failed_double_payment(self):
        order = Order(user_id=uuid.uuid4())
        order.pay()
        try:
            order.pay()
        except OrderAlreadyPaidError:
            pass
        assert order.status == OrderStatus.PAID

    def test_exception_contains_order_id(self):
        order = Order(user_id=uuid.uuid4())
        order.pay()
        with pytest.raises(OrderAlreadyPaidError) as exc_info:
            order.pay()
        assert str(order.id) in str(exc_info.value)
