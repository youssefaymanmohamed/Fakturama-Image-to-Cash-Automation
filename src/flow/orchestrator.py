"""
Continuous Order-First Orchestrator.

Implements the complete 5-step end-to-end workflow from the assignment:
  1. Extract image data → Open New Order → Set header fields
  2. Select or create Debtor (with conditional Payment Method creation)
  3. For each item: Select or create Product (with conditional VAT creation)
  4. Complete and save Order → Verify → Create follow-up Invoice
  5. Complete Invoice (payment status) → Save → Final verification

The orchestrator coordinates the FakturamaApp page-object controller
with the extracted OrderData, implementing all conditional branches
and verification checks.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.automation.fakturama_app import FakturamaApp
from src.automation.uia_wrapper import UIAWrapper, StopForReview, ensure_desktop_and_com
from src.extractors.base import BaseExtractor
from src.models.order import DocumentVerification, OrderData, PaidStatus

logger = logging.getLogger(__name__)


@dataclass
class FlowResult:
    """Comprehensive result of the Order-first automation flow."""
    success: bool = False
    order_data: Optional[OrderData] = None
    extraction_warnings: list[str] = field(default_factory=list)
    order_verification: Optional[DocumentVerification] = None
    invoice_verification: Optional[DocumentVerification] = None
    milestones: list[dict] = field(default_factory=list)
    error: Optional[str] = None
    steps_completed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize for UI display."""
        return {
            "success": self.success,
            "error": self.error,
            "steps_completed": self.steps_completed,
            "extraction_warnings": self.extraction_warnings,
            "order_summary": self.order_data.to_summary_dict() if self.order_data else None,
            "order_verification": {
                "all_ok": self.order_verification.all_ok,
                "screenshot": self.order_verification.screenshot_path,
            } if self.order_verification else None,
            "invoice_verification": {
                "all_ok": self.invoice_verification.all_ok,
                "screenshot": self.invoice_verification.screenshot_path,
            } if self.invoice_verification else None,
            "milestones": self.milestones,
        }


class Orchestrator:
    """
    Coordinates the full Image-to-Cash automation flow.

    Usage:
        extractor = LLMExtractor()
        uia = UIAWrapper(screenshot_dir="artifacts/screenshots")
        orch = Orchestrator(extractor, uia)
        result = orch.run("data/samples/purchase_order_01.png")
    """

    def __init__(
        self,
        extractor: BaseExtractor,
        uia: Optional[UIAWrapper] = None,
        dry_run: bool = False,
    ):
        self.extractor = extractor
        self.uia = uia
        self.app = FakturamaApp(uia) if uia else None
        self.dry_run = dry_run
        self._progress_callback = None

    def set_progress_callback(self, callback):
        """Set a callback function(step: str, message: str) for progress updates."""
        self._progress_callback = callback

    def _report(self, step: str, message: str):
        print(f"[{step}] {message}", flush=True)
        logger.info(f"[{step}] {message}")
        if self._progress_callback:
            self._progress_callback(step, message)

    def _complete_step(self, result: FlowResult, description: str) -> None:
        """Record completion and capture a captioned post-action screenshot."""
        result.steps_completed.append(description)
        if not self.dry_run and self.app:
            step = description.split(":", 1)[0]
            self.app._milestone(step, description)

    def run(self, image_path: str | Path, order_data: Optional[OrderData] = None) -> FlowResult:
        """
        Execute the complete Order-first automation flow.

        Args:
            image_path: Path to the purchase order image.
            order_data: Optional pre-extracted OrderData (skips redundant extraction).

        Returns:
            FlowResult with success status, verification results, and milestones.
        """
        result = FlowResult()
        image_path = Path(image_path)

        try:
            # =============================================================
            # STEP 1: Extract and Open New Order
            # =============================================================
            if order_data is None:
                self._report("1.1", "Extracting data from order image...")
                order_data = self.extractor.extract(image_path)
            else:
                self._report("1.1", "Using pre-extracted order data (instant fast-path)")

            result.order_data = order_data

            # Post-extraction validation
            warnings = self.extractor.validate_extraction(order_data)
            result.extraction_warnings = warnings
            if warnings:
                for w in warnings:
                    self._report("1.1", f"⚠ {w}")

            self._report("1.2", f"Extracted {len(order_data.items)} items, "
                         f"debtor: {order_data.debtor.display_name}")
            self._complete_step(result, "1.1-1.2: Data extraction")

            if self.dry_run:
                self._report("DRY-RUN", "Skipping UI automation (dry-run mode)")
                result.success = True
                result.steps_completed.append("DRY-RUN: Complete")
                return result

            # 1.3: Attach to Fakturama and open New Order
            ensure_desktop_and_com()
            self._report("1.3", "Attaching to Fakturama...")
            self.uia.attach_or_launch()
            time.sleep(1.0)

            # Clean slate: dismiss any leftover dialogs from previous failed runs
            self._report("1.3", "Dismissing any leftover dialogs...")
            try:
                import uiautomation as auto
                auto.SendKeys("{Escape}")
                time.sleep(0.3)
            except Exception:
                pass

            self._report("1.3", "Opening New Order...")
            self.app.open_new_order()
            time.sleep(1.0)
            self._complete_step(result, "1.3: New Order opened")

            # 1.5: Set Order Date
            date_str = order_data.order_date.strftime("%d.%m.%Y")
            self.app.set_order_date(date_str)
            self._complete_step(result, "1.5: Order date set")

            # 1.6: Set Cust.Ref
            self.app.set_cust_ref(order_data.external_reference)
            self._complete_step(result, "1.6: Cust.Ref set")

            # 1.7: Set price mode
            self.app.set_price_mode_net()
            self._complete_step(result, "1.7: Price mode set to Net")

            # =============================================================
            # STEP 2: Select or Create Debtor
            # =============================================================
            self._report("2.1", "Searching for existing Debtor...")
            debtor_found = self.app.search_and_select_debtor(order_data.debtor)

            if debtor_found:
                self._report("2.4", "Existing Debtor selected and verified")
                self._complete_step(result, "2.1-2.4: Existing Debtor selected")
            else:
                self._report("2.5", "Creating new Debtor...")
                self.app.create_debtor(order_data.debtor)
                self._complete_step(result, "2.5-2.11: New Debtor created")

                self._report("2.12", "Re-selecting Debtor in Order...")
                self.app.reselect_debtor_after_creation(order_data.debtor)
                self._complete_step(result, "2.12-2.13: Debtor re-selected")

            # Fakturama applies the Debtor's stored Gross/Net preference when
            # the address is selected, so the document rule must be enforced
            # after either debtor path completes.
            self.app.set_price_mode_net(force=True)
            self._complete_step(result, "2.14: Price mode re-verified as Net")

            # =============================================================
            # STEP 3: Select or Create each Product
            # =============================================================
            for idx, item in enumerate(order_data.items):
                item_label = f"Item {idx+1}/{len(order_data.items)}: {item.sku}"
                self._report("3.2", f"Searching for Product: {item_label}")

                product_found = self.app.search_and_select_product(item.sku)

                if not product_found:
                    # 3.4-3.6: Ensure VAT rate exists
                    self._report("3.4", f"Ensuring VAT: {item.vat_name}")
                    self.app.ensure_vat_rate(item.vat_name, item.vat_percent)

                    # 3.7-3.11: Create Product
                    self._report("3.7", f"Creating Product: {item.sku}")
                    self.app.create_product(item)

                    # 3.12: Re-select in Order — retry up to 3 times with increasing delays
                    self._report("3.12", f"Re-selecting Product: {item.sku}")
                    product_found = False
                    for attempt in range(1, 4):
                        wait = attempt * 1.5
                        self._report("3.12", f"Selection attempt {attempt}/3 (waiting {wait:.0f}s for Fakturama to index)")
                        time.sleep(wait)
                        product_found = self.app.search_and_select_product(item.sku)
                        if product_found:
                            break

                    if not product_found:
                        raise StopForReview(
                            f"Newly created Product '{item.sku}' not found in selector after 3 attempts. "
                            "Manual review required."
                        )

                # 3.13-3.16: Set line item details
                # Inserting a Product can reset Fakturama's internal pricing
                # mode without refreshing the visible ComboBox. Force a real
                # Gross -> Net transition before writing the transaction price.
                self.app.set_price_mode_net(force=True)
                self.app.set_order_line(item, row_index=idx)
                self._complete_step(result, f"3: Product {item.sku} added")

            # =============================================================
            # STEP 4: Complete and Save the Order
            # =============================================================
            # Product selection can reapply the Product/Debtor Gross setting.
            # Reassert the transaction's Net mode at the last possible point
            # and gate Save on the displayed gross total.
            self.app.set_price_mode_net(force=True)
            if not self.app._verify_order_total(order_data.total_gross):
                raise StopForReview(
                    f"Order total does not match extracted gross total "
                    f"{order_data.total_gross}; refusing to save."
                )
            self._complete_step(result, "4.3: Net mode and gross total verified")

            self._report("4.4", "Saving Order...")
            self.app.save_current()
            self._complete_step(result, "4.4: Order saved")

            # 4.5: Verify in Documents
            self._report("4.5", "Verifying saved Order...")
            result.order_verification = self.app.verify_order_in_documents(order_data)
            if not result.order_verification.all_ok:
                raise StopForReview(
                    "Saved Order failed Documents read-back; refusing to create an Invoice."
                )
            self._complete_step(result, "4.5: Order verified in Documents")

            # 4.6: Create follow-up Invoice
            self._report("4.6", "Creating follow-up Invoice...")
            self.app.create_followup_invoice()
            self._complete_step(result, "4.6: Follow-up Invoice created")

            # =============================================================
            # STEP 5: Complete and Verify Invoice
            # =============================================================
            is_paid = order_data.paid_status == PaidStatus.PAID
            pay_date = (order_data.payment_date.strftime("%d.%m.%Y")
                       if order_data.payment_date else None)
            total_str = str(order_data.total_gross) if is_paid else None

            self._report("5.2", "Setting Invoice payment...")
            self.app.set_invoice_payment(
                payment_method=order_data.debtor.payment_method,
                is_paid=is_paid,
                payment_date=pay_date,
                total=total_str,
            )
            self._complete_step(result, "5.2-5.3: Invoice payment set")

            # 5.4: Save Invoice
            self._report("5.4", "Saving Invoice...")
            self.app.save_current()
            self._complete_step(result, "5.4: Invoice saved")

            # 5.5: Final verification
            self._report("5.5", "Final verification...")
            result.invoice_verification = self.app.verify_invoice_in_documents(order_data)
            if not result.invoice_verification.all_ok:
                raise StopForReview("Saved Invoice failed Documents read-back.")
            if is_paid and not result.invoice_verification.paid_status_ok:
                raise StopForReview("Saved Invoice payment fields failed read-back verification.")
            self._complete_step(result, "5.5: Final verification complete")

            # Done!
            result.success = True
            result.milestones = self.app.milestones
            self._report("DONE", "✓ Image-to-Cash flow completed successfully!")

        except StopForReview as e:
            result.error = f"STOPPED FOR REVIEW: {e}"
            result.milestones = self.app.milestones if self.app else []
            self._report("STOP", str(e))

        except Exception as e:
            result.error = f"ERROR: {e}"
            result.milestones = self.app.milestones if self.app else []
            self._report("ERROR", str(e))
            logger.exception("Orchestrator error")

        return result
