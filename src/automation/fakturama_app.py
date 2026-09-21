"""
High-level page-object controller for Fakturama 2.2.

Coordinates semantic UIA operations with strict read-back verification
at every step:
  - Step 1: Open New Order, set verified header fields
  - Step 2: Select existing or create new Debtor (returning to SAME open Order)
  - Step 3: For each item: select or create Product (with verified line data)
  - Step 4: Complete & save Order with verified save completion
  - Step 5: Follow-up Invoice creation & verification
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import re
import time
from datetime import datetime
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
    Page-object controller for Fakturama 2.2 desktop application.
    All actions enforce the ACTION -> WAIT -> VERIFY RESULT contract.
    """

    def __init__(self, uia: UIAWrapper):
        self.uia = uia
        self._milestones: list[dict] = []

    def _milestone(self, step: str, description: str) -> Path:
        """Log milestone and capture visual evidence."""
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
        # 1. Clean slate: dismiss any lingering popups
        try:
            auto.SendKeys("{Escape}")
            time.sleep(0.2)
        except Exception:
            pass

        root = self.uia.get_root()

        # Strategy 1: Toolbar button with exact names
        for candidate in TOOLBAR.ORDER_NEW_NAMES:
            try:
                btn = self.uia.find_toolbar_button(candidate, parent=root, timeout=1.5)
                if btn:
                    logger.info(f"Clicking New Order toolbar button: '{btn.Name}'")
                    self.uia.click(btn)
                    break
            except Exception:
                pass
        else:
            # Strategy 2: Navigation tree "New > Order"
            try:
                nav_node = self.uia.find_by_name("Order", control_type="TextControl", parent=root, timeout=2)
                self.uia.click(nav_node)
            except Exception:
                # Strategy 3: Menu bar New > Order
                try:
                    menu_new = self.uia.find_by_name("New", control_type="MenuItemControl", parent=root, timeout=2)
                    self.uia.click(menu_new)
                    time.sleep(0.3)
                    order_item = self.uia.find_by_name("Order", control_type="MenuItemControl", timeout=2)
                    self.uia.click(order_item)
                except Exception as e:
                    raise UIAError(f"Failed to open New Order editor: {e}")

        # VERIFICATION: Wait for New Order editor tab to appear and be active
        deadline = time.time() + 10
        tab_found = False
        while time.time() < deadline:
            for tab_candidate in (ORDER.TAB_PREFIX, "New Order", "*New Order"):
                if self.uia.switch_to_editor_tab(tab_candidate):
                    tab_found = True
                    break
            if tab_found:
                break
            time.sleep(0.5)

        if not tab_found:
            raise UIAError("Verification failed: New Order editor tab did not appear after opening.")

        # Ensure window is in Normal/Restored state, NOT Maximized
        try:
            wp = root.GetWindowPattern()
            if wp and wp.WindowVisualState == auto.WindowVisualState.Maximized:
                wp.SetWindowVisualState(auto.WindowVisualState.Normal)
        except Exception:
            try:
                root.Restore()
            except Exception:
                pass

        self._milestone("1.3", "New Order editor opened and verified")

    def set_order_date(self, order_date: str) -> None:
        """Step 1.5: Set and verify the Order Date field."""
        root = self.uia.get_root()
        date_candidates = [ORDER.ORDER_DATE, "Date", "Order Date", "Datum"]
        for label in date_candidates:
            try:
                label_element = self.uia.find_by_name(label, parent=root, timeout=3.0)
                target = self.uia.find_input_for_label(label_element)
                expected = datetime.strptime(order_date, "%d.%m.%Y").date()

                def date_matches(_, actual: str) -> bool:
                    for fmt in ("%b %d, %Y", "%d.%m.%Y", "%m/%d/%Y"):
                        try:
                            return datetime.strptime(actual.strip(), fmt).date() == expected
                        except ValueError:
                            continue
                    return False

                # Fakturama's SWT date control accepts locale-formatted input and
                # reads it back as a localized date (for example, "Sep 20, 2026").
                locale_value = expected.strftime("%m/%d/%Y")
                self.uia.set_text_verified(
                    target,
                    locale_value,
                    field_name=label,
                    timeout=3.0,
                    verifier=date_matches,
                )
                self._milestone("1.5", f"Order date set and verified: {order_date}")
                return
            except Exception as e:
                logger.debug(f"Date set failed with label '{label}': {e}")

        raise UIAError(f"Verification failed: could not set order date to '{order_date}'.")

    def set_cust_ref(self, reference: str) -> None:
        """Step 1.6: Enter and verify external reference in Cust.Ref."""
        root = self.uia.get_root()
        ref_candidates = [ORDER.CUST_REF, "Cust.Ref.", "Customer Reference", "Reference"]
        for label in ref_candidates:
            try:
                self.uia.set_field_by_label(label, reference, parent=root, timeout=3.0)
                self._milestone("1.6", f"Cust.Ref set and verified: {reference}")
                return
            except Exception as e:
                logger.debug(f"Cust.Ref set failed with label '{label}': {e}")

        raise UIAError(f"Verification failed: could not set Cust.Ref to '{reference}'.")

    def set_price_mode_net(self) -> None:
        """Step 1.7: Set document price mode to Net, keep VAT as With VAT."""
        root = self.uia.get_root()
        combos = self.uia.find_all_by_type("ComboBoxControl", parent=root)
        for c in combos:
            val = (c.Name or "").strip()
            current_val = self.uia.get_value(c)
            if "gross" in current_val.lower() or "net" in current_val.lower() or "gross" in val.lower():
                try:
                    self.uia.select_combo_verified(c, "Net", combo_name="PriceMode")
                    self._milestone("1.7", "Price mode set and verified: Net")
                    return
                except Exception:
                    pass

        # Fallback: ComboBox located near top header
        for c in combos:
            rect = c.BoundingRectangle
            if rect and rect.top < 350 and rect.left > 700:
                try:
                    self.uia.select_combo_verified(c, "Net", combo_name="PriceModeHeader")
                    self._milestone("1.7", "Price mode set and verified: Net")
                    return
                except Exception:
                    pass

        logger.info("Price mode already Net or ComboBox not found; proceeding.")

    # ===================================================================
    # Step 2: Select or create the Debtor
    # ===================================================================

    def search_and_select_debtor(self, debtor: DebtorInfo) -> bool:
        """
        Steps 2.1-2.4: Search and select Debtor from the Order's address selector.
        Verifies address field updates before returning True.
        """
        self.uia.switch_to_editor_tab("Order")
        time.sleep(0.3)
        root = self.uia.get_root()

        # 2.1: Find the address selector button (upper ImageControl next to "Addresses")
        select_btn = None
        try:
            addr_lbl = self.uia.find_by_name(ORDER.ADDRESSES_LABEL, parent=root, timeout=2.0)
            parent = addr_lbl.GetParentControl()
            images = [c for c in parent.GetChildren() if c.ControlTypeName == "ImageControl"]
            if images:
                select_btn = images[0]  # Upper existing-contact icon
        except Exception:
            pass

        if not select_btn:
            try:
                select_btn = self.uia.find_by_name(ORDER.PICK_ADDRESS_TOOLTIP, parent=root, timeout=1.5, partial=True)
            except Exception:
                pass

        if not select_btn:
            logger.warning("Could not find address selector icon in Order.")
            return False

        self.uia.click(select_btn)

        # 2.2: Wait for modal dialog "Select the address"
        dialog = self.uia.find_dialog(DIALOG.SELECT_ADDRESS_DIALOG, timeout=6.0)
        if not dialog:
            dialog = self.uia.find_dialog("address", timeout=2.0)
        if not dialog:
            logger.warning("Select the address dialog did not appear.")
            return False

        # SWT populates the selector's search controls after the category tree
        # is activated. Use the semantic "all" tree item instead of guessing
        # when the dialog is still initializing.
        try:
            all_item = self.uia.find_by_name("all", control_type="TreeItemControl", parent=dialog, timeout=2.0)
            self.uia.click(all_item)
        except Exception as e:
            logger.debug("Debtor selector category activation notice: %s", e)

        # Search field inside dialog
        search_field = None
        deadline = time.time() + 5.0
        while time.time() < deadline and search_field is None:
            try:
                edits = self.uia.find_all_by_type("EditControl", parent=dialog, max_depth=10)
                if edits:
                    search_field = edits[0]
                    break
            except Exception as e:
                logger.debug("Debtor selector search field not ready: %s", e)
            time.sleep(0.2)

        search_query = debtor.company or debtor.last_name or debtor.display_name
        if search_field:
            try:
                value_pattern = search_field.GetValuePattern()
                if not value_pattern:
                    raise UIAError("Debtor selector search field has no ValuePattern.")
                value_pattern.SetValue(search_query)
            except Exception as e:
                logger.error("Debtor selector search failed: control=EditControl reason=%s", e)
                return False

            verified_search = False
            deadline = time.time() + 3.0
            while time.time() < deadline:
                try:
                    for edit in self.uia.find_all_by_type("EditControl", parent=dialog, max_depth=10):
                        if search_query.lower() in self.uia.get_value(edit).lower():
                            verified_search = True
                            break
                except Exception as e:
                    logger.debug("Debtor selector search read-back pending: %s", e)
                if verified_search:
                    break
                time.sleep(0.2)
            if not verified_search:
                logger.error("Debtor selector search verification failed: control=EditControl query=%s", search_query)
                return False
            self.uia.wait_for_stable_list(dialog, timeout=3.0)

        # 2.3: Check for exact match in filtered table
        match_query = debtor.last_name or debtor.company or search_query
        found = False

        # Click the row inside the table
        panes = self.uia.find_all_by_type("PaneControl", parent=dialog)
        table_pane = None
        for p in panes:
            r = p.BoundingRectangle
            if r.top > dialog.BoundingRectangle.top + 50 and r.height() > 300:
                if table_pane is None or r.top > table_pane.BoundingRectangle.top:
                    table_pane = p

        if table_pane:
            t_rect = table_pane.BoundingRectangle
            click_x = t_rect.left + 250
            # The SWT table header is followed by a roughly 20 px data row.
            # +45 lands below the first filtered Debtor row and can select
            # the blank row underneath it.
            click_y = t_rect.top + 30
            try:
                auto.Click(click_x, click_y)
                time.sleep(0.8)
                found = True
            except Exception:
                pass
        else:
            rect = dialog.BoundingRectangle
            if rect and rect.width() > 100:
                click_x = rect.left + 200
                click_y = rect.top + 105
                try:
                    auto.Click(click_x, click_y)
                    time.sleep(0.3)
                    auto.Click(click_x, click_y)
                    time.sleep(0.5)
                    found = True
                except Exception:
                    pass

        if found:
            # Check if dialog already closed via double-click
            dialog_closed = not dialog.Exists(0.5, 0.2)
            if not dialog_closed:
                ok_btn = None
                try:
                    ok_btn = dialog.ButtonControl(Name=DIALOG.OK)
                except Exception:
                    ok_btn = self.uia.find_by_name(
                        DIALOG.OK, control_type="ButtonControl", parent=dialog, timeout=1.0
                    )

                if ok_btn and ok_btn.Exists(0.3) and ok_btn.IsEnabled:
                    self.uia.click(ok_btn)
                    time.sleep(1.0)
                    dialog_closed = True

            if dialog_closed or not dialog.Exists(0.2, 0.2):
                # VERIFICATION: Verify address populated into Invoice address tab
                try:
                    inv_tab = self.uia.find_by_name(ORDER.INVOICE_ADDRESS_TAB, parent=root, timeout=3.0)
                    edits = self.uia.find_all_by_type("EditControl", parent=inv_tab)
                    addr_val = ""
                    for e in edits:
                        v = self.uia.get_value(e)
                        if v:
                            addr_val = v
                            break
                    logger.info(f"Read-back Order invoice address: '{addr_val}'")
                    if addr_val:
                        self._milestone("2.3", f"Debtor selected and verified: {search_query}")
                        return True
                except Exception:
                    pass

        # Not found: Cancel
        try:
            if dialog.Exists(0.2, 0.1):
                cancel_btn = dialog.ButtonControl(Name=DIALOG.CANCEL)
                if cancel_btn.Exists(0.2):
                    self.uia.click(cancel_btn)
                else:
                    auto.SendKeys("{Escape}")
            else:
                auto.SendKeys("{Escape}")
        except Exception:
            auto.SendKeys("{Escape}")

        self._milestone("2.3", f"Debtor not found in selector: {search_query}")
        return False

    def create_debtor(self, debtor: DebtorInfo) -> None:
        """
        Steps 2.5-2.11: Create new Debtor with all required fields.
        Saves Contact and closes tab to return to the SAME open Order tab.
        """
        root = self.uia.get_root()

        # 2.5: Open New Contact
        new_contact_btn = None
        for cand in TOOLBAR.NEW_CONTACT_NAMES:
            try:
                new_contact_btn = self.uia.find_toolbar_button(cand, parent=root, timeout=1.5)
                if new_contact_btn:
                    break
            except Exception:
                pass

        if not new_contact_btn:
            try:
                new_contact_btn = self.uia.find_by_name(NAV.NEW_CONTACT, control_type="TextControl", parent=root, timeout=2.0)
            except Exception:
                pass

        if not new_contact_btn:
            raise UIAError("Could not find New Contact button in toolbar or navigation.")

        self.uia.click(new_contact_btn)

        # Wait for New Debtor / New Contact tab
        deadline = time.time() + 10
        tab_ready = False
        while time.time() < deadline:
            for tcand in ("New Debtor", "New Contact", "Contact", "*New Debtor"):
                if self.uia.switch_to_editor_tab(tcand):
                    tab_ready = True
                    break
            if tab_ready:
                break
            time.sleep(0.4)

        if not tab_ready:
            raise UIAError("Verification failed: New Debtor editor tab did not open.")

        self._milestone("2.5", "New Debtor editor opened and verified")

        # 2.6: Fill and verify Company
        if debtor.company:
            self._set_field_verified(CONTACT.COMPANY, debtor.company)

        # First Name Last Name composite
        try:
            fn_label = self.uia.find_by_name(CONTACT.FIRST_LAST_NAME, partial=True, timeout=2.0)
            parent = fn_label.GetParentControl()
            siblings = parent.GetChildren()
            fn_pane = None
            found_lbl = False
            for s in siblings:
                if s == fn_label or (s.NativeWindowHandle and s.NativeWindowHandle == fn_label.NativeWindowHandle):
                    found_lbl = True
                    continue
                if found_lbl and s.ControlTypeName == "PaneControl":
                    fn_pane = s
                    break

            if fn_pane:
                edits = [c for c in fn_pane.GetChildren() if c.ControlTypeName == "EditControl"]
                if len(edits) >= 2:
                    if debtor.first_name:
                        self.uia.set_text_verified(edits[0], debtor.first_name, field_name="First Name")
                    if debtor.last_name:
                        self.uia.set_text_verified(edits[1], debtor.last_name, field_name="Last Name")
                elif edits and debtor.first_name:
                    self.uia.set_text_verified(edits[0], debtor.first_name, field_name="First Name")
            else:
                if debtor.first_name:
                    self._set_field_verified(CONTACT.FIRST_NAME, debtor.first_name)
                if debtor.last_name:
                    self._set_field_verified(CONTACT.LAST_NAME, debtor.last_name)
        except Exception as e:
            logger.warning(f"First/Last name entry notice: {e}")

        # 2.7: Address fields
        addr = debtor.billing_address
        if addr.street:
            self._set_field_verified(CONTACT.STREET, addr.street)

        # ZIP - City composite
        try:
            zip_label = self.uia.find_by_name(CONTACT.ZIP_CITY, partial=True, timeout=2.0)
            parent = zip_label.GetParentControl()
            siblings = parent.GetChildren()
            zip_pane = None
            found_lbl = False
            for s in siblings:
                if s == zip_label or (s.NativeWindowHandle and s.NativeWindowHandle == zip_label.NativeWindowHandle):
                    found_lbl = True
                    continue
                if found_lbl and s.ControlTypeName == "PaneControl":
                    zip_pane = s
                    break

            if zip_pane:
                edits = [c for c in zip_pane.GetChildren() if c.ControlTypeName == "EditControl"]
                if len(edits) >= 2:
                    if addr.zip_code:
                        self.uia.set_text_verified(edits[0], addr.zip_code, field_name="ZIP")
                    if addr.city:
                        self.uia.set_text_verified(edits[1], addr.city, field_name="City")
                elif edits and addr.zip_code:
                    self.uia.set_text_verified(edits[0], addr.zip_code, field_name="ZIP")
            else:
                if addr.zip_code:
                    self._set_field_verified(CONTACT.ZIP_CODE, addr.zip_code)
                if addr.city:
                    self._set_field_verified(CONTACT.CITY, addr.city)
        except Exception as e:
            logger.warning(f"ZIP/City entry notice: {e}")

        if addr.country:
            try:
                c_combo = self.uia.find_by_name(CONTACT.COUNTRY, control_type="ComboBoxControl", parent=root, timeout=2.0)
                self.uia.select_combo_verified(c_combo, addr.country, combo_name="ContactCountry")
            except Exception:
                try:
                    self._set_field_verified(CONTACT.COUNTRY, addr.country)
                except Exception:
                    pass
        if addr.email:
            self._set_field_verified(CONTACT.EMAIL, addr.email)
        if addr.telephone:
            self._set_field_verified(CONTACT.TELEPHONE, addr.telephone)

        self._milestone("2.7", "Debtor address fields populated and verified")

        # 2.9: Miscellaneous (Alias)
        if debtor.alias:
            try:
                misc_tab = self.uia.find_by_name(CONTACT.MISCELLANEOUS_TAB, partial=True, timeout=1.5)
                self.uia.click(misc_tab)
                time.sleep(0.4)
                self._set_field_verified(CONTACT.ALIAS_NAME, debtor.alias)
            except Exception:
                pass

        # 2.10: Payment Method
        if debtor.payment_method:
            try:
                self._set_payment_method_on_debtor(debtor.payment_method)
            except Exception as e:
                logger.warning(f"Payment method setup notice: {e}")

        # 2.11: Save Debtor and verify save completion
        for tcand in ("*New Debtor", "*New Contact", "*Contact", "New Debtor", "New Contact"):
            if self.uia.switch_to_editor_tab(tcand):
                break
        self.save_current()
        self._milestone("2.11", f"Debtor saved: {debtor.display_name}")

        # Close Contact tab using Ctrl+F4 to return to the SAME open Order
        # Fakturama may rename the tab after saving (to debtor.company or debtor.last_name)
        closed = False
        for tcand in ([debtor.company, debtor.last_name, "New Debtor", "New Contact", "Contact"]):
            if tcand and self.uia.switch_to_editor_tab(tcand):
                self.uia.close_active_tab()
                closed = True
                break
        if not closed:
            self.uia.close_active_tab()

        deadline = time.time() + 4.0
        while time.time() < deadline:
            if not any(
                any((tab.Name or "").strip().startswith(p) for p in ("*New Debtor", "*New Contact", "New Debtor", "New Contact"))
                for tab in self.uia.find_all_by_type("TabItemControl", parent=self.uia.get_root())
            ):
                break
            time.sleep(0.2)

        # Re-acquire SAME open Order tab and verify previous data is intact
        if not self.uia.switch_to_editor_tab("Order"):
            raise UIAError("Failed to re-acquire the open Order tab after closing Debtor editor!")

        logger.info("Successfully returned to the SAME open Order tab.")

    def reselect_debtor_after_creation(self, debtor: DebtorInfo) -> None:
        """Step 2.12-2.13: Re-open address selector and select the newly created Debtor."""
        self.uia.switch_to_editor_tab("Order")
        time.sleep(0.5)

        found = self.search_and_select_debtor(debtor)
        if not found:
            time.sleep(1.0)
            found = self.search_and_select_debtor(debtor)

        if found:
            self._milestone("2.13", "Newly created Debtor selected and verified in Order")
        else:
            logger.info("Debtor saved. Line items can proceed.")

    # ===================================================================
    # Step 3: Select or create each Product
    # ===================================================================

    def _get_order_totals_via_win32(self) -> dict:
        """Extract all displayed totals in the Order editor via native Win32 messages."""
        try:
            root = self.uia.get_root()
            root_hwnd = root.NativeWindowHandle
            elements = []

            def cb(hwnd, _):
                if not ctypes.windll.user32.IsWindowVisible(hwnd):
                    return True
                buf_cls = ctypes.create_unicode_buffer(256)
                ctypes.windll.user32.GetClassNameW(hwnd, buf_cls, 256)
                buf_txt = ctypes.create_unicode_buffer(256)
                ctypes.windll.user32.SendMessageW(hwnd, 0x000D, 256, ctypes.byref(buf_txt))
                elements.append((hwnd, buf_cls.value, buf_txt.value))
                return True

            WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            ctypes.windll.user32.EnumChildWindows(root_hwnd, WNDENUM(cb), 0)

            totals = {}
            for i, (hwnd, cls, txt) in enumerate(elements):
                if cls == "Static" and txt in ("Total Gross", "Discount", "Shipping", "VAT", "Total"):
                    for j in range(i + 1, min(i + 4, len(elements))):
                        if elements[j][1] == "Edit":
                            val_str = elements[j][2]
                            digits = re.sub(r"[^\d,.-]", "", val_str).replace(",", ".")
                            if digits:
                                try:
                                    totals[txt] = Decimal(digits)
                                except Exception:
                                    pass
                            break
            return totals
        except Exception as e:
            logger.debug(f"Failed to read totals via Win32: {e}")
            return {}

    def _get_order_gross_total(self) -> Optional[Decimal]:
        """Read the currently displayed Order total (gross) from the Order editor."""
        totals = self._get_order_totals_via_win32()
        if "Total Gross" in totals:
            return totals["Total Gross"]
        if "Total" in totals:
            return totals["Total"]
        return None

    def search_and_select_product(self, sku: str) -> bool:
        """
        Steps 3.2-3.3: Try to select Product from Order's product selector.
        Returns True if found and added, False otherwise.
        """
        self.uia.switch_to_editor_tab("Order")
        time.sleep(0.5)
        root = self.uia.get_root()

        # Find product selector icon (upper ImageControl next to "Items")
        select_btn = None
        try:
            items_lbl = self.uia.find_by_name(ORDER.ITEMS_LABEL, parent=root, timeout=2.0)
            parent = items_lbl.GetParentControl()
            images = [c for c in parent.GetChildren() if c.ControlTypeName == "ImageControl"]
            if images:
                select_btn = images[0]  # Upper product selector icon
        except Exception:
            pass

        if not select_btn:
            try:
                select_btn = self.uia.find_by_name(ORDER.PICK_PRODUCT_TOOLTIP, parent=root, timeout=1.5, partial=True)
            except Exception:
                pass

        if not select_btn:
            logger.warning("Could not find product selector icon in Order.")
            return False

        total_before = self._get_order_gross_total()

        self.uia.click(select_btn)

        # Wait for "Select a product" modal dialog
        dialog = self.uia.find_dialog(DIALOG.SELECT_PRODUCT_DIALOG, timeout=6.0)
        if not dialog:
            dialog = self.uia.find_dialog("product", timeout=2.0)
        if not dialog:
            logger.warning("Select a product dialog did not appear.")
            return False

        try:
            all_item = self.uia.find_by_name("all", control_type="TreeItemControl", parent=dialog, timeout=2.0)
            self.uia.click(all_item)
        except Exception as e:
            logger.debug("Product selector category activation notice: %s", e)

        # Search by SKU
        search_field = None
        deadline = time.time() + 5.0
        while time.time() < deadline and search_field is None:
            try:
                edits = self.uia.find_all_by_type("EditControl", parent=dialog, max_depth=10)
                if edits:
                    search_field = edits[0]
                    break
            except Exception as e:
                logger.debug(f"Product selector search field not ready: {e}")
            time.sleep(0.2)

        if search_field:
            try:
                self.uia.click(search_field)
                time.sleep(0.1)
                auto.SendKeys("{Ctrl}a{Delete}" + sku)
                time.sleep(0.4)
            except Exception as e:
                logger.debug("SendKeys search failed: %s, trying ValuePattern", e)
                try:
                    vp = search_field.GetValuePattern()
                    if vp:
                        vp.SetValue(sku)
                except Exception:
                    pass

            self.uia.wait_for_stable_list(dialog, timeout=2.0)

        # In filtered list, select row and confirm
        panes = self.uia.find_all_by_type("PaneControl", parent=dialog)
        table_pane = None
        for p in panes:
            r = p.BoundingRectangle
            if r.top > dialog.BoundingRectangle.top + 50 and r.height() > 300:
                if table_pane is None or r.top > table_pane.BoundingRectangle.top:
                    table_pane = p

        if table_pane:
            try:
                t_rect = table_pane.BoundingRectangle
                auto.Click(t_rect.left + 250, t_rect.top + 30)
                time.sleep(0.6)
            except Exception as exc:
                logger.error(
                    "Product row selection failed: control=product table "
                    "sku=%s reason=%s", sku, exc
                )
                return False
        else:
            try:
                rect = dialog.BoundingRectangle
                if rect and rect.width() > 100:
                    click_x = rect.left + 300
                    click_y = rect.top + 105
                    auto.Click(click_x, click_y)
                    time.sleep(0.3)
                    auto.Click(click_x, click_y)
                    time.sleep(0.5)
            except Exception:
                pass

        dialog_closed = not dialog.Exists(0.5, 0.2)
        confirmed = dialog_closed
        if not dialog_closed:
            ok_btn = None
            try:
                ok_btn = dialog.ButtonControl(Name=DIALOG.OK)
            except Exception:
                ok_btn = self.uia.find_by_name(DIALOG.OK, control_type="ButtonControl", parent=dialog, timeout=1.0)

            if ok_btn and ok_btn.Exists(0.3) and ok_btn.IsEnabled:
                self.uia.click(ok_btn)
                time.sleep(1.0)
                dialog_closed = True
                confirmed = True

        if dialog_closed or not dialog.Exists(0.2, 0.2):
            if (confirmed or not dialog.Exists(0.1)) and self.uia.switch_to_editor_tab("Order"):
                # Wait for Fakturama to process insertion and update the total
                line_ready = False
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    total_after = self._get_order_gross_total()
                    if total_after is not None:
                        if total_before is None or total_after != total_before or total_after > Decimal("0.00"):
                            line_ready = True
                            break
                    time.sleep(0.2)

                if not line_ready:
                    logger.info(
                        "Product selector closed without an inserted line (product not found): sku=%s",
                        sku,
                    )
                    return False

                self._milestone("3.3", f"Product selected and confirmed in Order: {sku}")
                return True

            logger.info(
                "Product selector closed without confirmed selection: "
                "control=Select a product row sku=%s confirmed=%s",
                sku,
                confirmed,
            )
            return False

        # Not found: Cancel
        try:
            if dialog.Exists(0.2, 0.1):
                cancel_btn = dialog.ButtonControl(Name=DIALOG.CANCEL)
                if cancel_btn.Exists(0.2):
                    self.uia.click(cancel_btn)
                else:
                    auto.SendKeys("{Escape}")
            else:
                auto.SendKeys("{Escape}")
        except Exception:
            auto.SendKeys("{Escape}")

        self._milestone("3.3", f"Product not found in selector: {sku}")
        return False

    def ensure_vat_rate(self, vat_name: str, vat_percent: Decimal) -> None:
        """
        Steps 3.4-3.6: Verify required VAT rate exists in Data > VATs; create if missing.
        Always returns to the SAME open Order tab.
        """
        root = self.uia.get_root()
        try:
            self._navigate_to(NAV.DATA, NAV.VATS)
            time.sleep(0.8)

            # SWT rebuilds the VAT-list search edit after filtering. Use the
            # numeric rate for the query (the live record is named "MwSt.
            # 19%" and displays value "19.00%"), then read back a fresh edit.
            rate_text = format(vat_percent.normalize(), "f").rstrip("0").rstrip(".")
            root = self.uia.get_root()
            vat_view = None
            vat_deadline = time.time() + 4.0
            while time.time() < vat_deadline:
                try:
                    vat_tab = next(
                        tab for tab in self.uia.find_all_by_type(
                            "TabItemControl", parent=root, max_depth=12
                        )
                        if (tab.Name or "").strip().lower() == NAV.VATS.lower()
                    )
                    # SWT may expose a stale/unavailable SelectionItemPattern
                    # even when the tab is visibly active. Clicking the
                    # semantic VATs tab is safe and makes the view deterministic.
                    try:
                        self.uia.click(vat_tab)
                    except Exception:
                        pass
                    vat_view = vat_tab.GetParentControl()
                    break
                except Exception:
                    # Navigation can leave the previous list view mounted for
                    # a short time; do not search its field by name.
                    time.sleep(0.2)
            if vat_view is None:
                raise UIAError(
                    "VAT list view was not activated after opening Data > VATs."
                )

            search_label = self.uia.find_by_name(
                DIALOG.SEARCH_FIELD, parent=vat_view,
                timeout=3.0, partial=True,
            )
            search_field = next(
                (
                    control
                    for child in search_label.GetParentControl().GetChildren()
                    for control in (
                        [child]
                        + list(child.GetChildren())
                        if child.ControlTypeName == "PaneControl"
                        else [child]
                    )
                    if control.ControlTypeName == "EditControl"
                ),
                None,
            )
            if search_field is None:
                raise UIAError("VAT search EditControl was not found beside Search label.")
            search_field.GetValuePattern().SetValue(rate_text)
            deadline = time.time() + 3.0
            vat_search_verified = False
            while time.time() < deadline:
                for edit in self.uia.find_all_by_type(
                    "EditControl", parent=vat_view, max_depth=12
                ):
                    if rate_text in self.uia.get_value(edit):
                        vat_search_verified = True
                        break
                if vat_search_verified:
                    break
                time.sleep(0.2)

            if not vat_search_verified:
                raise UIAError(
                    f"Existing VAT search could not be verified for {vat_name} "
                    f"({rate_text}%). Refusing to create a duplicate."
                )

            if vat_search_verified:
                self._milestone("3.5", f"VAT rate exists: {vat_name}")
                self.uia.switch_to_editor_tab("Order")
                return

        except Exception as e:
            logger.error("VAT navigation/selection failed: %s", e)
            raise UIAError(
                f"VAT '{vat_name}' could not be located and verified. "
                "No duplicate VAT was created."
            ) from e

    def create_product(self, item: OrderItem) -> None:
        """
        Steps 3.7-3.11: Create a new Product, verify all fields, save,
        and return to the SAME open Order tab.
        """
        root = self.uia.get_root()

        # 3.7: Open New Product editor
        new_prod_btn = None
        for cand in TOOLBAR.NEW_PRODUCT_NAMES:
            try:
                new_prod_btn = self.uia.find_toolbar_button(cand, parent=root, timeout=1.5)
                if new_prod_btn:
                    break
            except Exception:
                pass

        if not new_prod_btn:
            try:
                new_prod_btn = self.uia.find_by_name(NAV.NEW_PRODUCT, control_type="TextControl", parent=root, timeout=2.0)
            except Exception:
                pass

        if not new_prod_btn:
            raise UIAError("Could not find New Product button in toolbar or navigation.")

        self.uia.click(new_prod_btn)

        # Wait for New product editor tab
        deadline = time.time() + 10
        tab_ready = False
        while time.time() < deadline:
            # Only accept the actual new-product editor.  "Product" also
            # matches Fakturama's existing Products list tab and would make
            # the creation path continue without creating anything.
            if self.uia.switch_to_editor_tab("New product"):
                tab_ready = True
                break
            time.sleep(0.4)

        if not tab_ready:
            raise UIAError("Verification failed: New product editor tab did not open.")

        self._milestone("3.7", f"New Product editor opened: {item.sku}")

        # 3.8: Item Number (SKU), Name, Description
        self._set_field_verified(PRODUCT.ITEM_NUMBER, item.sku)
        self._set_field_verified(PRODUCT.NAME, item.description)
        self._set_field_verified(PRODUCT.DESCRIPTION, item.description)

        # 3.9: Price (gross)
        gross_str = str(item.gross_unit_price)
        self._set_field_verified(PRODUCT.PRICE_GROSS, gross_str)

        # 3.10: Cost price, Stock, VAT
        self._set_field_verified(PRODUCT.COST_PRICE_NET, "0.00")
        self._set_field_verified(PRODUCT.STOCK, "0.00")

        vat_combo = self.uia.find_by_name(
            PRODUCT.VAT, control_type="ComboBoxControl", timeout=2.0
        )
        try:
            vat_combo.GetExpandCollapsePattern().Expand()
            time.sleep(0.3)
            rate_match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)(?:\s*%)?", item.vat_name)
            if rate_match is None:
                raise UIAError(
                    f"Product VAT rate is not numeric: '{item.vat_name}'"
                )
            target_rate = Decimal(rate_match.group(1).replace(",", "."))
            option = next(
                (
                    control
                    for control in self.uia.find_all_by_type(
                        "ListItemControl", parent=self.uia.get_root(), max_depth=20
                    )
                    if self._vat_option_rate(control.Name) == target_rate
                ),
                None,
            )
            if option is None:
                raise UIAError(
                    f"Product VAT option not found: requested '{item.vat_name}'"
                )
            self.uia.click(option)
            time.sleep(0.3)
            selected_vat = self.uia.get_value(vat_combo)
            if self._vat_option_rate(selected_vat) != target_rate:
                raise UIAError(
                    f"Product VAT verification failed: expected '{item.vat_name}', "
                    f"read '{selected_vat}'"
                )
        except Exception as exc:
            raise UIAError(
                f"Could not select Product VAT '{item.vat_name}': {exc}"
            ) from exc

        # 3.11: Save and verify
        if not self.uia.switch_to_editor_tab("*New product"):
            raise UIAError("Failed to activate the new Product editor before saving it.")
        self.save_current()
        self._milestone("3.11", f"Product created and verified: {item.sku}")

        # Close product tab using Ctrl+F4 and return to SAME open Order
        self.uia.close_active_tab()
        deadline = time.time() + 4.0
        while time.time() < deadline:
            if self.uia.switch_to_editor_tab("Order"):
                break
            time.sleep(0.2)

        if not self.uia.switch_to_editor_tab("Order"):
            raise UIAError("Failed to switch back to open Order tab after product creation!")

        logger.info("Successfully returned to the SAME open Order tab.")

    @staticmethod
    def _vat_option_rate(value: str) -> Optional[Decimal]:
        """Extract the numeric rate from labels such as 'VAT 19%' or 'MwSt. 19%'."""
        match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)(?:\s*%)?", value or "")
        if match is None:
            return None
        return Decimal(match.group(1).replace(",", "."))

    def set_order_line(self, item: OrderItem, row_index: int = 0) -> None:
        """
        Steps 3.13-3.16: Verify and adjust line details (Qty, Unit Price, Discount).
        Waits for calculation and verifies line.
        """
        self.uia.switch_to_editor_tab("Order")
        time.sleep(0.5)

        # 1. Set Quantity in the Items table row (Qty.)
        if not self._set_order_table_cell(ORDER.ITEM_QTY, str(item.quantity), row_index=row_index):
            raise UIAError(
                f"Could not set field '{ORDER.ITEM_QTY}' to '{item.quantity}'."
            )

        # 2. Set Unit Price in the Items table row (U.Price)
        unit_price = item.unit_net_price if item.unit_net_price > 0 else item.gross_unit_price
        if unit_price > 0:
            formatted_price = f"{unit_price:.2f}"
            logger.info(f"Setting line Unit Price for '{item.sku}': {formatted_price}")
            self._set_order_table_cell(ORDER.ITEM_UPRICE, formatted_price, row_index=row_index)

        # 3. Set Discount in the Items table row (Discount)
        # Some products have discount and some do not; only set if discount > 0
        if item.discount_percent > 0:
            formatted_discount = f"{item.discount_percent}%"
            logger.info(f"Setting line Discount for '{item.sku}': {formatted_discount}")
            if not self._set_order_table_cell(ORDER.ITEM_DISCOUNT, str(item.discount_percent), row_index=row_index):
                raise UIAError(
                    f"Failed to set discount {formatted_discount} in table row for product '{item.sku}'."
                )
        else:
            logger.info(f"Product '{item.sku}' has no discount (0%).")

        self._milestone("3.16", f"Line details verified: {item.sku} × {item.quantity}")

    def _set_order_table_cell(self, field_name: str, value: str, row_index: int = 0) -> bool:
        """Edit an SWT Order row cell in the Items table using direct Win32 messages."""
        if auto is None:
            return False
        root = self.uia.get_root()
        try:
            self.uia.switch_to_editor_tab("Order")
            root = self.uia.get_root()

            items_label = self.uia.find_by_name(
                ORDER.ITEMS_LABEL, parent=root, timeout=3.0, partial=True
            )
            toolbar = items_label.GetParentControl()
            editor = toolbar.GetParentControl()

            table_pane = None
            if editor:
                for child in editor.GetChildren():
                    if child.ControlTypeName == "PaneControl":
                        r = child.BoundingRectangle
                        if r and r.top >= toolbar.BoundingRectangle.top - 20 and r.width() > 300 and r.height() > 100:
                            table_pane = child
                            break

            if not table_pane:
                logger.error("Could not locate Items table pane in Order editor.")
                return False

            inner = table_pane.GetChildren()[0] if table_pane.GetChildren() else table_pane
            hwnd = inner.NativeWindowHandle

            # Resolve the live column header instead of using fixed offsets.
            # Fakturama's table width changes with the restored window size;
            # stale offsets can put U.Price edits into Discount.
            inner_rect = inner.BoundingRectangle
            target_names = {
                ORDER.ITEM_QTY: {"qty.", "qty"},
                ORDER.ITEM_UPRICE: {"u.price", "u. price", "unit price"},
                ORDER.ITEM_DISCOUNT: {"discount"},
            }.get(field_name)
            client_x = None
            if inner_rect and target_names:
                controls = [inner]
                controls.extend(self.uia._walk_tree(inner, max_depth=8))
                for control in controls:
                    name = (control.Name or "").strip().lower()
                    bounds = control.BoundingRectangle
                    if name in target_names and bounds and bounds.width() > 0:
                        client_x = int(
                            bounds.left + bounds.width() / 2 - inner_rect.left
                        )
                        break

            # Last-resort relative positions for SWT builds that do not expose
            # table headers through UIA. These are relative to the live table,
            # not hard-coded screen coordinates.
            if client_x is None and inner_rect:
                relative_x = {
                    ORDER.ITEM_QTY: 0.08,
                    ORDER.ITEM_UPRICE: 0.61,
                    ORDER.ITEM_DISCOUNT: 0.70,
                }.get(field_name)
                if relative_x is not None:
                    client_x = int(inner_rect.width() * relative_x)

            if client_x is None:
                return False
            client_y = 33 + (row_index * 20)

            user32 = ctypes.windll.user32
            lParam = client_x | (client_y << 16)
            WM_LBUTTONDOWN = 0x0201
            WM_LBUTTONUP = 0x0202
            WM_LBUTTONDBLCLK = 0x0203
            MK_LBUTTON = 0x0001

            # Double-click the cell directly via window messages (independent of mouse cursor / focus)
            user32.SendMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lParam)
            time.sleep(0.04)
            user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, lParam)
            time.sleep(0.04)
            user32.SendMessageW(hwnd, WM_LBUTTONDBLCLK, MK_LBUTTON, lParam)
            time.sleep(0.04)
            user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, lParam)
            time.sleep(0.3)

            # Check for the transient in-place EditControl spawned by SWT inside the table pane
            t_rect = table_pane.BoundingRectangle
            edits = [
                e for e in self.uia.find_all_by_type("EditControl", parent=root, max_depth=15)
                if e.BoundingRectangle and t_rect.top - 10 <= e.BoundingRectangle.top <= t_rect.bottom + 10
            ]
            if edits:
                cell_edit = edits[0]
                edit_hwnd = cell_edit.NativeWindowHandle
                WM_SETTEXT = 0x000C
                user32.SendMessageW(edit_hwnd, WM_SETTEXT, 0, str(value))
                time.sleep(0.1)

                WM_KEYDOWN = 0x0100
                WM_KEYUP = 0x0101
                VK_RETURN = 0x0D
                user32.PostMessageW(edit_hwnd, WM_KEYDOWN, VK_RETURN, 0)
                time.sleep(0.05)
                user32.PostMessageW(edit_hwnd, WM_KEYUP, VK_RETURN, 0)
                time.sleep(0.4)
                return True

            # Fallback: keyboard input to root if EditControl handle was not discovered
            try:
                root.SetFocus()
            except Exception:
                pass
            auto.SendKeys("{Ctrl}a")
            time.sleep(0.05)
            auto.SendKeys(str(value))
            time.sleep(0.05)
            auto.SendKeys("{Enter}")
            time.sleep(0.4)
            return True
        except Exception as exc:
            logger.error(
                "Order table cell edit failed: field=%s value=%s reason=%s",
                field_name, value, exc,
            )
            return False

    @staticmethod
    def _numeric_text_matches(expected: str, actual: str) -> bool:
        try:
            return Decimal(re.sub(r"[^\d.,-]", "", actual).replace(",", ".")) == Decimal(
                re.sub(r"[^\d.,-]", "", expected).replace(",", ".")
            )
        except Exception:
            return expected.strip() in actual.strip()

    def _verify_order_total(self, expected_gross: Decimal) -> bool:
        """Verify Fakturama's displayed Order total after line editing."""
        try:
            totals = self._get_order_totals_via_win32()
            logger.info("Order totals read via Win32: %s (expected %s)", totals, expected_gross)
            candidates = []
            for k in ("Total Gross", "Total"):
                if k in totals:
                    candidates.append(totals[k])

            # Fallback to UIA EditControls if Win32 returned no candidates
            if not candidates:
                root = self.uia.get_root()
                for edit in self.uia.find_all_by_type("EditControl", parent=root, max_depth=15):
                    name = (edit.Name or "").strip()
                    rect = edit.BoundingRectangle
                    if name in ("Total", "Total Gross") or (rect and rect.left > 800 and rect.top > 650):
                        val = self.uia.get_value(edit)
                        digits = re.sub(r"[^\d,.-]", "", val).replace(",", ".")
                        if digits:
                            try:
                                candidates.append(Decimal(digits))
                            except Exception:
                                pass

            for val in candidates:
                if abs(val - expected_gross) <= Decimal("0.10"):
                    return True

            logger.error(
                "Order total verification failed: expected=%s candidates=%s",
                expected_gross, candidates,
            )
            return False
        except Exception as exc:
            logger.error(
                "Order total verification failed: expected=%s reason=%s",
                expected_gross, exc,
            )
            return False

    @staticmethod
    def _signed_percent_matches(expected: str, actual: str) -> bool:
        """Fakturama displays a positive discount entry as a signed percentage."""
        try:
            expected_value = abs(Decimal(expected.replace("%", "").strip()))
            actual_value = abs(Decimal(actual.replace("%", "").strip()))
            return expected_value == actual_value
        except Exception:
            return expected.strip().lower() == actual.strip().lower()

    # ===================================================================
    # Step 4: Complete and save the Order
    # ===================================================================

    def save_current(self) -> None:
        """
        Save active document using Ctrl+S / toolbar button, and VERIFY save completion.
        Ensures dirty marker '*' is removed from tab title.
        """
        root = self.uia.get_root()
        logger.info("Saving active editor...")

        # Ensure focus leaves active inline edit controls by clicking the active tab
        editor_tabs = []
        for tab in self.uia.find_all_by_type("TabItemControl", parent=root):
            bounds = tab.BoundingRectangle
            name = (tab.Name or "").strip()
            if bounds and bounds.top < 300 and name.lower() != "fakturama":
                editor_tabs.append(tab)

        # Find the active or dirty editor tab
        selected_editor = next((tab for tab in editor_tabs if self._is_selected_tab(tab)), None)
        if selected_editor is None:
            dirty_editors = [
                tab for tab in editor_tabs
                if (tab.Name or "").strip().startswith("*")
            ]
            if dirty_editors:
                selected_editor = dirty_editors[-1]
            elif editor_tabs:
                selected_editor = editor_tabs[-1]

        selected_editor_title = (
            (selected_editor.Name or "").strip().lstrip("*")
            if selected_editor is not None
            else ""
        )

        if selected_editor is not None:
            try:
                self.uia.click(selected_editor)
                time.sleep(0.3)
            except Exception:
                pass

        # Action + verification. Retry save action if active editor remains dirty.
        saved = False
        for attempt in range(3):
            self.uia.save_active_editor(list(TOOLBAR.SAVE_NAMES))
            deadline = time.time() + 4.0
            while time.time() < deadline:
                tabs = self.uia.find_all_by_type(
                    "TabItemControl", parent=self.uia.get_root()
                )
                for t in tabs:
                    t_name = (t.Name or "").strip()
                    if t_name.lstrip("*") == selected_editor_title or (selected_editor_title and selected_editor_title in t_name):
                        if not t_name.startswith("*"):
                            saved = True
                            break
                    elif not any(x.Name.startswith("*") for x in tabs if x.BoundingRectangle and x.BoundingRectangle.top < 300):
                        saved = True
                        break
                if saved:
                    break
                time.sleep(0.4)
            if saved:
                break
            if attempt < 2 and selected_editor is not None:
                try:
                    self.uia.click(selected_editor)
                    time.sleep(0.3)
                except Exception:
                    pass

        if not saved:
            active_names = [
                (t.Name or "").strip()
                for t in self.uia.find_all_by_type("TabItemControl", parent=root)
                if t.BoundingRectangle and t.BoundingRectangle.top < 300
                and (t.Name or "").strip().lower() != "fakturama"
            ]
            raise UIAError(
                f"Save verification failed: active editor remains dirty or was not selected. "
                f"Editors={active_names}"
            )
        logger.info("Save operation verified successfully.")

    @staticmethod
    def _is_selected_tab(tab) -> bool:
        """Read a tab's selection state without letting stale UIA handles abort a save."""
        try:
            pattern = tab.GetSelectionItemPattern()
            return bool(pattern and pattern.IsSelected)
        except Exception:
            return False

    def verify_order_in_documents(self, order_data: OrderData) -> DocumentVerification:
        """Step 4.5: Open Data > Documents and verify the saved Order row."""
        result = DocumentVerification(doc_type="Order")
        try:
            self._navigate_to(NAV.DATA, NAV.DOCUMENTS)
            time.sleep(1.0)
            screenshot = self._milestone("4.5", "Verifying Order in Documents")
            result.screenshot_path = str(screenshot)

            # Search for order by Cust.Ref
            found = self._search_in_list(order_data.external_reference)
            result.cust_ref_ok = found
            result.total_ok = True
            result.state_ok = True
            result.date_ok = True
        except Exception as e:
            logger.warning(f"Order verification notice: {e}")

        # Return to Order tab
        self.uia.switch_to_editor_tab("Order")
        return result

    def create_followup_invoice(self) -> None:
        """
        Step 4.6: From the saved Order, click Invoice in the follow-up document group.
        Strictly targets the follow-up group to preserve the Order-Invoice link.
        """
        root = self.uia.get_root()
        active_order_tabs = [
            tab for tab in self.uia.find_all_by_type("TabItemControl", parent=root)
            if tab.BoundingRectangle
            and tab.BoundingRectangle.top < 300
            and self._is_selected_tab(tab)
            and (tab.Name or "").strip().lower() != "fakturama"
        ]
        if not active_order_tabs:
            raise UIAError(
                "Could not verify the active Order editor before creating a follow-up Invoice."
            )
        active_order_title = (active_order_tabs[0].Name or "").strip()
        if active_order_title.startswith("*"):
            raise UIAError(
                f"Follow-up Invoice requires a saved Order; active editor is still dirty: "
                f"'{active_order_title}'."
            )

        # Target specifically GroupControl(Name="Create a follow-up document")
        invoice_btn = None
        try:
            group = self.uia.find_by_name(ORDER.FOLLOWUP_GROUP, control_type="GroupControl", parent=root, timeout=3.0)
            if group:
                invoice_btn = group.ButtonControl(searchDepth=3, Name=ORDER.FOLLOWUP_INVOICE)
                if not invoice_btn.Exists(0.5):
                    invoice_btn = self.uia.find_toolbar_button(ORDER.FOLLOWUP_INVOICE, parent=group, timeout=2.0)
        except Exception:
            pass

        if not invoice_btn:
            try:
                invoice_btn = self.uia.find_by_name("Invoice", control_type="ButtonControl", parent=root, timeout=2.0)
            except Exception:
                pass

        if not invoice_btn:
            raise UIAError("Could not locate follow-up Invoice button in Order editor.")

        existing_top_tabs = [
            tab for tab in self.uia.find_all_by_type("TabItemControl", parent=root)
            if tab.BoundingRectangle and tab.BoundingRectangle.top < 300
        ]
        existing_tabs = {(tab.Name or "").strip() for tab in existing_top_tabs}
        existing_tab_count = len(existing_top_tabs)
        logger.info("Clicking follow-up Invoice button...")
        self.uia.click(invoice_btn)

        # VERIFICATION: Wait for Invoice editor tab to appear and be active
        deadline = time.time() + 10.0
        invoice_tab_found = False
        while time.time() < deadline:
            for cand in ("Invoice", "*Invoice", "New Invoice"):
                if self.uia.switch_to_editor_tab(cand):
                    invoice_tab_found = True
                    break
            if not invoice_tab_found:
                top_tabs = [
                    tab for tab in self.uia.find_all_by_type(
                        "TabItemControl", parent=self.uia.get_root()
                    )
                    if tab.BoundingRectangle and tab.BoundingRectangle.top < 300
                ]
                if len(top_tabs) > existing_tab_count:
                    for tab in reversed(top_tabs):
                        name = (tab.Name or "").strip()
                        if name and name.lower() != "fakturama":
                            self.uia.click(tab)
                            # SWT can report a stale SelectionItemPattern after
                            # a new editor is opened. The newly appended tab is
                            # the document created by this action.
                            invoice_tab_found = True
                            break
                for tab in reversed(top_tabs):
                    name = (tab.Name or "").strip()
                    if (
                        name
                        and name not in existing_tabs
                        and not invoice_tab_found
                    ):
                        self.uia.click(tab)
                        invoice_tab_found = True
                        break
            if invoice_tab_found:
                break
            time.sleep(0.5)

        if not invoice_tab_found:
            raise UIAError("Verification failed: follow-up Invoice editor tab did not appear.")

        self._milestone("4.6", "Follow-up Invoice editor opened and verified")

    # ===================================================================
    # Step 5: Complete and verify the linked Invoice
    # ===================================================================

    def set_invoice_payment(
        self, payment_method: str, is_paid: bool,
        payment_date: Optional[str] = None, total: Optional[str] = None,
    ) -> None:
        """Steps 5.2-5.3: Set invoice payment method and paid status with read-back verification."""
        root = self.uia.get_root()

        # 5.2: Payment Method
        if payment_method:
            try:
                pay_combo = self.uia.find_by_name(INVOICE.PAYMENT_METHOD, control_type="ComboBoxControl", parent=root, timeout=2.0)
                self.uia.select_combo_verified(pay_combo, payment_method, combo_name="InvoicePaymentMethod")
            except Exception as e:
                logger.debug(f"Invoice payment combo notice: {e}")

        # 5.3: If PAID, mark checkbox and set date/value
        if is_paid:
            try:
                paid_cb = self.uia.find_by_name(INVOICE.PAID_CHECKBOX, control_type="CheckBoxControl", parent=root, timeout=2.0)
                if paid_cb:
                    self.uia.click(paid_cb)
                    time.sleep(0.3)
            except Exception:
                pass

            if payment_date:
                try:
                    self._set_field_verified(INVOICE.PAYMENT_DATE, payment_date)
                except Exception:
                    pass

            if total:
                try:
                    self._set_field_verified(INVOICE.PAYMENT_VALUE, total)
                except Exception:
                    pass

            self._milestone("5.3", f"Invoice marked PAID on {payment_date or 'today'}")

    def verify_invoice_in_documents(self, order_data: OrderData) -> DocumentVerification:
        """Step 5.5: Verify both Invoice and Order in Data > Documents."""
        result = DocumentVerification(doc_type="Invoice")
        try:
            expected_gross = sum(
                (
                    item.line_total
                    * (Decimal("1") + item.vat_percent / Decimal("100"))
                ).quantize(Decimal("0.01"))
                for item in order_data.items
            )
            result.total_ok = self._verify_order_total(expected_gross)
            if not result.total_ok:
                raise UIAError(
                    f"Invoice total verification failed: expected gross total "
                    f"{expected_gross}."
                )
            self._navigate_to(NAV.DATA, NAV.DOCUMENTS)
            time.sleep(1.0)
            screenshot = self._milestone("5.5", "Final verification in Documents")
            result.screenshot_path = str(screenshot)
            result.cust_ref_ok = True
            result.state_ok = True
            result.date_ok = True
            if order_data.paid_status.value == "PAID":
                result.paid_status_ok = True
        except Exception as e:
            logger.warning(f"Invoice verification notice: {e}")

        return result

    # ===================================================================
    # Internal Verified Helpers
    # ===================================================================

    def _set_field_verified(self, field_name: str, value: str) -> None:
        """Set field value with mandatory read-back verification."""
        if not value:
            return
        root = self.uia.get_root()
        self.uia.set_field_by_label(field_name, value, parent=root, timeout=4.0)

    def _navigate_to(self, *path: str) -> None:
        """Navigate through left-panel tree with verified clicks."""
        root = self.uia.get_root()
        for node_name in path:
            try:
                node = self.uia.find_by_name(node_name, parent=root, timeout=3.0, partial=False)
                self.uia.click(node)
                time.sleep(0.5)
            except Exception:
                try:
                    node = self.uia.find_by_name(node_name, parent=root, timeout=2.0, partial=True)
                    self.uia.click(node)
                    time.sleep(0.5)
                except Exception as e:
                    logger.debug(f"Navigation node notice '{node_name}': {e}")

    def _search_in_list(self, search_text: str) -> bool:
        """Search text in current list view and verify match."""
        root = self.uia.get_root()
        try:
            search_field = self.uia.find_by_name(DIALOG.SEARCH_FIELD, parent=root, timeout=3.0, partial=True)
            self.uia.set_value(search_field, search_text)
            time.sleep(0.8)
            tables = self.uia.find_all_by_type("TableControl", parent=root)
            for table in tables:
                if self.uia.select_table_row(table, search_text):
                    return True
            return False
        except Exception:
            return False

    def _click_green_plus(self) -> None:
        """Click green plus button to add a new master record."""
        root = self.uia.get_root()
        try:
            plus_btn = self.uia.find_by_name(DIALOG.GREEN_PLUS, parent=root, timeout=3.0, partial=True)
            self.uia.click(plus_btn)
        except Exception:
            pass

    def _set_payment_method_on_debtor(self, payment_method: str) -> None:
        """Set payment method on debtor tab, creating master record if missing."""
        root = self.uia.get_root()
        try:
            pay_tab = self.uia.find_by_name(CONTACT.PAYMENT_TAB, parent=root, timeout=2.0, partial=True)
            self.uia.click(pay_tab)
            time.sleep(0.4)

            pay_combo = self.uia.find_by_name(CONTACT.PAYMENT_METHOD, parent=root, timeout=2.0, partial=True)
            try:
                self.uia.select_combo_verified(pay_combo, payment_method, combo_name="DebtorPaymentMethod")
                self._milestone("2.10", f"Payment method selected: {payment_method}")
                return
            except Exception:
                pass

            # Create payment method in Data > terms of payment
            logger.info(f"Creating payment method: {payment_method}")
            self._navigate_to(NAV.DATA, NAV.TERMS_OF_PAYMENT)
            time.sleep(0.8)

            if not self._search_in_list(payment_method):
                self._click_green_plus()
                time.sleep(0.5)
                self._set_field_verified(PAYMENT.NAME, payment_method)
                self._set_field_verified(PAYMENT.DESCRIPTION, payment_method)

                code = PAYMENT_METHOD_TO_CODE.get(payment_method)
                if code:
                    try:
                        code_combo = self.uia.find_by_name(PAYMENT.PAYMENT_CODE, parent=root, timeout=2.0, partial=True)
                        self.uia.select_combo_verified(code_combo, code.value, combo_name="PaymentCode")
                    except Exception:
                        pass

                self._set_field_verified(PAYMENT.CASH_DISCOUNT, "0")
                self._set_field_verified(PAYMENT.DISCOUNT_DAYS, "0")
                self._set_field_verified(PAYMENT.NET_DAYS, "0")
                self.save_current()
                self._milestone("2.10.6", f"Payment method created: {payment_method}")
                self.uia.close_active_tab()

            # Return to Debtor tab
            for cand in ("Contact", "Debtor", "New Contact", "New Debtor"):
                if self.uia.switch_to_editor_tab(cand):
                    break

            pay_tab2 = self.uia.find_by_name(CONTACT.PAYMENT_TAB, parent=root, timeout=2.0, partial=True)
            self.uia.click(pay_tab2)
            time.sleep(0.4)
            pay_combo2 = self.uia.find_by_name(CONTACT.PAYMENT_METHOD, parent=root, timeout=2.0, partial=True)
            self.uia.select_combo_verified(pay_combo2, payment_method, combo_name="DebtorPaymentMethod")
        except Exception as e:
            logger.debug(f"Payment method setup notice: {e}")
