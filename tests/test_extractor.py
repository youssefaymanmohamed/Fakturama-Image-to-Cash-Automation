"""
Tests for extractor modules: BaseExtractor validation, OCRExtractor parsing,
and LLMExtractor response handling (using unit test mocks).
"""

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.extractors.base import BaseExtractor, ExtractionError
from src.extractors.llm_extractor import LLMExtractor
from src.extractors.ocr_extractor import (
    OCRExtractor,
    _parse_decimal,
    _normalize_payment_method,
    _normalize_date,
)
from src.models.order import (
    DebtorAddress,
    DebtorInfo,
    OrderData,
    OrderItem,
    PaidStatus,
)


@pytest.fixture
def valid_order_data() -> OrderData:
    """Fixture providing a valid OrderData instance."""
    debtor = DebtorInfo(
        company="Acme Corp",
        first_name="John",
        last_name="Doe",
        alias="acme-corp",
        billing_address=DebtorAddress(
            street="Main St 1",
            zip="12345",
            city="Berlin",
            country="Germany",
            email="john@acme.com",
            telephone="+4912345678",
        ),
        payment_method="Bank Transfer",
    )
    items = [
        OrderItem(
            sku="ITEM-001",
            description="Test Widget",
            quantity=Decimal("2"),
            unit_net_price=Decimal("50.00"),
            vat_percent=Decimal("19"),
            discount_percent=Decimal("0"),
            source_total=Decimal("100.00"),
        )
    ]
    return OrderData(
        order_date="2025-03-15",
        external_reference="PO-2025-9999",
        debtor=debtor,
        items=items,
        source_total_net=Decimal("100.00"),
        source_total_vat=Decimal("19.00"),
        source_total_gross=Decimal("119.00"),
        paid_status=PaidStatus.PAID,
        payment_date="2025-03-20",
    )


class TestBaseExtractorValidation:
    """Test BaseExtractor's validation and reconciliation logic."""

    class ConcreteExtractor(BaseExtractor):
        def extract(self, image_path: Path) -> OrderData:
            raise NotImplementedError

    def test_valid_extraction_no_warnings(self, valid_order_data):
        ext = self.ConcreteExtractor()
        warnings = ext.validate_extraction(valid_order_data)
        assert len(warnings) == 0

    def test_missing_items_warning(self, valid_order_data):
        ext = self.ConcreteExtractor()
        valid_order_data.items = []
        warnings = ext.validate_extraction(valid_order_data)
        assert any("No line items" in w for w in warnings)

    def test_missing_debtor_warning(self, valid_order_data):
        ext = self.ConcreteExtractor()
        valid_order_data.debtor.company = ""
        valid_order_data.debtor.last_name = ""
        warnings = ext.validate_extraction(valid_order_data)
        assert any("debtor" in w.lower() for w in warnings)

    def test_math_mismatch_warning(self, valid_order_data):
        ext = self.ConcreteExtractor()
        # Alter the source gross to produce a mathematical mismatch
        valid_order_data.source_total_gross = Decimal("999.99")
        warnings = ext.validate_extraction(valid_order_data)
        assert any("Order total gross" in w for w in warnings)


class TestOCRExtractorParsing:
    """Test OCRExtractor utility and regex parsing functions."""

    def test_parse_decimal_formats(self):
        assert _parse_decimal("123.45") == Decimal("123.45")
        assert _parse_decimal("123,45") == Decimal("123.45")
        assert _parse_decimal("1.234,56") == Decimal("1234.56")
        assert _parse_decimal("1,234.56") == Decimal("1234.56")
        assert _parse_decimal("€ 49.99") == Decimal("49.99")
        assert _parse_decimal("") is None

    def test_normalize_payment_method(self):
        assert _normalize_payment_method("Bank Transfer (Wire)") == "Bank Transfer"
        assert _normalize_payment_method("Credit Card Payment") == "Credit Card"
        assert _normalize_payment_method("SEPA Direct Debit") == "SEPA Direct Debit"
        assert _normalize_payment_method("Unknown") == "Bank Transfer"

    def test_normalize_date(self):
        assert _normalize_date("2025-03-15") == "2025-03-15"
        assert _normalize_date("15.03.2025") == "2025-03-15"
        assert _normalize_date("March 15, 2025") == "2025-03-15"
        assert _normalize_date("invalid") is None

    def test_ocr_text_parser(self):
        ext = OCRExtractor()
        raw_sample = """
PURCHASE ORDER
PO Number: PO-2025-0042
Order Date: 2025-03-15

Bill To:
Acme Corporation
John Smith
123 Innovation Drive
10115 Berlin
Germany
contact@acme.com
+49 30 1234567

Item: WIDGET-001 Premium Widget
Quantity: 10
Unit Price: 24.50
Line Total: 245.00
VAT: 19%

Total Net: 245.00
VAT: 46.55
Total Gross: 291.55
Payment: Bank Transfer
Status: PAID
Payment Date: 2025-03-20
"""
        order = ext._parse(raw_sample)
        assert order.external_reference == "PO-2025-0042"
        assert str(order.order_date) == "2025-03-15"
        assert order.debtor.company == "Acme Corporation"
        assert order.paid_status == PaidStatus.PAID


class TestLLMExtractorUnit:
    """Test LLMExtractor initialization and error handling."""

    def test_missing_api_key_raises_extraction_error(self, tmp_path):
        dummy_img = tmp_path / "po.png"
        dummy_img.write_bytes(b"dummy image bytes")

        with patch.dict("os.environ", {}, clear=True):
            ext = LLMExtractor(api_key="")
            ext._api_key = ""
            with pytest.raises(ExtractionError, match="GOOGLE_API_KEY"):
                ext.extract(dummy_img)

    def test_missing_image_file_raises_error(self):
        ext = LLMExtractor(api_key="test-key")
        with pytest.raises(ExtractionError, match="not found"):
            ext.extract(Path("non_existent_file.png"))
