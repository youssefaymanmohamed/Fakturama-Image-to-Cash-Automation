"""
Tests for the extractor modules: mock extractor and validation logic.
"""

import json
import pytest
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from src.extractors.mock_extractor import MockExtractor, SAMPLE_ORDER_SINGLE_LINE, SAMPLE_ORDER_MULTI_LINE
from src.extractors.base import BaseExtractor


class TestMockExtractor:
    """Test the MockExtractor's sample resolution and JSON loading."""

    def test_default_returns_single_line(self):
        ext = MockExtractor()
        data = ext.extract(Path("test_image.png"))
        assert len(data.items) == 1
        assert data.external_reference == "PO-2025-0042"

    def test_multi_keyword_returns_multi(self):
        ext = MockExtractor()
        data = ext.extract(Path("test_multi_order.png"))
        assert len(data.items) == 3
        assert data.external_reference == "PO-2025-0187"

    def test_forced_key_single(self):
        ext = MockExtractor(sample_key="single")
        data = ext.extract(Path("anything.png"))
        assert data.external_reference == "PO-2025-0042"

    def test_forced_key_multi(self):
        ext = MockExtractor(sample_key="multi")
        data = ext.extract(Path("anything.png"))
        assert len(data.items) == 3

    def test_json_sidecar_loading(self):
        """When a .json sidecar exists, data should be loaded from it."""
        with TemporaryDirectory() as tmpdir:
            json_data = {
                "order_date": "2025-12-25",
                "external_reference": "CUSTOM-REF",
                "items": [
                    {
                        "sku": "CUSTOM-SKU",
                        "description": "Custom Item",
                        "quantity": "3",
                        "unit_net_price": "10.00",
                        "vat_percent": "19",
                        "discount_percent": "0",
                    }
                ],
                "paid_status": "UNPAID",
            }
            json_path = Path(tmpdir) / "custom_order.json"
            img_path = Path(tmpdir) / "custom_order.png"

            # Create dummy image
            img_path.write_text("fake image")
            json_path.write_text(json.dumps(json_data))

            ext = MockExtractor()
            data = ext.extract(img_path)
            assert data.external_reference == "CUSTOM-REF"
            assert data.items[0].sku == "CUSTOM-SKU"

    def test_deep_copy_isolation(self):
        """Each extraction should return independent copies."""
        ext = MockExtractor(sample_key="single")
        d1 = ext.extract(Path("a.png"))
        d2 = ext.extract(Path("b.png"))
        d1.external_reference = "MODIFIED"
        assert d2.external_reference == "PO-2025-0042"


class TestExtractorValidation:
    """Test the base extractor's validation logic."""

    def test_valid_extraction_no_warnings(self):
        ext = MockExtractor(sample_key="single")
        data = ext.extract(Path("test.png"))
        warnings = ext.validate_extraction(data)
        assert len(warnings) == 0

    def test_missing_items_warning(self):
        ext = MockExtractor(sample_key="single")
        data = ext.extract(Path("test.png"))
        data.items = []
        warnings = ext.validate_extraction(data)
        assert any("No line items" in w for w in warnings)

    def test_missing_debtor_warning(self):
        ext = MockExtractor(sample_key="single")
        data = ext.extract(Path("test.png"))
        data.debtor.company = ""
        data.debtor.last_name = ""
        warnings = ext.validate_extraction(data)
        assert any("debtor" in w.lower() for w in warnings)


class TestBuiltinSampleIntegrity:
    """Verify that built-in samples have consistent calculated totals."""

    def test_single_line_totals(self):
        data = SAMPLE_ORDER_SINGLE_LINE
        assert data.total_net == data.source_total_net
        assert data.total_vat == data.source_total_vat
        assert data.total_gross == data.source_total_gross

    def test_multi_line_totals(self):
        data = SAMPLE_ORDER_MULTI_LINE
        # Allow small tolerance for multi-line rounding
        assert abs(data.total_net - data.source_total_net) <= Decimal("0.05")
        assert abs(data.total_gross - data.source_total_gross) <= Decimal("0.05")

    def test_single_line_items_valid(self):
        data = SAMPLE_ORDER_SINGLE_LINE
        for i, item in enumerate(data.items):
            assert item.validate_source_total(), f"Item {i} total mismatch"

    def test_multi_line_items_valid(self):
        data = SAMPLE_ORDER_MULTI_LINE
        for i, item in enumerate(data.items):
            assert item.validate_source_total(), f"Item {i} total mismatch"
