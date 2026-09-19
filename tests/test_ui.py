"""
Tests for Flask Web UI Dashboard endpoints.
"""

from decimal import Decimal
import json
from pathlib import Path
import time
from unittest.mock import patch
import pytest

from src.models.order import (
    DebtorAddress,
    DebtorInfo,
    OrderData,
    OrderItem,
    PaidStatus,
)
from src.ui.app import app, _state, _lock


@pytest.fixture
def sample_order_data() -> OrderData:
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


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        # Reset state before each test
        with _lock:
            _state["status"] = "idle"
            _state["progress"] = []
            _state["result"] = None
            _state["extracted_data"] = None
            _state["image_path"] = None
            _state["mode"] = "llm"
        yield client


def test_index_page(client):
    """Test that dashboard home page loads successfully."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"Fakturama" in response.data
    assert b"Image-to-Cash" in response.data


def test_select_sample_valid(client):
    """Test selecting a valid sample image."""
    sample_path = str(Path("data/samples/purchase_order_01.png").resolve())
    response = client.post(
        "/api/select-sample",
        data=json.dumps({"path": sample_path}),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["success"] is True


def test_select_sample_invalid(client):
    """Test selecting a non-existent sample image."""
    response = client.post(
        "/api/select-sample",
        data=json.dumps({"path": "non_existent.png"}),
        content_type="application/json",
    )
    assert response.status_code == 404


def test_extract_without_selection(client):
    """Test extracting without selecting an image."""
    response = client.post(
        "/api/extract",
        data=json.dumps({"mode": "llm"}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_extract_llm_success(client, sample_order_data):
    """Test extraction with LLMExtractor (mocked return)."""
    sample_path = str(Path("data/samples/purchase_order_01.png").resolve())
    client.post(
        "/api/select-sample",
        data=json.dumps({"path": sample_path}),
        content_type="application/json",
    )

    with patch("src.extractors.llm_extractor.LLMExtractor.extract", return_value=sample_order_data):
        response = client.post(
            "/api/extract",
            data=json.dumps({"mode": "llm"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True
        assert "data" in data
        assert data["data"]["external_reference"] == "PO-2025-0042"
        assert data["data"]["items_count"] == 1


def test_run_dry_run(client, sample_order_data):
    """Test running the flow in dry_run mode via UI API."""
    sample_path = str(Path("data/samples/purchase_order_01.png").resolve())
    client.post(
        "/api/select-sample",
        data=json.dumps({"path": sample_path}),
        content_type="application/json",
    )

    with patch("src.extractors.llm_extractor.LLMExtractor.extract", return_value=sample_order_data):
        response = client.post(
            "/api/run",
            data=json.dumps({"dry_run": True}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True

        # Wait for thread to complete
        status_data = {}
        for _ in range(30):
            time.sleep(0.1)
            status_resp = client.get("/api/status")
            status_data = json.loads(status_resp.data)
            if status_data["status"] in ("done", "error"):
                break

        assert status_data["status"] == "done"
        assert status_data["result"]["success"] is True


def test_reset_endpoint(client):
    """Test reset endpoint clears state."""
    sample_path = str(Path("data/samples/purchase_order_01.png").resolve())
    client.post(
        "/api/select-sample",
        data=json.dumps({"path": sample_path}),
        content_type="application/json",
    )

    response = client.post("/api/reset")
    assert response.status_code == 200

    status_resp = client.get("/api/status")
    status_data = json.loads(status_resp.data)
    assert status_data["status"] == "idle"
    assert status_data["image_path"] is None
