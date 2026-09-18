"""
Dry-run tests for the orchestrator flow.

Tests that the orchestrator correctly sequences extraction, validation,
and state transitions WITHOUT requiring Fakturama to be running.
Uses dry_run=True mode which skips all UI automation.
"""

import pytest
from pathlib import Path

from src.extractors.mock_extractor import MockExtractor
from src.flow.orchestrator import Orchestrator, FlowResult


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
        extractor = MockExtractor(sample_key="single")
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
        extractor = MockExtractor(sample_key="multi")
        uia = FakeUIAWrapper(screenshot_dir="artifacts/screenshots")
        orch = Orchestrator(extractor, uia, dry_run=True)

        result = orch.run("data/samples/purchase_order_02.png")

        assert result.success is True
        assert result.order_data is not None
        assert len(result.order_data.items) == 3
        assert result.error is None

    def test_dry_run_extraction_warnings(self):
        extractor = MockExtractor(sample_key="single")
        uia = FakeUIAWrapper(screenshot_dir="artifacts/screenshots")
        orch = Orchestrator(extractor, uia, dry_run=True)

        result = orch.run("data/samples/purchase_order_01.png")
        # Built-in samples should produce no warnings
        assert len(result.extraction_warnings) == 0

    def test_result_serialization(self):
        extractor = MockExtractor(sample_key="single")
        uia = FakeUIAWrapper(screenshot_dir="artifacts/screenshots")
        orch = Orchestrator(extractor, uia, dry_run=True)

        result = orch.run("data/samples/purchase_order_01.png")
        d = result.to_dict()

        assert isinstance(d, dict)
        assert d["success"] is True
        assert d["order_summary"] is not None
        assert d["order_summary"]["items_count"] == 1

    def test_progress_callback_fires(self):
        extractor = MockExtractor(sample_key="single")
        uia = FakeUIAWrapper(screenshot_dir="artifacts/screenshots")
        orch = Orchestrator(extractor, uia, dry_run=True)

        progress_log = []
        orch.set_progress_callback(lambda step, msg: progress_log.append((step, msg)))

        result = orch.run("test.png")
        assert len(progress_log) > 0
        assert any("1.1" in step for step, _ in progress_log)

    def test_paid_status_carried_through(self):
        extractor = MockExtractor(sample_key="single")
        uia = FakeUIAWrapper(screenshot_dir="artifacts/screenshots")
        orch = Orchestrator(extractor, uia, dry_run=True)

        result = orch.run("test.png")
        assert result.order_data.paid_status.value == "PAID"
        assert result.order_data.payment_date is not None

    def test_unpaid_status(self):
        extractor = MockExtractor(sample_key="multi")
        uia = FakeUIAWrapper(screenshot_dir="artifacts/screenshots")
        orch = Orchestrator(extractor, uia, dry_run=True)

        result = orch.run("test.png")
        assert result.order_data.paid_status.value == "UNPAID"
        assert result.order_data.payment_date is None
