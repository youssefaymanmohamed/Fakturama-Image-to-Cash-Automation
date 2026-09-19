"""
Dry-run tests for the orchestrator flow.

Tests that the orchestrator correctly sequences extraction, validation,
and state transitions WITHOUT requiring Fakturama to be running.
Uses dry_run=True mode which skips all UI automation.
"""

from decimal import Decimal
from pathlib import Path
import pytest

from src.extractors.base import BaseExtractor
from src.flow.orchestrator import Orchestrator, FlowResult
from src.models.order import (
    DebtorAddress,
    DebtorInfo,
    OrderData,
    OrderItem,
    PaidStatus,
)


class StubExtractor(BaseExtractor):
    """Test stub that returns deterministic OrderData for testing flow sequencing."""

    def __init__(self, mode: str = "single"):
        self.mode = mode

    def extract(self, image_path: Path) -> OrderData:
        debtor = DebtorInfo(
            company="Acme Corporation",
            first_name="John",
            last_name="Smith",
            alias="acme-corp",
            billing_address=DebtorAddress(
                street="123 Innovation Drive",
                zip="10115",
                city="Berlin",
                country="Germany",
                email="contact@acme.com",
                telephone="+49 30 1234567",
            ),
            payment_method="Bank Transfer",
        )

        if self.mode == "single":
            items = [
                OrderItem(
                    sku="WIDGET-001",
                    description="Premium Widget",
                    quantity=Decimal("10"),
                    unit_net_price=Decimal("24.50"),
                    vat_percent=Decimal("19"),
                    discount_percent=Decimal("0"),
                    source_total=Decimal("245.00"),
                )
            ]
            return OrderData(
                order_date="2025-03-15",
                external_reference="PO-2025-0042",
                debtor=debtor,
                items=items,
                source_total_net=Decimal("245.00"),
                source_total_vat=Decimal("46.55"),
                source_total_gross=Decimal("291.55"),
                paid_status=PaidStatus.PAID,
                payment_date="2025-03-20",
            )
        else:
            items = [
                OrderItem(
                    sku="BOLT-M8-50",
                    description="Hex Bolt M8x50mm Steel",
                    quantity=Decimal("500"),
                    unit_net_price=Decimal("0.35"),
                    vat_percent=Decimal("19"),
                    discount_percent=Decimal("5"),
                    source_total=Decimal("166.25"),
                ),
                OrderItem(
                    sku="NUT-M8-NYLOC",
                    description="Nyloc Nut M8 Zinc Plated",
                    quantity=Decimal("500"),
                    unit_net_price=Decimal("0.15"),
                    vat_percent=Decimal("19"),
                    discount_percent=Decimal("0"),
                    source_total=Decimal("75.00"),
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
            ]
            return OrderData(
                order_date="2025-03-18",
                external_reference="PO-2025-0187",
                debtor=debtor,
                items=items,
                source_total_net=Decimal("318.50"),
                source_total_vat=Decimal("50.92"),
                source_total_gross=Decimal("369.42"),
                paid_status=PaidStatus.UNPAID,
                payment_date=None,
            )


class FakeUIAWrapper:
    """Minimal stub for UIAWrapper that satisfies the orchestrator interface."""
    def __init__(self, **kwargs):
        self._screenshot_dir = Path(kwargs.get("screenshot_dir", "artifacts/screenshots"))
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._screenshot_counter = 0

    def attach_or_launch(self, **kwargs):
        pass

    def find_fakturama_window(self, **kwargs):
        return None

    def capture_screenshot(self, label=""):
        self._screenshot_counter += 1
        return self._screenshot_dir / f"fake_{self._screenshot_counter}.png"


class TestOrchestratorDryRun:
    """Test the orchestrator in dry-run mode (no UI automation)."""

    def test_dry_run_single_line_success(self):
        extractor = StubExtractor(mode="single")
        uia = FakeUIAWrapper(screenshot_dir="artifacts/screenshots")
        orch = Orchestrator(extractor, uia, dry_run=True)

        result = orch.run("data/samples/purchase_order_01.png")

        assert result.success is True
        assert result.order_data is not None
        assert result.order_data.external_reference == "PO-2025-0042"
        assert len(result.steps_completed) >= 2
        assert any("extraction" in s.lower() for s in result.steps_completed)
        assert result.error is None

    def test_dry_run_multi_line_success(self):
        extractor = StubExtractor(mode="multi")
        uia = FakeUIAWrapper(screenshot_dir="artifacts/screenshots")
        orch = Orchestrator(extractor, uia, dry_run=True)

        result = orch.run("data/samples/purchase_order_02_multi.png")

        assert result.success is True
        assert result.order_data is not None
        assert len(result.order_data.items) == 3
        assert result.error is None

    def test_dry_run_extraction_warnings(self):
        extractor = StubExtractor(mode="single")
        uia = FakeUIAWrapper(screenshot_dir="artifacts/screenshots")
        orch = Orchestrator(extractor, uia, dry_run=True)

        result = orch.run("data/samples/purchase_order_01.png")
        assert len(result.extraction_warnings) == 0

    def test_result_serialization(self):
        extractor = StubExtractor(mode="single")
        uia = FakeUIAWrapper(screenshot_dir="artifacts/screenshots")
        orch = Orchestrator(extractor, uia, dry_run=True)

        result = orch.run("data/samples/purchase_order_01.png")
        d = result.to_dict()

        assert isinstance(d, dict)
        assert d["success"] is True
        assert d["order_summary"] is not None
        assert d["order_summary"]["items_count"] == 1

    def test_progress_callback_fires(self):
        extractor = StubExtractor(mode="single")
        uia = FakeUIAWrapper(screenshot_dir="artifacts/screenshots")
        orch = Orchestrator(extractor, uia, dry_run=True)

        progress_log = []
        orch.set_progress_callback(lambda step, msg: progress_log.append((step, msg)))

        result = orch.run("test.png")
        assert len(progress_log) > 0
        assert any("1.1" in step for step, _ in progress_log)

    def test_paid_status_carried_through(self):
        extractor = StubExtractor(mode="single")
        uia = FakeUIAWrapper(screenshot_dir="artifacts/screenshots")
        orch = Orchestrator(extractor, uia, dry_run=True)

        result = orch.run("test.png")
        assert result.order_data.paid_status.value == "PAID"
        assert result.order_data.payment_date is not None

    def test_unpaid_status(self):
        extractor = StubExtractor(mode="multi")
        uia = FakeUIAWrapper(screenshot_dir="artifacts/screenshots")
        orch = Orchestrator(extractor, uia, dry_run=True)

        result = orch.run("test.png")
        assert result.order_data.paid_status.value == "UNPAID"
        assert result.order_data.payment_date is None
