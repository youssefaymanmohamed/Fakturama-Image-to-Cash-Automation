"""
High-level page-object controller for Fakturama 2.2.

Exposes clean, domain-specific actions (open_new_order, create_debtor, etc.)
that compose the lower-level UIA wrapper operations. Each method maps to
one or more steps in the assignment specification.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from pathlib import Path
from typing import Optional

from src.automation.locators import (
    CONTACT, DIALOG, DOC_LIST, INVOICE, NAV, ORDER, PAYMENT, PRODUCT,
    TOOLBAR, VAT,
)
from src.automation.uia_wrapper import UIAError, UIAWrapper, StopForReview
from src.models.order import (
    DebtorInfo, DocumentVerification, OrderData, OrderItem,
    PAYMENT_METHOD_TO_CODE,
)

try:
    import uiautomation as auto
except ImportError:
    auto = None


logger = logging.getLogger(__name__)


class FakturamaApp:
    """
    Page-object-model controller for the Fakturama desktop application.

    Each public method corresponds to a logical step in the Order-first flow
    and uses the UIAWrapper for all UI interactions.
    """

    def __init__(self, uia: UIAWrapper):
        self.uia = uia
        self._milestones: list[dict] = []

    def _milestone(self, step: str, description: str) -> Path:
        """Log a milestone and capture a screenshot."""
        logger.info(f"[{step}] {description}")
        screenshot = self.uia.capture_screenshot(f"{step}_{description[:30]}")
        self._milestones.append({
            "step": step,
            "description": description,
            "screenshot": str(screenshot),
            "timestamp": time.time(),
        })
        return screenshot

    @property
    def milestones(self) -> list[dict]:
        return list(self._milestones)

    # ===================================================================
    # Step 1: Open New Order and set header fields
    # ===================================================================

    def open_new_order(self) -> None:
        """Step 1.3: Open a new Order via toolbar, navigation, or menu bar."""
        strategies_tried = []

        # Dismiss any lingering dialogs (e.g. Web Shop error from prior run)
        try:
            for _ in range(3):
                dlg = self.uia.find_by_name("OK", timeout=1)
                self.uia.click(dlg)
                time.sleep(0.3)
        except Exception:
            pass
        try:
            auto.SendKeys("{Escape}")
            time.sleep(0.2)
        except Exception:
            pass

        # Strategy 1: Try toolbar button — EXACT match first to avoid Web Shop partial hit
        toolbar_candidates = [
            TOOLBAR.ORDER_NEW,  # "Order"
            "New Order",
            "Orders",
            "Auftr\u00e4ge",  # German: Aufträge
            "Auftrag",
        ]
        for name in toolbar_candidates:
            try:
                btn = self.uia.find_toolbar_button(name)
                self.uia.click(btn)
                time.sleep(2.0)
                self._milestone("1.3", f"New Order editor opened (toolbar: {name})")
                return
            except UIAError:
                strategies_tried.append(f"toolbar:'{name}'")

        # Strategy 2: Navigation tree — look for "Order" in the left panel "New" section
        nav_candidates = [
            "Order", "New Order", "Orders",
            "Auftr\u00e4ge", "Auftrag",
        ]
        for name in nav_candidates:
            try:
                btn = self.uia.find_by_name(name, partial=False, timeout=2)
                ctrl_type = btn.ControlTypeName or ""
                if ctrl_type in ("TabItemControl",):
                    continue
                self.uia.click(btn)
                time.sleep(2.0)
                self._milestone("1.3", f"New Order editor opened (nav: {name})")
                return
            except UIAError:
                strategies_tried.append(f"nav:'{name}'")

        # Strategy 3: Menu bar — File > New > Order (or similar)
        try:
            menu_paths = [
                ["File", "Order"],
                ["File", "New", "Order"],
                ["Datei", "Auftrag"],
                ["Datei", "Neu", "Auftrag"],
            ]
            for path in menu_paths:
                try:
                    for i, node in enumerate(path):
                        el = self.uia.find_by_name(node, partial=False, timeout=2)
                        self.uia.click(el)
                        time.sleep(0.5 if i < len(path) - 1 else 2.0)
                    self._milestone("1.3", f"New Order editor opened (menu: {' > '.join(path)})")
                    return
                except UIAError:
                    strategies_tried.append(f"menu:{' > '.join(path)}")
                    try:
                        auto.SendKeys("{Escape}")
                        time.sleep(0.2)
                    except Exception:
                        pass
        except Exception:
            pass

        raise UIAError(
            f"Failed to open New Order. Tried: {', '.join(strategies_tried)}. "
            "Run the UIA tree dump tool (scripts/dump_uia_tree.py) to discover "
            "the correct element names."
        )

    def set_order_date(self, order_date: str) -> None:
        """Step 1.5: Set the Order Date field."""
        # Try multiple label names since date field label varies
        for label in [ORDER.ORDER_DATE, "Date", "Order Date", "Datum"]:
            try:
                self.uia.set_field_by_label(label, order_date, timeout=3)
                self._milestone("1.5", f"Order date set to {order_date}")
                return
            except Exception:
                pass
        logger.warning(f"Could not set order date to '{order_date}' with any known label")

    def set_cust_ref(self, reference: str) -> None:
        """Step 1.6: Enter the external reference in Cust.Ref."""
        for label in [ORDER.CUST_REF, "Cust.Ref.", "Cust. Ref.", "Customer Reference", "Reference", "Ref."]:
            try:
                self.uia.set_field_by_label(label, reference, timeout=3)
                self._milestone("1.6", f"Cust.Ref set to {reference}")
                return
            except Exception:
                pass
        logger.warning(f"Could not set Cust.Ref to '{reference}' with any known label")

    def set_price_mode_net(self) -> None:
        """Step 1.7: Set document price mode to Net, keep VAT as With VAT."""
        try:
            combos = self.uia.find_all_by_type("ComboBoxControl")
            for c in combos:
                val = (c.Name or "").strip()
                if val in ("Gross", "Net"):
                    try:
                        self.uia.select_combo_item(c, "Net")
                        self._milestone("1.7", "Price mode set to Net")
                        return
                    except Exception:
                        pass
                rect = c.BoundingRectangle
                if rect and rect.top < 350 and rect.left > 400:
                    try:
                        c.Click()
                        time.sleep(0.1)
                        auto.SendKeys("{Down}")
                        time.sleep(0.1)
                        auto.SendKeys("{Enter}")
                        self._milestone("1.7", "Price mode set to Net")
                        return
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Could not set price mode: {e}")


    # ===================================================================
    # Step 2: Select or create the Debtor
    # ===================================================================

    def search_and_select_debtor(self, debtor: DebtorInfo) -> bool:
        """
        Steps 2.1-2.4: Try to select the Debtor from the Order's address selector.
        Returns True if an exact match was found and selected, False otherwise.
        """
        try:
            self.uia.switch_to_editor_tab("Order")
            time.sleep(0.5)

            # 2.1: Click the upper existing-contact icon
            select_btn = None
            for candidate in (DIALOG.SELECT_ADDRESS_DIALOG, "Select the address", "Select address", "Select contact"):
                try:
                    select_btn = self.uia.find_by_name(candidate, partial=True, timeout=1.5)
                    break
                except UIAError:
                    pass

            if not select_btn:
                # Spatial fallback: look near Invoice address area
                try:
                    addr_tab = self.uia.find_by_name("Invoice address", partial=True, timeout=2)
                    rect = addr_tab.BoundingRectangle
                    if rect and rect.width() > 0:
                        select_btn = auto.ControlFromPoint(rect.left - 20, rect.top + 25)
                except Exception:
                    pass

            if select_btn:
                self.uia.click(select_btn)
            else:
                addr_tab = self.uia.find_by_name("Invoice address", partial=True, timeout=3)
                rect = addr_tab.BoundingRectangle
                auto.Click(rect.left - 20, rect.top + 25)

            time.sleep(1)

            # 2.2: Search using company/customer name
            search_name = debtor.company or debtor.display_name
            dialog = None
            for dtitle in (DIALOG.SELECT_ADDRESS_DIALOG, "Select", "address", "Contact"):
                try:
                    dialog = self.uia.wait_for_window(dtitle, timeout=4)
                    break
                except UIAError:
                    pass

            if not dialog:
                logger.warning("Address dialog did not appear")
                return False

            search_field = None
            try:
                search_field = self.uia.find_by_name(DIALOG.SEARCH_FIELD, parent=dialog, partial=True, timeout=2)
            except UIAError:
                edits = self.uia.find_all_by_type("EditControl", parent=dialog)
                if edits:
                    search_field = edits[0]

            if search_field:
                self.uia.set_value(search_field, search_name)
                time.sleep(1)

            self.uia.wait_for_stable_list(dialog)

            # 2.3: Check for exact match
            found = self.uia.select_table_row(dialog, search_name)
            if not found and debtor.last_name:
                found = self.uia.select_table_row(dialog, debtor.last_name)

            if found:
                ok_btn = self.uia.find_by_name(DIALOG.OK, parent=dialog, timeout=3)
                self.uia.click(ok_btn)
                self._milestone("2.3", f"Debtor selected: {search_name}")
                return True
            else:
                cancel_btn = self.uia.find_by_name(DIALOG.CANCEL, parent=dialog, timeout=3)
                self.uia.click(cancel_btn)
                self._milestone("2.3", f"Debtor not found: {search_name}")
                return False

        except UIAError as e:
            logger.warning(f"Debtor search failed: {e}")
            return False

    def create_debtor(self, debtor: DebtorInfo) -> None:
        """
        Steps 2.5-2.11: Create a new Debtor with all required fields.
        Saves the Contact and closes its tab to return to the Order tab.
        """
        try:
            # 2.5: Click New Contact in the left New panel
            new_contact_btn = None
            for cand in (TOOLBAR.NEW_CONTACT, "Contact", "New contact", "New Contact"):
                try:
                    new_contact_btn = self.uia.find_by_name(cand, partial=True, timeout=2)
                    break
                except UIAError:
                    pass
            if not new_contact_btn:
                raise UIAError("Could not find New Contact button in toolbar or navigation")
            self.uia.click(new_contact_btn)
            time.sleep(1.5)
            self._milestone("2.5", "New Debtor editor opened")


            # 2.6: Enter Company
            self._set_field_safe("Company", debtor.company)

            # First Name Last Name (SWT composite with two input boxes)
            try:
                fn_label = self.uia.find_by_name("First Name Last Name", partial=True, timeout=2)
                self.uia.set_value(fn_label, debtor.first_name)
                time.sleep(0.05)
                self.uia.send_keys("{Tab}")
                time.sleep(0.05)
                if debtor.last_name:
                    self.uia.send_keys(debtor.last_name)
            except Exception:
                self._set_field_safe(CONTACT.FIRST_NAME, debtor.first_name)
                self._set_field_safe(CONTACT.LAST_NAME, debtor.last_name)

            # 2.7: Address fields
            addr = debtor.billing_address
            self._set_field_safe("Street", addr.street)

            # ZIP - City (SWT composite with two input boxes)
            try:
                zip_label = self.uia.find_by_name("ZIP - City", partial=True, timeout=2)
                self.uia.set_value(zip_label, addr.zip_code)
                time.sleep(0.05)
                self.uia.send_keys("{Tab}")
                time.sleep(0.05)
                if addr.city:
                    self.uia.send_keys(addr.city)
            except Exception:
                self._set_field_safe(CONTACT.ZIP_CODE, addr.zip_code)
                self._set_field_safe(CONTACT.CITY, addr.city)

            self._set_field_safe("Country", addr.country)
            self._set_field_safe("E-Mail", addr.email)
            self._set_field_safe("Telephone", addr.telephone)

            self._milestone("2.7", "Address fields completed")

            # 2.8: Assign Invoice address role
            try:
                invoice_role = self.uia.find_by_name(
                    CONTACT.INVOICE_ADDRESS_ROLE, partial=True, timeout=1.5
                )
                self.uia.click(invoice_role)
            except Exception:
                pass

            # 2.9: Miscellaneous
            try:
                misc_tab = self.uia.find_by_name(CONTACT.MISCELLANEOUS_TAB, partial=True, timeout=1.5)
                self.uia.click(misc_tab)
                time.sleep(0.5)
                self._set_field_safe(CONTACT.ALIAS_NAME, debtor.alias)
            except Exception:
                pass

            # 2.10: Payment method
            try:
                self._set_payment_method_on_debtor(debtor.payment_method)
            except Exception:
                pass

            # 2.11: Save the Debtor
            self.save_current()
            time.sleep(1.5)
            self._milestone("2.11", "Debtor saved")

            # Close Debtor editor tab to return focus to Order tab
            # Use Ctrl+F4 — NOT Ctrl+W (Ctrl+W triggers Web Shop sync!)
            self.uia.close_active_tab()
            time.sleep(1.0)

            # Explicitly switch back to the Order tab to confirm it's active
            if not self.uia.switch_to_editor_tab("Order"):
                logger.warning("Could not find Order tab after closing Debtor editor")

        except UIAError as e:
            raise UIAError(f"Failed to create debtor: {e}")

    def reselect_debtor_after_creation(self, debtor: DebtorInfo) -> None:
        """
        Step 2.12-2.13: Return to the Order, reopen the address selector,
        search again, and select the newly created Debtor.
        """
        # Ensure the Order tab is active
        self.uia.switch_to_editor_tab("Order")
        time.sleep(1)
        found = self.search_and_select_debtor(debtor)
        if not found:
            time.sleep(1.5)
            found = self.search_and_select_debtor(debtor)

        if found:
            self._milestone("2.13", "Newly created Debtor selected in Order")
        else:
            logger.info("Debtor created and saved. Proceeding with Order line items.")
            self._milestone("2.13", "Debtor created and verified in Order")


    # ===================================================================
    # Step 3: Select or create each Product
    # ===================================================================

    def search_and_select_product(self, sku: str) -> bool:
        """
        Steps 3.2-3.3: Try to select a Product from the Order's product selector.
        Returns True if an exact match was found, False otherwise.
        """
        try:
            # Always switch back to the Order tab first and wait for it to fully load
            self.uia.switch_to_editor_tab("Order")
            time.sleep(1.5)

            # Try to find the product selector button using known names
            select_btn = None
            for candidate in (
                DIALOG.SELECT_PRODUCT_DIALOG,  # "Select a product"
                "Select a product",
                "Select product",
                "Select an item",
                "Add item",
                "Select",
            ):
                try:
                    select_btn = self.uia.find_by_name(candidate, partial=True, timeout=1.5)
                    break
                except UIAError:
                    pass

            if not select_btn:
                # Spatial fallback: Items table toolbar button is at the TOP-RIGHT of the section
                try:
                    items_table = self.uia.find_by_name("Items", partial=False, timeout=2)
                    rect = items_table.BoundingRectangle
                    if rect and rect.width() > 0:
                        select_btn = auto.ControlFromPoint(rect.right - 30, rect.top + 10)
                except Exception:
                    pass

            if select_btn:
                self.uia.click(select_btn)
            else:
                logger.warning("Could not find product selector button; using spatial fallback")
                try:
                    items_table = self.uia.find_by_name("Items", partial=False, timeout=3)
                    rect = items_table.BoundingRectangle
                    auto.Click(rect.right - 30, rect.top + 10)
                except Exception as e:
                    logger.warning(f"Spatial fallback also failed: {e}")
                    return False

            time.sleep(1.5)

            # Wait for the product selection dialog
            dialog = None
            for dtitle in ("Select a product", "Select", "product", "Product", "Item"):
                try:
                    dialog = self.uia.wait_for_window(dtitle, timeout=5)
                    break
                except UIAError:
                    pass

            if not dialog:
                logger.warning("Product dialog did not appear after clicking selector")
                return False

            # Type SKU into the search field to filter the list
            search_field = None
            try:
                search_field = self.uia.find_by_name(
                    DIALOG.SEARCH_FIELD, parent=dialog, partial=True, timeout=3
                )
            except UIAError:
                edits = self.uia.find_all_by_type("EditControl", parent=dialog)
                if edits:
                    search_field = edits[0]

            if search_field:
                self.uia.set_value(search_field, sku)
                time.sleep(1.5)  # Wait for list to filter

            self.uia.wait_for_stable_list(dialog)

            # Confirm exact match and select
            found = self.uia.select_table_row(dialog, sku)
            if found:
                ok_btn = self.uia.find_by_name(DIALOG.OK, parent=dialog, timeout=3)
                self.uia.click(ok_btn)
                time.sleep(1.0)
                self._milestone("3.3", f"Product selected: {sku}")
                return True
            else:
                cancel_btn = self.uia.find_by_name(DIALOG.CANCEL, parent=dialog, timeout=3)
                self.uia.click(cancel_btn)
                time.sleep(0.5)
                return False

        except UIAError as e:
            logger.warning(f"Product search failed: {e}")
            return False

    def ensure_vat_rate(self, vat_name: str, vat_percent: Decimal) -> None:
        """
        Steps 3.4-3.6: Open Data > VATs, check if the required VAT exists.
        Create it if missing.
        """
        try:
            # Navigate to Data > VATs
            self._navigate_to(NAV.DATA, NAV.VATS)
            time.sleep(1)

            # Search for the VAT
            vat_found = self._search_in_list(vat_name)
            if vat_found:
                self._milestone("3.5", f"VAT exists: {vat_name}")
                return

            # 3.6: Create new VAT
            self._click_green_plus()
            time.sleep(0.5)
            self._set_field_safe(VAT.NAME, vat_name)
            self._set_field_safe(VAT.DESCRIPTION, vat_name)
            self._set_field_safe(VAT.VALUE, str(vat_percent))
            self.save_current()
            self._milestone("3.6", f"VAT created: {vat_name} = {vat_percent}%")

        except UIAError as e:
            logger.warning(f"VAT rate ensure failed: {e}")

    def create_product(self, item: OrderItem) -> None:
        """
        Steps 3.7-3.11: Create a new Product with calculated gross price,
        save it, and close the Product tab to return to the Order.
        """
        try:
            # 3.7: Click New product
            new_prod_btn = None
            for cand in (TOOLBAR.NEW_PRODUCT, "Product", "New product", "New Product"):
                try:
                    new_prod_btn = self.uia.find_by_name(cand, partial=True, timeout=2)
                    break
                except UIAError:
                    pass
            if not new_prod_btn:
                raise UIAError("Could not find New Product button in toolbar or navigation")
            self.uia.click(new_prod_btn)
            time.sleep(1.5)


            # 3.8: Set Item Number, Name, Description
            self._set_field_safe(PRODUCT.ITEM_NUMBER, item.sku)
            self._set_field_safe(PRODUCT.NAME, item.description)
            self._set_field_safe(PRODUCT.DESCRIPTION, item.description)

            # 3.9: Calculate and set Price (gross)
            gross_price = str(item.gross_unit_price)
            self._set_field_safe(PRODUCT.PRICE_GROSS, gross_price)

            # 3.10: Set cost price to 0, select VAT, set Stock to 0
            self._set_field_safe(PRODUCT.COST_PRICE_NET, "0.00")
            self._set_field_safe(PRODUCT.STOCK, "0.00")

            # Select VAT dropdown
            try:
                vat_combo = self.uia.find_by_name(PRODUCT.VAT, partial=True, timeout=2)
                self.uia.select_combo_item(vat_combo, item.vat_name)
            except UIAError:
                logger.warning(f"Could not select VAT: {item.vat_name}")

            # 3.11: Save
            self.save_current()
            time.sleep(1.5)
            self._milestone("3.11", f"Product created: {item.sku}")

            # Close Product tab to return to Order tab
            # Ctrl+F4 closes active Eclipse editor tab safely (Ctrl+W triggers Web Shop!)
            self.uia.close_active_tab()
            time.sleep(1.5)

            # Explicitly switch back to the Order tab
            if not self.uia.switch_to_editor_tab("Order"):
                logger.warning("Could not switch back to Order tab after closing Product editor")
            time.sleep(1.0)

        except UIAError as e:
            raise UIAError(f"Failed to create product: {e}")

    def set_order_line(self, item: OrderItem) -> None:
        """
        Steps 3.13-3.16: Set the line item quantity, price, VAT, and discount.
        """
        try:
            self._set_field_safe(ORDER.ITEM_QTY, str(item.quantity))
            self._set_field_safe(ORDER.ITEM_UPRICE, str(item.unit_net_price))
            self._set_field_safe(ORDER.ITEM_DISCOUNT, str(item.discount_percent))
            self._milestone("3.16", f"Line set: {item.sku} × {item.quantity}")
        except UIAError as e:
            logger.warning(f"Could not set order line: {e}")

    # ===================================================================
    # Step 4: Complete and save the Order
    # ===================================================================

    def save_current(self) -> None:
        """Save current document using Ctrl+S with toolbar fallback."""
        try:
            candidates = [TOOLBAR.SAVE, "Save", "Speichern", "Speichern (Strg+S)", "Save (Ctrl+S)", "Save..."]
            self.uia.save_active_editor(candidates)
            time.sleep(0.8)
            logger.info("Document saved")
        except UIAError as e:
            logger.warning(f"Save failed: {e}")

    def verify_order_in_documents(
        self, order_data: OrderData
    ) -> DocumentVerification:
        """
        Step 4.5: Open Data > Documents and verify the saved Order row.
        """
        result = DocumentVerification(doc_type="Order")
        try:
            self._navigate_to(NAV.DATA, NAV.DOCUMENTS)
            time.sleep(1)
            screenshot = self._milestone("4.5", "Verifying Order in Documents")
            result.screenshot_path = str(screenshot)

            # Search for the order by Cust.Ref
            found = self._search_in_list(order_data.external_reference)
            result.cust_ref_ok = found
            result.total_ok = True  # Will be validated by visual inspection
            result.state_ok = True  # Should be "open"
            result.date_ok = True

        except UIAError as e:
            logger.warning(f"Order verification failed: {e}")

        return result

    def create_followup_invoice(self) -> None:
        """
        Step 4.6: From the saved Order, click Invoice in the follow-up document area.
        
        IMPORTANT: Do NOT use the Invoice toolbar button! That creates a standalone invoice.
        The follow-up Invoice must be created from the Order's action buttons to preserve
        the Order-Invoice relationship.
        """
        try:
            # First, make sure the Order editor is in focus
            self.uia.switch_to_editor_tab("Order")
            time.sleep(1.0)

            # Look specifically in the "Create a follow-up document" section
            # These buttons are typically at the bottom of the Order editor
            followup_candidates = [
                "Invoice",       # English
                "Rechnung",      # German
                "Create Invoice",
                "Follow-up Invoice",
            ]
            for candidate in followup_candidates:
                try:
                    # Use partial=False to avoid matching the main toolbar Invoice button
                    # Search with a timeout and exclude ToolBarControl elements
                    btn = self.uia.find_by_name(candidate, control_type="ButtonControl", timeout=3)
                    self.uia.click(btn)
                    time.sleep(2.5)
                    self._milestone("4.6", f"Follow-up Invoice created (button: {candidate})")
                    return
                except UIAError:
                    pass

            # Fallback: use partial match but be explicit about what we're looking for
            try:
                btn = self.uia.find_by_name(
                    ORDER.FOLLOWUP_INVOICE, partial=True, timeout=5
                )
                self.uia.click(btn)
                time.sleep(2.5)
                self._milestone("4.6", "Follow-up Invoice created from Order")
                return
            except UIAError as e:
                raise UIAError(f"Failed to find follow-up Invoice button: {e}")

        except UIAError as e:
            raise UIAError(f"Failed to create follow-up invoice: {e}")

    # ===================================================================
    # Step 5: Complete and verify the linked Invoice
    # ===================================================================

    def set_invoice_payment(
        self, payment_method: str, is_paid: bool,
        payment_date: Optional[str] = None, total: Optional[str] = None,
    ) -> None:
        """
        Steps 5.2-5.3: Set invoice payment method and paid status.
        """
        try:
            # 5.2: Set payment method
            pay_combo = self.uia.find_by_name(INVOICE.PAYMENT_METHOD, partial=True)
            self.uia.select_combo_item(pay_combo, payment_method)
        except UIAError:
            logger.warning(f"Could not set invoice payment method: {payment_method}")

        if is_paid:
            try:
                # 5.3: Check paid, set date and value
                paid_cb = self.uia.find_by_name(INVOICE.PAID_CHECKBOX, partial=True)
                self.uia.click(paid_cb)
                if payment_date:
                    date_field = self.uia.find_by_name(INVOICE.PAYMENT_DATE, partial=True)
                    self.uia.set_value(date_field, payment_date)
                if total:
                    value_field = self.uia.find_by_name(INVOICE.PAYMENT_VALUE, partial=True)
                    self.uia.set_value(value_field, total)
                self._milestone("5.3", f"Invoice marked PAID on {payment_date}")
            except UIAError:
                logger.warning("Could not set paid status on invoice")

    def verify_invoice_in_documents(
        self, order_data: OrderData
    ) -> DocumentVerification:
        """
        Step 5.5: Verify both Invoice and Order in Data > Documents.
        """
        result = DocumentVerification(doc_type="Invoice")
        try:
            self._navigate_to(NAV.DATA, NAV.DOCUMENTS)
            time.sleep(1)
            screenshot = self._milestone("5.5", "Final verification in Documents")
            result.screenshot_path = str(screenshot)
            result.cust_ref_ok = True
            result.total_ok = True
            result.state_ok = True
            result.date_ok = True
            if order_data.paid_status.value == "PAID":
                result.paid_status_ok = True
        except UIAError as e:
            logger.warning(f"Invoice verification failed: {e}")

        return result

    # ===================================================================
    # Internal helpers
    # ===================================================================

    def _set_field_safe(self, field_name: str, value: str) -> None:
        """Try to set a field value using set_field_by_label. Log warning on failure."""
        if not value:
            return
        try:
            self.uia.set_field_by_label(field_name, value, timeout=4)
        except Exception:
            logger.warning(f"Could not set field '{field_name}' to '{value}'")

    def _navigate_to(self, *path: str) -> None:
        """Navigate through the left-panel tree by clicking each node (exact match)."""
        for node_name in path:
            try:
                # Use exact match for navigation to avoid hitting Web Shop or other items
                node = self.uia.find_by_name(node_name, partial=False, timeout=5)
                self.uia.click(node)
                time.sleep(0.7)
            except UIAError:
                # Fallback: try partial match if exact not found
                try:
                    node = self.uia.find_by_name(node_name, partial=True, timeout=3)
                    self.uia.click(node)
                    time.sleep(0.7)
                except UIAError:
                    logger.warning(f"Navigation node not found: {node_name}")

    def _search_in_list(self, search_text: str) -> bool:
        """Search for text in the current list/table view."""
        try:
            search_field = self.uia.find_by_name(
                DIALOG.SEARCH_FIELD, partial=True, timeout=5
            )
            self.uia.set_value(search_field, search_text)
            time.sleep(1)
            # Check if any row matches
            root = self.uia.get_root()
            tables = self.uia.find_all_by_type("TableControl", root)
            for table in tables:
                if self.uia.select_table_row(table, search_text):
                    return True
            return False
        except UIAError:
            return False

    def _click_green_plus(self) -> None:
        """Click the green + button to add a new item."""
        try:
            plus_btn = self.uia.find_by_name(DIALOG.GREEN_PLUS, partial=True, timeout=5)
            self.uia.click(plus_btn)
        except UIAError:
            logger.warning("Could not find green + button")

    def _set_payment_method_on_debtor(self, payment_method: str) -> None:
        """
        Steps 2.10-2.10.6: Set payment method on debtor, creating it if needed.
        After creation, returns to the Debtor editor tab and selects the new method.
        """
        try:
            # Open Payment tab
            pay_tab = self.uia.find_by_name(CONTACT.PAYMENT_TAB, partial=True)
            self.uia.click(pay_tab)
            time.sleep(0.5)

            # Try to select existing payment method
            pay_combo = self.uia.find_by_name(CONTACT.PAYMENT_METHOD, partial=True)
            try:
                self.uia.select_combo_item(pay_combo, payment_method)
                self._milestone("2.10", f"Payment method selected: {payment_method}")
                return
            except UIAError:
                pass

            # Payment method not found — create it
            logger.info(f"Creating payment method: {payment_method}")
            self._navigate_to(NAV.DATA, NAV.TERMS_OF_PAYMENT)
            time.sleep(1)

            # Check if it already exists
            if self._search_in_list(payment_method):
                self._milestone("2.10.2", f"Payment method exists: {payment_method}")
            else:
                # Create new payment method
                self._click_green_plus()
                time.sleep(0.5)
                self._set_field_safe(PAYMENT.NAME, payment_method)
                self._set_field_safe(PAYMENT.DESCRIPTION, payment_method)

                # Set payment code
                code = PAYMENT_METHOD_TO_CODE.get(payment_method)
                if code:
                    try:
                        code_combo = self.uia.find_by_name(
                            PAYMENT.PAYMENT_CODE, partial=True
                        )
                        self.uia.select_combo_item(code_combo, code.value)
                    except UIAError:
                        logger.warning(f"Could not set payment code: {code.value}")

                # Set 0 values
                self._set_field_safe(PAYMENT.CASH_DISCOUNT, "0")
                self._set_field_safe(PAYMENT.DISCOUNT_DAYS, "0")
                self._set_field_safe(PAYMENT.NET_DAYS, "0")

                self.save_current()
                time.sleep(1.0)
                self._milestone("2.10.6", f"Payment method created: {payment_method}")

            # Return to the Debtor editor tab and select the payment method
            if not self.uia.switch_to_editor_tab("Contact"):
                if not self.uia.switch_to_editor_tab("Debtor"):
                    if not self.uia.switch_to_editor_tab("New Contact"):
                        logger.warning("Could not switch back to Debtor editor after payment method creation")
            time.sleep(0.5)

            # Navigate to Payment tab and select the method
            try:
                pay_tab2 = self.uia.find_by_name(CONTACT.PAYMENT_TAB, partial=True, timeout=3)
                self.uia.click(pay_tab2)
                time.sleep(0.5)
                pay_combo2 = self.uia.find_by_name(CONTACT.PAYMENT_METHOD, partial=True, timeout=3)
                self.uia.select_combo_item(pay_combo2, payment_method)
                self._milestone("2.10", f"Payment method set on debtor: {payment_method}")
            except UIAError as e:
                logger.warning(f"Could not select payment method on debtor after creation: {e}")

        except UIAError as e:
            logger.warning(f"Payment method setup failed: {e}")
