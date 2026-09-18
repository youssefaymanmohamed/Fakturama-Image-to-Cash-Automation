"""
Deterministic mock extractor for testing and offline evaluation.

Loads pre-defined order data from JSON sidecar files or returns built-in
sample orders when no sidecar is available. Ensures repeatable test runs
without requiring API keys or network access.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from src.extractors.base import BaseExtractor
from src.models.order import (
    DebtorAddress,
    DebtorInfo,
    OrderData,
    OrderItem,
    PaidStatus,
)


# ---------------------------------------------------------------------------
# Built-in sample orders (used when no JSON sidecar exists)
# ---------------------------------------------------------------------------

SAMPLE_ORDER_SINGLE_LINE = OrderData(
    order_date="2025-03-15",
    external_reference="PO-2025-0042",
    debtor=DebtorInfo(
        company="Acme Corporation",
        first_name="John",
        last_name="Smith",
        alias="acme-smith",
        billing_address=DebtorAddress(
            street="123 Innovation Drive",
            zip_code="10115",
            city="Berlin",
            country="Germany",
            email="john.smith@acme-corp.de",
            telephone="+49 30 12345678",
        ),
        delivery_address=None,  # same as billing
        payment_method="Bank Transfer",
        discount_percent=Decimal("0"),
        net_or_gross="Net",
    ),
    items=[
        OrderItem(
            sku="WIDGET-001",
            description="Premium Stainless Steel Widget",
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


SAMPLE_ORDER_MULTI_LINE = OrderData(
    order_date="2025-06-01",
    external_reference="PO-2025-0187",
    debtor=DebtorInfo(
        company="TechParts GmbH",
        first_name="Maria",
        last_name="Mueller",
        alias="techparts-mueller",
        billing_address=DebtorAddress(
            street="Friedrichstraße 45",
            zip_code="80331",
            city="Munich",
            country="Germany",
            email="maria.mueller@techparts.de",
            telephone="+49 89 87654321",
        ),
        delivery_address=DebtorAddress(
            street="Lagerweg 12",
            zip_code="80339",
            city="Munich",
            country="Germany",
            email="warehouse@techparts.de",
            telephone="+49 89 87654322",
        ),
        payment_method="Credit Card",
        discount_percent=Decimal("0"),
        net_or_gross="Net",
    ),
    items=[
        OrderItem(
            sku="BOLT-M8X20",
            description="Hex Head Bolt M8x20 Grade 8.8",
            quantity=Decimal("500"),
            unit_net_price=Decimal("0.35"),
            vat_percent=Decimal("19"),
            discount_percent=Decimal("10"),
            source_total=Decimal("157.50"),
        ),
        OrderItem(
            sku="NUT-M8-FLANGE",
            description="Flanged Lock Nut M8 Zinc Plated",
            quantity=Decimal("500"),
            unit_net_price=Decimal("0.18"),
            vat_percent=Decimal("19"),
            discount_percent=Decimal("10"),
            source_total=Decimal("81.00"),
        ),
        OrderItem(
            sku="WASHER-M8-FLAT",
            description="Flat Washer M8 Stainless A2",
            quantity=Decimal("1000"),
            unit_net_price=Decimal("0.08"),
            vat_percent=Decimal("7"),
            discount_percent=Decimal("0"),
            source_total=Decimal("80.00"),
        ),
    ],
    source_total_net=Decimal("318.50"),
    source_total_vat=Decimal("50.92"),
    source_total_gross=Decimal("369.42"),
    paid_status=PaidStatus.UNPAID,
    payment_date=None,
)

BUILTIN_SAMPLES = {
    "single": SAMPLE_ORDER_SINGLE_LINE,
    "multi": SAMPLE_ORDER_MULTI_LINE,
}


class MockExtractor(BaseExtractor):
    """
    Deterministic extractor that returns pre-defined order data.

    Resolution order:
    1. If a JSON sidecar file exists (same name, .json extension), load it.
    2. If the image filename contains 'multi', return the multi-line sample.
    3. Otherwise, return the single-line sample.
    """

    def __init__(self, sample_key: str | None = None):
        """
        Args:
            sample_key: Force a specific built-in sample ('single' or 'multi').
                        If None, auto-detect from image filename.
        """
        self._forced_key = sample_key

    def extract(self, image_path: Path) -> OrderData:
        image_path = Path(image_path)

        # 1. Try JSON sidecar
        json_path = image_path.with_suffix(".json")
        if json_path.exists():
            return self._load_from_json(json_path)

        # 2. Force or auto-detect
        if self._forced_key and self._forced_key in BUILTIN_SAMPLES:
            return BUILTIN_SAMPLES[self._forced_key].model_copy(deep=True)

        if "multi" in image_path.stem.lower():
            return SAMPLE_ORDER_MULTI_LINE.model_copy(deep=True)

        return SAMPLE_ORDER_SINGLE_LINE.model_copy(deep=True)

    def _load_from_json(self, json_path: Path) -> OrderData:
        """Load OrderData from a JSON sidecar file."""
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return OrderData(**data)
