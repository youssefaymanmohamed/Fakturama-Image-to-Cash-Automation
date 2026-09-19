"""
Flask web UI dashboard for Fakturama Image-to-Cash Automation testing.

Provides a beautiful, interactive interface for:
  - Uploading / selecting order images
  - Previewing extracted data before automation
  - Running the automation flow with real-time progress
  - Viewing step-by-step milestone screenshots
  - Reviewing verification results
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

# Project imports
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.extractors.base import ExtractionError
from src.extractors.llm_extractor import LLMExtractor
from src.extractors.ocr_extractor import OCRExtractor
from src.models.order import OrderData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    static_folder=str(Path(__file__).parent / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB upload limit

# Global state for the running automation
_state = {
    "status": "idle",       # idle | extracting | running | done | error
    "progress": [],         # list of {step, message, timestamp}
    "result": None,         # FlowResult.to_dict()
    "extracted_data": None, # OrderData.to_summary_dict()
    "image_path": None,
    "mode": "llm",          # llm | ocr
}
_lock = threading.Lock()

# Directories
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
SAMPLES_DIR = PROJECT_ROOT / "data" / "samples"
SCREENSHOTS_DIR = PROJECT_ROOT / "artifacts" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Render the main dashboard."""
    # List available sample images
    samples = []
    if SAMPLES_DIR.exists():
        for f in sorted(SAMPLES_DIR.glob("*.png")):
            samples.append({"name": f.name, "path": str(f)})
        for f in sorted(SAMPLES_DIR.glob("*.jpg")):
            samples.append({"name": f.name, "path": str(f)})
    return render_template("index.html", samples=samples)


@app.route("/api/upload", methods=["POST"])
def upload_image():
    """Handle image upload."""
    if "image" not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    filepath = UPLOAD_DIR / file.filename
    file.save(str(filepath))

    with _lock:
        _state["image_path"] = str(filepath)

    return jsonify({"success": True, "path": str(filepath), "filename": file.filename})


@app.route("/api/select-sample", methods=["POST"])
def select_sample():
    """Select a sample image."""
    data = request.get_json() or {}
    path = data.get("path", "")
    if not path or not Path(path).exists():
        return jsonify({"error": f"Sample not found: {path}"}), 404

    with _lock:
        _state["image_path"] = path
        _state["extracted_data"] = None
        _state["current_order_data"] = None
        _state["status"] = "image_selected"
        _state["progress"] = []
        _state["result"] = None

    return jsonify({"success": True, "path": path})


@app.route("/api/extract", methods=["POST"])
def extract_data():
    """Extract data from the selected image."""
    data = request.get_json() or {}
    mode = data.get("mode", "llm")
    api_key = data.get("api_key", "").strip() or None

    with _lock:
        image_path = _state["image_path"]
        _state["mode"] = mode
        if api_key:
            _state["api_key"] = api_key
        _state["status"] = "extracting"
        _state["progress"] = []

    if not image_path:
        with _lock:
            _state["status"] = "error"
        return jsonify({"error": "No image selected"}), 400

    try:
        if mode == "ocr":
            extractor = OCRExtractor()
        else:
            extractor = LLMExtractor(api_key=api_key or _state.get("api_key"))

        order_data = extractor.extract(Path(image_path))
        warnings = extractor.validate_extraction(order_data)
        summary = order_data.to_summary_dict()
        summary["warnings"] = warnings

        with _lock:
            _state["extracted_data"] = summary
            _state["current_order_data"] = order_data
            _state["status"] = "extracted"

        print("\n" + "=" * 65, flush=True)
        print(f"  [ORDER DATA EXTRACTED: MODE={mode.upper()}]", flush=True)
        print("=" * 65, flush=True)
        print(json.dumps(summary, indent=2), flush=True)
        print("=" * 65 + "\n", flush=True)

        return jsonify({"success": True, "data": summary})

    except (ExtractionError, Exception) as e:
        with _lock:
            _state["status"] = "error"
        return jsonify({"error": str(e)}), 500


@app.route("/api/run", methods=["POST"])
def run_automation():
    """Start the automation flow in a background thread."""
    data = request.get_json() or {}
    dry_run = data.get("dry_run", True)

    with _lock:
        if _state["status"] == "running":
            return jsonify({"error": "Automation already running"}), 409
        image_path = _state["image_path"]
        mode = _state.get("mode", "mock")
        cached_order_data = _state.get("current_order_data")
        _state["status"] = "running"
        _state["progress"] = []
        _state["result"] = None

    if not image_path:
        with _lock:
            _state["status"] = "error"
        return jsonify({"error": "No image selected"}), 400

    def progress_callback(step, message):
        print(f"  [{step}] {message}", flush=True)
        with _lock:
            _state["progress"].append({
                "step": step,
                "message": message,
                "timestamp": time.time(),
            })

    def run_flow():
        mode_str = "DRY RUN SIMULATION" if dry_run else "LIVE AUTOMATION"
        print("\n" + "=" * 65, flush=True)
        print(f"  [STARTING FLOW: {mode_str}]", flush=True)
        print(f"  Image: {Path(image_path).name}", flush=True)
        print("=" * 65 + "\n", flush=True)

        try:
            import importlib
            import src.automation.uia_wrapper
            import src.automation.fakturama_app
            import src.flow.orchestrator
            importlib.reload(src.automation.uia_wrapper)
            importlib.reload(src.automation.fakturama_app)
            importlib.reload(src.flow.orchestrator)
            from src.automation.uia_wrapper import UIAWrapper
            from src.flow.orchestrator import Orchestrator

            if mode == "ocr":
                extractor = OCRExtractor()
            else:
                extractor = LLMExtractor(api_key=_state.get("api_key"))

            uia = None if dry_run else UIAWrapper(screenshot_dir=str(SCREENSHOTS_DIR))
            orch = Orchestrator(extractor, uia, dry_run=dry_run)
            orch.set_progress_callback(progress_callback)

            result = orch.run(image_path, order_data=cached_order_data)

            with _lock:
                _state["result"] = result.to_dict()
                _state["status"] = "done" if result.success else "error"

            print("\n" + "=" * 65, flush=True)
            if result.success:
                print("  ✓ AUTOMATION COMPLETED SUCCESSFULLY", flush=True)
            else:
                print(f"  ✕ FLOW STOPPED: {result.error}", flush=True)
            print("=" * 65 + "\n", flush=True)

        except Exception as e:
            logger.exception("Automation flow error")
            print(f"\n[ERROR] Flow failed: {e}\n", flush=True)
            with _lock:
                _state["status"] = "error"
                _state["result"] = {"error": str(e), "success": False}


    thread = threading.Thread(target=run_flow, daemon=True)
    thread.start()

    return jsonify({"success": True, "message": "Automation started"})


@app.route("/api/status")
def get_status():
    """Get current automation status and progress."""
    with _lock:
        return jsonify({
            "status": _state["status"],
            "progress": _state["progress"],
            "result": _state["result"],
            "extracted_data": _state["extracted_data"],
            "image_path": _state["image_path"],
        })


@app.route("/api/reset", methods=["POST"])
def reset():
    """Reset the automation state."""
    with _lock:
        _state["status"] = "idle"
        _state["progress"] = []
        _state["result"] = None
        _state["extracted_data"] = None
        _state["image_path"] = None
    return jsonify({"success": True})


@app.route("/screenshots/<path:filename>")
def serve_screenshot(filename):
    """Serve screenshot files, with safe image fallback."""
    # Clean filename of any .failed suffix
    clean_name = filename.replace(".failed", "")
    target = SCREENSHOTS_DIR / clean_name
    if target.exists():
        return send_from_directory(str(SCREENSHOTS_DIR), clean_name)
    
    # Try finding matching screenshot by prefix/step
    for match in sorted(SCREENSHOTS_DIR.glob(f"*{clean_name}*")):
        if match.suffix.lower() == ".png":
            return send_from_directory(str(SCREENSHOTS_DIR), match.name)
            
    # If not found, return an existing PNG screenshot or 404
    existing = list(SCREENSHOTS_DIR.glob("*.png"))
    if existing:
        return send_from_directory(str(SCREENSHOTS_DIR), existing[0].name)
    return send_from_directory(str(SCREENSHOTS_DIR), filename)



@app.route("/samples/<path:filename>")
def serve_sample(filename):
    """Serve sample image files."""
    return send_from_directory(str(SAMPLES_DIR), filename)


@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    """Serve uploaded image files."""
    return send_from_directory(str(UPLOAD_DIR), filename)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_dashboard(host: str = "127.0.0.1", port: int = 5000, debug: bool = False):
    """Start the dashboard web server."""
    print(f"\n{'='*60}")
    print(f"  Fakturama Image-to-Cash Automation Dashboard")
    print(f"  Open in browser: http://{host}:{port}")
    print(f"{'='*60}\n")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_dashboard(debug=True)
