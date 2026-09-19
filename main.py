"""
Fakturama Image-to-Cash Automation — Main Entry Point

Usage:
    # Launch the web UI dashboard (recommended for testing)
    python main.py

    # Launch with custom port
    python main.py --port 8080

    # CLI: dry-run extraction only
    python main.py --cli --image data/samples/purchase_order_01.png --dry-run

    # CLI: full automation (requires Fakturama to be running)
    python main.py --cli --image data/samples/purchase_order_01.png

    # CLI: use LLM extraction (requires GOOGLE_API_KEY env var)
    python main.py --cli --image order.png --llm
"""

import argparse
import logging
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Fakturama Image-to-Cash Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Mode selection
    parser.add_argument(
        "--cli", action="store_true",
        help="Run in CLI mode instead of launching the web UI dashboard",
    )

    # Web UI options
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Dashboard port (default: 5000)")

    # CLI options
    parser.add_argument("--image", type=str, help="Path to the order image (CLI mode)")
    parser.add_argument("--llm", action="store_true", help="Use Gemini Multimodal Vision extraction (default)")
    parser.add_argument("--ocr", action="store_true", help="Use Tesseract OCR extraction (offline)")
    parser.add_argument("--dry-run", action="store_true", help="Skip UI automation, extract + validate only")
    parser.add_argument("--screenshot-dir", default="artifacts/screenshots", help="Screenshot output directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # Logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.cli:
        run_cli(args)
    else:
        run_dashboard(args)


def run_dashboard(args):
    """Launch the web UI dashboard."""
    from src.ui.app import run_dashboard as start_dashboard

    # Generate sample images if they don't exist
    samples_dir = Path("data/samples")
    if not any(samples_dir.glob("*.png")):
        print("Generating sample purchase order images...")
        from scripts.generate_sample_po import generate_samples
        generate_samples(samples_dir)
        print()

    start_dashboard(host=args.host, port=args.port)


def run_cli(args):
    """Run the automation in CLI mode."""
    if not args.image:
        print("Error: --image is required in CLI mode")
        sys.exit(1)

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"Error: Image file not found: {image_path}")
        sys.exit(1)

    # Select extractor
    if args.ocr:
        from src.extractors.ocr_extractor import OCRExtractor
        extractor = OCRExtractor()
        print("Using: Tesseract OCR extraction (offline)")
    else:
        from src.extractors.llm_extractor import LLMExtractor
        extractor = LLMExtractor()
        print("Using: Gemini Multimodal Vision extraction")

    # Create UIA wrapper (only if live automation)
    if args.dry_run:
        uia = None
    else:
        from src.automation.uia_wrapper import UIAWrapper
        uia = UIAWrapper(screenshot_dir=args.screenshot_dir)

    # Create orchestrator
    from src.flow.orchestrator import Orchestrator
    orch = Orchestrator(extractor, uia, dry_run=args.dry_run)

    # Progress callback for CLI
    def on_progress(step, message):
        print(f"  [{step}] {message}")

    orch.set_progress_callback(on_progress)

    print(f"\n{'='*60}")
    print(f"  Image: {image_path}")
    print(f"  Mode: {'Dry Run' if args.dry_run else 'LIVE AUTOMATION'}")
    print(f"{'='*60}\n")

    result = orch.run(str(image_path))

    # Print results
    print(f"\n{'='*60}")
    if result.success:
        print("  ✓ FLOW COMPLETED SUCCESSFULLY")
    else:
        print("  ✕ FLOW STOPPED")
        if result.error:
            print(f"  Error: {result.error}")
    print(f"{'='*60}")

    print(f"\nSteps completed ({len(result.steps_completed)}):")
    for step in result.steps_completed:
        print(f"  ✓ {step}")

    if result.extraction_warnings:
        print(f"\nWarnings ({len(result.extraction_warnings)}):")
        for w in result.extraction_warnings:
            print(f"  ⚠ {w}")

    if result.order_data:
        summary = result.order_data.to_summary_dict()
        print(f"\nOrder Summary:")
        print(f"  Date: {summary['order_date']}")
        print(f"  Reference: {summary['external_reference']}")
        print(f"  Debtor: {summary['debtor']}")
        print(f"  Items: {summary['items_count']}")
        print(f"  Total: €{summary['total_gross']}")
        print(f"  Status: {summary['paid_status']}")

    print()


if __name__ == "__main__":
    main()
