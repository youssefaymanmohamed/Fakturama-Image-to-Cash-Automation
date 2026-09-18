"""
Unit tests for data models: Pydantic validation, VAT math, gross calculation,
payment code mapping, line totals, and order total reconciliation.
"""

import pytest
from decimal import Decimal
from datetime import date

from src.models.order import (
    DebtorAddress,
    DebtorInfo,
    DocumentVerification,
    OrderData,
    OrderItem,
    PaidStatus,
    PaymentMethodCode,
    PAYMENT_METHOD_TO_CODE,
)


class TestPaymentMethodMapping:
    """Verify payment method name → Fakturama payment code mapping."""

    def test_bank_transfer(self):
        assert PAYMENT_METHOD_TO_CODE["Bank Transfer"] == PaymentMethodCode.CREDIT_TRANSFER

    def test_credit_card(self):
        assert PAYMENT_METHOD_TO_CODE["Credit Card"] == PaymentMethodCode.CREDIT_CARD

    def test_sepa(self):
        assert PAYMENT_METHOD_TO_CODE["SEPA Direct Debit"] == PaymentMethodCode.SEPA_DIRECT_DEBIT

    def test_unknown_returns_none(self):
        assert PAYMENT_METHOD_TO_CODE.get("Cash") is None


class TestOrderItem:
    """Test OrderItem calculations."""

    def test_gross_price_19_percent(self):
        item = OrderItem(
            sku="TEST",
            unit_net_price=Decimal("100.00"),
            vat_percent=Decimal("19"),
        )
        assert item.gross_unit_price == Decimal("119.00")

    def test_gross_price_7_percent(self):
        item = OrderItem(
            sku="TEST",
            unit_net_price=Decimal("10.00"),
            vat_percent=Decimal("7"),
        )
        assert item.gross_unit_price == Decimal("10.70")

    def test_gross_price_rounding(self):
        """Gross price should be rounded to 2 decimal places."""
        item = OrderItem(
            sku="TEST",
            unit_net_price=Decimal("24.50"),
            vat_percent=Decimal("19"),
        )
        # 24.50 × 1.19 = 29.155 → 29.16
        assert item.gross_unit_price == Decimal("29.16")

    def test_line_total_no_discount(self):
        item = OrderItem(
            sku="TEST",
            quantity=Decimal("10"),
            unit_net_price=Decimal("5.00"),
            discount_percent=Decimal("0"),
        )
        assert item.line_total == Decimal("50.00")

    def test_line_total_with_discount(self):
        item = OrderItem(
            sku="TEST",
            quantity=Decimal("10"),
            unit_net_price=Decimal("24.50"),
            discount_percent=Decimal("5"),
        )
        # 10 × 24.50 × 0.95 = 232.75
        assert item.line_total == Decimal("232.75")

    def test_vat_name(self):
        item = OrderItem(sku="TEST", vat_percent=Decimal("19"))
        assert item.vat_name == "VAT 19%"

    def test_vat_name_fractional(self):
        item = OrderItem(sku="TEST", vat_percent=Decimal("7.5"))
        assert item.vat_name == "VAT 7.5%"

    def test_source_total_validation_pass(self):
        item = OrderItem(
            sku="TEST",
            quantity=Decimal("10"),
            unit_net_price=Decimal("24.50"),
            discount_percent=Decimal("5"),
            source_total=Decimal("232.75"),
        )
        assert item.validate_source_total() is True

    def test_source_total_validation_fail(self):
        item = OrderItem(
            sku="TEST",
            quantity=Decimal("10"),
            unit_net_price=Decimal("24.50"),
            discount_percent=Decimal("5"),
            source_total=Decimal("999.99"),
        )
        assert item.validate_source_total() is False

    def test_source_total_none_passes(self):
        item = OrderItem(sku="TEST", source_total=None)
        assert item.validate_source_total() is True


class TestDebtorInfo:
    """Test debtor info properties."""

    def test_display_name_company_and_name(self):
        debtor = DebtorInfo(company="Acme", first_name="John", last_name="Smith")
        assert debtor.display_name == "Acme John Smith"

    def test_display_name_no_company(self):
        debtor = DebtorInfo(first_name="Jane", last_name="Doe")
        assert debtor.display_name == "Jane Doe"

    def test_delivery_same_as_billing(self):
        debtor = DebtorInfo(delivery_address=None)
        assert debtor.delivery_same_as_billing is True

    def test_delivery_different(self):
        debtor = DebtorInfo(delivery_address=DebtorAddress(street="Other St"))
        assert debtor.delivery_same_as_billing is False

    def test_payment_code(self):
        debtor = DebtorInfo(payment_method="Bank Transfer")
        assert debtor.payment_code == PaymentMethodCode.CREDIT_TRANSFER


class TestOrderData:
    """Test full order data model."""

    def _make_order(self) -> OrderData:
        return OrderData(
            order_date="2025-03-15",
            external_reference="PO-001",
            debtor=DebtorInfo(company="Test Corp"),
            items=[
                OrderItem(
                    sku="A",
                    quantity=Decimal("10"),
                    unit_net_price=Decimal("24.50"),
                    vat_percent=Decimal("19"),
                    discount_percent=Decimal("5"),
                    source_total=Decimal("232.75"),
                ),
            ],
            source_total_net=Decimal("232.75"),
            source_total_vat=Decimal("44.22"),
            source_total_gross=Decimal("276.97"),
            paid_status=PaidStatus.PAID,
            payment_date="2025-03-20",
        )

    def test_date_parsing_iso(self):
        order = self._make_order()
        assert order.order_date == date(2025, 3, 15)

    def test_date_parsing_european(self):
        order = OrderData(order_date="15.03.2025", items=[])
        assert order.order_date == date(2025, 3, 15)

    def test_total_net(self):
        order = self._make_order()
        assert order.total_net == Decimal("232.75")

    def test_total_vat(self):
        order = self._make_order()
        assert order.total_vat == Decimal("44.22")

    def test_total_gross(self):
        order = self._make_order()
        assert order.total_gross == Decimal("276.97")

    def test_validate_totals(self):
        order = self._make_order()
        result = order.validate_totals()
        assert result["net"] is True
        assert result["vat"] is True
        assert result["gross"] is True

    def test_summary_dict(self):
        order = self._make_order()
        summary = order.to_summary_dict()
        assert summary["order_date"] == "2025-03-15"
        assert summary["items_count"] == 1
        assert summary["paid_status"] == "PAID"

    def test_payment_date_none(self):
        order = OrderData(
            order_date="2025-01-01",
            paid_status=PaidStatus.UNPAID,
            payment_date=None,
            items=[],
        )
        assert order.payment_date is None

    def test_validate_all_line_totals(self):
        order = self._make_order()
        results = order.validate_all_line_totals()
        assert all(ok for _, ok in results)


class TestDocumentVerification:
    """Test verification result model."""

    def test_all_ok_true(self):
        v = DocumentVerification(
            doc_type="Order",
            date_ok=True, cust_ref_ok=True, total_ok=True, state_ok=True,
        )
        assert v.all_ok is True

    def test_all_ok_false(self):
        v = DocumentVerification(doc_type="Order", date_ok=True, cust_ref_ok=False)
        assert v.all_ok is False
