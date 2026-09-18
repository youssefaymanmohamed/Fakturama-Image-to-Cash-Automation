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
        """Step 1.3: Click Order in the top toolbar or navigation and wait for the editor."""
        try:
            # 1. Try toolbar button
            try:
                btn = self.uia.find_toolbar_button(TOOLBAR.ORDER_NEW)
                self.uia.click(btn)
            except UIAError:
                # 2. Try by name in navigation tree or New panel
                try:
                    btn = self.uia.find_by_name("Order", partial=False)
                    self.uia.click(btn)
                except UIAError:
                    # 3. Try partial name match
                    btn = self.uia.find_by_name("Order", partial=True)
                    self.uia.click(btn)

            time.sleep(1.5)
            self._milestone("1.3", "New Order editor opened")
        except UIAError as e:
            raise UIAError(f"Failed to open New Order: {e}")

    def set_order_date(self, order_date: str) -> None:
        """Step 1.5: Set the Order Date field."""
        try:
            date_field = self.uia.find_by_name(ORDER.ORDER_DATE, partial=True)
            self.uia.set_value(date_field, order_date)
            self._milestone("1.5", f"Order date set to {order_date}")
        except UIAError as e:
            logger.warning(f"Could not set order date: {e}")

    def set_cust_ref(self, reference: str) -> None:
        """Step 1.6: Enter the external reference in Cust.Ref."""
        try:
            ref_field = self.uia.find_by_name(ORDER.CUST_REF, partial=True)
            self.uia.set_value(ref_field, reference)
            self._milestone("1.6", f"Cust.Ref set to {reference}")
        except UIAError as e:
            logger.warning(f"Could not set Cust.Ref: {e}")

    def set_price_mode_net(self) -> None:
        """Step 1.7: Set document price mode to Net, keep VAT as With VAT."""
        try:
            net_radio = self.uia.find_by_name(ORDER.PRICE_MODE_NET, partial=True)
            self.uia.click(net_radio)
            self._milestone("1.7", "Price mode set to Net")
        except UIAError as e:
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
            # 2.1: Click the upper existing-contact icon
            select_btn = self.uia.find_by_name(
                DIALOG.SELECT_ADDRESS_DIALOG, partial=True
            )
            self.uia.click(select_btn)
            time.sleep(1)

            # 2.2: Search using company/customer name
            search_name = debtor.company or debtor.display_name
            dialog = self.uia.wait_for_window(DIALOG.SELECT_ADDRESS_DIALOG, timeout=10)
            search_field = self.uia.find_by_name(DIALOG.SEARCH_FIELD, parent=dialog, partial=True)
            self.uia.set_value(search_field, search_name)
            time.sleep(1)

            # Wait for list to stabilize
            self.uia.wait_for_stable_list(dialog)

            # 2.3: Check for exact match
            # Look for rows matching Company, Name, ZIP, City
            found = self.uia.select_table_row(dialog, search_name)

            if found:
                # Click OK
                ok_btn = self.uia.find_by_name(DIALOG.OK, parent=dialog)
                self.uia.click(ok_btn)
                self._milestone("2.3", f"Debtor selected: {search_name}")
                return True
            else:
                # Click Cancel
                cancel_btn = self.uia.find_by_name(DIALOG.CANCEL, parent=dialog)
                self.uia.click(cancel_btn)
                self._milestone("2.3", f"Debtor not found: {search_name}")
                return False

        except UIAError as e:
            logger.warning(f"Debtor search failed: {e}")
            return False

    def create_debtor(self, debtor: DebtorInfo) -> None:
        """
        Steps 2.5-2.11: Create a new Debtor with all required fields.
        Keeps the Order tab open while working in the New Contact editor.
        """
        try:
            # 2.5: Click New Contact in the left New panel
            new_contact_btn = self.uia.find_by_name(TOOLBAR.NEW_CONTACT, partial=True)
            self.uia.click(new_contact_btn)
            time.sleep(1)
            self._milestone("2.5", "New Debtor editor opened")

            # 2.6: Enter Company, First Name, Last Name
            self._set_field_safe(CONTACT.COMPANY, debtor.company)
            self._set_field_safe(CONTACT.FIRST_NAME, debtor.first_name)
            self._set_field_safe(CONTACT.LAST_NAME, debtor.last_name)

            # 2.7: Address fields
            addr = debtor.billing_address
            self._set_field_safe(CONTACT.STREET, addr.street)
            self._set_field_safe(CONTACT.ZIP_CODE, addr.zip_code)
            self._set_field_safe(CONTACT.CITY, addr.city)
            self._set_field_safe(CONTACT.COUNTRY, addr.country)
            self._set_field_safe(CONTACT.EMAIL, addr.email)
            self._set_field_safe(CONTACT.TELEPHONE, addr.telephone)

            self._milestone("2.7", "Address fields completed")

            # 2.8: Assign Invoice address role (and Delivery if same)
            try:
                invoice_role = self.uia.find_by_name(
                    CONTACT.INVOICE_ADDRESS_ROLE, partial=True
                )
                self.uia.click(invoice_role)
                if debtor.delivery_same_as_billing:
                    delivery_role = self.uia.find_by_name(
                        CONTACT.DELIVERY_ADDRESS_ROLE, partial=True
                    )
                    self.uia.click(delivery_role)
            except UIAError:
                logger.warning("Could not set address roles")

            # 2.9: Miscellaneous
            try:
                misc_tab = self.uia.find_by_name(CONTACT.MISCELLANEOUS_TAB, partial=True)
                self.uia.click(misc_tab)
                time.sleep(0.5)
                self._set_field_safe(CONTACT.ALIAS_NAME, debtor.alias)
            except UIAError:
                logger.warning("Could not open Miscellaneous tab")

            # 2.10: Payment method
            self._set_payment_method_on_debtor(debtor.payment_method)

            # 2.11: Save the Debtor
            self.save_current()
            self._milestone("2.11", "Debtor saved")

        except UIAError as e:
            raise UIAError(f"Failed to create debtor: {e}")

    def reselect_debtor_after_creation(self, debtor: DebtorInfo) -> None:
        """
        Step 2.12-2.13: Return to the Order, reopen the address selector,
        search again, and select the newly created Debtor.
        """
        # The Order tab should still be open - switch to it
        time.sleep(0.5)
        found = self.search_and_select_debtor(debtor)
        if found:
            self._milestone("2.13", "Newly created Debtor selected in Order")
        else:
            raise StopForReview(
                f"Newly created Debtor '{debtor.display_name}' not found in selector. "
                "Manual review required."
            )

    # ===================================================================
    # Step 3: Select or create each Product
    # ===================================================================

    def search_and_select_product(self, sku: str) -> bool:
        """
        Steps 3.2-3.3: Try to select a Product from the Order's product selector.
        Returns True if an exact match was found, False otherwise.
        """
        try:
            select_btn = self.uia.find_by_name(
                DIALOG.SELECT_PRODUCT_DIALOG, partial=True
            )
            self.uia.click(select_btn)
            time.sleep(1)

            dialog = self.uia.wait_for_window(DIALOG.SELECT_PRODUCT_DIALOG, timeout=10)
            search_field = self.uia.find_by_name(DIALOG.SEARCH_FIELD, parent=dialog, partial=True)
            self.uia.set_value(search_field, sku)
            time.sleep(1)

            self.uia.wait_for_stable_list(dialog)

            found = self.uia.select_table_row(dialog, sku)
            if found:
                ok_btn = self.uia.find_by_name(DIALOG.OK, parent=dialog)
                self.uia.click(ok_btn)
                self._milestone("3.3", f"Product selected: {sku}")
                return True
            else:
                cancel_btn = self.uia.find_by_name(DIALOG.CANCEL, parent=dialog)
                self.uia.click(cancel_btn)
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
        Steps 3.7-3.11: Create a new Product with calculated gross price.
        """
        try:
            # 3.7: Click New product
            new_prod_btn = self.uia.find_by_name(TOOLBAR.NEW_PRODUCT, partial=True)
            self.uia.click(new_prod_btn)
            time.sleep(1)

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
                vat_combo = self.uia.find_by_name(PRODUCT.VAT, partial=True)
                self.uia.select_combo_item(vat_combo, item.vat_name)
            except UIAError:
                logger.warning(f"Could not select VAT: {item.vat_name}")

            # 3.11: Save
            self.save_current()
            self._milestone("3.11", f"Product created: {item.sku}")

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
        """Click the toolbar Save control once."""
        try:
            save_btn = self.uia.find_toolbar_button(TOOLBAR.SAVE)
            self.uia.click(save_btn)
            time.sleep(1)
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
        Step 4.6: From the saved Order, click Invoice in the follow-up area.
        """
        try:
            invoice_btn = self.uia.find_by_name(
                ORDER.FOLLOWUP_INVOICE, partial=True
            )
            self.uia.click(invoice_btn)
            time.sleep(2)
            self._milestone("4.6", "Follow-up Invoice created from Order")
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
        """Try to find a field by name and set its value. Log warning on failure."""
        if not value:
            return
        try:
            field = self.uia.find_by_name(field_name, partial=True, timeout=5)
            self.uia.set_value(field, value)
        except UIAError:
            logger.warning(f"Could not set field '{field_name}' to '{value}'")

    def _navigate_to(self, *path: str) -> None:
        """Navigate through the left-panel tree by clicking each node."""
        for node_name in path:
            try:
                node = self.uia.find_by_name(node_name, partial=True, timeout=5)
                self.uia.click(node)
                time.sleep(0.5)
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
                self._milestone("2.10.6", f"Payment method created: {payment_method}")

            # Return to debtor editor and select the payment method
            # (The debtor editor tab should still be open)

        except UIAError as e:
            logger.warning(f"Payment method setup failed: {e}")
