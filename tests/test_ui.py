"""
Tests for Flask Web UI Dashboard endpoints.
"""

import json
import time
from pathlib import Path
import pytest

from src.ui.app import app, _state, _lock


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
            _state["mode"] = "mock"
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
        data=json.dumps({"mode": "mock"}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_extract_mock_success(client):
    """Test extraction with mock extractor on selected sample."""
    sample_path = str(Path("data/samples/purchase_order_01.png").resolve())
    client.post(
        "/api/select-sample",
        data=json.dumps({"path": sample_path}),
        content_type="application/json",
    )

    response = client.post(
        "/api/extract",
        data=json.dumps({"mode": "mock"}),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["success"] is True
    assert "data" in data
    assert data["data"]["external_reference"] == "PO-2025-0042"
    assert data["data"]["items_count"] == 1


def test_run_dry_run(client):
    """Test running the flow in dry_run mode via UI API."""
    sample_path = str(Path("data/samples/purchase_order_01.png").resolve())
    client.post(
        "/api/select-sample",
        data=json.dumps({"path": sample_path}),
        content_type="application/json",
    )

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
    for _ in range(20):
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
